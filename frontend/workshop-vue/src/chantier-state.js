// Submitted/cancelled dossiers are copied from the saved source, never saved first.
export function needsSaveBeforeCopy({dirty, docstatus, editable}) {
 return !!dirty && Number(docstatus) === 0 && !!editable;
}

export function sameRevision(left, right) {
 const normalize = value => String(value || '').replace('T', ' ').replace(/(:\d{2})(?:\.(\d+))?$/, (_, seconds, fraction='') => seconds+'.'+fraction.padEnd(6,'0'));
 return !!left && !!right && normalize(left) === normalize(right);
}
