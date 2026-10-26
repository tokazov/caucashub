import {test} from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';

const source=path=>readFileSync(new URL('../../../'+path,import.meta.url),'utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function helper(path,context){
 const api=source(path.startsWith('frontend/')?'frontend/api.js':'api.js'),capacity=api.indexOf('function carrierTonnageValue(');
 vm.runInContext(api.slice(capacity,api.indexOf('// ── AUTH',capacity)),context);
 const code=source(path),a=code.indexOf('function applyCarrierProfileDefaults(');
 vm.runInContext(code.slice(a,code.indexOf('async function doLogin()',a)),context);
}
function app(path,profile={id:7,truck_type:'ref',tonnage:3.5}){
 const fields={},calls={requests:[],timers:[],saved:[]},button={disabled:false};
 for(const [id,value] of Object.entries({loginEmail:'carrier@example.test',loginPass:'StrongPass39!',
  regName:'Carrier',regEmail:'new@example.test',regPass:'StrongPass39!',regPhone:'+995599000001',
  regRole:'carrier',regInn:'',regOrgType:'',regCity:'Tbilisi',regTruckType:'ref',regTonnage:'3.5'}))
  fields[id]={value,style:{}};
 fields.regAgree={checked:true};fields.loginSuccess={style:{}};fields.regSuccess={style:{}};
 const saved={name:'Saved',truckType:'tent',tonnage:20};
 const context={user:null,currentUserId:null,lang:'ru',TRANSLATIONS:{ru:{}},API_BASE:'https://api.test',
  document:{getElementById:id=>fields[id]||null,querySelector:()=>button},getToken:()=> 'token',setToken:()=>{},
  fetch:async()=>({ok:true,status:200,json:async()=>profile}),AbortSignal,
  CaucasAPI:{login:async()=>({ok:true,user_id:7,token:'token',role:'carrier'}),
    register:async body=>{calls.requests.push(body);return {ok:true,user_id:7,token:'token',truck_type:'ref',tonnage:3.5};}},
  _lsSet:(key,value)=>calls.saved.push(JSON.parse(value)),_lsGet:()=>JSON.stringify(saved),_lsDel:()=>{},
  localStorage:{getItem:()=>null,removeItem:()=>{}},closeModal:()=>{},showUserState:()=>{},
  setTimeout:callback=>calls.timers.push(callback),alert:message=>{throw Error(message);},showToastWarn:()=>{}};
 context.sessionToken='token';context.getToken=()=>context.sessionToken;context.setToken=value=>{context.sessionToken=value;};
 vm.createContext(context);helper(path,context);
 return {context,calls,fields,code:source(path)};
}
for(const path of ['main.js','frontend/main.js']){
 test(path+': new login hydrates server carrier defaults',async()=>{
  const {context,calls,code}=app(path);
  const start=code.indexOf('async function doLogin()');
  vm.runInContext(code.slice(start,code.indexOf('async function doRegister()',start)),context);
  await context.doLogin();calls.timers[0]();await tick();
  assert.equal(context.user.truckType,'ref');assert.equal(context.user.tonnage,3.5);
 });
 test(path+': saved session reads server defaults and explicit clearing',async()=>{
  for(const profile of [{id:7,truck_type:'ref',tonnage:3.5},{id:7,truck_type:null,tonnage:null}]){
   const {context,code}=app(path,profile);
   const start=code.indexOf('// Восстанавливаем сессию безопасно');
   vm.runInContext(code.slice(start,code.indexOf('// Устанавливаем min дату',start)),context);
   await tick();
   assert.equal(context.user.truckType,profile.truck_type??'');
   assert.equal(context.user.tonnage,profile.tonnage??'');
  }
 });
 test(path+': registration submits defaults and stores confirmed values',async()=>{
  const {context,calls,code}=app(path);const start=code.indexOf('async function doRegister()');
  vm.runInContext(code.slice(start,code.indexOf('function showUserState()',start)),context);
  await context.doRegister();
  assert.equal(calls.requests[0].truckType,'ref');assert.equal(calls.requests[0].tonnage,3.5);
  assert.equal(context.user.truckType,'ref');assert.equal(context.user.tonnage,3.5);
 });
 test(path+': missing legacy fields preserve defaults; null clears them',()=>{
  const {context}=app(path);context.user={truckType:'tent',tonnage:20};
  context.applyCarrierProfileDefaults({},context.user);
  assert.equal(context.user.truckType,'tent');assert.equal(context.user.tonnage,20);
  context.applyCarrierProfileDefaults({truck_type:null,tonnage:null},context.user);
  assert.equal(context.user.truckType,'');assert.equal(context.user.tonnage,'');
 });
 test(path+': opening settings clears a stale truck selection',()=>{
  const {context,code,fields}=app(path);
  for(const id of ['sTruckType','sTonnage','sRole'])fields[id]={value:'stale'};
  fields.settingsOverlay={classList:{add:()=>{}},style:{},querySelector:()=>null};
  Object.assign(context,{user:{name:'Carrier',truckType:'',tonnage:''},window:{innerWidth:1000},
    _setupCityAutocomplete:()=>{},_initTgStatus:()=>{}});
  const start=code.indexOf('function openSettings()');
  vm.runInContext(code.slice(start,code.indexOf('async function saveSettings()',start)),context);
  context.openSettings();assert.equal(fields.sTruckType.value,'');assert.equal(fields.sTonnage.value,'');
 });
}
for(const path of ['api.js','frontend/api.js']){
 test(path+': registration API sends and returns server defaults',async()=>{
  const requests=[],context={AbortSignal,localStorage:{getItem:()=>null,setItem:()=>{},removeItem:()=>{}},
   fetch:async(url,opts)=>{requests.push(JSON.parse(opts.body));return {ok:true,status:200,
    json:async()=>({token:'token',user_id:7,truck_type:'ref',tonnage:3.5})};}};
  vm.createContext(context);const code=source(path);
  vm.runInContext(code.slice(0,code.indexOf('// ── SYNC'))+';globalThis.client=CaucasAPI;',context);
  const result=await context.client.register({email:'new@example.test',password:'Strong39!',truckType:'ref',tonnage:'3.5'});
  assert.equal(requests[0].truck_type,'ref');assert.equal(requests[0].tonnage,3.5);
  assert.equal(result.truck_type,'ref');assert.equal(result.tonnage,3.5);
 });
 test(path+': update API distinguishes omitted and cleared defaults',async()=>{
  const requests=[],context={AbortSignal,localStorage:{getItem:()=>null},
   fetch:async(url,opts)=>{requests.push(JSON.parse(opts.body));return {ok:true,status:200,json:async()=>({ok:true})};}};
  vm.createContext(context);const code=source(path);
  vm.runInContext(code.slice(0,code.indexOf('// ── SYNC'))+';globalThis.client=CaucasAPI;',context);
  await context.client.updateProfile({city:'Tbilisi'});
  assert.equal(Object.hasOwn(requests[0],'truck_type'),false);assert.equal(Object.hasOwn(requests[0],'tonnage'),false);
  await context.client.updateProfile({truck_type:null,tonnage:null});
  assert.equal(requests[1].truck_type,null);assert.equal(requests[1].tonnage,null);
 });
}

