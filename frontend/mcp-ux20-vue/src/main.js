import {createApp} from 'vue';
import {createPinia} from 'pinia';
import App from './App.vue';
import {renderPreview} from './lib/preview.js';
import {createFrappeClient} from './services/frappeClient.js';
import {simulate} from './lib/geometry.js';
import {useCuttingStore} from './stores/cutting.js';
let mountSequence=0;
function mount(element,{tree,onApplyPreview,onReset,onToggleExpand,context,readonly=false,server=null,session=null}={}){
 if(!element)throw new Error('Élément de montage introuvable.');
 const pinia=createPinia(); const app=createApp(App,{onApplyPreview,onReset,onToggleExpand,context});app.config.idPrefix=`mcp-${++mountSequence}`;app.use(pinia);
 const store=useCuttingStore(pinia);store.load(server?.baseTree||tree||{nodes:[]});store.configureServer(server);store.restoreSession(session);store.setLocked(readonly);app.mount(element);
 return {unmount(){app.unmount();},store};
}
const version='20261014_move_cursor_1';
window.MatRecoMCPVue={mount,renderPreview,simulate,version,createFrappeClient};
export {mount,renderPreview,simulate,version,createFrappeClient};
