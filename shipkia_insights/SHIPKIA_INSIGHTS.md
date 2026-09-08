# ShipKia portable reporting pack

## What is installed

Testing profile: ShipKia Testing. Workbook: ShipKia Business Insights - Testing.
Ten reporting datasets, thirteen reusable queries, six dashboards and 28 charts.
Marketing, Sales, Activation and Orders, Wallet Activity, Support, Customer Journey.
Read-only source connections; reporting queries use Insights warehouse snapshots.
Initial verification matched 29 leads, 14 CRM customers, 30 panel accounts,
2,100 orders, 20 wallets, 8,081 wallet transactions, 29 recharges, 13 tickets,
19 comments and 3 stores. Counts describe the testing snapshot, not production.

Table definitions live in shipkia_insights_models.json. Queries and charts are
built from source bindings by shipkia_insights.py. Passwords/hosts are never
embedded in the report definitions. API credentials remain in Insights sources.
Postgres UUID transaction IDs are cast to text for warehouse compatibility.
Amounts supplied in paise are divided by 100 in queries, not in source data.
Wallet balances are grouped by currency. Wallet movements and order values are
not presented as accounting revenue.

## Production deployment

1. Deploy the ERPNext/Insights code changes and run site migration (this installs
   ShipKia Insights Deployment and scheduler hooks).
2. Create fresh Insights data-source records for the production CRM and Postgres
   databases, using read-only credentials. Set the Postgres schema and refresh
   table lists. Do not overwrite the endpoints of already-imported Testing sources.
3. Install the same pack with production bindings:

   bench --site YOUR_SITE execute shipkia_insights.reporting.install --kwargs '{"profile":"ShipKia Production","environment":"Production","crm_source":"CRM Production","application_source":"ShipKia Application Production","account_connection":"ShipKia Production"}'

   Substitute actual Insights source names and the CRM ShipKia connection name.
   On a dedicated production ERP, crm_source can be its existing Site DB source.
   On a shared test/production analytics site, use separate source records for
   each environment. The installer refuses cross-environment source reuse.
4. Run initial imports for the configured models. Inspect Insights Table Import
   Logs, compare row counts and key uniqueness, execute the workbook queries,
   and review customer mappings. Schema validation fails clearly for missing
   required columns. No billing source is assumed to exist.
5. Enable Automatic Refresh on the production deployment. Five-minute cron queues
   incremental upserts with duplicate-job protection. Verify imports complete
   within the required freshness window, and test dashboard access for each team.

The installer is idempotent for an existing profile. A new profile creates a new
workbook; existing reports and source records are not deleted or overwritten.
Credentials can rotate without rebuilding reports. Endpoint/schema changes require
fresh source records and a new profile so cached testing rows cannot enter production.
An endpoint fingerprint mismatch pauses that profile's automatic imports.
Changing connections alone is sufficient for the generated reporting logic only
when production matches the tested schema and meanings of fields. Initial imports
and validation are still required before enabling the production reports.

## Billing module

Optional billing_source adds Sales Invoice and Payment Entry models and a Billing
dashboard. It expects a connected ERP database with those standard tables. If
accounts.shipkia.com is available only through API, a separate API ingestion mapping
must first populate the expected reporting tables; URL alone is insufficient.
Billing templates have not been executed against that external site. Revenue
recognition, tax treatment and company currency definitions require finance review.

## Definitions and limits

- Source/channel charts measure lead counts; campaign spend, CAC and ROAS are not
  available until advertising cost data and attribution rules are connected.
- Sales charts show current owner/status, not historic ownership or sales credit.
- Customer Journey joins exact recorded CUST IDs within the selected CRM ShipKia
  environment. Unlinked IDs remain unmatched; no fuzzy financial joins are made.
- Orders are aggregated per customer before the account join. Account rows must
  remain one row per account. Order totals are not multiplied by lead duplicates.
- Ticket counts/stages/comments are available. First-response and resolution SLA
  metrics need validated actor/status semantics and reliable event timestamps.
- Incremental timestamps do not detect hard deletions or edits that fail to update
  the cursor. Reconciliation/deletion handling and late-commit policy must be
  established before production. Comment imports use created_at; comment edits
  need an updated_at field or reconciliation to appear.
