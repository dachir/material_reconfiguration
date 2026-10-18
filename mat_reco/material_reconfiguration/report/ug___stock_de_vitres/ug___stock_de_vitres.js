frappe.query_reports['UG - Stock de Vitres'] = {
 filters: [
  {fieldname:'stock_type',label:'Type de stock',fieldtype:'Select',options:'Les deux\nPlaques\nChutes',default:'Les deux',reqd:1},
  {fieldname:'primary_item',label:'Article primaire',fieldtype:'Link',options:'Item',get_query:()=>({filters:{custom_item_types:'PRIMAIRE'}})},
  {fieldname:'company',label:'Société',fieldtype:'Link',options:'Company'},
  {fieldname:'warehouse',label:'Dépôt',fieldtype:'Link',options:'Warehouse',get_query:()=>({filters:{is_group:0,...(frappe.query_report.get_filter_value('company')?{company:frappe.query_report.get_filter_value('company')}: {})}})},
  {fieldname:'detail',label:'Présentation',fieldtype:'Select',options:'Synthèse\nDétail par série',default:'Synthèse',reqd:1}
 ],
 onload(report) {
  report.page.add_inner_button('Imprimer le stock',()=>report.print_report({orientation:'Landscape',include_filters:1}));
  report.page.add_inner_button('Retour au cockpit',()=>frappe.set_route('workshop-cockpit'));
 },
 formatter(value,row,column,data,default_formatter) {
  const formatted=default_formatter(value,row,column,data);
  return data?.item_name==='TOTAL'?'<strong>'+formatted+'</strong>':formatted;
 }
};
