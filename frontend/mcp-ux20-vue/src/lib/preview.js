import {createApp} from 'vue';
import {createPinia} from 'pinia';
import App from '../App.vue';
import CuttingCanvas from '../components/CuttingCanvas.vue';
import {useCuttingStore} from '../stores/cutting.js';
export function renderPreview(container,tree,options={}){
 const readonly=options.readonly!==false;
 const host=document.createElement('div');host.className=readonly?'mcpv-app mcpv-readonly':'mcpv-preview-editor';container.replaceChildren(host);
 const pinia=createPinia(),store=useCuttingStore(pinia);store.load(options.server?.baseTree||tree);store.configureServer(options.server);store.restoreSession(options.session);store.setLocked(readonly);
 if(!readonly){
  const app=createApp(App,options);app.use(pinia);app.mount(host);
  return {store,unmount(){app.unmount();}};
 }
 const app=createApp(CuttingCanvas,{readonly:true});app.use(pinia);
 const heading=document.createElement('p');heading.textContent=options.submitted?'Document soumis · Modifications terminées · Simulation locale non validée par Python':'Simulation locale · Non enregistrée · Non validée par Python';host.appendChild(heading);
 const select=document.createElement('select');select.setAttribute('aria-label','Plaque de l’aperçu');store.sheets.forEach((s,i)=>{const option=document.createElement('option');option.value=i;option.textContent=`Plaque ${i+1} / ${store.sheets.length}`;select.appendChild(option);});select.onchange=()=>store.setSheet(Number(select.value));host.appendChild(select);
 const canvas=document.createElement('div');host.appendChild(canvas);app.mount(canvas);return {store,unmount(){select.onchange=null;app.unmount();}};
}
