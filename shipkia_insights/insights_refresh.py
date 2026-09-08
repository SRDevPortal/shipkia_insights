"""Five-minute reporting refresh for the two explicitly configured local CRM tables."""

import frappe

TABLES = ("tabLead", "tabCustomer")


def refresh():
	if "insights" not in frappe.get_installed_apps():
		return
	if frappe.db.table_exists("ShipKia Insights Deployment") and frappe.db.exists("ShipKia Insights Deployment", {"enabled": 1, "crm_source": "Site DB"}):
		return
	from shipkia_insights.importer import WarehouseTable
	for table in TABLES:
		row = frappe.db.get_value("Insights Table v3", {"data_source": "Site DB", "table": table},
			["stored", "sync_mode", "sync_strategy"], as_dict=True)
		if row and row.stored and row.sync_mode == "Incremental" and row.sync_strategy == "Update or Insert":
			WarehouseTable("Site DB", table).enqueue_import()
