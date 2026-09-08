app_name = "shipkia_insights"
app_title = "Shipkia Insights"
app_publisher = "ShipKia"
app_description = "ShipKia custom integrations"
app_email = "admin@shipkia.com"
app_license = "MIT"
required_apps = ['erpnext', 'insights', 'shipkia_lead']

override_doctype_class = {"Insights Table v3": "shipkia_insights.importer.InsightsTable"}
scheduler_events = {"cron": {"*/5 * * * *": ["shipkia_insights.insights_refresh.refresh", "shipkia_insights.reporting.refresh"]}}
