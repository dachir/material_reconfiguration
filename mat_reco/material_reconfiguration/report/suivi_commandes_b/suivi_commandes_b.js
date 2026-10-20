frappe.query_reports['Suivi commandes B'] = {
 filters: [
  {fieldname:'company',label:__('Société'),fieldtype:'Link',options:'Company',default:frappe.defaults.get_user_default('Company')},
  {fieldname:'customer',label:__('Client'),fieldtype:'Link',options:'Customer'},
  {fieldname:'from_date',label:__('Du'),fieldtype:'Date'},
  {fieldname:'to_date',label:__('Au'),fieldtype:'Date'},
  {fieldname:'stage',label:__('Étape'),fieldtype:'Select',options:'\nBrouillon\nFiche technique à préparer\nÀ produire\nProduction partielle\nÀ sortir\nSortie partielle\nÀ exporter vers Sage\nExportée vers Sage\nImport Sage confirmé\nAnnulée'}
 ]
};
