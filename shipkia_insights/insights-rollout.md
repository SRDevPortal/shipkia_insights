# Insights reporting rollout

Local development setup: Site DB is the existing Insights v3 connection.
Lead and Customer are stored in the Insights DuckDB reporting store and refreshed
by shipkia_insights.insights_refresh.refresh every five minutes. Imports use modified
as the cursor and name as the upsert key, beginning at 1970-01-01. The native
import worker deduplicates overlapping queued jobs. No external connection was
created and no credentials were copied.

Warehouse paging now uses the primary key to disambiguate equal timestamps.
Upserts include the watermark boundary to safely replay rows at that timestamp.
Two regression tests cover both cases. Local source/reporting row counts match:
29 leads and 14 customers at setup; repeat imports did not introduce duplicates.
Validation output is in private/files/insights-rollout/local-crm-validation.json.

This is a local pilot using the existing reporting store, not deployment of a
separate production reporting server. External application database type/access
and billing ERP URL/access are pending. Dashboards and automatic browser refresh
have not yet been built. Five minutes is the scheduled import interval; completion
also depends on worker availability and import duration.

Before production rollout: assess volumes, isolate reporting resources, configure
access, handle deletion reconciliation and late commits older than the watermark,
and validate monetary definitions/customer mapping. Incremental imports alone do
not remove physically deleted source rows. No source records were deleted.

## Confirmed external sources

- ShipKia application: PostgreSQL. Host, port, database, schema, read-only access and network reachability are pending.
- Billing ERP: https://accounts.shipkia.com/. Read-only database/replica access or authenticated Frappe API access is pending.
- Neither external connection is configured or verified yet. Enter credentials through protected configuration fields, not this document.
