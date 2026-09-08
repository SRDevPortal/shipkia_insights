"""Portable ShipKia Insights reporting pack. No credentials are embedded here."""

import hashlib
import json
from pathlib import Path

import frappe


def models(deployment=None):
    result = json.loads(Path(__file__).with_name("shipkia_insights_models.json").read_text())
    if deployment:
        schema = frappe.db.get_value("Insights Data Source v3", deployment.application_source, "schema") or "public"
        for model in result.values():
            if model["source"] == "application":
                model["table"] = schema + "." + model["table"]
    return result


def bindings(deployment):
    return {key: deployment.get(key + "_source") for key in ("crm", "application", "billing")}


def fingerprint(source):
    doc = frappe.get_doc("Insights Data Source v3", source)
    fields = ("database_type", "host", "port", "database_name", "schema", "is_site_db", "api_base_url")
    return hashlib.sha256(json.dumps({f: doc.get(f) for f in fields}, sort_keys=True).encode()).hexdigest()


def check_bindings(deployment):
    expected = json.loads(deployment.source_fingerprints or "{}")
    for source in filter(None, bindings(deployment).values()):
        if expected.get(source) != fingerprint(source):
            frappe.throw("A source endpoint changed. Create a new Insights source and deployment profile to avoid mixing environments.")


def prepare_tables(deployment):
    from insights.utils import InsightsDataSourcev3
    planned = []
    # Validate all schemas before changing import settings.
    for key, model in models(deployment).items():
        source = bindings(deployment)[model["source"]]
        if not source:
            continue
        ds = InsightsDataSourcev3.get_doc(source)
        remote = ds.get_ibis_table(model["table"])
        missing = set(model["columns"]) - set(remote.columns)
        if missing:
            frappe.throw(f"Schema mismatch for {key}: missing {', '.join(sorted(missing))}")
        table_name = frappe.db.get_value("Insights Table v3", {"data_source": source, "table": model["table"]}, "name")
        if not table_name:
            frappe.throw(f"Refresh the table list for {source} first.")
        planned.append((model, table_name))
    for model, name in planned:
        doc = frappe.get_doc("Insights Table v3", name)
        doc.sync_mode = "Incremental"
        doc.sync_strategy = "Update or Insert"
        doc.sync_cursor_column = model["cursor"]
        doc.sync_primary_key_column = model["key"]
        doc.sync_from = "1970-01-01 00:00:00"
        # Keep existing CRM warehouse schemas; app imports only reporting columns.
        if model["source"] != "crm":
            doc.before_import_script = "table.select(" + ", ".join(repr(c) for c in model["columns"]) + ")"
            if model["table"].endswith(".wallet_transactions"):
                doc.before_import_script += ".mutate(id=table.id.cast('string'))"
        doc.save()
    return len(planned)


