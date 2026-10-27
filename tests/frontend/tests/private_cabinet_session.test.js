import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const read=path=>readFileSync(new URL('../../../'+path,import.meta.url),'utf8');
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};};
const reply=(data,status=200)=>({ok:status===200,status,json:async()=>data});
const drain=async()=>{for(let i=0;i<24;i++)await Promise.resolve();};
function evaluateFunction(source,name,context,last=false){
 const start=last?source.lastIndexOf('async function '+name+'('):source.indexOf('async function '+name+'(')>=0?source.indexOf('async function '+name+'('):source.indexOf('function '+name+'(');
 const end=source.indexOf('\n}',start)+2;assert.ok(start>=0&&end>start,name);vm.runInContext(source.slice(start,end),context);
}
function cabinet(path){
 const source=read(path),fields={},calls={fetch:[],removed:[],stored:[],closed:[],renders:[],stopped:0,shown:0};
 for(const id of ['myLoadsList','myResponsesList','myDealsList','myTransportList','myTransportRequestsIn','myTransportRequestsOut','myTransportSubsList','subscriptionsList','paymentsList',
  'ordersList','dealsList','cabUserName','cabUserSub','cabAvatar','cabStatLoads','cabStatResponses','cabStatDeals','cabStatRevenue','cabinetPanel','profileOverlay','settingsOverlay',
  'cargoOverlay','postOverlay','postTruckOverlay','postTransportOverlay','transportRequestOverlay','onlineDot','btnLogin','btnReg','authBtns','userAvatar','notifBtn','ordersEmpty']){
  fields[id]={innerHTML:'OLD PRIVATE A',textContent:'OLD PRIVATE A',style:{display:'block'},previousElementSibling:null};
 }
 const context={user:{userId:7,name:'Account A'},currentUserId:7,token:'token-a',window:{_serverTrucks:[{id:11}],_truckCache:{1:{phone:'PRIVATE A'}}},
  _myLoads:[{id:11}],_orders:[{id:12}],_deals:[{id:13}],_loadResponses:{11:[{id:14,phone:'PRIVATE A'}]},_myTrucks:[{id:15}],_subscriptions:[{id:16}],dealsData:[{id:17}],
  performance:{now:()=>0},_currentCabTab:'loads',lang:'ru',TRANSLATIONS:{ru:{}},API_BASE:'https://local.test',AbortSignal,
  document:{getElementById:id=>fields[id]||null,querySelector:()=>null},
  getToken:()=>context.token,setToken:value=>{context.token=value;},
  _lsDel:key=>calls.removed.push(key),_lsSet:(key,value)=>calls.stored.push({key,value}),
  _lsGet:()=>JSON.stringify({userId:7,name:'Account A',token:'token-a'}),
  localStorage:{getItem:()=>context.token,removeItem:key=>calls.removed.push(key)},
  stopCabRefresh:()=>calls.stopped++,closeModal:id=>{calls.closed.push(id);if(fields[id])fields[id].style.display='none';},
  fetch:(url,options)=>{calls.fetch.push({url,options});return context.respond(url,options);},
  respond:async()=>reply({loads:[],responses:[],deals:[],offers:[],requests:[],subscriptions:[],payments:[]}),
  mapServerLoad:row=>({...row,fromServer:true}),persistOrders:()=>calls.stored.push('orders'),
  renderCabLoads:()=>calls.renders.push('loads'),renderCabResponses:()=>calls.renders.push('responses'),renderCabDeals:()=>calls.renders.push('deals'),
  renderMyTransportOffers:()=>calls.renders.push('offers'),renderIncomingTransportRequests:()=>calls.renders.push('requests-in'),
  renderMyTransportRequestsOut:()=>calls.renders.push('requests-out'),renderMyTransportSubs:()=>calls.renders.push('transport-subs'),
  renderSubscriptions:()=>calls.renders.push('subscriptions'),renderTrucks:()=>calls.renders.push('trucks'),renderDeals:()=>calls.renders.push('legacy-deals'),
  showUserState:()=>calls.shown++,setTimeout(){},console};
 vm.createContext(context);
 for(const name of ['resetCabinetState','doLogout','loadCabinetData','loadMyTransportOffers','loadIncomingTransportRequests','loadMyTransportRequestsOut','loadMyTransportSubs','loadSubscriptions','loadMyPayments','syncTrucksFromServer'])
  evaluateFunction(source,name,context);
 evaluateFunction(source,'loadDeals',context,true);
 return{context,fields,calls,source,switchAccount(){
  context.resetCabinetState();context.user={userId:8,name:'Account B'};context.currentUserId=8;context.token='token-b';
 }};
}
for(const path of ['main.js','frontend/main.js']){
 test(path+': real logout clears every private cache and visible cabinet while preserving public feeds',()=>{
  const h=cabinet(path);h.context.LOCAL=[{id:99,public:true}];h.context.doLogout();
  for(const key of ['_myLoads','_orders','_deals','_myTrucks','_subscriptions','dealsData'])assert.equal(h.context[key].length,0,key);
  assert.equal(Object.keys(h.context._loadResponses).length,0);assert.equal(Object.keys(h.context.window._truckCache).length,0);
  for(const key of ['ch_my_loads','ch_orders','ch_my_trucks','ch_notifs','ch_ai_parsed_load','ch_user'])assert.ok(h.calls.removed.includes(key),key);
  assert.equal(h.context.user,null);assert.equal(h.context.token,null);assert.equal(h.fields.cabinetPanel.style.display,'none');
  for(const id of ['myLoadsList','myDealsList','myTransportRequestsIn','paymentsList','subscriptionsList'])assert.equal(h.fields[id].innerHTML,'',id);
  assert.ok(h.calls.stopped>0);assert.equal(h.context.LOCAL[0].id,99);
 });
 test(path+': all three deferred cabinet responses cannot repopulate a different account',async()=>{
  for(const mode of ['logout','new-account','same-token-new-owner','rotated-token']){
   const h=cabinet(path),held=deferred();h.context.respond=()=>held.promise;
   h.context.loadCabinetData();assert.equal(h.calls.fetch.length,3);
   h.context.resetCabinetState();
   if(mode==='logout'){h.context.user=null;h.context.token=null;}
   if(mode==='new-account'){h.context.user={userId:8};h.context.token='token-b';}
   if(mode==='same-token-new-owner')h.context.user={userId:8};
   if(mode==='rotated-token')h.context.token='new-token-a';
   h.context._myLoads=[{id:900}];h.context._orders=[{id:901}];h.context._deals=[{id:902}];
   held.resolve(reply({loads:[{id:11}],responses:[{id:12,carrier_phone:'PRIVATE A'}],deals:[{id:13,carrier:{phone:'PRIVATE A'}}]}));await drain();
   assert.equal(h.context._myLoads[0].id,900);assert.equal(h.context._orders[0].id,901);assert.equal(h.context._deals[0].id,902);
   assert.equal(h.calls.renders.length,0);assert.equal(h.calls.stored.length,0);assert.equal(h.calls.fetch.length,3,'No child request for old loads');
  }
 });
 test(path+': child response reads are still guarded when the load list arrived before the switch',async()=>{
  const h=cabinet(path),held=deferred();
  h.context.respond=async url=>url.endsWith('/api/loads/my/loads')?reply({loads:[{id:11}]}):
   url.includes('/api/responses/load/')?held.promise:reply({responses:[],deals:[]});
  h.context.loadCabinetData();await drain();assert.ok(h.calls.fetch.some(x=>x.url.endsWith('/api/responses/load/11')));
  h.switchAccount();h.calls.renders.length=0;h.calls.stored.length=0;
  held.resolve(reply({responses:[{id:14,carrier_phone:'PRIVATE A'}]}));await drain();
  assert.equal(Object.keys(h.context._loadResponses).length,0);assert.equal(h.calls.renders.length,0);assert.equal(h.calls.stored.length,0);
 });
 test(path+': a current session still loads all canonical cabinet data and renders its selected tab',async()=>{
  for(const tab of ['loads','responses','deals']){
   const h=cabinet(path);h.context._currentCabTab=tab;
   h.context.respond=async url=>reply(url.endsWith('/api/loads/my/loads')?{loads:[{id:21}]}:
    url.endsWith('/api/responses/my')?{responses:[{id:22,load_id:21,from:'A',to:'B'}]}:
    url.endsWith('/api/deals/my')?{deals:[{id:23,shipper:{id:7,phone:'CURRENT'}}]}:{responses:[{id:24,carrier_phone:'CURRENT'}]});
   h.context.loadCabinetData();await drain();
   assert.ok(h.context._myLoads.some(x=>x.id===21));assert.equal(h.context._orders[0].id,22);assert.equal(h.context._deals[0].id,23);
   assert.equal(h.context._loadResponses[21][0].phone,'CURRENT');assert.ok(h.calls.renders.includes(tab));
  }
 });
 test(path+': deferred private transport, subscriptions, truck and payment loaders cannot render account A into B',async()=>{
  for(const name of ['loadMyTransportOffers','loadMyTransportRequestsOut','loadMyTransportSubs','loadSubscriptions','syncTrucksFromServer','loadMyPayments','loadDeals']){
   const h=cabinet(path),held=deferred();h.context.respond=()=>held.promise;
   const pending=h.context[name]();h.switchAccount();h.fields.paymentsList.innerHTML='Account B';
   held.resolve(reply({offers:[{id:11}],requests:[{id:12}],subscriptions:[{id:13}],trucks:[{id:14,user_id:7}],payments:[{id:15}],deals:[{id:16}]}));await pending;
   assert.equal(h.calls.renders.length,0,name);assert.equal(h.context._subscriptions.length,0,name);
   assert.equal(h.context._myTrucks.length,0,name);assert.equal(h.context.dealsData.length,0,name);assert.equal(h.fields.paymentsList.innerHTML,'Account B');
  }
 });
 test(path+': nested transport request loads stop both before and after private child reads on account switch',async()=>{
  for(const stage of ['offers','requests']){
   const h=cabinet(path),held=deferred();
   h.context.respond=(url)=>stage==='offers'||url.includes('/requests')?held.promise:Promise.resolve(reply({offers:[{id:11,status:'active'}]}));
   const pending=h.context.loadIncomingTransportRequests();await drain();h.switchAccount();
   held.resolve(reply(stage==='offers'?{offers:[{id:11,status:'active'}]}:{requests:[{id:12,shipper_phone:'PRIVATE A'}]}));await pending;
   assert.equal(h.calls.renders.length,0);assert.equal(h.calls.fetch.length,stage==='offers'?1:2);
  }
 });
 test(path+': late payment errors cannot replace the next account history with an old error',async()=>{
  const h=cabinet(path),held=deferred();h.context.respond=()=>held.promise;
  const pending=h.context.loadMyPayments();h.switchAccount();h.fields.paymentsList.innerHTML='Account B';
  held.reject(Error('old network failure'));await pending;assert.equal(h.fields.paymentsList.innerHTML,'Account B');
 });
 test(path+': private loaders make no request when only a stale token remains without a user',async()=>{
  const h=cabinet(path);h.context.user=null;
  h.context.loadCabinetData();
  for(const name of ['loadMyTransportOffers','loadIncomingTransportRequests','loadMyTransportRequestsOut','loadMyTransportSubs','loadSubscriptions','loadMyPayments','syncTrucksFromServer','loadDeals'])await h.context[name]();
  assert.equal(h.calls.fetch.length,0);assert.equal(h.calls.renders.length,0);
 });
 test(path+': revoked saved-session restore uses real logout and never calls signed-in UI with null user',async()=>{
  const h=cabinet(path);h.fields.btnLogin.style.display='none';const held=deferred();h.context.respond=()=>held.promise;
  const start=h.source.indexOf('// Восстанавливаем сессию безопасно'),end=h.source.indexOf('// Устанавливаем min дату',start);
  vm.runInContext(h.source.slice(start,end),h.context);
  held.resolve(reply({},401));await drain();
  assert.equal(h.context.user,null);assert.equal(h.context.token,null);assert.equal(h.fields.btnLogin.style.display,'');
  assert.equal(h.fields.userAvatar.style.display,'none');assert.equal(h.calls.shown,0);assert.equal(h.context._deals.length,0);
 });
}

