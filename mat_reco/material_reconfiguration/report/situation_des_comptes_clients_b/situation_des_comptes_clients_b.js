frappe.query_reports['Situation des comptes clients B']={filters:[
 {fieldname:'company',label:__('Société'),fieldtype:'Link',options:'Company',default:frappe.defaults.get_user_default('Company')},
 {fieldname:'from_date',label:__('Du'),fieldtype:'Date',reqd:1,default:frappe.datetime.month_start()},
 {fieldname:'to_date',label:__('Au'),fieldtype:'Date',reqd:1,default:frappe.datetime.get_today()},
 {fieldname:'customer',label:__('Client'),fieldtype:'Link',options:'Customer'},
 {fieldname:'sales_order',label:__('Commande B'),fieldtype:'Link',options:'Sales Order',get_query:()=>({filters:{custom_ug_order_type:'B',docstatus:1}}),description:__('Sans commande : tous les règlements B du client sont comptés une seule fois, avances comprises.')},
 {fieldname:'currency',label:__('Devise'),fieldtype:'Link',options:'Currency'}
]};
frappe.query_reports['Situation des comptes clients B'].formatter=function(value,row,column,data,default_formatter){
 if(data&&['XOF','XAF'].includes(data.currency)&&['debit','credit','balance'].includes(column.fieldname))return format_currency(value,data.currency,0);
 return default_formatter(value,row,column,data);
};
