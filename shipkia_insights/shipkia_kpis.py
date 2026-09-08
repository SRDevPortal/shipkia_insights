"""Marketing and sales KPIs calculated from reporting snapshots, not live databases."""
import json
from pathlib import Path

import frappe

from shipkia_insights.reporting import bindings, check_bindings, models


def identifier(value):
    return '"' + value.replace('"', '""') + '"'


def literal(value):
    return "'" + (value or "").replace("'", "''") + "'"


def sql_models(deployment):
    schema = frappe.db.get_value("Insights Data Source v3", deployment.application_source, "schema") or "public"
    tables = {k: identifier(schema + '.' + v["table"].split('.')[-1]) for k, v in models(deployment).items() if v["source"] == "application"}
    r = f"""r AS (
      SELECT t.id, t.customer_id, t.created_at, t.category, t.type,
        COALESCE(w.currency,'Unknown') AS currency,
        CASE WHEN t.type='credit' THEN t.amount/100.0 ELSE -ABS(t.amount)/100.0 END AS recharge
      FROM {tables['wallet_transactions']} t
      LEFT JOIN {tables['wallets']} w ON t.wallet_id=w.id AND t.customer_id=w.customer_id
      WHERE t.category IN ('Recharge','COD Remittance Recharge') AND t.type IN ('credit','debit')
    )"""
    queries = {}
    queries['Customer Recharge and Orders'] = f"""WITH {r}, amounts AS (
      SELECT customer_id,currency,SUM(recharge) AS total_recharge,
        SUM(CASE WHEN category='Recharge' THEN recharge ELSE 0 END) AS direct_recharge,
        SUM(CASE WHEN category='COD Remittance Recharge' THEN recharge ELSE 0 END) AS cod_recharge,
        MIN(CASE WHEN type='credit' AND recharge>0 THEN created_at END) AS first_recharge,
        MAX(created_at) AS last_recharge FROM r GROUP BY customer_id,currency
    ), orders AS (SELECT customer_id,COUNT(*) AS orders FROM {tables['orders']} GROUP BY customer_id)
    SELECT c.id AS customer_id,c.company_name,c.created_at AS signup_date,
      COALESCE(a.currency,c.currency,'Unknown') AS currency,
      COALESCE(a.total_recharge,0) AS total_recharge,COALESCE(a.direct_recharge,0) AS direct_recharge,
      COALESCE(a.cod_recharge,0) AS cod_recharge,COALESCE(o.orders,0) AS orders,a.first_recharge,a.last_recharge
    FROM {tables['accounts']} c LEFT JOIN amounts a ON a.customer_id=c.id LEFT JOIN orders o ON o.customer_id=c.id"""
    queries['Observed Recharge LTV'] = f"""WITH {r}, customers AS (
      SELECT customer_id,currency,SUM(recharge) AS lifetime_recharge
      FROM r GROUP BY customer_id,currency HAVING COUNT(CASE WHEN type='credit' AND recharge>0 THEN 1 END)>0)
    SELECT currency,COUNT(*) AS paying_customers,SUM(lifetime_recharge) AS net_recharges,
      AVG(lifetime_recharge) AS observed_recharge_ltv FROM customers GROUP BY currency"""
    queries['Monthly Average Recharge per Customer'] = f"""WITH {r}
    SELECT DATE_TRUNC('month',created_at) AS period,currency,SUM(recharge) AS net_recharges,
      COUNT(DISTINCT CASE WHEN type='credit' AND recharge>0 THEN customer_id END) AS recharging_customers,
      SUM(recharge)/NULLIF(COUNT(DISTINCT CASE WHEN type='credit' AND recharge>0 THEN customer_id END),0) AS average_recharge
    FROM r WHERE created_at<DATE_TRUNC('month',CURRENT_TIMESTAMP)
      AND created_at>=DATE_TRUNC('month',CURRENT_TIMESTAMP)-INTERVAL '12 months'
    GROUP BY 1,2 ORDER BY 1,2"""
    queries['Monthly Order Retention'] = f"""WITH periods AS (
      SELECT period FROM generate_series(DATE_TRUNC('month',CURRENT_TIMESTAMP)-INTERVAL '12 months',
        DATE_TRUNC('month',CURRENT_TIMESTAMP)-INTERVAL '1 month',INTERVAL '1 month') AS p(period)
    ), active AS (SELECT DISTINCT customer_id,DATE_TRUNC('month',created_at) AS period
      FROM {tables['orders']} WHERE customer_id IS NOT NULL)
    SELECT p.period,COUNT(previous.customer_id) AS previous_active_customers,
      COUNT(current.customer_id) AS retained_customers,
      100.0*COUNT(current.customer_id)/NULLIF(COUNT(previous.customer_id),0) AS retention_pct
    FROM periods p LEFT JOIN active previous ON previous.period=p.period-INTERVAL '1 month'
      LEFT JOIN active current ON current.period=p.period AND current.customer_id=previous.customer_id
    GROUP BY p.period ORDER BY p.period"""
    queries['Recharge Acquisition Cohorts'] = f"""WITH {r}, firsts AS (
      SELECT customer_id,currency,MIN(created_at) AS acquired_at FROM r WHERE type='credit' AND recharge>0 GROUP BY 1,2
    ) SELECT DATE_TRUNC('month',f.acquired_at) AS cohort,f.currency,
      COUNT(DISTINCT f.customer_id) AS acquired_paying_customers,SUM(r.recharge) AS cumulative_recharges,
      SUM(r.recharge)/NULLIF(COUNT(DISTINCT f.customer_id),0) AS recharge_per_acquired_customer
    FROM firsts f JOIN r ON r.customer_id=f.customer_id AND r.currency=f.currency
    GROUP BY 1,2 ORDER BY 1,2"""
    queries['Orders by Stage'] = f"SELECT COALESCE(stage,'Unspecified') AS stage,COUNT(*) AS orders FROM {tables['orders']} GROUP BY 1"
    queries['Orders by Customer'] = f"""SELECT o.customer_id,MAX(c.company_name) AS company_name,COUNT(*) AS orders
      FROM {tables['orders']} o LEFT JOIN {tables['accounts']} c ON c.id=o.customer_id GROUP BY o.customer_id"""
    for unit in ('week','month','quarter'):
        interval = '3 months' if unit=='quarter' else '1 '+unit
        span = '36 months' if unit=='quarter' else '12 '+unit+'s'
        prefix = f"""WITH {r}, periods AS (
          SELECT period FROM generate_series(DATE_TRUNC('{unit}',CURRENT_TIMESTAMP)-INTERVAL '{span}',
          DATE_TRUNC('{unit}',CURRENT_TIMESTAMP)-INTERVAL '{interval}',INTERVAL '{interval}') AS p(period)
        )"""
        queries[unit.title()+' Customer and Order Growth'] = prefix+f""", counts AS (
          SELECT p.period,
           (SELECT COUNT(*) FROM {tables['accounts']} c WHERE c.created_at>=p.period AND c.created_at<p.period+INTERVAL '{interval}') AS new_customers,
           (SELECT COUNT(*) FROM {tables['orders']} o WHERE o.created_at>=p.period AND o.created_at<p.period+INTERVAL '{interval}') AS orders
          FROM periods p
        ) SELECT period,new_customers,orders,
          100.0*(new_customers-LAG(new_customers) OVER (ORDER BY period))/NULLIF(LAG(new_customers) OVER (ORDER BY period),0) AS customer_growth_pct,
          100.0*(orders-LAG(orders) OVER (ORDER BY period))/NULLIF(LAG(orders) OVER (ORDER BY period),0) AS order_growth_pct
        FROM counts ORDER BY period"""
        queries[unit.title()+' Recharge Growth'] = prefix+f""", currencies AS (SELECT DISTINCT currency FROM r), totals AS (
          SELECT p.period,c.currency,COALESCE(SUM(r.recharge),0) AS total_recharge,
          COALESCE(SUM(CASE WHEN r.category='Recharge' THEN r.recharge ELSE 0 END),0) AS direct_recharge,
          COALESCE(SUM(CASE WHEN r.category='COD Remittance Recharge' THEN r.recharge ELSE 0 END),0) AS cod_recharge
          FROM periods p CROSS JOIN currencies c LEFT JOIN r ON r.currency=c.currency AND r.created_at>=p.period AND r.created_at<p.period+INTERVAL '{interval}'
          GROUP BY p.period,c.currency
        ) SELECT *,100.0*(total_recharge-LAG(total_recharge) OVER (PARTITION BY currency ORDER BY period))/
          NULLIF(LAG(total_recharge) OVER (PARTITION BY currency ORDER BY period),0) AS recharge_growth_pct
        FROM totals ORDER BY period,currency"""
    queries['Customer Monthly Growth'] = f"""WITH {r}, periods AS (
      SELECT period FROM generate_series(DATE_TRUNC('month',CURRENT_TIMESTAMP)-INTERVAL '12 months',
      DATE_TRUNC('month',CURRENT_TIMESTAMP)-INTERVAL '1 month',INTERVAL '1 month') AS p(period)
    ), order_totals AS (SELECT customer_id,DATE_TRUNC('month',created_at) AS period,COUNT(*) AS orders FROM {tables['orders']} GROUP BY 1,2),
    recharge_totals AS (SELECT customer_id,currency,DATE_TRUNC('month',created_at) AS period,SUM(recharge) AS recharge FROM r GROUP BY 1,2,3),
    currencies AS (SELECT id AS customer_id,COALESCE(currency,'Unknown') AS currency FROM {tables['accounts']} UNION SELECT customer_id,currency FROM r),
    totals AS (SELECT c.id AS customer_id,c.company_name,k.currency,p.period,COALESCE(o.orders,0) AS orders,COALESCE(t.recharge,0) AS recharge
      FROM {tables['accounts']} c JOIN currencies k ON k.customer_id=c.id CROSS JOIN periods p
      LEFT JOIN order_totals o ON o.customer_id=c.id AND o.period=p.period
      LEFT JOIN recharge_totals t ON t.customer_id=c.id AND t.period=p.period AND t.currency=k.currency
      WHERE c.created_at<p.period+INTERVAL '1 month')
    SELECT *,100.0*(orders-LAG(orders) OVER w)/NULLIF(LAG(orders) OVER w,0) AS order_growth_pct,
      100.0*(recharge-LAG(recharge) OVER w)/NULLIF(LAG(recharge) OVER w,0) AS recharge_growth_pct
    FROM totals WINDOW w AS (PARTITION BY customer_id,currency ORDER BY period) ORDER BY period,customer_id,currency"""
    return queries


