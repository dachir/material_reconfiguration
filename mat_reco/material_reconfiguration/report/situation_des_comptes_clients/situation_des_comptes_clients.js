frappe.query_reports['Situation des comptes clients'] = {
 filters: [
  {fieldname: 'company', label: __('Société'), fieldtype: 'Link', options: 'Company', default: frappe.defaults.get_user_default('Company')},
  {fieldname: 'from_date', label: __('Du'), fieldtype: 'Date', reqd: 1, default: frappe.datetime.month_start()},
  {fieldname: 'to_date', label: __('Au'), fieldtype: 'Date', reqd: 1, default: frappe.datetime.get_today()},
  {fieldname: 'customer', label: __('Client'), fieldtype: 'Link', options: 'Customer'},
  {fieldname: 'order_type', label: __('Type de commande'), fieldtype: 'Select', reqd: 1,
   options: [{value: 'All', label: __('A + B')}, {value: 'A', label: 'A'}, {value: 'B', label: 'B'}], default: 'All',
   on_change(report) {
    if (report.get_filter_value('sales_order')) return report.set_filter_value('sales_order', '');
    if (!report._no_refresh) return report.refresh(true);
   }},
  {fieldname: 'sales_order', label: __('Commande'), fieldtype: 'Link', options: 'Sales Order', get_query() {
   const kind = frappe.query_report.get_filter_value('order_type');
   const filters = {docstatus: 1};
   for (const field of ['company', 'customer', 'currency']) {
    const value = frappe.query_report.get_filter_value(field);
    if (value) filters[field] = value;
   }
   if (kind === 'B') filters.custom_ug_order_type = 'B';
   if (kind === 'A') return {filters, or_filters: [['custom_ug_order_type', '=', 'A'], ['custom_ug_order_type', '=', ''], ['custom_ug_order_type', 'is', 'not set']]};
   return {filters};
  }},
  {fieldname: 'currency', label: __('Devise'), fieldtype: 'Link', options: 'Currency'}
 ],
 onload(report) {
  report.page.set_inner_message(__('Soldes séparés par société, client, devise et type. A : factures/avoirs et affectations des règlements ERPNext rattachés aux commandes, en TTC. B : bordereaux et règlements spéciaux en HT, avec soldes d’ouverture historiques. Les écritures comptables sans lien avec une commande sont hors périmètre.'));
 },
 formatter(value, row, column, data, default_formatter) {
  if (column.fieldtype === 'Currency' && (value === null || value === undefined || value === '')) return '—';
  if (data && ['XOF', 'XAF'].includes(data.currency) && ['debit', 'credit', 'balance'].includes(column.fieldname)) return format_currency(value, data.currency, 0);
  return default_formatter(value, row, column, data);
 }
};