def build_pack(deployment):
    workbook = "shipkia-reporting-template"
    sources = bindings(deployment)
    queries, charts, dashboards = {}, {}, {}
    for key, model in models(deployment).items():
        if not sources[model["source"]]:
            continue
        ops = [{"type": "source", "table": {"type": "table", "data_source": sources[model["source"]], "table_name": model["table"]}}]
        if key in ("invoices", "payments"):
            ops.append({"type": "filter_group", "logical_operator": "And", "filters": [{"column": {"type": "column", "column_name": "docstatus"}, "operator": "=", "value": 1}]})
        for amount in ("balance", "amount", "chargeable_amount", "tax_amount", "total_order_value", "shipping_charge"):
            if amount in model["columns"] and model["source"] == "application":
                ops.append({"type": "mutate", "new_name": amount + "_rupees", "data_type": "Decimal", "expression": {"type": "expression", "expression": amount + " / 100.0"}})
        queries[key] = {"name": key, "title": key.replace("_", " ").title(), "workbook": workbook, "sort_order": len(queries), "use_live_connection": 0, "is_builder_query": 1, "is_script_query": 0, "is_native_query": 0, "operations": ops}

    def chart(group, key, title, dimension=None, value=None, aggregation="count"):
        model = models()[key]
        name = "chart-" + str(len(charts))
        measure = {"measure_name": title, "column_name": value or model["key"], "data_type": "Decimal" if value else "Integer", "aggregation": aggregation}
        config = {"filters": {"logical_operator": "And", "filters": []}, "order_by": [], "limit": 100}
        if dimension:
            config.update({"rows": [{"dimension_name": dimension.replace("_", " ").title(), "column_name": dimension, "data_type": "String"}], "columns": [], "values": [measure]})
            chart_type = "Table"
            if key != "wallets":
                date_axis = dimension in ("creation", "created_at")
                axis = {"dimension_name": dimension, "column_name": dimension, "data_type": "Datetime" if date_axis else "String"}
                if date_axis:
                    axis["granularity"] = "day"
                config = {"x_axis": {"dimension": axis}, "y_axis": {"series": [{"measure": measure}], "show_data_labels": False},
                    "filters": {"logical_operator": "And", "filters": []}, "order_by": [], "limit": 100}
                chart_type = "Line" if date_axis else "Bar"
        else:
            config.update({"number_columns": [measure], "number_column_options": [{"shorten_numbers": False}], "comparison": False, "sparkline": False})
            chart_type = "Number"
        charts[name] = {"name": name, "title": title, "workbook": workbook, "query": key, "chart_type": chart_type, "config": config}
        dashboard = dashboards.setdefault(group, {"name": group, "title": group + " - " + deployment.environment, "workbook": workbook, "items": []})
        index = sum(i["type"] == "chart" for i in dashboard["items"])
        dashboard["items"].append({"type": "chart", "chart": name, "layout": {"i": name, "x": (index % 2) * 10, "y": 1 + (index // 2) * 7, "w": 10, "h": 7}})
        return name

    for title, dimension in [("Total Leads", None), ("Leads by Source", "source"), ("Leads by Campaign", "source_campaign_name"), ("Leads by Medium", "source_medium")]:
        chart("Marketing", "leads", title, dimension)
    for title, dimension in [("Leads by Agent", "lead_owner"), ("Leads by Status", "status"), ("ShipKia Onboarding", "shipkia_onboarding_status"), ("CRM Customers", None)]:
        chart("Sales", "crm_customers" if title == "CRM Customers" else "leads", title, dimension)
    for key, title, dim in [("accounts", "Panel Accounts", None), ("orders", "Orders", None), ("orders", "Orders by Status", "status"), ("orders", "Orders by Courier", "courier_partner"), ("orders", "Orders by Customer", "customer_id"), ("stores", "Stores by Platform", "platform")]:
        chart("Activation and Orders", key, title, dim)
    chart("Wallet Activity", "wallets", "Wallet Balance in Currency Units", "currency", "balance_rupees", "sum")
    chart("Wallet Activity", "wallet_transactions", "Transactions by Type", "type")
    chart("Wallet Activity", "wallet_transactions", "Transactions by Category", "category")
    chart("Wallet Activity", "recharges", "Recharges by Status", "status")
    for key, title, dim in [("support", "Support Tickets", None), ("support", "Tickets by Stage", "stage"), ("support", "Tickets by Issue", "issue_type"), ("support", "Tickets by Customer", "customer_id"), ("comments", "Comments by Type", "type")]:
        chart("Support", key, title, dim)
    chart("Marketing", "leads", "New Leads Over Time", "creation")
    chart("Activation and Orders", "accounts", "Signups Over Time", "created_at")
    chart("Activation and Orders", "orders", "Orders Over Time", "created_at")
    if sources["billing"]:
        chart("Billing", "invoices", "Submitted Invoices", None)
        chart("Billing", "invoices", "Invoice Status", "status")
        chart("Billing", "invoices", "Net Invoiced Base Amount", "company", "base_net_total", "sum")
        chart("Billing", "invoices", "Outstanding by Currency", "currency", "outstanding_amount", "sum")
        chart("Billing", "payments", "Submitted Payment Entries", "payment_type")
    for dashboard in dashboards.values():
        links = {}
        for item in dashboard["items"]:
            c = charts[item["chart"]]
            key = c["query"]
            date = "posting_date" if key in ("invoices", "payments") else ("creation" if models()[key]["source"] == "crm" else "created_at")
            if key != "wallets":
                links[c["name"]] = f"`{key}`.`{date}`"
        dashboard["items"].insert(0, {"type": "filter", "filter_name": "Date Range", "filter_type": "Date", "icon": "calendar", "default_operator": "within", "links": links, "layout": {"i": "date-filter", "x": 0, "y": 0, "w": 6, "h": 1}})
    return {"version": "1.0", "type": "Workbook", "name": workbook, "doc": {"name": workbook, "title": "ShipKia Business Insights - " + deployment.environment}, "dependencies": {"folders": [], "queries": queries, "charts": charts, "dashboards": dashboards}}


def install(profile, crm_source, application_source, environment="Testing", billing_source=None, account_connection=None):
    frappe.only_for("System Manager")
    from insights.insights.doctype.insights_workbook.insights_workbook import import_workbook
    selected = {s for s in (crm_source, application_source, billing_source) if s}
    for existing in frappe.get_all("ShipKia Insights Deployment", fields=["name", "environment", "crm_source", "application_source", "billing_source"]):
        if existing.environment != environment and selected.intersection(filter(None, bindings(existing).values())):
            frappe.throw("Use separate Insights data-source records for Testing and Production.")
    if account_connection and frappe.db.get_value("ShipKia API Connection", account_connection, "environment") != environment:
        frappe.throw("The CRM account connection must belong to the deployment environment.")
    if frappe.db.exists("ShipKia Insights Deployment", profile):
        deployment = frappe.get_doc("ShipKia Insights Deployment", profile)
        if bindings(deployment) != {"crm": crm_source, "application": application_source, "billing": billing_source} or deployment.environment != environment:
            frappe.throw("Use a new profile when changing source bindings.")
        check_bindings(deployment)
        if deployment.workbook:
            add_customer_journey(deployment)
            from shipkia_insights.shipkia_kpis import install_kpis
            install_kpis(deployment)
            return deployment.workbook
    else:
        deployment = frappe.get_doc({"doctype": "ShipKia Insights Deployment", "profile": profile, "environment": environment, "crm_source": crm_source, "application_source": application_source, "billing_source": billing_source, "account_connection": account_connection, "enabled": 0})
        deployment.source_fingerprints = json.dumps({source: fingerprint(source) for source in filter(None, bindings(deployment).values())})
        deployment.insert()
    prepare_tables(deployment)
    pack = build_pack(deployment)
    deployment.workbook = import_workbook(pack)
    deployment.save()
    add_customer_journey(deployment)
    from shipkia_insights.shipkia_kpis import install_kpis
    install_kpis(deployment)
    return deployment.workbook


def refresh():
    if "insights" not in frappe.get_installed_apps() or not frappe.db.table_exists("ShipKia Insights Deployment"):
        return
    from shipkia_insights.importer import WarehouseTable
    for row in frappe.get_all("ShipKia Insights Deployment", filters={"enabled": 1}, pluck="name"):
        deployment = frappe.get_doc("ShipKia Insights Deployment", row)
        try:
            check_bindings(deployment)
        except frappe.ValidationError:
            deployment.db_set({"enabled": 0, "last_error": "Source endpoint changed; refresh paused to protect environment separation."})
            continue
        for model in models(deployment).values():
            source = bindings(deployment)[model["source"]]
            if source:
                WarehouseTable(source, model["table"]).enqueue_import()
        deployment.db_set({"last_refresh": frappe.utils.now(), "last_error": None})


def add_customer_journey(deployment):
    """Join at account grain; aggregate orders before joining to avoid inflated counts."""
    def ensure_query(title, operations):
        name = frappe.db.get_value("Insights Query v3", {"workbook": deployment.workbook, "title": title}, "name")
        if name:
            return name
        return frappe.get_doc({"doctype": "Insights Query v3", "workbook": deployment.workbook, "title": title,
            "use_live_connection": 0, "is_builder_query": 1, "operations": operations}).insert().name

    def source(key):
        model = models(deployment)[key]
        return {"type": "source", "table": {"type": "table", "data_source": bindings(deployment)[model["source"]], "table_name": model["table"]}}

    def col(name):
        return {"type": "column", "column_name": name}

    order_counts = ensure_query("Orders Per Account", [source("orders"), {"type": "summarize",
        "dimensions": [{"dimension_name": "customer_id", "column_name": "customer_id", "data_type": "String"}],
        "measures": [{"measure_name": "order_count", "column_name": "id", "data_type": "Integer", "aggregation": "count"}]}])
    accounts = ensure_query("Account Order Activity", [source("accounts"), {"type": "join", "join_type": "left",
        "table": {"type": "query", "workbook": deployment.workbook, "query_name": order_counts},
        "select_columns": [col("order_count")], "join_condition": {"left_column": col("id"), "right_column": col("customer_id")}}])
    report_queries = [(accounts, "Account Order Activity", ["id", "company_name"], [{"measure_name": "Orders", "column_name": "order_count", "data_type": "Integer", "aggregation": "sum"}])]
    if deployment.account_connection:
        model = models(deployment)["accounts"]
        linked = ensure_query("Lead to Panel Mapping", [source("leads"), {"type": "filter_group", "logical_operator": "And",
            "filters": [{"column": col("shipkia_connection"), "operator": "=", "value": deployment.account_connection}]},
            {"type": "join", "join_type": "left", "table": {"type": "table", "data_source": deployment.application_source, "table_name": model["table"]},
            "select_columns": [col("id")], "join_condition": {"left_column": col("shipkia_cust_id"), "right_column": col("id")}}])
        report_queries.append((linked, "Lead to Panel Mapping", ["source"], [
            {"measure_name": "Leads", "column_name": "name", "data_type": "Integer", "aggregation": "count"},
            {"measure_name": "Matched Panel Accounts", "column_name": "id", "data_type": "Integer", "aggregation": "count"}]))
    title = "Customer Journey - " + deployment.environment
    dashboard_name = frappe.db.get_value("Insights Dashboard v3", {"workbook": deployment.workbook, "title": title}, "name")
    if dashboard_name:
        return
    items = []
    for query, chart_title, dimensions, values in report_queries:
        chart = frappe.get_doc({"doctype": "Insights Chart v3", "workbook": deployment.workbook, "title": chart_title, "query": query,
            "chart_type": "Table", "config": {"rows": [{"dimension_name": d, "column_name": d, "data_type": "String"} for d in dimensions],
            "columns": [], "values": values, "limit": 100, "order_by": [], "filters": {"logical_operator": "And", "filters": []}}}).insert()
        items.append({"type": "chart", "chart": chart.name, "layout": {"i": chart.name, "x": 0, "y": len(items)*9, "w": 20, "h": 9}})
    frappe.get_doc({"doctype": "Insights Dashboard v3", "workbook": deployment.workbook, "title": title, "items": items}).insert()
