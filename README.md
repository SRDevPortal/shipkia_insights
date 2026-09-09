# ShipKia Insights

Portable reporting profiles, models, Marketing/Sales KPIs, dashboards and
incremental warehouse imports. Requires ERPNext, Insights and shipkia_lead.

Use Frappe/ERPNext v15 and Insights v3. The Cloud compatibility declaration
includes Frappe 15.120.0. A clean site with Frappe 15.116.0, ERPNext 15.118.0,
Insights 3.12.2 and only the two ShipKia apps passed installation, migration,
repeated setup and 87 combined tests on 2026-09-09. Runtime execution on
15.120.0 is not covered by that local run.

`test_installation` checks reporting columns, deployment links and registration
of the warehouse importer override. Fresh sites safely have no scheduled
reporting work until data sources and deployment profiles are configured.

Install using `bench --site SITE install-app shipkia_insights`, then restart the
web, scheduler and worker processes so they load the new Python package.
The existing ShipKia Insights Deployment DocType remains unchanged in name and
moves to this app's module. Existing source credentials, snapshots and workbooks
are retained. Reporting implementation is shipkia_insights.reporting; KPI logic
is shipkia_insights.shipkia_kpis.

## Import extension

shipkia_insights.importer subclasses the installed Insights WarehouseTableImporter
and adds inclusive upsert watermark replay plus primary-key tie-breaking for
rows with equal timestamps. It uses the upstream writer, logs and storage format.
The supported override_doctype_class hook for Insights Table v3 routes its Import
button and data-store daily import through this importer. The custom reporting
schedules also call it directly. No upstream class is monkey-patched.

For initial imports or administrative scripts, use
shipkia_insights.importer.execute_warehouse_table_import(data_source, table_name).
Direct calls to upstream importer functions and the upstream query builder's
missing-snapshot fallback remain upstream behavior; initialize snapshots using
this app before opening queries. Do not depend on that fallback for ShipKia imports.

The extension was tested against installed Insights 3.12.2. Its base importer API
is an integration dependency: run the importer/query tests when upgrading Insights.
Report definitions contain source bindings, not passwords or endpoint credentials.
See shipkia_insights/SHIPKIA_INSIGHTS.md for production setup and KPI definitions.

Tests: shipkia_insights.test_incremental_paging, test_shipkia_insights and
test_shipkia_kpis. Existing workbooks are not recreated by the ownership migration.
