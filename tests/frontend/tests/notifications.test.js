import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const source=path=>readFileSync(new URL('../../../'+path,import.meta.url),'utf8');
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return{promise,resolve};};
const reply=(data,ok=true)=>({ok,status:ok?200:500,json:async()=>data});
const drain=async()=>{for(let i=0;i<15;i++)await Promise.resolve();};
function classes(){
 const values=new Set();
 return{add:v=>values.add(v),remove:v=>values.delete(v),contains:v=>values.has(v),
  toggle(v,force){const yes=force===undefined?!values.has(v):force;if(yes)values.add(v);else values.delete(v);return yes;}};
}
const row=(id,type='new_response',data={})=>({id,type,created_at:'2026-10-27T12:00:00Z',read_at:null,
 data:{source:'cargo',load_id:12,from_city:'Тбилиси',to_city:'Батуми',actor_name:'Carrier',...data}});
function inbox(path){
 const elements={notifPanel:{style:{},classList:classes(),contains:()=>false},
  notifList:{innerHTML:''},notifBadge:{textContent:'',classList:classes()},notifBtn:{contains:()=>false}};
 const calls={fetch:[],warnings:[],sections:[],tabs:[],storage:[],intervals:new Map(),listeners:{}};
 let intervalId=0;
 const context={user:{userId:7},currentUserId:7,token:'first-token',_notifs:[],window:{},API_BASE:'https://local.test',
  lang:'ru',TRANSLATIONS:{ru:{},ge:{}},Map,URL,
  document:{visibilityState:'visible',getElementById:id=>elements[id]||null,querySelector:()=>null,
   addEventListener(type,listener){(calls.listeners[type]||=[]).push(listener);}},
  getToken:()=>context.token,
  fetch:(url,options={})=>{calls.fetch.push({url,options});return context.respond(url,options);},
  respond:async()=>reply({notifications:[],unread_count:0}),
  setInterval:(fn,ms)=>{const id=++intervalId;calls.intervals.set(id,{fn,ms});return id;},
  clearInterval:id=>calls.intervals.delete(id),setTimeout:()=>{},
  localStorage:{getItem:key=>{calls.storage.push(key);return JSON.stringify([{title:'OTHER ACCOUNT PRIVATE'}]);},
   setItem:key=>calls.storage.push(key),removeItem:key=>calls.storage.push(key)},
  showToastWarn:value=>calls.warnings.push(value),showSection:(name)=>calls.sections.push(name),
  switchCabTab:tab=>calls.tabs.push(tab),translateCity:value=>value};
 vm.createContext(context);
 const code=source(path),a=code.indexOf('function esc(s) {'),b=code.indexOf('// ── SAFE LOCALSTORAGE',a);
 vm.runInContext(code.slice(a,b),context);
 const start=code.indexOf('// ── AUTHENTICATED NOTIFICATIONS'),end=code.indexOf('// ── END AUTHENTICATED NOTIFICATIONS',start);
 assert.ok(start>=0&&end>start);
 vm.runInContext(code.slice(start,end),context);
 return{context,calls,elements,async load(rows,count=rows.filter(x=>!x.read_at).length){
  context.respond=async()=>reply({notifications:rows,unread_count:count,total:rows.length,limit:50,offset:0});
  await context.refreshNotifications();
 },visibility(value){context.document.visibilityState=value;calls.listeners.visibilitychange.forEach(fn=>fn());}};
}
for(const path of ['main.js','frontend/main.js']){
 test(path+': canonical inbox refreshes deduplicate stable IDs and use the real bell badge',async()=>{
  const h=inbox(path);await h.load([row(1),row(1),row(2)],2);await h.context.refreshNotifications();
  assert.equal(h.context._notifs.length,2);assert.equal((h.elements.notifList.innerHTML.match(/data-notification-key=/g)||[]).length,2);
  assert.equal(h.elements.notifBadge.textContent,'2');assert.equal(h.elements.notifBadge.classList.contains('has'),true);
  assert.equal(h.calls.fetch[0].url,'https://local.test/api/notifications?limit=50&offset=0');
  assert.equal(h.calls.fetch[0].options.headers.Authorization,'Bearer first-token');
  assert.deepEqual(h.calls.storage,[],'Never import the global legacy cache or persist self acknowledgements');
 });
 test(path+': opening the current header bell preserves rows and does not mark or delete them',async()=>{
  const h=inbox(path);await h.load([row(1)]);h.context.toggleNotifs();await drain();
  assert.equal(h.elements.notifPanel.classList.contains('open'),true);
  assert.equal(h.context._notifs.length,1);assert.equal(h.context._notifs[0].read_at,null);
  assert.ok(h.calls.fetch.every(x=>!x.options.method));assert.equal(h.elements.notifPanel.style.display,'');
  h.context.toggleNotifs();assert.equal(h.elements.notifPanel.classList.contains('open'),false);
 });
 test(path+': an individual read persists once, updates unread state and keeps the record',async()=>{
  const h=inbox(path);await h.load([row(1)]);
  h.context.respond=async()=>reply({ok:true,id:1,read_at:'2026-10-27T13:00:00Z',unread_count:0});
  await Promise.all([h.context.markRead('server:1'),h.context.markRead('server:1')]);
  assert.equal(h.calls.fetch.filter(x=>x.options.method==='POST').length,1);
  assert.equal(h.calls.fetch.at(-1).url,'https://local.test/api/notifications/1/read');
  assert.equal(h.context._notifs.length,1);assert.ok(h.context._notifs[0].read_at);
  assert.equal(h.elements.notifBadge.textContent,'');assert.ok(!h.elements.notifList.innerHTML.includes('notif-item unread'));
 });
 test(path+': read-all marks existing rows without erasing history or hiding the dropdown',async()=>{
  const h=inbox(path);await h.load([row(1),row(2)]);h.elements.notifPanel.classList.add('open');
  h.context.pushNotif('Local acknowledgement','Only this session',[]);
  h.context.respond=async()=>reply({ok:true,read_at:'2026-10-28T13:00:00Z',unread_count:0});
  await h.context.clearNotifs();
  assert.match(h.calls.fetch.at(-1).url,/\/api\/notifications\/read-all$/);
  assert.equal(h.context._notifs.length,3);assert.ok(h.context._notifs.every(x=>x.read_at));
  assert.equal(h.elements.notifPanel.classList.contains('open'),true);
  assert.equal(h.elements.notifBadge.textContent,'');
 });
 test(path+': failed read leaves the original row and unread badge intact',async()=>{
  const h=inbox(path);await h.load([row(1)]);h.context.respond=async()=>reply({detail:'Unavailable'},false);
  assert.equal(await h.context.markRead('server:1'),false);
  assert.equal(h.context._notifs[0].read_at,null);assert.equal(h.elements.notifBadge.textContent,'1');
  assert.equal(h.calls.warnings.length,1);
 });
 test(path+': an old GET cannot restore unread state after a successful read',async()=>{
  const h=inbox(path);await h.load([row(1)]);const held=deferred();
  h.context.respond=(url,opts)=>opts.method==='POST'?Promise.resolve(reply({ok:true,id:1,read_at:'2026-10-27T13:00:00Z',unread_count:0})):held.promise;
  const old=h.context.refreshNotifications();await h.context.markRead('server:1');
  held.resolve(reply({notifications:[row(1)],unread_count:1}));await old;
  assert.ok(h.context._notifs[0].read_at);assert.equal(h.elements.notifBadge.textContent,'');
 });
 test(path+': logout immediately clears visible records and stops authenticated polling',async()=>{
  const h=inbox(path);await h.load([row(1)]);h.context.startNotificationPolling();await drain();
  assert.equal(h.calls.intervals.size,1);
  h.context.resetNotifications();h.context.user=null;h.context.token=null;
  assert.equal(h.calls.intervals.size,0);assert.equal(h.context._notifs.length,0);
  assert.equal(h.elements.notifBadge.textContent,'');assert.ok(!h.elements.notifList.innerHTML.includes('Carrier'));
  assert.equal(h.elements.notifPanel.classList.contains('open'),false);
 });
 test(path+': pending inbox responses cannot populate a different logged-in account',async()=>{
  const h=inbox(path),held=deferred();h.context.respond=()=>held.promise;
  const old=h.context.refreshNotifications();
  h.context.user={userId:8};h.context.currentUserId=8;h.context.token='second-token';
  await h.load([row(8,'new_transport_request',{source:'transport',actor_name:'New account only'})]);
  held.resolve(reply({notifications:[row(1,'new_response',{actor_name:'OLD PRIVATE'})],unread_count:1}));await old;
  assert.equal(h.context._notifs.length,1);assert.equal(h.context._notifs[0].id,8);
  assert.ok(!h.elements.notifList.innerHTML.includes('OLD PRIVATE'));
 });
 test(path+': late single-read responses cannot change a new account badge or navigate it',async()=>{
  const h=inbox(path);await h.load([row(1)]);const held=deferred();h.context.respond=()=>held.promise;
  const old=h.context.openNotification('server:1');await drain();
  h.context.user={userId:8};h.context.token='second-token';await h.load([row(8)],5);
  held.resolve(reply({ok:true,id:1,read_at:'2026-10-27T13:00:00Z',unread_count:0}));await old;
  assert.equal(h.elements.notifBadge.textContent,'5');assert.equal(h.context._notifs[0].id,8);
  assert.deepEqual(h.calls.tabs,[]);assert.deepEqual(h.calls.sections,[]);
 });
 test(path+': local self acknowledgements are ephemeral and isolated when the account changes',async()=>{
  const h=inbox(path);await h.load([]);h.context.pushNotif('A private acknowledgement','A body',[]);
  assert.ok(h.elements.notifList.innerHTML.includes('A private acknowledgement'));
  h.context.user={userId:8};h.context.token='second-token';await h.load([]);
  assert.ok(!h.elements.notifList.innerHTML.includes('A private acknowledgement'));
  assert.equal(h.context._notifs.length,0);assert.deepEqual(h.calls.storage,[]);
 });
 test(path+': authenticated polling runs every 30 seconds, pauses when hidden and refreshes when visible',async()=>{
  const h=inbox(path);h.context.startNotificationPolling();await drain();
  assert.equal(h.calls.intervals.size,1);assert.equal([...h.calls.intervals.values()][0].ms,30000);
  h.context.startNotificationPolling();await drain();assert.equal(h.calls.intervals.size,1);
  h.visibility('hidden');assert.equal(h.calls.intervals.size,0);const before=h.calls.fetch.length;
  await h.context.refreshNotifications();assert.equal(h.calls.fetch.length,before);
  h.visibility('visible');await drain();assert.equal(h.calls.intervals.size,1);assert.equal(h.calls.fetch.length,before+1);
 });
 test(path+': unauthenticated pages never poll or add private self acknowledgements',async()=>{
  const h=inbox(path);h.context.user=null;h.context.token=null;
  h.context.startNotificationPolling();h.context.toggleNotifs();h.context.pushNotif('No','No',[]);
  await h.context.refreshNotifications();assert.equal(h.calls.fetch.length,0);assert.equal(h.calls.intervals.size,0);
  assert.equal(h.context._notifs.length,0);
 });
 test(path+': notification rows navigate only to the canonical cabinet tab for their event and source',async()=>{
  for(const[type,data,target]of[
   ['new_response',{source:'cargo'},'loads'],
   ['new_transport_request',{source:'transport'},'transport-requests-in'],
   ['deal_created',{source:'cargo',deal_id:31},'deals'],
   ['delivery_waiting',{source:'transport',deal_id:31},'deals'],
   ['delivery_confirmation_required',{source:'cargo',deal_id:31},'deals'],
   ['deal_completed',{source:'transport',deal_id:31},'deals'],
   ['response_rejected',{source:'cargo'},'responses'],
   ['transport_request_rejected',{source:'transport'},'transport-requests-out']
  ]){
   const h=inbox(path);await h.load([row(1,type,data)]);
   h.context.respond=async()=>reply({ok:true,id:1,read_at:'2026-10-27T13:00:00Z',unread_count:0});
   await h.context.openNotification('server:1');
   assert.deepEqual(h.calls.sections,['orders']);assert.deepEqual(h.calls.tabs,[target]);
  }
 });
 test(path+': untrusted URLs or unknown sources cannot turn a notification into external navigation',async()=>{
  const h=inbox(path);await h.load([row(1,'deal_created',{source:'javascript:bad',deal_id:31,url:'https://evil.test'})]);
  h.context.respond=async()=>reply({ok:true,id:1,read_at:'2026-10-27T13:00:00Z',unread_count:0});
  await h.context.openNotification('server:1');assert.deepEqual(h.calls.tabs,[]);assert.deepEqual(h.calls.sections,[]);
 });
 test(path+': server names, routes, timestamps and local text cannot inject notification markup',async()=>{
  const h=inbox(path);await h.load([row(1,'new_response',{actor_name:'<img src=x onerror=bad()>',from_city:'<script>bad()</script>'})]);
  const html=h.elements.notifList.innerHTML;
  assert.ok(html.includes('&lt;img'));assert.ok(!html.includes('<img'));assert.ok(!html.includes('<script>'));
  h.context.pushNotif('<svg onload=bad()>','<b>text</b>',[{label:'<img>',actionId:'bad" onclick="bad()'}]);
  assert.ok(!h.elements.notifList.innerHTML.includes('<svg'));assert.ok(!h.elements.notifList.innerHTML.includes('onclick="bad()'));
  assert.ok(h.elements.notifList.innerHTML.includes('data-action="bad&quot; onclick=&quot;bad()"'));
 });
 test(path+': RU and GE labels come from the current UI language while stable event IDs stay unchanged',async()=>{
  const h=inbox(path);await h.load([row(1,'deal_completed',{source:'cargo',deal_id:31,deal_number:'CH-0031'})]);
  assert.ok(h.elements.notifList.innerHTML.includes('Сделка завершена'));
  h.context.lang='ge';h.context.renderNotifs();assert.ok(h.elements.notifList.innerHTML.includes('გარიგება დასრულებულია'));
  assert.ok(h.elements.notifList.innerHTML.includes('server:1'));assert.ok(h.elements.notifList.innerHTML.includes('CH-0031'));
 });
 test(path+': concurrent reads are serialized and do not lose the final unread count',async()=>{
  const h=inbox(path);await h.load([row(1),row(2)]);
  const held=deferred();let first=true;h.context.respond=async()=>first?(first=false,held.promise):reply({ok:true,id:2,read_at:'2026-10-27T13:01:00Z',unread_count:0});
  const one=h.context.markRead('server:1'),two=h.context.markRead('server:2');await drain();
  assert.equal(h.calls.fetch.filter(x=>x.options.method==='POST').length,1);
  held.resolve(reply({ok:true,id:1,read_at:'2026-10-27T13:00:00Z',unread_count:1}));await Promise.all([one,two]);
  assert.equal(h.context._notifs.filter(x=>!x.read_at).length,0);assert.equal(h.elements.notifBadge.textContent,'');
 });
 test(path+': the actual row-click delegate uses the selected server notification key',async()=>{
  const h=inbox(path);await h.load([row(1)]);
  h.context.respond=async()=>reply({ok:true,id:1,read_at:'2026-10-27T13:00:00Z',unread_count:0});
  const target={closest:selector=>selector==='[data-notification-key]'?{dataset:{notificationKey:'server:1'}}:null};
  h.calls.listeners.click.forEach(fn=>fn({target,stopPropagation(){}}));await drain();
  assert.deepEqual(h.calls.tabs,['loads']);assert.equal(h.context._notifs[0].read_at,'2026-10-27T13:00:00Z');
 });
}
for(const path of ['index.html','frontend/index.html'])test(path+': one canonical bell, badge and inbox remain in actual markup',()=>{
 const html=source(path);
 for(const id of ['notifBtn','notifBadge','notifPanel','notifList'])assert.equal((html.match(new RegExp('id="'+id+'"','g'))||[]).length,1,id);
 assert.match(html,/id="notifBtn"[^>]*onclick="toggleNotifs\(\)"/);
 assert.match(html,/onclick="clearNotifs\(\)">/);
});

