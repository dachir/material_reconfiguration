// One palette and unique SVG pattern IDs for simultaneous modal/preview instances.
export const canvasColors=Object.freeze({piece:'#bfdbfe',leftover:'#e2e8f0',leftoverHatch:'#94a3b8',waste:'#fecaca',wasteHatch:'#e99aaa',single:'#bbf7d0',singleHatch:'#4ade80',destroyed:'#475569'});
let canvasSequence=0;
export const canvasPatternPrefix=()=>`mcp-canvas-${++canvasSequence}`;
