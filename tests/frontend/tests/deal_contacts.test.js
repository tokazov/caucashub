import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const source=path=>readFileSync(new URL('../../../'+path,import.meta.url),'utf8');
const deal={
 id:31,deal_number:'QA-0031',deal_source:'cargo',status:'confirmed',
 load_from:'Тбилиси',load_to:'Батуми',load_kg:3000,price:500,
 shipper_id:7,carrier_id:8,
 shipper:{id:7,name:'QA shipper',phone:'+995 (599) 10-20-30',email:'shipper@example.test'},
 carrier:{id:8,name:'QA carrier',phone:'+995 (599) 40-50-60',email:'carrier@example.test'}
};
function environment(path,viewer={userId:7},currentId=7,record=deal){
 const elements={myDealsList:{innerHTML:''}},calls={warnings:[],auth:[],closed:[],paywalls:[]};
 const context={document:{getElementById:id=>elements[id]||null},user:viewer,currentUserId:currentId,
  currentCargoId:11,window:{allLoads:[],location:{href:'unchanged'}},
  lang:'ru',TRANSLATIONS:{ru:{sig_shipper:'Отправитель',sig_carrier:'Перевозчик'},ge:{sig_shipper:'გამგზავნი',sig_carrier:'გადამზიდველი'}},
  _deals:[structuredClone(record)],getToken:()=> 'local-synthetic-token',translateCity:value=>value,
  canSeeContact:()=>true,showToastWarn:value=>calls.warnings.push(value),
  closeModal:id=>calls.closed.push(id),openAuth:mode=>calls.auth.push(mode),
  openPaywall:mode=>calls.paywalls.push(mode)};
 vm.createContext(context);const code=source(path);
 const escapeStart=code.indexOf('function esc(s) {'),escapeEnd=code.indexOf('// ── SAFE LOCALSTORAGE',escapeStart);
 assert.ok(escapeStart>=0&&escapeEnd>escapeStart);
 vm.runInContext(code.slice(escapeStart,escapeEnd),context);
 const helperStart=code.indexOf('function dealPhoneHref('),renderEnd=code.indexOf('function showSection(',helperStart);
 assert.ok(helperStart>=0&&renderEnd>helperStart,'Evaluate real contact helper and cabinet renderer');
 vm.runInContext(code.slice(helperStart,renderEnd),context);
 const phoneStart=code.indexOf('function showPhone(){'),phoneEnd=code.indexOf('// ── AUTH',phoneStart);
 vm.runInContext(code.slice(phoneStart,phoneEnd),context);
 return{context,calls,elements,render(){context.renderCabDeals();return elements.myDealsList.innerHTML;}};
}
for(const path of ['main.js','frontend/main.js']){
 for(const source of ['cargo','transport'])test(path+': shipper sees actual carrier contacts in '+source+' deal',()=>{
  const h=environment(path,{userId:7},7,{...deal,deal_source:source}),html=h.render();
  assert.match(html,/href="tel:\+995599405060"/);
  assert.match(html,/href="mailto:carrier%40example\.test"/);
  assert.ok(!html.includes('href="tel:+995599102030"'),'Do not show own phone as counterparty');
  assert.ok(html.indexOf('cab-deal-contact')<html.indexOf('cab-deal-actions'),'Keep contacts within existing metadata');
  assert.match(html,/class="cab-deal-actions"/,'Existing actions retain their position');
 });
 test(path+': carrier receives the shipper contact rather than its own',()=>{
  const html=environment(path,{userId:8},8).render();
  assert.match(html,/href="tel:\+995599102030"/);
  assert.match(html,/href="mailto:shipper%40example\.test"/);
  assert.ok(!html.includes('href="tel:+995599405060"'));
 });
 test(path+': viewer identity uses userId then legacy id then currentUserId',()=>{
  for(const[viewer,currentId,phone]of[
   [{userId:7,id:8},8,'+995599405060'],
   [{id:8},7,'+995599102030'],
   [{},8,'+995599102030']
  ])assert.ok(environment(path,viewer,currentId).render().includes('href="tel:'+phone+'"'));
 });
 test(path+': anonymous and non-participant viewers get no contact links',()=>{
  for(const[viewer,id]of[[null,null],[{userId:99},99]])
   assert.ok(!environment(path,viewer,id).render().includes('cab-deal-contact'));
 });
 test(path+': anonymous viewer with a stale participant ID still gets no contacts',()=>{
  const html=environment(path,null,7).render();
  assert.ok(!html.includes('cab-deal-contact'));
  assert.ok(!html.includes('href="tel:'));assert.ok(!html.includes('href="mailto:'));
 });
 test(path+': missing API contacts do not invent phone or email',()=>{
  const record={...deal,carrier:{id:8,name:'Carrier',phone:null,email:null}};
  const html=environment(path,{userId:7},7,record).render();
  assert.ok(!html.includes('cab-deal-contact'));assert.ok(!html.includes('href="tel:'));
  assert.ok(!html.includes('href="mailto:'));
 });
 test(path+': contact text is escaped and mailto payload is encoded',()=>{
  const record={...deal,carrier:{...deal.carrier,name:'<img src=x onerror=alert(1)>',
   email:"o'hara+qa@example.test"}};
  const html=environment(path,{userId:7},7,record).render();
  assert.ok(!html.includes('<img'));assert.ok(html.includes('&lt;img'));
  assert.ok(html.includes('mailto:o%27hara%2Bqa%40example.test'));
  assert.ok(html.includes('o&#x27;hara+qa@example.test'));
 });
 test(path+': malformed contact values cannot inject href attributes or scripts',()=>{
  const record={...deal,carrier:{...deal.carrier,phone:'+995599405060" onclick="alert(1)',
   email:'bad@example.test" onclick="alert(1)'}};
  const html=environment(path,{userId:7},7,record).render();
  assert.ok(!html.includes('cab-deal-contact'));assert.ok(!html.includes('onclick="alert(1)'));
 });
 test(path+': Georgian contact label reuses the current language',()=>{
  const h=environment(path);h.context.lang='ge';
  assert.ok(h.render().includes('გადამზიდველი:'));
 });
 test(path+': missing cargo phone shows a toast without dialing a fictional number',()=>{
  const h=environment(path);h.context.window.allLoads=[{id:11}];h.context.showPhone();
  assert.equal(h.context.window.location.href,'unchanged');assert.equal(h.calls.warnings.length,1);
  assert.ok(!h.calls.warnings[0].includes('+995 555 123 456'));
 });
 test(path+': phone action uses only the real contact of the current cargo',()=>{
  const h=environment(path);
  h.context.window.allLoads=[{id:11,owner_phone:'+995 (599) 10-20-30'},{id:12,phone:'+995599999999'}];
  h.context.showPhone();assert.equal(h.context.window.location.href,'tel:+995599102030');
  h.context.window.location.href='unchanged';h.context.currentCargoId=13;h.context.showPhone();
  assert.equal(h.context.window.location.href,'unchanged');assert.equal(h.calls.warnings.length,1);
 });
 test(path+': existing login and contact entitlement checks are preserved',()=>{
  const anonymous=environment(path,null,null);anonymous.context.showPhone();
  assert.deepEqual(anonymous.calls.auth,['login']);assert.equal(anonymous.context.window.location.href,'unchanged');
  const gated=environment(path);gated.context.canSeeContact=()=>false;gated.context.showPhone();
  assert.deepEqual(gated.calls.paywalls,['contact']);assert.equal(gated.context.window.location.href,'unchanged');
 });
}
