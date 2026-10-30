frappe.query_reports['Suivi commandes'] = {
 filters: [
  {fieldname:'order_type',label:__('Type de commande'),fieldtype:'Select',options:[{value:'All',label:__('A + B')},{value:'A',label:'A'},{value:'B',label:'B'}],default:'All',on_change(report){
   if(report.get_filter_value('sales_order'))return report.set_filter_value('sales_order','');
   if(!report._no_refresh)return report.refresh(true);
  }},
  {fieldname:'company',label:__('Société'),fieldtype:'Link',options:'Company',default:frappe.defaults.get_user_default('Company')},
  {fieldname:'customer',label:__('Client'),fieldtype:'Link',options:'Customer'},
  {fieldname:'from_date',label:__('Du'),fieldtype:'Date'},
  {fieldname:'to_date',label:__('Au'),fieldtype:'Date'},
  {fieldname:'sales_order',label:__('Commande'),fieldtype:'Link',options:'Sales Order',get_query:()=>{
   const type=frappe.query_report.get_filter_value('order_type');
   const filters={};
   for(const field of ['company','customer','currency']){
    const value=frappe.query_report.get_filter_value(field);if(value)filters[field]=value;
   }
   if(type==='B')filters.custom_ug_order_type='B';
   if(type==='A')return {filters,or_filters:[['custom_ug_order_type','=','A'],['custom_ug_order_type','=',''],['custom_ug_order_type','is','not set']]};
   return {filters};
  }},
  {fieldname:'currency',label:__('Devise'),fieldtype:'Link',options:'Currency'},
  {fieldname:'stage',label:__('Étape'),fieldtype:'Select',options:'\nBrouillon\nFiche technique à préparer\nÀ produire\nProduction partielle\nÀ livrer\nLivraison partielle\nLivrée\nÀ sortir\nSortie partielle\nÀ exporter vers Sage\nExportée vers Sage\nImport Sage confirmé\nAnnulée'}
 ],
 formatter(value,row,column,data,default_formatter){
  if(column.fieldtype==='Currency'&&(value===null||value===undefined||value===''))return '—';
  if(data&&['XOF','XAF'].includes(data.currency)&&column.fieldtype==='Currency')return format_currency(value,data.currency,0);
  return default_formatter(value,row,column,data);
 }
};
