import {test as nodeTest} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

for(const path of ['main.js','frontend/main.js']){
const source=readFileSync(new URL('../../../'+path,import.meta.url),'utf8');
const test=(name,run)=>nodeTest(path+': '+name,run);
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};};
const reply=(data,status=200)=>({ok:status===200,status,json:async()=>data});
const settle=async()=>{for(let n=0;n<24;n++)await Promise.resolve();};
function loadFunction(name,context){
 const start=source.indexOf('async function '+name+'(')>=0?source.indexOf('async function '+name+'('):source.indexOf('function '+name+'(');
 const end=source.indexOf('\n}',start)+2;assert.ok(start>=0&&end>start,name);
 vm.runInContext(source.slice(start,end),context);
}
const deal={id:31,deal_number:'LOCAL-0031',deal_source:'transport',status:'confirmed',price:500,
 load_from:'Тбилиси',load_to:'Батуми',shipper_id:7,carrier_id:8,
 shipper:{id:7,name:'Local shipper',phone:'+995 (599) 10-20-30',email:'shipper@example.test'},
 carrier:{id:8,name:'Local carrier',phone:'+995599405060',email:'carrier@example.test'}};
function transport(){
 const fields={},calls={requests:[],warnings:[],incoming:0,notifications:0};
 for(const id of ['myDealsList','cabStatDeals','cabStatRevenue','cabTab-deals'])fields[id]={innerHTML:'',textContent:'0',style:{}};
 const context={window:null,user:{userId:8,name:'Local carrier'},currentUserId:8,token:'token-a',
  API_BASE:'http://127.0.0.1:8765',lang:'ru',TRANSLATIONS:{ru:{}},_currentCabTab:'transport-requests-in',
  _deals:[],_myLoads:[],_orders:[],_loadResponses:{},getToken:()=>context.token,
  document:{getElementById:id=>fields[id]||null,querySelectorAll:()=>[]},localStorage:{setItem(){}},
  publicUserName:value=>context.esc(value),persistOrders(){},renderCabLoads(){},renderCabResponses(){},
  loadIncomingTransportRequests:async()=>{calls.incoming++;},showToastWarn:value=>calls.warnings.push(value),
  refreshNotifications:()=>calls.notifications++,
  fetch:(url,options)=>{calls.requests.push({url,options});return context.respond(url,options);},
  respond:async url=>reply(url.includes('/accept')?{ok:true,deal_id:31}:url.endsWith('/api/deals/my')?{deals:[deal]}:
   url.endsWith('/api/loads/my/loads')?{loads:[]}:{responses:[]})};
 context.window=context;vm.createContext(context);
 const escapeStart=source.indexOf('function esc(s) {');
 vm.runInContext(source.slice(escapeStart,source.indexOf('// ── SAFE LOCALSTORAGE',escapeStart)),context);
 const contacts=source.indexOf('function dealPhoneHref(');
 vm.runInContext(source.slice(contacts,source.indexOf('function showSection(',contacts)),context);
 loadFunction('loadCabinetData',context);loadFunction('switchCabTab',context);
 const accept=source.indexOf('window.acceptTransportReq = async function(');
 vm.runInContext(source.slice(accept,source.indexOf('\n};',accept)+3),context);
 return{context,fields,calls};
}

test('transport acceptance makes the real cabinet tab, contacts and counters current without reload',async()=>{
 const h=transport();await h.context.acceptTransportReq(11);
 assert.equal(h.calls.incoming,1);assert.equal(h.context._deals[0].id,31);
 assert.equal(h.fields.cabStatDeals.textContent,1);assert.equal(h.fields.cabStatRevenue.textContent,'₾500');
 assert.match(h.fields.myDealsList.innerHTML,/href="tel:\+995599102030"/);
 assert.match(h.fields.myDealsList.innerHTML,/mailto:shipper%40example\.test/);
 const before=h.calls.requests.length;h.context.switchCabTab('deals',null);
 assert.equal(h.calls.requests.length,before);assert.equal(h.fields['cabTab-deals'].style.display,'block');
 assert.match(h.fields.myDealsList.innerHTML,/LOCAL-0031/);assert.doesNotMatch(h.fields.myDealsList.innerHTML,/Нет сделок/);
 assert.equal(h.calls.notifications,1);assert.equal(h.calls.warnings.length,1);
});

