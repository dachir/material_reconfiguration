export function assignmentIds(checked, clicked) { return checked.length ? [...new Set(checked)] : [clicked]; }
