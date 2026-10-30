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
app_include_js = ["/assets/mat_reco/js/ug_task_links.js"]

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
    "Quotation": "public/js/chantier_commercial.js",
    "Sales Order": ["public/js/chantier_commercial.js","public/js/order_b_actions.js"],
    "Delivery Note": "public/js/dimension_from_serial.js",
    "Sales Invoice": "public/js/dimension_from_serial.js",
    "Stock Entry": "public/js/stock_entry_repack_from_so.js",
}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
doctype_list_js = {"ToDo": "public/js/ug_todo_list.js"}
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
    "Material Cutting Plan": {
        "on_update": ["mat_reco.material_reconfiguration.services.workshop_service.notify_stock_change", "mat_reco.material_reconfiguration.services.chantier_service.mark_chantier_used"],
        "on_cancel": "mat_reco.material_reconfiguration.services.workshop_service.notify_stock_change",
        "before_submit": "mat_reco.material_reconfiguration.services.task_notifications.lock_workshop_validation",
        "on_submit": [
            "mat_reco.material_reconfiguration.services.workshop_service.notify_stock_change",
            "mat_reco.material_reconfiguration.services.task_notifications.mcp_submitted",
        ],
    },
    "Stock Ledger Entry": {
        "after_insert": "mat_reco.material_reconfiguration.services.glass_stock.notify_stock_change",
    },
    **{dt: {event: "mat_reco.material_reconfiguration.services.workshop_service.notify_stock_change"
            for event in ("on_submit", "on_cancel")}
       for dt in ("Workshop Refabrication", "Stock Reservation Entry", "Sales Order", "Delivery Note")},
    "Sales Order": {
        "before_naming": "mat_reco.material_reconfiguration.services.sales_order_types.before_naming",
        "after_insert": "mat_reco.material_reconfiguration.services.chantier_service.mark_chantier_used",
        "on_update": "mat_reco.material_reconfiguration.services.workshop_service.notify_stock_change",
        "after_mapping": "mat_reco.material_reconfiguration.services.chantier_service.map_chantier",
        "validate": ["mat_reco.material_reconfiguration.services.order_b.validate_order", "mat_reco.material_reconfiguration.services.sales_order_types.validate", "mat_reco.material_reconfiguration.services.chantier_service.validate_commercial"],
        "before_update_after_submit": ["mat_reco.material_reconfiguration.services.order_b.validate_order", "mat_reco.material_reconfiguration.services.sales_order_types.validate", "mat_reco.material_reconfiguration.services.chantier_service.validate_commercial"],
        "before_cancel": "mat_reco.material_reconfiguration.services.chantier_service.protect_produced_order",
        "on_submit": ["mat_reco.material_reconfiguration.services.workshop_service.notify_stock_change", "mat_reco.material_reconfiguration.services.task_notifications.order_created"],
        "on_cancel": ["mat_reco.material_reconfiguration.services.workshop_service.notify_stock_change", "mat_reco.material_reconfiguration.services.task_notifications.order_cancelled"],
    },
    "Chantier Section": {"on_trash": "mat_reco.material_reconfiguration.services.ft_activation.guard_section_delete"},
    "Chantier": {"before_update_after_submit": "mat_reco.material_reconfiguration.services.ft_activation.validate_activation", "on_update_after_submit": "mat_reco.material_reconfiguration.services.ft_activation.after_chantier_update", "on_update": "mat_reco.material_reconfiguration.services.ft_activation.after_chantier_update", "on_submit": "mat_reco.material_reconfiguration.services.task_notifications.chantier_finished", "on_cancel": "mat_reco.material_reconfiguration.services.task_notifications.chantier_finished"},
    "Chantier Technical Study": {"after_insert": "mat_reco.material_reconfiguration.services.ft_activation.study_created", "on_trash": "mat_reco.material_reconfiguration.services.ft_activation.study_before_delete", "after_delete": "mat_reco.material_reconfiguration.services.ft_activation.study_deleted", "on_submit": "mat_reco.material_reconfiguration.services.task_notifications.study_finished", "on_cancel": "mat_reco.material_reconfiguration.services.task_notifications.study_finished"},
    "Quotation": {"validate": "mat_reco.material_reconfiguration.services.chantier_service.validate_commercial", "after_insert": "mat_reco.material_reconfiguration.services.chantier_service.mark_chantier_used"},
    "Stock Entry": {
        "before_validate": "mat_reco.stock_hooks.stock_entry_before_validate",
        "validate": "mat_reco.stock_hooks.stock_entry_validate",
        "before_submit": "mat_reco.stock_hooks.stock_entry_before_submit",
        "on_submit": "mat_reco.material_reconfiguration.services.workshop_service.notify_stock_change",
        "on_cancel": "mat_reco.material_reconfiguration.services.workshop_service.notify_stock_change"
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
override_doctype_dashboards = {
    "Sales Order": "mat_reco.material_reconfiguration.services.special_b.sales_order_dashboard"
}

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
    {"dt": "Property Setter", "filters": [["module", "=", "Material Reconfiguration"]]},
    {"dt": "Custom Field", "filters": [["module", "=", "Material Reconfiguration"]]},
    {"dt": "Client Script", "filters": [["enabled", "=", 1],["module", "=", "Material Reconfiguration"]]},
    {"dt": "Server Script", "filters": [["disabled", "=", 0],["module", "=", "Material Reconfiguration"]]},
    {"dt": "Print Format", "filters": [["disabled", "=", 0],["module", "=", "Material Reconfiguration"]]},
]