for(const path of ['main.js','frontend/main.js']){
 function rejection(){
  const requests=[],warnings=[],calls={rendered:0,refreshed:0},held=deferred();
  const context={user:{userId:7},token:'token-a',getToken:()=>context.token,Set,lang:'ru',API_BASE:'https://local.test',
   _loadResponses:{12:[{id:31,status:'pending'}]},
   fetch:(url,options)=>{requests.push({url,options});return context.respond();},respond:()=>held.promise,
   showToastWarn:value=>warnings.push(value),renderCabLoads:()=>calls.rendered++,refreshNotifications:()=>calls.refreshed++};
  vm.createContext(context);const code=source(path),start=code.indexOf('async function rejectResponse('),end=code.indexOf('function updateRespondCount()',start);
  assert.ok(start>=0&&end>start);vm.runInContext(code.slice(start,end),context);
  return{context,requests,warnings,calls,held};
 }
 test(path+': cargo rejection sends a deduplicated real POST and only then updates the pending row',async()=>{
  const h=rejection(),pending=h.context.rejectResponse(12,31);await h.context.rejectResponse(12,31);
  assert.equal(h.requests.length,1);assert.equal(h.context._loadResponses[12][0].status,'pending');
  assert.equal(h.requests[0].url,'https://local.test/api/responses/reject/31');assert.equal(h.requests[0].options.method,'POST');
  assert.equal(h.requests[0].options.headers.Authorization,'Bearer token-a');
  h.held.resolve(reply({ok:true}));await pending;
  assert.equal(h.context._loadResponses[12][0].status,'rejected');assert.equal(h.calls.rendered,1);assert.equal(h.calls.refreshed,1);
 });
 test(path+': failed or malformed cargo rejection preserves pending state and permits retry',async()=>{
  const h=rejection();h.context.respond=async()=>reply({detail:'Not your load'},false);
  await h.context.rejectResponse(12,31);assert.equal(h.context._loadResponses[12][0].status,'pending');assert.equal(h.warnings.length,1);
  h.context.respond=async()=>reply({});await h.context.rejectResponse(12,31);
  assert.equal(h.context._loadResponses[12][0].status,'pending');assert.equal(h.requests.length,2);assert.equal(h.calls.rendered,0);assert.equal(h.calls.refreshed,0);
 });
 test(path+': late cargo rejection cannot update a different account or emit its old error',async()=>{
  for(const ok of [true,false]){
   const h=rejection(),pending=h.context.rejectResponse(12,31);
   h.context.user={userId:8};h.context.token='token-b';
   h.held.resolve(reply(ok?{ok:true}:{detail:'Old failure'},ok));await pending;
   assert.equal(h.context._loadResponses[12][0].status,'pending');assert.equal(h.calls.rendered,0);assert.equal(h.calls.refreshed,0);assert.equal(h.warnings.length,0);
  }
 });
 test(path+': offline cargo rejection keeps the pending row and a later real retry can succeed',async()=>{
  const h=rejection();h.context.respond=async()=>{throw Error('offline');};
  await h.context.rejectResponse(12,31);assert.equal(h.context._loadResponses[12][0].status,'pending');
  h.context.respond=async()=>reply({ok:true});await h.context.rejectResponse(12,31);
  assert.equal(h.context._loadResponses[12][0].status,'rejected');assert.equal(h.requests.length,2);
 });
 test(path+': delivery confirmation refreshes canonical inbox without creating a local duplicate event',async()=>{
  const context={user:{userId:7},getToken:()=> 'token-a',TRANSLATIONS:{ru:{}},lang:'ru',
   document:{querySelector:()=>null},_deals:[{id:31,status:'delivered'}],fetch:async()=>reply({id:31,status:'completed'}),
   showToastWarn(){},pushNotif(){throw Error('Covered workflow events must come from the server inbox');},
   rendered:0,refreshed:0,renderCabDeals(){context.rendered++;},refreshNotifications(){context.refreshed++;},setTimeout(){}};
  vm.createContext(context);const code=source(path),start=code.indexOf('async function confirmDelivery('),end=code.indexOf('// Отклики на мои грузы:',start);
  vm.runInContext(code.slice(start,end),context);await context.confirmDelivery(31);
  assert.equal(context.rendered,1);assert.equal(context.refreshed,1);assert.equal(context._deals[0].status,'completed');
 });
}
