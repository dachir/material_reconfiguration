frappe.pages['glass-stock'].on_page_load = function(wrapper) {
 const page=frappe.ui.make_app_page({parent:wrapper,title:'Stock verre',single_column:true});
 frappe.require(['/assets/mat_reco/js/glass_stock_dist/glass-stock-r3.js','/assets/mat_reco/js/glass_stock_dist/glass-stock.css'],()=>{
  wrapper.glassStock=window.UGGlassStock.mount(page.main[0]);
  if(frappe.get_route()[0]==='glass-stock')wrapper.glassStock.show();
 });
};
frappe.pages['glass-stock'].on_page_show=function(wrapper){document.body.classList.add('ug-glass-active');wrapper.glassStock?.show();};
frappe.pages['glass-stock'].on_page_hide=function(wrapper){document.body.classList.remove('ug-glass-active');wrapper.glassStock?.hide();};
