// Print the saved document through native printview and its permission checks.
export function printDocument(doctype, name) {
 if (!name) return;
 const query = new URLSearchParams({doctype, name, format: `Mat Reco A4 - ${doctype}`, _lang: 'fr'});
 window.open(`/printview?${query}`, '_blank', 'noopener,noreferrer');
}
