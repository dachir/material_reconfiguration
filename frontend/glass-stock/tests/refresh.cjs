const path=require('node:path');
const assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../../..');
const {chromium}=require(path.resolve(root,'../crm/node_modules/playwright'));
(async()=>{
 const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 const page=await browser.newPage({viewport:{width:1680,height:941}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/assets/mat_reco/images/glass_stock/vitres_header_overlay.png',r=>r.fulfill({path:root+'/mat_reco/public/images/glass_stock/vitres_header_overlay.png',contentType:'image/png'}));
 await page.route('http://isolated.test/',r=>r.fulfill({contentType:'text/html',body:'<html></html>'}));
 await page.goto('http://isolated.test/');
 await page.setContent('<html><head><base href="http://isolated.test/"></head><body style="margin:0"><div id="app"></div></body></html>');
 await page.addStyleTag({path:root+'/mat_reco/public/js/glass_stock_dist/glass-stock.css'});
 await page.evaluate(()=>{
 window.testEvents={};window.testCalls=0;window.testVersion=0;
 const interval=window.setInterval;window.setInterval=(fn,ms)=>{window.testInterval=fn;return interval(fn,ms);};
 const all=Array.from({length:10000},(_,i)=>({serial_no:'TEST-'+String(i).padStart(5,'0'),item_code:'RAW',length_mm:2000,width_mm:1000,thickness_mm:6,warehouse:i%2?'B':'A',area_m2:2,classification:i%2?'chutes':'volumes'}));
 const filtered=a=>all.filter(r=>(!a.warehouse||r.warehouse===a.warehouse)&&(!a.search||r.serial_no.includes(a.search)));
 window.frappe={realtime:{on(name,fn){window.testEvents[name]=fn;},off(name){delete window.testEvents[name];},socket:{connected:true,on(){},off(){}}},async call({method,args:a}){window.testCalls++;await new Promise(r=>setTimeout(r,80));if(method.endsWith('get_warehouses'))return {message:['A','B']};const rows=filtered(a),volumes=rows.filter(r=>r.classification==='volumes').length;if(method.endsWith('get_stock_overview'))return {message:{volumes,chutes:rows.length-volumes,total:rows.length,surface_m2:rows.length*2,as_of:'2026-10-16 12:00:00',groups:rows.length?[{item_code:'RAW',item_name:'Verre clair — données de test',volumes,chutes:rows.length-volumes,total:rows.length,surface_m2:rows.length*2,warehouse:a.warehouse||'—'}]:[],diagnostics:{}}};const remaining=rows.filter(r=>r.classification==='chutes').map(r=>({...r,area_m2:2+window.testVersion})).filter(r=>!a.cursor||r.serial_no>a.cursor);return {message:{rows:remaining.slice(0,100),next_cursor:remaining.length>100?remaining[99].serial_no:null,total:rows.length}};}};
 });
 // Exercise the actual Frappe loader and page lifecycle, without authentication.
 await page.route('**/assets/mat_reco/js/glass_stock_dist/**',route=>{
  const name=new URL(route.request().url()).pathname.split('/').pop();
  return route.fulfill({path:path.join(root,'mat_reco/public/js/glass_stock_dist',name),contentType:name.endsWith('.css')?'text/css':'application/javascript'});
 });
 await page.evaluate(()=>{
  window.frappe.pages={'glass-stock':{}};window.frappe.get_route=()=>['glass-stock'];
  window.frappe.ui={make_app_page:()=>({main:[document.querySelector('#app')]})};
  window.frappe.boot={developer_mode:true};
  window.frappe.dom={freeze(){window.testFrozen=true;},unfreeze(){window.testFrozen=false;},eval(txt){(0,eval)(txt);},set_style(txt){const style=document.createElement('style');style.textContent=txt;document.head.append(style);}};
 });
 await page.addScriptTag({path:path.resolve(root,'../frappe/frappe/public/js/frappe/assets.js')});
 await page.addScriptTag({path:root+'/mat_reco/material_reconfiguration/page/glass_stock/glass_stock.js'});
 await page.evaluate(()=>{window.testWrapper={};frappe.pages['glass-stock'].on_page_load(window.testWrapper);frappe.pages['glass-stock'].on_page_show(window.testWrapper);});
 await page.waitForFunction(()=>window.testWrapper.glassStock&&!window.testFrozen);
 console.log('Actual Frappe asset loader: page mounted and screen unfrozen');
 await page.getByRole('button',{name:/données de test/}).click();await page.locator('.glass-serial').first().waitFor();

 // Load two pages, then retain selection and scroll across every refresh source.
 await page.locator('.glass-viewport').evaluate(e=>e.scrollTop=2900);
 await page.getByRole('button',{name:'Charger les pièces suivantes'}).click();
 await page.waitForFunction(()=>!document.querySelector('.glass-more button')?.disabled);
 await page.locator('.glass-viewport').evaluate(e=>e.scrollTop=600);
 assert.ok((await page.locator('.glass-serial').allTextContents()).every(s=>Number(s.split('-')[1])%2===1),'Only cuts have serial detail');
 await page.locator('.glass-serial').nth(5).click();
 const before=await page.locator('.glass-viewport').evaluate(e=>e.scrollTop);
 const chosen=await page.locator('.glass-selected .glass-serial').textContent();
 for(const source of ['manual','event','interval']){
  const calls=await page.evaluate(()=>window.testCalls);
  await page.evaluate(()=>window.testVersion++);
  if(source==='manual')await page.getByRole('button',{name:'Actualiser',exact:true}).click();
  else await page.evaluate(source=>source==='event'?window.testEvents.glass_stock_updated():window.testInterval(),source);
  await page.waitForFunction(n=>window.testCalls>n,calls);
  assert.equal(await page.locator('.glass-empty').count(),0);
  await page.waitForFunction(()=>!document.querySelector('.glass-refresh').disabled);
  assert.equal(await page.locator('.glass-selected .glass-serial').textContent(),chosen);
  assert.equal(await page.locator('.glass-viewport').evaluate(e=>e.scrollTop),before);
  const area=await page.locator('.glass-selected > span').nth(3).textContent();
  assert.equal(area,source==='manual'?'3,00':source==='event'?'4,00':'5,00');
  await page.locator('.glass-viewport').evaluate(e=>e.scrollTop=5700);
  await page.waitForFunction(()=>[...document.querySelectorAll('.glass-serial')].some(e=>e.textContent>='TEST-00180')); 
  await page.locator('.glass-viewport').evaluate((e,y)=>e.scrollTop=y,before);
  await page.locator('.glass-viewport').evaluate(e=>e.scrollTop=0);
  assert.equal(await page.locator('.glass-toggle').getAttribute('aria-expanded'),'true');
  await page.locator('.glass-viewport').evaluate((e,y)=>e.scrollTop=y,before);
  console.log(source+': open group, selection, scroll, loaded pages and updated data retained');
 }
 await page.getByRole('combobox',{name:'Warehouse',exact:true}).selectOption('A');
 await page.waitForFunction(()=>!document.querySelector('.glass-refresh').disabled);
 assert.equal(await page.locator('.glass-toggle').isDisabled(),true);
 assert.equal(await page.locator('.glass-serial').count(),0);
 await page.getByRole('combobox',{name:'Warehouse',exact:true}).selectOption('B');await page.waitForFunction(()=>document.querySelector('.glass-kpis strong')?.textContent==='0');
 console.log('Filtered KPIs',await page.locator('.glass-kpis strong').allTextContents());
 await page.getByRole('textbox').fill('TEST-00001');await page.waitForFunction(()=>document.querySelectorAll('.glass-kpis strong')[1]?.textContent==='1');
 console.log('Server search',await page.locator('.glass-kpis strong').allTextContents());
 await page.getByRole('textbox').fill('');await page.getByRole('combobox',{name:'Warehouse',exact:true}).selectOption('');await page.waitForFunction(()=>document.querySelector('.glass-kpis strong')?.textContent==='5 000');
 await page.setViewportSize({width:390,height:844});
 assert.equal(await page.evaluate(()=>document.body.scrollWidth>innerWidth),false);console.log('Errors',errors);
 await browser.close();if(errors.length)process.exitCode=1;
})().catch(e=>{console.error(e);process.exit(1)});