def install_kpis(deployment):
    frappe.only_for("System Manager")
    check_bindings(deployment)
    folder = Path(frappe.get_site_path('private','files','insights-rollout'))
    folder.mkdir(parents=True,exist_ok=True)
    dashboards = {group: frappe.get_doc('Insights Dashboard v3', {'workbook':deployment.workbook,'title':group+' - '+deployment.environment}) for group in ('Marketing','Sales')}
    backup = folder / ('before-marketing-sales-' + deployment.name.replace('/','_') + '.json')
    if not backup.exists():
        backup.write_text(json.dumps({k:v.as_dict() for k,v in dashboards.items()},default=str,indent=2),encoding='utf-8')
    query_ids = {}
    def query(title, operations, native=True):
        full='KPI - '+title
        name=frappe.db.get_value('Insights Query v3',{'workbook':deployment.workbook,'title':full},'name')
        doc=frappe.get_doc('Insights Query v3',name) if name else frappe.new_doc('Insights Query v3')
        doc.update({'workbook':deployment.workbook,'title':full,'use_live_connection':0,'is_native_query':int(native),'is_builder_query':int(not native),'is_script_query':0,'operations':operations})
        doc.save();query_ids[title]=doc.name
        return doc.name
    for title,sql in sql_models(deployment).items():
        query(title,[{'type':'sql','data_source':deployment.application_source,'raw_sql':sql}])
    agent_sql = f"""SELECT shipkia_cust_id AS customer_id,
      CASE WHEN COUNT(DISTINCT NULLIF(lead_owner,''))>1 THEN 'Conflicting CRM owners'
      ELSE COALESCE(MAX(NULLIF(lead_owner,'')),'Unassigned') END AS agent
      FROM `tabLead` WHERE shipkia_connection={literal(deployment.account_connection)} AND shipkia_cust_id IS NOT NULL AND shipkia_cust_id<>'' GROUP BY shipkia_cust_id"""
    agents=query('Current CRM Agent Mapping',[{'type':'sql','data_source':deployment.crm_source,'raw_sql':agent_sql}])
    def col(name):return {'type':'column','column_name':name}
    agent_customers=query('Sales Agent Customers',[
      {'type':'source','table':{'type':'query','query_name':query_ids['Customer Recharge and Orders'],'workbook':deployment.workbook}},
      {'type':'join','join_type':'left','table':{'type':'query','query_name':agents,'workbook':deployment.workbook},'select_columns':[col('agent')],
       'join_condition':{'left_column':col('customer_id'),'right_column':col('customer_id')}},
      {'type':'mutate','new_name':'agent','data_type':'String','expression':{'type':'expression','expression':"agent.fill_null('Unmapped to CRM')"}}
    ],False)
    items={k:[] for k in dashboards}
    def note(group,text,height=3):
        y=max((i['layout']['y']+i['layout']['h'] for i in items[group]),default=0)
        items[group].append({'type':'text','text':text,'layout':{'i':'note-'+str(len(items[group])),'x':0,'y':y,'w':20,'h':height}})
    def chart(group,title,query_title,dimensions,measures,line=False):
        full='KPI - '+title
        name=frappe.db.get_value('Insights Chart v3',{'workbook':deployment.workbook,'title':full},'name')
        doc=frappe.get_doc('Insights Chart v3',name) if name else frappe.new_doc('Insights Chart v3')
        dims=[{'dimension_name':c,'column_name':c,'data_type':'Date' if c in ('period','cohort') else 'String'} for c in dimensions]
        vals=[{'measure_name':c,'column_name':c,'data_type':'Decimal','aggregation':agg} for c,agg in measures]
        config={'rows':dims,'columns':[],'values':vals,'order_by':[],'limit':1000,'filters':{'logical_operator':'And','filters':[]}}
        if line:
            config={'x_axis':{'dimension':dims[0]},'y_axis':{'series':[{'measure':v} for v in vals]},'order_by':[],'limit':1000,'filters':{'logical_operator':'And','filters':[]}}
        doc.update({'workbook':deployment.workbook,'title':full,'query':query_ids[query_title],'chart_type':('Line' if line is True else 'Bar') if line else 'Table','config':config});doc.save()
        data=frappe.get_doc('Insights Query v3',doc.data_query);data.use_live_connection=0;data.is_builder_query=1
        data.operations=[{'type':'source','table':{'type':'query','query_name':query_ids[query_title],'workbook':deployment.workbook}}, {'type':'summarize','dimensions':dims,'measures':vals}];data.save()
        y=max((i['layout']['y']+i['layout']['h'] for i in items[group]),default=0)
        items[group].append({'type':'chart','chart':doc.name,'layout':{'i':doc.name,'x':0,'y':y,'w':20,'h':8}})
    note('Marketing','<h2>Marketing performance - wallet recharge basis</h2><p>Amounts are rupees for INR. Direct Recharge and COD Remittance Recharge credits are included; debits in those same categories reduce the totals. Billing revenue is separate. Trends use completed UTC periods; blank percentages mean no prior-period denominator.</p>')
    note('Marketing','<h3>CAC: unavailable | ROAS: unavailable | Cohort ROAS: unavailable</h3><p>No connected advertising spend or campaign-to-paying-customer attribution is available. These metrics are not zero. CAC = acquisition spend / new paying customers. Recharge ROAS = attributed wallet recharges / ad spend. Cohort ROAS follows the same acquired customers over time. Accounting-revenue ROAS awaits billing data.</p>',4)
    chart('Marketing','Observed LTV - Recharge Basis','Observed Recharge LTV',['currency'],[('observed_recharge_ltv','max'),('paying_customers','max'),('net_recharges','max')])
    chart('Marketing','Average Revenue per Customer - Recharge Basis','Monthly Average Recharge per Customer',['period','currency'],[('average_recharge','max'),('net_recharges','max'),('recharging_customers','max')])
    chart('Marketing','Monthly Customer Retention - Orders','Monthly Order Retention',['period'],[('retention_pct','max')],True)
    chart('Marketing','Retention Denominators','Monthly Order Retention',['period'],[('previous_active_customers','max'),('retained_customers','max'),('retention_pct','max')])
    chart('Marketing','Acquisition Cohorts - Recharge Value, Not ROAS','Recharge Acquisition Cohorts',['cohort','currency'],[('acquired_paying_customers','max'),('cumulative_recharges','max'),('recharge_per_acquired_customer','max')])
    note('Sales','<h2>Sales performance - wallet recharge basis</h2><p>Customer counts are panel accounts. Agents are current CRM Lead owners linked by ShipKia CUST ID, not historical acquisition credit. Conflicting owners and unmapped accounts remain visible. Growth compares complete UTC weeks (Monday start), months and quarters. First periods and zero baselines show no percentage.</p>',4)
    chart('Sales','Sales Agent Customers','Sales Agent Customers',['agent','currency'],[('customer_id','count_distinct'),('total_recharge','sum')])
    chart('Sales','Customers by Agent - Detail','Sales Agent Customers',['agent','customer_id','company_name','currency'],[('total_recharge','max'),('direct_recharge','max'),('cod_recharge','max'),('orders','max')])
    chart('Sales','Orders by Stage','Orders by Stage',['stage'],[('orders','max')],'Bar')
    chart('Sales','Orders at Customer Level','Orders by Customer',['customer_id','company_name'],[('orders','max')])
    for unit in ('Week','Month','Quarter'):
        chart('Sales',unit+' Customer and Order Trends',unit+' Customer and Order Growth',['period'],[('new_customers','max'),('orders','max')],True)
        chart('Sales',unit+' Customer and Orders Growth',unit+' Customer and Order Growth',['period'],[('new_customers','max'),('customer_growth_pct','max'),('orders','max'),('order_growth_pct','max')])
        chart('Sales',unit+' Revenue Growth - Recharge Basis',unit+' Recharge Growth',['period','currency'],[('direct_recharge','max'),('cod_recharge','max'),('total_recharge','max'),('recharge_growth_pct','max')])
    chart('Sales','Customer Level Monthly Growth','Customer Monthly Growth',['period','customer_id','company_name','currency'],[('orders','max'),('order_growth_pct','max'),('recharge','max'),('recharge_growth_pct','max')])
    note('Sales','<p>Recharge totals are counted once from wallet transactions. Orders are pre-aggregated before customer/agent joins. Customer growth means new signups versus the previous period. Retention counts any recorded order, including canceled orders; it does not mean delivered-shipment retention. Historical ownership, customer billing and ad-spend metrics require their respective source data.</p>',3)
    for group,doc in dashboards.items():
        doc.items=items[group];doc.save()
    return query_ids
