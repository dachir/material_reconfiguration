// Frappe dialogs are mounted under body, outside the Vue component tree.
// Keep their theme tied to our routes so native Desk pages keep their own theme.
const routes = new Set(['chantiers', 'technical-study', 'workshop-cockpit']);
function syncDialogTheme() {
 document.body.classList.toggle('ug-vue-dialogs-active', routes.has(window.frappe.get_route()[0]));
}
window.frappe.router.on('change', syncDialogTheme);
syncDialogTheme();
