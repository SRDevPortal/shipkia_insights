"""ShipKia importer extension; upstream Insights remains unmodified."""
import frappe
import ibis
from ibis import _
from insights.insights.doctype.insights_data_source_v3.data_warehouse import WarehouseTable as BaseTable, WarehouseTableImporter as BaseImporter, WarehouseTableWriter
from insights.insights.doctype.insights_table_v3.insights_table_v3 import InsightsTablev3 as BaseDocument
from frappe.utils.background_jobs import is_job_enqueued

class WarehouseTableImporter(BaseImporter):
    def _prepare_incremental_table(self) -> None:
        self.cursor_column = self.settings.sync_cursor_column
        self.dedupe_key_column = self.settings.sync_primary_key_column
        self.sync_strategy = self.settings.sync_strategy or "Append Only"

        self._apply_before_import_script()

        bookmark = self._resolve_incremental_bookmark()
        self._log(f"Incremental sync: {self.cursor_column} > {bookmark}")
        # Upsert can safely reread the boundary timestamp, including late arrivals.
        predicate = (_[self.cursor_column] >= bookmark) if self.sync_strategy == "Update or Insert" else (_[self.cursor_column] > bookmark)
        self.remote_table = self.remote_table.filter(predicate)

        self.writer_mode = "upsert" if self.sync_strategy == "Update or Insert" else "append"

    def process_batches(self, batch_size: int, writer: WarehouseTableWriter) -> int:
        remote_table = self.remote_table
        if self.cursor_column:
            ordering = [ibis.asc(self.cursor_column, nulls_first=True)]
            if self.dedupe_key_column:
                ordering.append(ibis.asc(self.dedupe_key_column))
            remote_table = remote_table.order_by(*ordering)

        batch_number = 0
        total_rows = 0

        while True:
            self._log(f"Processing batch: {batch_number + 1}")
            batch = remote_table.head(batch_size)
            self._log(f"Batch Query: \n{ibis.to_sql(batch)}")

            batch = writer.insert(batch)

            batch_count = int(batch.count().execute())
            total_rows += batch_count

            self._log(f"Rows: {batch_count} Total Rows: {total_rows}")

            if batch_count < batch_size or not self.cursor_column:
                break

            last_cursor = batch[self.cursor_column].max().execute()
            self._log(f"Bookmark: {last_cursor}")
            after = _[self.cursor_column] > last_cursor
            if self.dedupe_key_column:
                last_key = batch.filter(batch[self.cursor_column] == last_cursor)[self.dedupe_key_column].max().execute()
                after = after | ((_[self.cursor_column] == last_cursor) & (_[self.dedupe_key_column] > last_key))
            remote_table = remote_table.filter(after)
            batch_number += 1

        self._log(f"Total Batches: {batch_number + 1} Total Rows: {total_rows}")
        return total_rows

    def enqueue_import(self):
        job_id = f"import_{frappe.scrub(self.table.data_source)}_{frappe.scrub(self.table.table_name)}"
        if is_job_enqueued(job_id) or self.import_in_progress():
            return
        frappe.enqueue("shipkia_insights.importer.execute_warehouse_table_import", data_source=self.table.data_source,
            table_name=self.table.table_name, queue="long", timeout=1800, job_id=job_id, deduplicate=True)

class WarehouseTable(BaseTable):
    def enqueue_import(self):
        if frappe.db.get_value("Insights Data Source v3", self.data_source, "type") == "REST API":
            frappe.throw("Import not supported for API data sources")
        WarehouseTableImporter(self).enqueue_import()

class InsightsTable(BaseDocument):
    @frappe.whitelist()
    def import_to_warehouse(self):
        frappe.only_for("Insights Admin")
        WarehouseTable(self.data_source, self.table).enqueue_import()

def execute_warehouse_table_import(data_source, table_name):
    WarehouseTableImporter(WarehouseTable(data_source, table_name)).start_import()
