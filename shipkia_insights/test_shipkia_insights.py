from unittest import TestCase
from unittest.mock import patch
import json
import frappe
from shipkia_insights import reporting


class TestShipKiaInsights(TestCase):
    def profile(self):
        return frappe._dict(environment="Production", crm_source="CRM Prod", application_source="Panel Prod", billing_source=None)

    def test_bindings_are_portable_and_billing_is_optional(self):
        with patch.object(frappe.db, "get_value", return_value="public"):
            pack = reporting.build_pack(self.profile())
        source_ids = {q["operations"][0]["table"]["data_source"] for q in pack["dependencies"]["queries"].values()}
        self.assertEqual(source_ids, {"CRM Prod", "Panel Prod"})
        self.assertNotIn("Billing", pack["dependencies"]["dashboards"])
        self.assertNotIn("192.168.", json.dumps(pack))
        self.assertTrue(all(q["use_live_connection"] == 0 for q in pack["dependencies"]["queries"].values()))

    def test_paise_conversion_and_currency_grouping(self):
        with patch.object(frappe.db, "get_value", return_value="public"):
            pack = reporting.build_pack(self.profile())
        ops = pack["dependencies"]["queries"]["wallet_transactions"]["operations"]
        self.assertTrue(any(op.get("expression", {}).get("expression") == "amount / 100.0" for op in ops))
        balance = next(c for c in pack["dependencies"]["charts"].values() if c["query"] == "wallets")
        self.assertEqual(balance["config"]["rows"][0]["column_name"], "currency")

    def test_changed_endpoint_is_rejected(self):
        profile = self.profile()
        profile.source_fingerprints = json.dumps({"CRM Prod": "old", "Panel Prod": "old"})
        with patch.object(reporting, "fingerprint", return_value="changed"), self.assertRaises(frappe.ValidationError):
            reporting.check_bindings(profile)

    def test_sensitive_tables_and_payloads_are_not_in_pack(self):
        models = reporting.models()
        tables = {m["table"] for m in models.values()}
        self.assertFalse(tables & {"sessions", "users", "bank_accounts"})
        for model in models.values():
            self.assertIn(model["key"], model["columns"])
            self.assertIn(model["cursor"], model["columns"])
            self.assertFalse(set(model["columns"]) & {"password", "payload", "attachments"})