test('a cabinet read started before acceptance cannot erase its newly fetched deal',async()=>{
 const h=transport(),old=deferred();let reads=0;
 const respond=h.context.respond;h.context.respond=(url,options)=>url.endsWith('/api/deals/my')&&++reads===1?old.promise:respond(url,options);
 const first=h.context.loadCabinetData();await settle();await h.context.acceptTransportReq(11);
 old.resolve(reply({deals:[]}));assert.equal(await first,false);
 assert.equal(h.context._deals[0].id,31);assert.equal(h.fields.cabStatDeals.textContent,1);
 assert.match(h.fields.myDealsList.innerHTML,/LOCAL-0031/);
});

test('current empty cabinet results reset counters and failed reads preserve the last good deal',async()=>{
 const h=transport();await h.context.acceptTransportReq(11);
 const respond=h.context.respond;
 for(const bad of [reply({},500),reply({deals:{}})]){
  h.context.respond=(url,options)=>url.endsWith('/api/deals/my')?Promise.resolve(bad):respond(url,options);
  assert.equal(await h.context.loadCabinetData(),false);assert.equal(h.context._deals[0].id,31);
 }
 h.context.respond=(url,options)=>url.endsWith('/api/deals/my')?Promise.resolve(reply({deals:[]})):respond(url,options);
 assert.equal(await h.context.loadCabinetData(),true);
 assert.equal(h.fields.cabStatDeals.textContent,0);assert.equal(h.fields.cabStatRevenue.textContent,'₾0');
 assert.match(h.fields.myDealsList.innerHTML,/Нет сделок/);
});

for(const mode of ['logout','other-account-with-same-token','new-token'])test('late transport acceptance ignores '+mode,async()=>{
 const h=transport(),held=deferred();h.context.respond=()=>held.promise;
 const pending=h.context.acceptTransportReq(11);
 if(mode==='logout')h.context.user=null;
 if(mode==='other-account-with-same-token')h.context.user={userId:9,name:'Other account'};
 if(mode==='new-token')h.context.token='token-b';
 held.resolve(reply({ok:true,deal_id:31}));await pending;
 assert.equal(h.calls.requests.length,1);assert.equal(h.calls.incoming,0);
 assert.equal(h.calls.warnings.length,0);assert.equal(h.calls.notifications,0);assert.equal(h.context._deals.length,0);
});

for(const stage of ['incoming','cabinet'])test('account switch during '+stage+' refresh cannot receive the previous acceptance',async()=>{
 const h=transport(),held=deferred(),respond=h.context.respond;
 if(stage==='incoming')h.context.loadIncomingTransportRequests=()=>{h.calls.incoming++;return held.promise;};
 else h.context.respond=(url,options)=>url.endsWith('/api/deals/my')?held.promise:respond(url,options);
 const pending=h.context.acceptTransportReq(11);await settle();
 h.context.user={userId:9,name:'Other account'};h.context.token='token-b';h.context._deals=[{id:900}];
 h.fields.myDealsList.innerHTML='Other account';h.fields.cabStatDeals.textContent=9;
 held.resolve(stage==='cabinet'?reply({deals:[deal]}):undefined);await pending;
 assert.equal(h.context._deals[0].id,900);assert.equal(h.fields.myDealsList.innerHTML,'Other account');
 assert.equal(h.fields.cabStatDeals.textContent,9);assert.equal(h.calls.warnings.length,0);assert.equal(h.calls.notifications,0);
 if(stage==='incoming')assert.equal(h.calls.requests.length,1);
});

