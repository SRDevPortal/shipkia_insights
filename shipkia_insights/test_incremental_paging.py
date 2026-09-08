from unittest import TestCase
from unittest.mock import Mock

import frappe
import ibis
import pandas as pd

from shipkia_insights.importer import WarehouseTableImporter


class TestIncrementalPaging(TestCase):
    def setUp(self):
        self.db = ibis.duckdb.connect()
        frame = pd.DataFrame({"name": ["a", "b", "c", "d", "e"],
            "modified": pd.to_datetime(["2026-01-01"] * 4 + ["2026-01-02"])})
        self.table = self.db.create_table("records", frame)
        self.importer = WarehouseTableImporter(Mock())
        self.importer.remote_table = self.table
        self.importer.cursor_column = "modified"
        self.importer.dedupe_key_column = "name"
        self.importer._log = Mock()

    def tearDown(self):
        self.db.disconnect()

    def test_equal_timestamps_cross_batch_boundary(self):
        names = []
        def insert(batch):
            names.extend(batch.execute()["name"].tolist())
            return batch
        writer = Mock()
        writer.insert.side_effect = insert
        self.assertEqual(self.importer.process_batches(2, writer), 5)
        self.assertEqual(names, ["a", "b", "c", "d", "e"])

    def test_upsert_rechecks_watermark_boundary(self):
        self.importer.settings = frappe._dict(sync_cursor_column="modified",
            sync_primary_key_column="name", sync_strategy="Update or Insert")
        self.importer._apply_before_import_script = Mock()
        self.importer._resolve_incremental_bookmark = Mock(return_value="2026-01-01")
        self.importer._prepare_incremental_table()
        self.assertEqual(self.importer.remote_table.count().execute(), 5)