for(const path of ['main.js','frontend/main.js']){
 test(path+': late login profile cannot hydrate after logout or a different login',async()=>{
  for(const mode of ['logout','new-login','mismatched-id']){
   const {context,calls,code}=app(path);let resolve;
   context.fetch=()=>new Promise(r=>{resolve=r;});
   const start=code.indexOf('async function doLogin()');
   vm.runInContext(code.slice(start,code.indexOf('async function doRegister()',start)),context);
   await context.doLogin();calls.timers[0]();
   const oldUser=context.user;
   if(mode==='logout')context.user=null;
   if(mode==='new-login')context.user={userId:8,name:'Other',truckType:'tent',tonnage:20};
   const before=calls.saved.length;
   resolve({ok:true,status:200,json:async()=>({id:mode==='mismatched-id'?8:7,truck_type:'ref',tonnage:3.5})});
   await tick();
   assert.equal(calls.saved.length,before);
   if(mode==='logout')assert.equal(context.user,null);
   if(mode==='new-login'){assert.equal(context.user.userId,8);assert.equal(context.user.truckType,'tent');}
   if(mode==='mismatched-id'){assert.equal(context.user,oldUser);assert.equal(context.user.truckType,undefined);}
  }
 });
 test(path+': late saved-session response cannot replace a new login or restore after logout',async()=>{
  for(const mode of ['new-login','logout','late-401','late-network']){
   const {context,calls,code}=app(path);let resolve,reject,token='token';
   context.getToken=()=>token;context.setToken=value=>{token=value;};
   context.fetch=()=>new Promise((r,j)=>{resolve=r;reject=j;});
   const start=code.indexOf('// Восстанавливаем сессию безопасно');
   vm.runInContext(code.slice(start,code.indexOf('// Устанавливаем min дату',start)),context);
   if(mode==='logout'){token=null;context.user=null;}
   else {token='other-token';context.user={userId:8,name:'Other',truckType:'tent',tonnage:20};}
   const other=context.user;
   if(mode==='late-network')reject(new Error('offline'));
   else resolve({ok:mode!=='late-401',status:mode==='late-401'?401:200,
    json:async()=>({id:7,truck_type:'ref',tonnage:3.5})});
   await tick();
   assert.equal(context.user,other);assert.equal(calls.saved.length,0);
   if(other)assert.equal(context.user.truckType,'tent');
  }
 });
 test(path+': delayed login timer cannot close a form after logout',async()=>{
  const{context,calls,code}=app(path);let closed=0,fetched=0;
  context.closeModal=()=>closed++;context.fetch=async()=>{fetched++;throw Error('should not fetch');};
  const start=code.indexOf('async function doLogin()');
  vm.runInContext(code.slice(start,code.indexOf('async function doRegister()',start)),context);
  await context.doLogin();context.user=null;calls.timers[0]();await tick();
  assert.equal(closed,0);assert.equal(fetched,0);
 });
 test(path+': registration rejects invalid capacities before calling its API',async()=>{
  for(const capacity of ['NaN','Infinity','0','-1','100.01']){
   const{context,calls,fields,code}=app(path);fields.regTonnage.value=capacity;
   let focused=false;fields.regTonnage.classList={add(){},remove(){}};fields.regTonnage.addEventListener=()=>{};
   fields.regTonnage.focus=()=>{focused=true;};
   const start=code.indexOf('async function doRegister()');
   vm.runInContext(code.slice(start,code.indexOf('function showUserState()',start)),context);
   await context.doRegister();assert.equal(calls.requests.length,0);assert.equal(context.user,null);assert.ok(focused);
  }
 });
 test(path+': omitted canonical values retain legacy cache keys while null clears defaults',()=>{
  const{context}=app(path);
  const target={truck_type:'legacy-type',truckType:'tent',tonnage:20,type:'legacy-body'};
  context.applyCarrierProfileDefaults({truck_type:undefined,tonnage:undefined},target);
  assert.equal(target.truckType,'tent');assert.equal(target.tonnage,20);
  context.applyCarrierProfileDefaults({truck_type:'ref',tonnage:3.5},target);
  assert.equal(target.truckType,'ref');assert.equal(target.tonnage,3.5);
  assert.equal(target.truck_type,'legacy-type');assert.equal(target.type,'legacy-body');
  for(const tonnage of [NaN,Infinity,true,0,-1,101]){
   context.applyCarrierProfileDefaults({tonnage},target);assert.equal(target.tonnage,3.5);
  }
  context.applyCarrierProfileDefaults({truck_type:null,tonnage:null},target);
  assert.equal(target.truckType,'');assert.equal(target.tonnage,'');
 });
}
for(const path of ['api.js','frontend/api.js']){
 test(path+': invalid capacities are never serialized as null or sent to the server',async()=>{
  let requests=0;
  const context={AbortSignal,localStorage:{getItem:()=>null,setItem(){},removeItem(){}},
   fetch:async()=>{requests++;throw Error('invalid capacity reached API');}};
  vm.createContext(context);const code=source(path);
  vm.runInContext(code.slice(0,code.indexOf('// ── SYNC'))+';globalThis.client=CaucasAPI;',context);
  for(const tonnage of [NaN,Infinity,-Infinity,true,false,0,-1,100.1,'NaN','Infinity','0',{},[]]){
   const registered=await context.client.register({email:'x@example.test',password:'Strong39!',truckType:'ref',tonnage});
   assert.equal(registered.ok,false);assert.equal(registered.status,422);
   const updated=await context.client.updateProfile({tonnage});
   assert.equal(updated.ok,false);assert.equal(updated.status,422);
  }
  assert.equal(requests,0);
 });
 test(path+': fractional tonnes are numeric and blank capacity explicitly clears',async()=>{
  const requests=[],context={AbortSignal,localStorage:{getItem:()=>null,setItem(){},removeItem(){}},
   fetch:async(url,opts)=>{requests.push(JSON.parse(opts.body));return{ok:true,status:200,json:async()=>({ok:true})};}};
  vm.createContext(context);const code=source(path);
  vm.runInContext(code.slice(0,code.indexOf('// ── SYNC'))+';globalThis.client=CaucasAPI;',context);
  await context.client.updateProfile({truck_type:'ref',tonnage:'24.125'});
  await context.client.updateProfile({truck_type:'',tonnage:'   '});
  assert.equal(requests[0].tonnage,24.125);assert.equal(requests[1].tonnage,null);assert.equal(requests[1].truck_type,null);
 });
}