# Accounting Dimensions
# ---------------------
# Register the custom planning DocType so ERPNext creates the same dynamic
# Accounting Dimension fields (Branch, etc.) on it.
accounting_dimension_doctypes = [
    "Material Receipt Plan",
]

# Existing Accounting Dimensions may pre-date this app/hook, therefore sync the
# fields after migrate as well.
after_migrate = [
    "mat_reco.setup.sync_material_receipt_plan_accounting_dimensions",
    "mat_reco.material_reconfiguration.services.workshop_service.backfill_workshop_allocations",
]

# Native print/PDF reports shared by Vue document actions and Desk.
jinja = {"methods": ["mat_reco.printing.render_mat_reco_a4"]}
after_migrate.append("mat_reco.printing.install_print_formats")
after_install = "mat_reco.printing.install_print_formats"

after_migrate.append("mat_reco.material_reconfiguration.services.task_notifications.install_task_notifications")

after_migrate.extend(["mat_reco.material_reconfiguration.services.chantier_work_types.install_fields", "mat_reco.material_reconfiguration.services.chantier_work_types.migrate_draft_types"])

after_migrate.append("mat_reco.material_reconfiguration.services.chantier_service.backfill_chantier_usage")

after_migrate.append("mat_reco.material_reconfiguration.services.chantier_pricing.install_fields")

after_migrate.append("mat_reco.material_reconfiguration.services.sales_order_types.install")

after_migrate.append("mat_reco.material_reconfiguration.services.order_technical.install")

after_migrate.append("mat_reco.material_reconfiguration.services.order_b.install")
permission_query_conditions = {
    "Sales Order": "mat_reco.material_reconfiguration.services.order_b.query_conditions",
    "Chantier Technical Study": "mat_reco.material_reconfiguration.services.order_b.study_query_conditions",
}
has_permission = {
    "Sales Order": "mat_reco.material_reconfiguration.services.order_b.has_permission",
    "Chantier Technical Study": "mat_reco.material_reconfiguration.services.order_b.study_has_permission",
}
for _ug_dt in ('Delivery Note', 'Sales Invoice'):
    for _ug_event in ('validate', 'before_submit'):
        _ug_previous=doc_events.setdefault(_ug_dt,{}).get(_ug_event,[])
        if isinstance(_ug_previous,str):_ug_previous=[_ug_previous]
        doc_events[_ug_dt][_ug_event]=_ug_previous + ['mat_reco.material_reconfiguration.services.order_b.validate_downstream']

