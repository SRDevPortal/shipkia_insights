from unittest import TestCase
from unittest.mock import patch
import duckdb
import frappe
import sqlglot

from shipkia_insights.shipkia_kpis import sql_models


class TestShipKiaKPIs(TestCase):
    def setUp(self):
        self.db = duckdb.connect()
        self.db.execute('CREATE TABLE "public.wallet_transactions" (id VARCHAR, customer_id VARCHAR, wallet_id INT, created_at TIMESTAMPTZ, category VARCHAR, type VARCHAR, amount BIGINT)')
        self.db.execute('CREATE TABLE "public.wallet" (id INT, customer_id VARCHAR, currency VARCHAR)')
        self.db.execute('CREATE TABLE "public.customers" (id VARCHAR, company_name VARCHAR, currency VARCHAR, created_at TIMESTAMPTZ)')
        self.db.execute('CREATE TABLE "public.order_details" (id VARCHAR,customer_id VARCHAR,created_at TIMESTAMPTZ,stage VARCHAR)')
        self.db.execute("INSERT INTO \"public.wallet\" VALUES (1,'a','INR'),(2,'b','INR'),(3,'c','INR')".replace('\"','"'))
        self.db.execute("INSERT INTO \"public.customers\" VALUES ('a','A','INR','2026-01-01'),('b','B','INR','2026-01-01'),('c','C','INR','2026-02-01')".replace('\"','"'))
        self.db.executemany('INSERT INTO "public.wallet_transactions" VALUES (?,?,?,?,?,?,?)', [
            ('1','a',1,'2026-01-01','Recharge','credit',10000),
            ('2','a',1,'2026-01-02','COD Remittance Recharge','credit',20000),
            ('3','a',1,'2026-01-03','Recharge','debit',1000),
            ('4','a',1,'2026-01-04','Freight charge','credit',900000),
            ('5','b',2,'2026-02-03','Recharge','credit',3000)])
        self.db.executemany('INSERT INTO "public.order_details" VALUES (?,?,?,?)', [
            ('1','a','2026-01-01','Delivered'),('2','b','2026-01-02','New'),
            ('3','a','2026-02-01','Delivered'),('4','c','2026-02-02','New')])
        with patch.object(frappe.db, 'get_value', return_value='public'):
            self.queries=sql_models(frappe._dict(application_source='app'))

    def tearDown(self):
        self.db.close()

    def result(self,title):
        sql=self.queries[title].replace('CURRENT_TIMESTAMP', "CAST('2026-04-15 12:00:00+00' AS TIMESTAMPTZ)")
        sql=sqlglot.transpile(sql,read='postgres',write='duckdb')[0]
        return self.db.execute(sql).fetchdf()

    def test_wallet_only_totals_reversals_and_paise(self):
        data=self.result('Observed Recharge LTV').iloc[0]
        self.assertEqual(data.net_recharges,320)
        self.assertEqual(data.paying_customers,2)
        self.assertEqual(data.observed_recharge_ltv,160)
        customer=self.result('Customer Recharge and Orders').set_index('customer_id')
        self.assertEqual(customer.loc['a','total_recharge'],290)
        self.assertEqual(customer.loc['a','orders'],2)
        self.assertEqual(customer.loc['c','total_recharge'],0)

    def test_retention_excludes_new_customers(self):
        data=self.result('Monthly Order Retention')
        feb=data[data.period.dt.month.eq(2) & data.period.dt.year.eq(2026)].iloc[0]
        self.assertEqual(feb.previous_active_customers,2)
        self.assertEqual(feb.retained_customers,1)
        self.assertEqual(feb.retention_pct,50)

    def test_growth_fills_zero_periods_and_avoids_divide_by_zero(self):
        data=self.result('Month Customer and Order Growth')
        jan=data[data.period.dt.month.eq(1) & data.period.dt.year.eq(2026)].iloc[0]
        self.assertTrue(__import__('pandas').isna(jan.order_growth_pct))
        march=data[data.period.dt.month.eq(3) & data.period.dt.year.eq(2026)].iloc[0]
        self.assertEqual(march.orders,0)
        self.assertEqual(march.order_growth_pct,-100)
        self.assertFalse((data.period.dt.month.eq(4) & data.period.dt.year.eq(2026)).any())

    def test_all_application_queries_execute_and_cohorts_reconcile(self):
        for title in self.queries:
            self.result(title)
        data=self.result('Recharge Acquisition Cohorts')
        self.assertEqual(data.cumulative_recharges.sum(),320)
        self.assertEqual(data.acquired_paying_customers.sum(),2)