function logoutActual(h){
 const{context,fields,code}=h;
 for(const id of ['btnLogin','btnReg','userAvatar','ordersList','ordersEmpty','authBtns','onlineDot'])
  fields[id]={style:{},innerHTML:''};
 const start=code.indexOf('function doLogout()');
 vm.runInContext(code.slice(start,code.indexOf('function openProfile()',start)),context);
 context.doLogout();
}
for(const path of ['main.js','frontend/main.js']){
 test(path+': actual logout invalidates a pending login profile response',async()=>{
  const h=app(path),{context,calls,code}=h;let resolve;
  context.fetch=()=>new Promise(r=>{resolve=r;});
  const start=code.indexOf('async function doLogin()');
  vm.runInContext(code.slice(start,code.indexOf('async function doRegister()',start)),context);
  await context.doLogin();calls.timers[0]();const before=calls.saved.length;
  logoutActual(h);assert.equal(context.getToken(),null);assert.equal(context.currentUserId,null);
  resolve({ok:true,status:200,json:async()=>({id:7,truck_type:'ref',tonnage:3.5})});await tick();
  assert.equal(context.user,null);assert.equal(calls.saved.length,before);
 });
 test(path+': a second actual login keeps its own profile when the earlier response arrives',async()=>{
  const h=app(path),{context,calls,code}=h;let resolve;
  context.fetch=()=>new Promise(r=>{resolve=r;});
  const start=code.indexOf('async function doLogin()');
  vm.runInContext(code.slice(start,code.indexOf('async function doRegister()',start)),context);
  await context.doLogin();calls.timers[0]();
  context.CaucasAPI.login=async()=>{context.setToken('second-token');return{ok:true,user_id:8,token:'second-token',role:'carrier'};};
  await context.doLogin();const second=context.user,before=calls.saved.length;
  resolve({ok:true,status:200,json:async()=>({id:7,truck_type:'ref',tonnage:3.5})});await tick();
  assert.equal(context.user,second);assert.equal(context.currentUserId,8);
  assert.equal(context.getToken(),'second-token');assert.equal(calls.saved.length,before);
  assert.equal(context.user.truckType,undefined);
 });
 test(path+': actual logout cannot be undone by startup saved-session hydration',async()=>{
  const h=app(path),{context,calls,code}=h;let resolve;
  context.fetch=()=>new Promise(r=>{resolve=r;});
  const start=code.indexOf('// Восстанавливаем сессию безопасно');
  vm.runInContext(code.slice(start,code.indexOf('// Устанавливаем min дату',start)),context);
  logoutActual(h);
  resolve({ok:true,status:200,json:async()=>({id:7,truck_type:'ref',tonnage:3.5})});await tick();
  assert.equal(context.user,null);assert.equal(context.getToken(),null);assert.equal(calls.saved.length,0);
 });
}