for(const path of ['main.js','frontend/main.js']){
 function phone(name){
  const fields={sPhoneNew:{value:'+995599000001'},sPhoneCode:{value:'123456'},phoneChangeErr1:{style:{}},phoneChangeErr2:{style:{}},
   phoneChangeStep1:{style:{}},phoneChangeStep2:{style:{}},sPhone:{value:'BEFORE'}};
  const calls={stored:[],acks:[],requests:0},held=deferred(),button={disabled:false};
  const context={user:{userId:7,phone:'BEFORE'},token:'token-a',getToken:()=>context.token,API_BASE:'https://local.test',
   event:{target:button},document:{getElementById:id=>fields[id]||null},fetch:()=>{calls.requests++;return held.promise;},
   _lsSet:(...args)=>calls.stored.push(args),pushNotif:(...args)=>calls.acks.push(args),
   closePhoneChange(){},lang:'ru',TRANSLATIONS:{ru:{}}};
  vm.createContext(context);evaluateFunction(read(path),name,context);
  return{context,fields,calls,held};
 }
 for(const name of ['sendPhoneCode','confirmPhoneCode'])test(path+': '+name+' cannot apply a late account-A result to account B',async()=>{
  const h=phone(name),pending=h.context[name]();assert.equal(h.calls.requests,1,'Exercise an actual pending phone request');
  h.context.user={userId:8,phone:'ACCOUNT B'};h.context.token='token-b';
  h.held.resolve(reply({ok:true,phone:'+995599000001'}));await pending;
  assert.equal(h.context.user.phone,'ACCOUNT B');assert.equal(h.fields.sPhone.value,'BEFORE');
  assert.equal(h.calls.stored.length,0);assert.equal(h.calls.acks.length,0);
 });
}
