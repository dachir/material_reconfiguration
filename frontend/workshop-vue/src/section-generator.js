const api = 'mat_reco.material_reconfiguration.services.section_generation.';
const frappe = window.frappe;
const readImage = (file) => new Promise((resolve, reject) => {
 const reader = new FileReader();
 reader.onload = () => resolve(reader.result);
 reader.onerror = () => reject(new Error('Impossible de lire le plan.'));
 reader.readAsDataURL(file);
});

export function showSectionGenerator(chantier, onApplied, describe) {
 let running = false;
 const dialog = new frappe.ui.Dialog({
  title: 'Générer des sections depuis un descriptif ou des plans', size: 'large',
  fields: [
   {fieldname:'prompt', label:'Descriptif et consignes de découpage', fieldtype:'Long Text', description:'Exemple : bâtiment → étage → zone → pièce. Conserver les noms présents sur les plans.'},
   {fieldname:'plans', fieldtype:'HTML', options:'<label>Images de plans (4 maximum, 5 Mo chacune)</label><input class="form-control" type="file" accept="image/png,image/jpeg,image/webp" multiple aria-label="Images de plans"><p class="text-muted">Le descriptif et les images sélectionnées seront envoyés au service LLM configuré dans Mat Reco Settings.</p>'}
  ],
  primary_action_label: 'Proposer les sections',
  async primary_action(values) {
   if (running) return;
   const files = [...dialog.fields_dict.plans.$wrapper.find('input')[0].files];
   if (files.length > 4 || files.some(f => f.size > 5000000)) {
    frappe.msgprint('Choisir au maximum 4 images de 5 Mo chacune.'); return;
   }
   if (!values.prompt?.trim() && !files.length) {
    frappe.msgprint('Saisir un descriptif ou joindre une image de plan.'); return;
   }
   running = true; dialog.disable_primary_action();
   dialog.set_primary_action_label('Analyse en cours…');
   try {
    const images = await Promise.all(files.map(readImage));
    const result = await frappe.call({method:api+'generate_sections', args:{chantier,prompt:values.prompt||'',images:JSON.stringify(images)}});
    let state;
    for (let attempt=0; attempt<480; attempt++) {
     await new Promise(resolve=>setTimeout(resolve,1500));
     state=(await frappe.call({method:api+'get_generation',args:{job_id:result.message.job_id},type:'GET'})).message;
     if (state.status!=='pending') break;
    }
    if (state?.status==='error') throw new Error(state.message);
    if (state?.status!=='done') throw new Error('Le délai de génération est dépassé. Réessayer.');
    dialog.hide();
    showProposal(chantier, state.proposal, onApplied, describe);
   } catch (e) { frappe.msgprint(describe(e)); }
   finally { running = false; dialog.enable_primary_action(); dialog.set_primary_action_label('Proposer les sections'); }
  }
 });
 dialog.show();
}

function showProposal(chantier, proposal, onApplied, describe) {
 let applying = false;
 const escape = frappe.utils.escape_html;
 const dialog = new frappe.ui.Dialog({
  title:'Vérifier les sections proposées',size:'extra-large',
  fields:[
   {fieldname:'guidance',fieldtype:'HTML',options:'<p>Corrigez les noms et les numéros des lignes parentes avant validation. Une ligne parente doit précéder ses enfants ; 0 désigne une racine. Les sections existantes seront conservées.</p>'},
   {fieldname:'warnings',fieldtype:'HTML',options:proposal.warnings.length?'<div class="alert alert-warning"><strong>Points à vérifier</strong><ul>'+proposal.warnings.map(w=>'<li>'+escape(w)+'</li>').join('')+'</ul></div>':''},
   {fieldname:'sections',label:'Sections proposées',fieldtype:'Table',in_place_edit:true,data:proposal.sections,fields:[
    {fieldname:'section_name',label:'Désignation',fieldtype:'Data',reqd:1,in_list_view:1,columns:7},
    {fieldname:'parent_row',label:'Ligne parente (0 = racine)',fieldtype:'Int',in_list_view:1,columns:3}
   ]}
  ],
  primary_action_label:'Créer les sections validées',
  async primary_action(values) {
   if (applying) return;
   applying = true; dialog.disable_primary_action();
   try {
    const sections = values.sections.map(row => ({section_name:row.section_name,parent_row:Number(row.parent_row||0)}));
    const result = await frappe.call({method:api+'apply_generated_sections',args:{chantier,sections:JSON.stringify(sections)}});
    dialog.hide();
    frappe.show_alert({message:result.message.count+' section(s) créée(s)',indicator:'green'});
    await onApplied();
   } catch (e) { frappe.msgprint(describe(e)); }
   finally { applying = false; dialog.enable_primary_action(); }
  }
 });
 dialog.show();
}
