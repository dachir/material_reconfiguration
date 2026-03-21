app_name = "mat_reco"
app_title = "Material Reconfiguration"
app_publisher = "Richard Amouzou"
app_description = "This app purpose is to help splitting an item into chunck"
app_email = "dodziamouzou@gmail.com"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "mat_reco",
# 		"logo": "/assets/mat_reco/logo.png",
# 		"title": "Material Reconfiguration",
# 		"route": "/mat_reco",
# 		"has_permission": "mat_reco.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/mat_reco/css/app.css"
# app_include_js = "/assets/mat_reco/js/mat_reco.js"

# include js, css files in header of web template
# web_include_css = "/assets/mat_reco/css/mat_reco.css"
# web_include_js = "/assets/mat_reco/js/mat_reco.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "mat_reco/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
doctype_js = {
    "Delivery Note": "public/js/dimension_from_serial.js",
    "Sales Invoice": "public/js/dimension_from_serial.js",
    "Stock Entry": "public/js/stock_entry_repack_from_so.js",
}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "mat_reco/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "mat_reco.utils.jinja_methods",
# 	"filters": "mat_reco.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "mat_reco.install.before_install"
# after_install = "mat_reco.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "mat_reco.uninstall.before_uninstall"
# after_uninstall = "mat_reco.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "mat_reco.utils.before_app_install"
# after_app_install = "mat_reco.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "mat_reco.utils.before_app_uninstall"
# after_app_uninstall = "mat_reco.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "mat_reco.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
    "Stock Entry": {
        "validate": "mat_reco.stock_hooks.stock_entry_validate",
        "before_submit": "mat_reco.stock_hooks.stock_entry_before_submit"
    },
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
}

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"mat_reco.tasks.all"
# 	],
# 	"daily": [
# 		"mat_reco.tasks.daily"
# 	],
# 	"hourly": [
# 		"mat_reco.tasks.hourly"
# 	],
# 	"weekly": [
# 		"mat_reco.tasks.weekly"
# 	],
# 	"monthly": [
# 		"mat_reco.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "mat_reco.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "mat_reco.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "mat_reco.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["mat_reco.utils.before_request"]
# after_request = ["mat_reco.utils.after_request"]

# Job Events
# ----------
# before_job = ["mat_reco.utils.before_job"]
# after_job = ["mat_reco.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"mat_reco.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

fixtures = [
    {"dt": "Custom Field", "filters": [["module", "=", "Material Reconfiguration"]]},
    {"dt": "Client Script", "filters": [["enabled", "=", 1],["module", "=", "Material Reconfiguration"]]},
    {"dt": "Server Script", "filters": [["disabled", "=", 0],["module", "=", "Material Reconfiguration"]]},
    {"dt": "Print Format", "filters": [["disabled", "=", 0],["module", "=", "Material Reconfiguration"]]},
]