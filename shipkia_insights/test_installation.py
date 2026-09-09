"""Checks that run on a clean ERPNext/Insights/Shipkia installation."""
from unittest import TestCase

import frappe
from frappe.model.base_document import get_controller
from shipkia_insights import reporting
from shipkia_insights.importer import InsightsTable


class TestInstallation(TestCase):
    def test_reporting_columns_exist_in_local_erpnext_schema(self):
        for model in reporting.models().values():
            if model['source'] != 'crm':
                continue
            with self.subTest(table=model['table']):
                columns = set(frappe.db.get_table_columns(model['table'][3:]))
                self.assertFalse(set(model['columns']) - columns)

    def test_deployment_links_resolve_to_installed_doctypes(self):
        for field in frappe.get_meta('ShipKia Insights Deployment').fields:
            if field.fieldtype == 'Link':
                with self.subTest(field=field.fieldname):
                    self.assertTrue(frappe.db.exists('DocType', field.options))

    def test_warehouse_importer_override_is_registered(self):
        self.assertIs(get_controller('Insights Table v3'), InsightsTable)