- Five minutes is an import schedule, not a guaranteed end-to-end freshness SLA.
  Insights Data Store shows last successful sync; Table Import Logs show failures.
  An open dashboard currently needs its Refresh button to force fresh chart queries;
  automatic browser refresh and a dashboard freshness banner are not included.
- This pilot uses the local Insights warehouse and long worker queue. A dedicated
  production analytics host/worker and load test are still required for isolation.
- No public sharing or additional user access has been granted by this setup.

## Verification

Four portable-pack tests cover source binding, optional billing, paise conversion,
currency grouping, endpoint mismatch and sensitive-field exclusions. Two earlier
warehouse tests cover duplicate timestamps at batch boundaries and watermark replay.
All 28 generated chart aggregations executed on stored data. Initial source/warehouse
counts and unique keys match for all ten datasets. Reinstall reuses the workbook.
Private validation: private/files/insights-rollout/reporting-pack-validation.json.
These are backend/query checks; a browser visual/access review remains required.

## Marketing and sales KPI update

Run `install_kpis(deployment)` from shipkia_insights.shipkia_kpis, or reinstall the
existing profile through shipkia_insights.install. This replaces the displayed
Marketing/Sales layouts with the KPI suite, preserving previous chart/query
records. The prior dashboard layout is backed up once per profile under
private/files/insights-rollout/before-marketing-sales-*.json.

The suite adds 16 queries and 19 chart views. Queries use stored snapshots only;
no additional API calls or source sync schedules are introduced. Bindings are
resolved from the deployment for production reuse. Native SQL uses quoted
Insights table identifiers (for example "public.wallet_transactions") rather
than live PostgreSQL qualified references; keep use_live_connection disabled.

Revenue basis here means wallet recharge funding, not recognized accounting
revenue. Exact wallet categories: Recharge and COD Remittance Recharge. Other
credits (claim, freight reversals, etc.) are excluded. Credit amounts retain their
sign; debit amounts in those categories subtract their absolute amount. Amounts
are divided by 100. A positive credit establishes a paying customer/acquisition.
Currency comes from the matching wallet ID and customer ID; missing wallets show
Unknown. Recharge and remittance source tables are not added again to totals.

Marketing:
- Observed recharge LTV = cumulative net eligible recharges / customers with a
  positive eligible credit, by currency; not projected lifetime billing revenue.
- Average recharge per customer = period net eligible recharge / distinct
  customers with positive eligible credits that period, by currency.
- Monthly retention = customers ordering in both months / prior-month ordering
  customers. Includes all recorded orders regardless of stage; no delivery or
  cancellation semantics are inferred. New customers do not enter the numerator
  unless they were also active previously. Empty denominator returns NULL.
- Cohorts group customers by first positive recharge month. Cumulative values are
  observed-to-date and have different cohort ages; these are not cohort ROAS.
- CAC, recharge ROAS and cohort ROAS show an unavailable explanation. Google Ads
  Campaign KPI and Meta Marketing KPI each had zero records when checked. Ad
  attribution and eligible acquisition spend must be linked before computing them.
  Billing-based revenue LTV/ARPC/ROAS still await accounting integration.

Sales:
- Agent mapping uses current Lead.lead_owner within the configured ShipKia
  environment; repeated same-owner mappings deduplicate. Conflicting owners
  remain in a separate bucket, and accounts without CRM links are Unmapped.
- Customer and order totals are aggregated before joins to avoid multiplying
  recharge transactions by order counts. Currency remains a grouping dimension.
- Customer growth compares new panel-account signups, not cumulative customer stock.
- Week (Monday start), month and calendar-quarter series show the last 12 completed
  UTC periods. No incomplete period is compared against a full prior period.
- Growth = (current - previous)/previous * 100. Zero/missing baselines return NULL,
  and empty periods are present as zeros. Customer-level growth is monthly.
- New period-comparison views use fixed windows documented on the dashboard;
  they do not inherit the previous generic dashboard date-range filter.

Validation: four synthetic tests cover exact category exclusions, credit/debit
handling, paise conversion, two-customer LTV, order-count join safety, cohort totals,
new-customer exclusion from retention, zero periods/baselines and query execution.
All 16 KPI queries and all 19 chart aggregations executed successfully against
local snapshots. No browser visual test was performed. Report:
private/files/insights-rollout/marketing-sales-validation.json.
