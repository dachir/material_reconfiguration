function svgCursor(shape){
 const svg=`<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32"><g fill="#2563eb" stroke="#fff" stroke-width="4" stroke-linejoin="round">${shape}</g><g fill="#2563eb" stroke="#10233f" stroke-width="1.4" stroke-linejoin="round">${shape}</g></svg>`;
 return `url("data:image/svg+xml,${encodeURIComponent(svg)}") 16 16, crosshair`;
}
const targetCursors=Object.freeze({
 Move:'move',
 Merge:svgCursor('<path d="M3 3h9v9H3zM20 3h9v9h-9zM10 22h12v8H10z"/><path d="M7 14v3h9v4m9-7v3h-9" fill="none"/>'),
 Single:svgCursor('<path d="M18 3h11v26H3V18h15z"/>')
});
export const actionCursor=action=>targetCursors[action]||null;
export function pieceCursor(action,isCandidate,readonly=false){
 if(readonly)return 'default';
 const cursor=actionCursor(action);
 return cursor?(isCandidate?cursor:'not-allowed'):'pointer';
}
