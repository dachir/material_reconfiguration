import {defineStore} from 'pinia';
import {computed,ref} from 'vue';
import {normalizeTree,copy,findPiece,allowedActions,candidateFor,nodeId,simulate} from '../lib/geometry.js';
export const useCuttingStore=defineStore('cutting',()=>{
 const originalTree=ref({nodes:[]}),simulationTree=ref({nodes:[]}),sheetIndex=ref(0),selectedNodeId=ref(null),activeAction=ref(null),targetNodeIds=ref([]),previewState=ref(null),zoom=ref(1),panelCollapsed=ref(false),isDirty=ref(false),error=ref(''),menuPoint=ref(null),menuOpen=ref(false),parameters=ref({});
 const allowRotation=ref(false),locked=ref(false),pendingIncidents=ref([]),isPreviewing=ref(false),isSaving=ref(false),documentVersion=ref(null),warnings=ref([]);
 const compensationOpen=ref(false),compensationRequirements=ref([]),brokenPieces=ref([]),replacementPieces=ref([]),internalCandidates=ref([]),stockCandidates=ref([]),selectedSources=ref([]),compensationPreview=ref(null),compensationWarnings=ref([]),isCalculating=ref(false),isApplying=ref(false),isLoadingCompensation=ref(false),compensationOperations=ref([]),compensationCoverage=ref({}),compensationStrategy=ref('automatic'),compensationReason=ref(''),compensationError=ref(''),confirmedCompensation=ref(null);
 const compensationEnabled=ref(false);
 const canCompensate=computed(()=>compensationEnabled.value&&!locked.value&&!isDirty.value&&!activeAction.value&&!isPreviewing.value&&!isSaving.value);
 let server=null,requestId=0,compensationRequest=0,compensationReturnView=null;
 function keepCompensationSheet(){sheetIndex.value=Math.min(sheetIndex.value,Math.max(0,sheets.value.length-1));}
 function invalidateCompensation(){compensationRequest++;isCalculating.value=false;compensationPreview.value=null;compensationError.value='';keepCompensationSheet();}
 function restoreWorkshopView(){
  if(!compensationReturnView)return;
  const saved=compensationReturnView;const index=simulationTree.value.nodes.findIndex(n=>nodeId(n)===saved.sheetId);
  sheetIndex.value=index<0?Math.min(saved.sheetIndex,Math.max(0,simulationTree.value.nodes.length-1)):index;
  zoom.value=saved.zoom;panelCollapsed.value=saved.panelCollapsed;menuOpen.value=false;
  selectedNodeId.value=saved.selectedNodeId&&findPiece(simulationTree.value,saved.selectedNodeId)?saved.selectedNodeId:null;
  focusedNodeId.value=saved.focusedNodeId&&findPiece(simulationTree.value,saved.focusedNodeId)?saved.focusedNodeId:null;
  compensationReturnView=null;
 }
 async function loadCompensation(){
  if(!canCompensate.value||isApplying.value)return;
  const visibleId=currentSheetId.value;const token=++compensationRequest;isLoadingCompensation.value=true;compensationError.value='';compensationPreview.value=null;
  try{const result=await server.compensationLoad();if(token!==compensationRequest)return;
   compensationOperations.value=(result.requirements||[]).flatMap(r=>r.operations||[]);compensationRequirements.value=result.compensation_requirements||[];brokenPieces.value=result.broken_pieces||[];replacementPieces.value=result.replacement_pieces||[];
   internalCandidates.value=result.internal_candidates||[];stockCandidates.value=result.stock_candidates||[];compensationWarnings.value=result.warnings||[];compensationCoverage.value=result.summary||{};
   documentVersion.value=result.document_version;load(result.effective_tree);const index=sheets.value.findIndex(n=>nodeId(n)===visibleId);sheetIndex.value=Math.max(0,index);selectedSources.value=[];
  }catch(e){if(token===compensationRequest)compensationError.value=e.message;}
  finally{if(token===compensationRequest)isLoadingCompensation.value=false;}
 }
 async function openCompensation(){
  if(!canCompensate.value||compensationOpen.value)return;
  compensationReturnView={sheetId:currentSheetId.value,sheetIndex:sheetIndex.value,zoom:zoom.value,panelCollapsed:panelCollapsed.value,selectedNodeId:selectedNodeId.value,focusedNodeId:focusedNodeId.value};
  compensationOpen.value=true;confirmedCompensation.value=null;await loadCompensation();
 }
 function closeCompensation(){if(isApplying.value||isCalculating.value||isLoadingCompensation.value)return;compensationOpen.value=false;invalidateCompensation();selectedSources.value=[];restoreWorkshopView();}
 function compensationOptions(){return {strategy:compensationStrategy.value,selected_sources:copy(selectedSources.value),override_reason:compensationReason.value};}
 async function calculateCompensation(){
  if(!canCompensate.value||isCalculating.value||isLoadingCompensation.value||isApplying.value)return;
  const token=++compensationRequest;isCalculating.value=true;compensationError.value='';compensationPreview.value=null;
  try{const result=await server.compensationPreview(compensationOptions());if(token!==compensationRequest)return;
   compensationPreview.value=result;keepCompensationSheet();compensationWarnings.value=result.warnings||[];
  }catch(e){if(token===compensationRequest)compensationError.value=e.message;}
  finally{if(token===compensationRequest)isCalculating.value=false;}
 }
 async function applyCompensation(){
  if(!canCompensate.value||isApplying.value||isCalculating.value||!compensationPreview.value?.placements?.length)return;
  isApplying.value=true;compensationError.value='';let conflict=false,applied=false;
  try{const preview=compensationPreview.value;
   const saved=await server.compensationApply({...preview.options,proposal_id:preview.proposal_id,document_version:preview.document_version});
   if(!saved.applied||!saved.effective_tree)throw new Error('Application non confirmée par Python.');
   confirmedCompensation.value=saved;load(saved.effective_tree);documentVersion.value=saved.document_version;compensationPreview.value=null;applied=true;
  }catch(e){compensationError.value=e.message;conflict=!!e.conflict;compensationPreview.value=null;}
  finally{isApplying.value=false;}
  if(conflict){const message=compensationError.value;await loadCompensation();compensationError.value=message;}
  else if(applied){closeCompensation();}
 }

 function configureServer(value){server=value;compensationEnabled.value=!!value?.compensationLoad;documentVersion.value=value?.documentVersion||null;allowRotation.value=!!(value?.allowRotation??true);}

 const history=ref([]),historyIndex=ref(0),comparisonMode=ref('overlay'),focusedNodeId=ref(null);
 const canUndo=computed(()=>historyIndex.value>0&&!compensationOpen.value&&!activeAction.value&&!locked.value&&!isSaving.value&&!isPreviewing.value),canRedo=computed(()=>historyIndex.value<history.value.length-1&&!compensationOpen.value&&!activeAction.value&&!locked.value&&!isSaving.value&&!isPreviewing.value);
 const historyLabel=computed(()=>history.value[historyIndex.value]?.label||'État initial');
 const sheets=computed(()=>compensationOpen.value?(compensationPreview.value?.effective_tree||simulationTree.value).nodes:simulationTree.value.nodes),sheet=computed(()=>sheets.value[sheetIndex.value]),currentSheetId=computed(()=>nodeId(sheet.value)),sourceNodeId=computed(()=>selectedNodeId.value),selected=computed(()=>findPiece(simulationTree.value,selectedNodeId.value)),actionOptions=computed(()=>locked.value||compensationOpen.value?[]:allowedActions(selected.value?.node));
 const candidateNodeIds=computed(()=>activeAction.value?sheets.value.flatMap(s=>(s.children||[]).filter(n=>candidateFor(activeAction.value,selected.value,{sheet:s,node:n},{allow_rotation:allowRotation.value,rotation_degrees:parameters.value.rotation_degrees??'auto'})).map(nodeId)):[]);
 const displayTree=computed(()=>compensationOpen.value?compensationPreview.value?.effective_tree||simulationTree.value:comparisonMode.value==='before'?simulationTree.value:previewState.value?.tree||simulationTree.value),displaySheet=computed(()=>displayTree.value.nodes[sheetIndex.value]);
 function cancel(){requestId++;isPreviewing.value=false;warnings.value=[];activeAction.value=null;targetNodeIds.value=[];previewState.value=null;error.value='';menuOpen.value=false;}
 function clear(){cancel();selectedNodeId.value=null;menuPoint.value=null;focusedNodeId.value=null;}
 function reset(){if(locked.value||isSaving.value)return;simulationTree.value=copy(originalTree.value);sheetIndex.value=0;zoom.value=1;isDirty.value=false;pendingIncidents.value=[];history.value=[{tree:copy(originalTree.value),incidents:[],label:'État initial'}];historyIndex.value=0;clear();}
 async function resetPlanning(){
  if(locked.value||isSaving.value||compensationOpen.value)return false;
  if(!server?.resetPlan){reset();return true;}
  requestId++;isPreviewing.value=false;isSaving.value=true;error.value='';
  try{const result=await server.resetPlan({document_version:copy(documentVersion.value)});
   if(!result?.reset||!result.effective_tree)throw new Error('La réinitialisation n’a pas été confirmée par le serveur.');
   isSaving.value=false;load(result.effective_tree);documentVersion.value=result.document_version;confirmedCompensation.value=null;return true;
  }catch(e){error.value=e.message;return false;}finally{isSaving.value=false;}
 }
 function load(t){if(locked.value)return;originalTree.value=normalizeTree(t);reset();}
 function restoreSession(session){
  if(!session?.pendingIncidents?.length)return;
  simulationTree.value=normalizeTree(session.tree);pendingIncidents.value=copy(session.pendingIncidents);documentVersion.value=session.documentVersion||documentVersion.value;isDirty.value=true;
  history.value.push({tree:copy(simulationTree.value),incidents:copy(pendingIncidents.value),label:'Opérations en attente'});historyIndex.value=history.value.length-1;
 }
 function setSheet(i){if(i<0||i>=sheets.value.length)return;sheetIndex.value=i;zoom.value=1;focusedNodeId.value=null;if(!activeAction.value)clear();menuOpen.value=false;}
 async function updatePreview(){
  if(locked.value||isSaving.value)return;
  const token=++requestId;previewState.value=null;error.value='';
  const operation={action:activeAction.value,sourceNodeId:sourceNodeId.value,targetNodeIds:copy(targetNodeIds.value),parameters:copy(parameters.value)};
  if(server){
   isPreviewing.value=true;
   try{const result=await server.previewAction({action:operation.action,source_node_id:operation.sourceNodeId,target_node_ids:operation.targetNodeIds,parameters:operation.parameters,pending_incidents:copy(pendingIncidents.value),document_version:documentVersion.value});
    if(token!==requestId)return;
    previewState.value={tree:normalizeTree(result.effective_tree),incidents:result.pending_incidents};warnings.value=result.warnings||[];
   }catch(e){if(token===requestId)error.value=e.message;}
   finally{if(token===requestId)isPreviewing.value=false;}
  }else{try{previewState.value={tree:simulate(simulationTree.value,{...operation,parameters:{...operation.parameters,allow_rotation:allowRotation.value}})};}catch(e){error.value=e.message;}}
 }

 function select(id,point){if(locked.value||isSaving.value||compensationOpen.value)return;if(activeAction.value){if(!candidateNodeIds.value.includes(String(id))){error.value='Zone incompatible avec cette action.';return;}targetNodeIds.value=[String(id)];updatePreview();return;}selectedNodeId.value=String(id);menuPoint.value=point;menuOpen.value=true;}
 function choose(a){if(locked.value||isSaving.value||compensationOpen.value)return;if(!actionOptions.value.includes(a))return;activeAction.value=a;panelCollapsed.value=false;comparisonMode.value='overlay';menuOpen.value=false;targetNodeIds.value=[];parameters.value={length_mm:selected.value.node.effective_length_mm??selected.value.node.length_mm,width_mm:selected.value.node.effective_width_mm??selected.value.node.width_mm};if(a==='Move')parameters.value.rotation_degrees=allowRotation.value?'auto':0;if(a==='Resize'||a==='Destroy')updatePreview();}
 function updateMoveOrientation(){
  requestId++;isPreviewing.value=false;previewState.value=null;error.value='';
  if(targetNodeIds.value.length&&candidateNodeIds.value.includes(targetNodeIds.value[0]))updatePreview();
  else targetNodeIds.value=[];
 }
 function confirm(){
  if(locked.value||isSaving.value||isPreviewing.value||!previewState.value)return;
  const next=copy(previewState.value.tree);
  history.value=history.value.slice(0,historyIndex.value+1);
  const incidents=copy(previewState.value.incidents||pendingIncidents.value);pendingIncidents.value=incidents;
  history.value.push({tree:next,incidents,label:`${activeAction.value} · ${sourceNodeId.value}`});
  if(history.value.length>51)history.value.shift();
  historyIndex.value=history.value.length-1;
  simulationTree.value=copy(next);isDirty.value=JSON.stringify(next)!==JSON.stringify(originalTree.value);clear();
 }
 function travel(index){historyIndex.value=index;simulationTree.value=copy(history.value[index].tree);pendingIncidents.value=copy(history.value[index].incidents||[]);isDirty.value=JSON.stringify(simulationTree.value)!==JSON.stringify(originalTree.value);clear();}
 function undo(){if(canUndo.value)travel(historyIndex.value-1);}
 function redo(){if(canRedo.value)travel(historyIndex.value+1);}
 function focusSelection(){if(selected.value){focusedNodeId.value=selectedNodeId.value;zoom.value=1;menuOpen.value=false;}}
 function fit(){focusedNodeId.value=null;setZoom(1);}
 function setZoom(v){zoom.value=Math.min(4,Math.max(.25,v));menuOpen.value=false;}
 function setLocked(value){locked.value=!!value;if(locked.value){clear();compensationOpen.value=false;invalidateCompensation();}}
 return {resetPlanning,allowRotation,updateMoveOrientation,canCompensate,compensationOpen,compensationOperations,compensationRequirements,brokenPieces,replacementPieces,internalCandidates,stockCandidates,selectedSources,compensationPreview,compensationWarnings,isCalculating,isApplying,isLoadingCompensation,compensationCoverage,compensationStrategy,compensationReason,compensationError,confirmedCompensation,openCompensation,closeCompensation,loadCompensation,calculateCompensation,applyCompensation,invalidateCompensation,restoreSession,configureServer,pendingIncidents,isPreviewing,isSaving,documentVersion,warnings,locked,setLocked,historyIndex,historyLabel,canUndo,canRedo,comparisonMode,focusedNodeId,undo,redo,focusSelection,fit,originalTree,simulationTree,currentSheetId,selectedNodeId,sourceNodeId,targetNodeIds,candidateNodeIds,previewState,zoom,panelCollapsed,isDirty,error,menuPoint,menuOpen,parameters,sheets,sheet,sheetIndex,selected,activeAction,actionOptions,displayTree,displaySheet,load,reset,cancel,clear,setSheet,select,choose,updatePreview,confirm,setZoom};
});