const carrierTypes=['tent','ref','reftent','megatent','bort','termos','gazel','container','auto','evacuator','cistern','grain','dump'];
for(const path of ['index.html','frontend/index.html']){
 for(const id of ['regTruckType','sTruckType'])test(path+': '+id+' submits canonical enum values from actual HTML',()=>{
  const html=source(path);
  const select=html.match(new RegExp('<select[^>]*id="'+id+'"[^>]*>[\\s\\S]*?<\\/select>'));
  assert.ok(select,'Expected carrier selector '+id);
  const options=[...select[0].matchAll(/<option\b([^>]*)>([\s\S]*?)<\/option>/g)];
  assert.equal(options.length,carrierTypes.length+(id==='sTruckType'?1:0));
  const values=options.map(([,attributes,label])=>{
   const value=attributes.match(/\bvalue="([^"]*)"/);
   assert.ok(value,'Every option must have an explicit API value: '+label);
   return value[1];
  });
  assert.deepEqual(values.filter(Boolean).sort(),[...carrierTypes].sort());
  assert.equal(new Set(values).size,values.length);
  assert.equal(values.includes(''),id==='sTruckType','Settings must support explicit clearing');
  assert.equal(values.includes('Другой'),false);
 });
}
for(const path of ['main.js','frontend/main.js']){
 function telegramContext(){
  let token=null;
  const calls={requests:[],rendered:[],reads:0};
  const context={getToken:()=>{calls.reads++;return token;},
   apiFetch:async route=>{calls.requests.push(route);return{linked:true};},
   _renderTgStatus:linked=>calls.rendered.push(linked)};
  vm.createContext(context);
  const code=source(path),start=code.indexOf('async function _initTgStatus(){');
  assert.ok(start>=0);
  vm.runInContext(code.slice(start,code.indexOf('window.connectTelegram',start)),context);
  return{context,calls,setToken:value=>{token=value;}};
 }
 test(path+': Telegram initialization with no token makes no request',async()=>{
  const h=telegramContext();
  assert.equal(Object.hasOwn(h.context,'token'),false);
  await h.context._initTgStatus();
  assert.equal(h.calls.reads,1);assert.equal(h.calls.requests.length,0);
  assert.equal(h.calls.rendered.length,0);
 });
 test(path+': Telegram initialization reads current authentication without a token global',async()=>{
  const h=telegramContext();h.setToken('active-token');
  await h.context._initTgStatus();
  assert.deepEqual(h.calls.requests,['/api/tg/status']);
  assert.deepEqual(h.calls.rendered,[true]);
  assert.equal(Object.hasOwn(h.context,'token'),false);
  h.setToken(null);await h.context._initTgStatus();
  assert.equal(h.calls.requests.length,1);assert.equal(h.calls.reads,2);
 });
}


