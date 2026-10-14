export function createFrappeClient(frappe,mcpName){
 const prefix='mat_reco.material_reconfiguration.services.mcp_action_preview.';
 async function call(method,args={},compensation=false){
  let response;
  try{response=await frappe.call({method:(compensation?'mat_reco.material_reconfiguration.services.mcp_compensation_service.':prefix)+method,args:{mcp_name:mcpName,...args}});}catch(error){throw new Error(error?.message||'Requête Python refusée ou connexion interrompue. Consultez le message du serveur et rechargez le formulaire avant de réessayer.');}
  const value=response?.message;
  if(!value)throw new Error('Le serveur n’a pas renvoyé de résultat.');
  if(value.valid===false){const error=new Error((value.errors||[]).join('\n')||'Opération refusée par Python.');error.conflict=!!value.conflict;throw error;}
  return value;
 }
 return {reset:payload=>call('reset_mcp_incidents',payload),load:()=>call('load_mcp_effective_plan'),preview:payload=>call('preview_mcp_action',payload),prepare:payload=>call('prepare_mcp_incidents',payload),compensationLoad:()=>call('load_compensation',{},true),compensationPreview:payload=>call('preview_compensation',payload,true),compensationApply:payload=>call('apply_compensation',payload,true)};
}
