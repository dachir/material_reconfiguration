(() => {
 const settings = frappe.listview_settings.ToDo;
 const originalLink = settings.get_form_link;
 settings.get_form_link = doc => frappe.ug_task_links?.href(doc)
  || (originalLink ? originalLink(doc) : frappe.utils.get_form_link('ToDo',doc.name));
 const originalAction = settings.button?.action;
 if (settings.button) settings.button.action = doc => {
  const target = frappe.ug_task_links?.href(doc);
  if (target) frappe.set_route(target);
  else originalAction?.(doc);
 };
})();
