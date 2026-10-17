// Copy editable definitions only: identities, dimensions and commercial quantities stay local.
export function applyTechnicalDefinition(lines, sourceId, targetIds) {
 const source=lines.find(line=>line.line_id===sourceId);
 if(!source?.tree)return 0;
 const targets=new Set(targetIds);
 let count=0;
 for(const line of lines){
  if(line.line_id===sourceId||!targets.has(line.line_id))continue;
  line.tree=JSON.parse(JSON.stringify(source.tree));
  line.thickness_mm=source.thickness_mm;
  count++;
 }
 return count;
}