after_migrate.extend([
    "mat_reco.material_reconfiguration.services.order_b_stock.install",
    "mat_reco.material_reconfiguration.services.order_b_export.install",
])
for _ug_event in ('validate','before_submit'):
    _ug_previous=doc_events['Stock Entry'].get(_ug_event,[])
    if isinstance(_ug_previous,str):_ug_previous=[_ug_previous]
    doc_events['Stock Entry'][_ug_event]=_ug_previous+['mat_reco.material_reconfiguration.services.order_b_stock.validate_issue']
doc_events['Stock Entry']['before_cancel']='mat_reco.material_reconfiguration.services.order_b_stock.before_cancel'
for _ug_event in ('on_submit','on_cancel'):
    _ug_previous=doc_events['Stock Entry'][_ug_event]
    if isinstance(_ug_previous,str):_ug_previous=[_ug_previous]
    doc_events['Stock Entry'][_ug_event]=_ug_previous+['mat_reco.material_reconfiguration.services.order_b_stock.stock_updated']
for _ug_dt in ('Payment Entry','Journal Entry'):
    doc_events[_ug_dt]={_ug_event:'mat_reco.material_reconfiguration.services.order_b.validate_customer_entries' for _ug_event in ('validate','before_submit')}
for _ug_event in ('validate','before_update_after_submit'):
    doc_events['Sales Order'][_ug_event].append('mat_reco.material_reconfiguration.services.order_b_export.validate_order')

# Circuit B operational deliveries/receipts; no customer GL documents are created.
after_migrate.append('mat_reco.material_reconfiguration.services.special_b.install')
for _ug_special_dt in ('Bordereau Special','Reglement Special','Solde Initial Client B'):
    permission_query_conditions[_ug_special_dt]='mat_reco.material_reconfiguration.services.special_b.query_conditions'
    has_permission[_ug_special_dt]='mat_reco.material_reconfiguration.services.special_b.permission'
    doctype_js[_ug_special_dt]='public/js/special_b_forms.js'
permission_query_conditions['Bordereau Special']='mat_reco.material_reconfiguration.services.special_b.delivery_query_conditions'
permission_query_conditions['Reglement Special']='mat_reco.material_reconfiguration.services.special_b.payment_query_conditions'

# A special documents own their native delivery/invoice/payment lifecycle.
for _ug_dt in ('Delivery Note','Sales Invoice','Payment Entry'):
    for _ug_event in ('validate','before_submit','before_cancel','on_cancel','before_update_after_submit'):
        _ug_previous=doc_events.setdefault(_ug_dt,{}).get(_ug_event,[])
        if isinstance(_ug_previous,str):_ug_previous=[_ug_previous]
        doc_events[_ug_dt][_ug_event]=_ug_previous+['mat_reco.material_reconfiguration.services.special_a.guard_native']

# Prefill the operational warehouse for glass without restricting manual choices.
for _ug_warehouse_dt in ('Item', 'Quotation', 'Sales Order', 'Material Cutting Plan', 'Bordereau Special'):
    _ug_events = doc_events.setdefault(_ug_warehouse_dt, {})
    _ug_previous = _ug_events.get('before_validate', [])
    if isinstance(_ug_previous, str):
        _ug_previous = [_ug_previous]
    _ug_events['before_validate'] = _ug_previous + ['mat_reco.material_reconfiguration.services.ug_warehouse.apply_defaults']
after_migrate.append('mat_reco.material_reconfiguration.services.ug_warehouse.install_defaults')

override_doctype_class = {
    'Stock Reservation Entry': 'mat_reco.overrides.stock_reservation_entry.UGStockReservationEntry'
}
after_migrate.append('mat_reco.material_reconfiguration.services.production_reservations.install')
_ug_previous = doc_events['Stock Entry']['before_cancel']
doc_events['Stock Entry']['before_cancel'] = [
    _ug_previous, 'mat_reco.material_reconfiguration.services.production_reservations.before_cancel_production'
]
for _ug_event in ('on_submit', 'on_cancel'):
    doc_events['Stock Entry'][_ug_event].append('mat_reco.material_reconfiguration.services.production_reservations.stock_updated')