test('a rejected transport request never refreshes the cabinet or announces a deal',async()=>{
 const h=transport();h.context.respond=async()=>reply({detail:'Rejected'},403);
 await h.context.acceptTransportReq(11);
 assert.equal(h.calls.requests.length,1);assert.equal(h.calls.incoming,0);assert.equal(h.calls.warnings.length,0);
});

function login(){
 const fields={},calls={timers:[],saved:[]},button={disabled:false},profile=deferred();
 for(const id of ['loginSuccess','loginErrorMsg','btnLogin','btnReg','authBtns','userAvatar','profileName','profilePlanBadge','ordersEmpty','notifBtn','onlineDot'])fields[id]={style:{},textContent:'',innerHTML:''};
 fields.loginEmail={value:'carrier@example.test'};fields.loginPass={value:'LocalLogin39!'};
 const context={user:null,currentUserId:null,token:'token-a',lang:'ru',TRANSLATIONS:{ru:{}},API_BASE:'http://127.0.0.1:8765',
  document:{getElementById:id=>fields[id]||null,querySelector:()=>button},getToken:()=>context.token,
  CaucasAPI:{login:async()=>({ok:true,user_id:8,token:'token-a',role:'carrier'})},fetch:()=>profile.promise,
  applyCarrierProfileDefaults:(data,owner)=>{owner.truckType=data.truck_type;owner.tonnage=data.tonnage;},
  _lsSet:(key,value)=>calls.saved.push({key,value:JSON.parse(value)}),getPlanBadge:()=>'',closeModal(){},
  setTimeout:fn=>{calls.timers.push(fn);},showToastWarn(){},alert:msg=>{throw Error(msg);}};
 vm.createContext(context);loadFunction('doLogin',context);loadFunction('showUserState',context);
 return{context,fields,calls,profile};
}

test('login redraws the actual header and profile name as soon as its server profile arrives',async()=>{
 const h=login();await h.context.doLogin();h.calls.timers[0]();
 assert.equal(h.fields.userAvatar.textContent,'CA');
 h.profile.resolve(reply({id:8,company_name:'ტესტი გადამზიდავი',truck_type:'ref',tonnage:3.5}));await settle();
 assert.equal(h.fields.userAvatar.textContent,'ტე'.toUpperCase());
 assert.equal(h.fields.profileName.textContent,'ტესტი გადამზიდავი');
 assert.equal(h.context.user.truckType,'ref');assert.equal(h.context.user.tonnage,3.5);
 assert.equal(h.calls.saved.at(-1).value.name,'ტესტი გადამზიდავი');
 assert.equal(h.fields.notifBtn.style.display,'inline-flex');
});

for(const mode of ['logout','other-account-with-same-token','new-token','mismatched-profile-id'])test('late login profile cannot repaint '+mode,async()=>{
 const h=login();await h.context.doLogin();h.calls.timers[0]();
 if(mode==='logout')h.context.user=null;
 if(mode==='other-account-with-same-token')h.context.user={userId:9,name:'Other account'};
 if(mode==='new-token')h.context.token='token-b';
 h.fields.userAvatar.textContent='OTHER';h.fields.profileName.textContent='Other account';const stored=h.calls.saved.length;
 h.profile.resolve(reply({id:mode==='mismatched-profile-id'?9:8,company_name:'Old private name'}));await settle();
 assert.equal(h.fields.userAvatar.textContent,'OTHER');assert.equal(h.fields.profileName.textContent,'Other account');
 assert.equal(h.calls.saved.length,stored);
});

test('unavailable profile hydration keeps a successful login usable',async()=>{
 const h=login();await h.context.doLogin();h.calls.timers[0]();
 h.profile.reject(Error('offline'));await settle();
 assert.equal(h.context.user.userId,8);assert.equal(h.fields.userAvatar.textContent,'CA');
 assert.equal(h.fields.profileName.textContent,'carrier');assert.equal(h.fields.userAvatar.style.display,'flex');
});
}
