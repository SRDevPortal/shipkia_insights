import frappe
from frappe.model.document import Document


class ShipKiaInsightsDeployment(Document):
    def validate(self):
        before = self.get_doc_before_save()
        if before and before.workbook:
            for field in ("environment", "crm_source", "application_source", "billing_source", "account_connection"):
                if self.has_value_changed(field):
                    frappe.throw("Create a new deployment profile to change environments or source bindings. Existing reports and snapshots are preserved.")
