import {test} from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';

const source=path=>readFileSync(new URL('../../../'+path,import.meta.url),'utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function helper(path,context){
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
  fetch:async()=>({status:200,json:async()=>profile}),AbortSignal,
  CaucasAPI:{login:async()=>({ok:true,user_id:7,token:'token',role:'carrier'}),
    register:async body=>{calls.requests.push(body);return {ok:true,user_id:7,token:'token',truck_type:'ref',tonnage:3.5};}},
  _lsSet:(key,value)=>calls.saved.push(JSON.parse(value)),_lsGet:()=>JSON.stringify(saved),_lsDel:()=>{},
  localStorage:{getItem:()=>null,removeItem:()=>{}},closeModal:()=>{},showUserState:()=>{},
  setTimeout:callback=>calls.timers.push(callback),alert:message=>{throw Error(message);},showToastWarn:()=>{}};
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
  assert.equal(calls.requests[0].truckType,'ref');assert.equal(calls.requests[0].tonnage,'3.5');
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
  assert.equal(requests[0].truck_type,'ref');assert.equal(requests[0].tonnage,'3.5');
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
