/* Direct document-page navigation for Univers Glass tasks, including existing ToDos. */
(() => {
 const routes = {'Sales Order':'workshop-cockpit','Chantier':'chantiers','Chantier Technical Study':'technical-study'};
 function href(doc) {
  if (!String(doc.description || '').startsWith('[Univers Glass — ') || !doc.reference_name) return null;
  const stockOrExport=doc.reference_type==='Sales Order'&&/^\[Univers Glass — (Sortie directe B|Export Sage B)\]/.test(doc.description||'');
  const route = stockOrExport?'sales-order':routes[doc.reference_type];
  return route ? `/app/${route}/${encodeURIComponent(doc.reference_name)}` : null;
 }
 frappe.ug_task_links = {href};
 function install() {
  const factory = frappe.widget?.widget_factory;
  if (!factory?.quick_list || factory.quick_list.ug_direct_links) return;
  frappe.listview_settings ||= {};
  const settings = frappe.listview_settings.ToDo ||= {};
  settings.add_fields = [...new Set([...(settings.add_fields || []),'description','reference_type','reference_name'])];
  const Base = factory.quick_list;
  class TaskQuickList extends Base {
   setup_quick_list_item(doc) {
    const item = super.setup_quick_list_item(doc);
    const target = this.document_type === 'ToDo' && href(doc);
    if (!target) return item;
    item.find('.title').wrapInner($('<a>').attr('href',target));
    item.off('click').on('click', event => {
     event.preventDefault();
     if (event.ctrlKey || event.metaKey) window.open(target,'_blank','noopener,noreferrer');
     else frappe.set_route(target);
    });
    return item;
   }
  }
  TaskQuickList.ug_direct_links = true;
  factory.quick_list = TaskQuickList;
 }
 install();
 $(install);
 frappe.router?.on('change',install);
})();
