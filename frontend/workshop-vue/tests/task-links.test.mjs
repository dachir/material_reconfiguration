import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('../../../mat_reco/public/js/ug_task_links.js',import.meta.url),'utf8');
const listSource=fs.readFileSync(new URL('../../../mat_reco/public/js/ug_todo_list.js',import.meta.url),'utf8');
function setup(){
 let target,opened;
 class Base {setup_quick_list_item(){const row={native:true,find(){return{wrapInner(a){row.href=a.href}}},off(){row.native=false;return row},on(event,fn){row.click=fn;return row}};return row}}
 const context={frappe:{widget:{widget_factory:{quick_list:Base}},listview_settings:{},router:{on(){}},set_route:r=>target=r},window:{open:r=>opened=r},$:value=>{if(typeof value==='function')return value();return{attr(k,v){this[k]=v;return this}}}};
 vm.runInNewContext(source,context);
 return{context,get target(){return target},get opened(){return opened}};
}
const task=(type,name='DOC 1')=>({description:'[Univers Glass — Atelier] tâche existante',reference_type:type,reference_name:name,name:'TODO1'});
test('existing UG tasks route to their exact document page',()=>{
 const {context}=setup();
 for(const [type,page]of [['Sales Order','workshop-cockpit'],['Chantier','chantiers'],['Chantier Technical Study','technical-study']]){
  assert.equal(context.frappe.ug_task_links.href(task(type)),`/app/${page}/DOC%201`);
 }
 assert.equal(context.frappe.ug_task_links.href({...task('Chantier'),description:'Ordinary task'}),null);
});
test('workspace row opens its page and supports Ctrl-click',()=>{
 const s=setup(),widget=new s.context.frappe.widget.widget_factory.quick_list();widget.document_type='ToDo';
 const row=widget.setup_quick_list_item(task('Chantier'));
 assert.equal(row.href,'/app/chantiers/DOC%201');assert.equal(row.native,false);
 row.click({preventDefault(){}});assert.equal(s.target,row.href);
 row.click({preventDefault(){},ctrlKey:true});assert.equal(s.opened,row.href);
 const ordinary=widget.setup_quick_list_item({...task('Chantier'),description:'Ordinary'});assert.equal(ordinary.native,true);
});
test('ToDo table and Open action use the same page while preserving ordinary tasks',()=>{
 const s=setup();let fallback;
 s.context.frappe.listview_settings.ToDo={button:{action:doc=>fallback=doc.name}};
 s.context.frappe.utils={get_form_link:(dt,name)=>`/app/todo/${name}`};
 vm.runInNewContext(listSource,s.context);
 const settings=s.context.frappe.listview_settings.ToDo;
 assert.equal(settings.get_form_link(task('Sales Order')),'/app/workshop-cockpit/DOC%201');
 settings.button.action(task('Chantier Technical Study'));assert.equal(s.target,'/app/technical-study/DOC%201');
 const ordinary={...task('Chantier'),description:'Ordinary'};
 assert.equal(settings.get_form_link(ordinary),'/app/todo/TODO1');settings.button.action(ordinary);assert.equal(fallback,'TODO1');
});