for(const path of ['main.js','frontend/main.js']){
 test(path+': a late login profile read preserves an explicitly cleared settings draft and null PUT',async()=>{
  const {context,calls,fields,code}=app(path);
  let resolveProfile;
  const pendingProfile=new Promise(resolve=>{resolveProfile=resolve;});
  const puts=[];
  context.fetch=async(url,options={})=>{
   if(options.method==='PUT'){
    puts.push(JSON.parse(options.body));
    return{ok:true,status:200,json:async()=>({ok:true,id:7,truck_type:null,tonnage:null})};
   }
   return pendingProfile;
  };
  let settingsOpen=false;
  for(const id of ['sName','sEmail','sPhone','sTelegram','sRole','sInn','sInnAll','sOrgType','sOrgTypeAll','sCityAll','sTruckType','sTonnage']){
   fields[id]={value:'',style:{},getClientRects:()=>[{}],
    classList:{add(){},remove(){}},addEventListener(){},focus(){}};
  }
  fields.settingsOverlay={classList:{add:()=>{settingsOpen=true;},contains:()=>settingsOpen},
   style:{},querySelector:()=>null};
  Object.assign(context,{window:{innerWidth:1000},_setupCityAutocomplete(){},_initTgStatus(){},pushNotif(){},
   closeModal:id=>{if(id==='settingsOverlay')settingsOpen=false;}});
  context.document.createElement=()=>({style:{},remove(){}});
  context.document.body={appendChild(){}};
  const loginStart=code.indexOf('async function doLogin()');
  vm.runInContext(code.slice(loginStart,code.indexOf('async function doRegister()',loginStart)),context);
  const settingsStart=code.indexOf('function openSettings()');
  vm.runInContext(code.slice(settingsStart,code.indexOf('function _refreshAnalytics()',settingsStart)),context);
  await context.doLogin();calls.timers[0]();
  // A pending server read may coexist with already known cached defaults.
  context.user.truckType='tent';context.user.tonnage=12.5;
  context.openSettings();assert.equal(fields.sTonnage.value,12.5);
  fields.sTruckType.value='';fields.sTonnage.value='';
  resolveProfile({ok:true,status:200,json:async()=>({id:7,truck_type:'tent',tonnage:12.5})});
  await tick();
  assert.equal(context.user.tonnage,12.5,'The profile read still hydrates its canonical cache');
  assert.equal(fields.sTruckType.value,'');assert.equal(fields.sTonnage.value,'','Hydration must not overwrite an edited input');
  await context.saveSettings();
  assert.equal(puts.length,1);assert.equal(puts[0].truck_type,null);assert.equal(puts[0].tonnage,null);
  assert.equal(context.user.truckType,'');assert.equal(context.user.tonnage,'');
 });
}
