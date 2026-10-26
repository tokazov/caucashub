import {test} from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
function form(path,reply){
 const c={closed:[],warnings:[],saved:[],notifs:[],requests:0},fields={};
 for(const id of ['sName','sPhone','sTelegram','sRole','sInn','sInnAll','sOrgType','sOrgTypeAll','sCityAll','sTruckType','sTonnage','userAvatar','profileName']){
 fields[id]={value:id==='sInnAll'?'12345':'draft',getClientRects:()=>id==='sInn'?[]:[{}],classList:{add:()=>c.highlight=id,remove:()=>{}},addEventListener:()=>{},focus:()=>c.focus=id};
 }
 fields.settingsOverlay={classList:{contains:()=>true}};
 const ctx={openSettings:()=>{},lang:'ru',user:{name:'Before'},getToken:()=>ctx.token,token:'token',
 document:{getElementById:id=>fields[id],createElement:()=>({style:{},remove(){}}),body:{appendChild(){}}},
 fetch:async()=>{c.requests++;return typeof reply==='function'?await reply():reply;},
 showToastWarn:m=>c.warnings.push(m),closeModal:id=>c.closed.push(id),_lsSet:(k,v)=>c.saved.push(v),pushNotif:(...x)=>c.notifs.push(x),setTimeout:()=>{}};
 vm.createContext(ctx);
 const src=readFileSync(new URL('../../../'+path,import.meta.url),'utf8'),a=src.indexOf('async function saveSettings(){');
 vm.runInContext(src.slice(a,src.indexOf('\nfunction _refreshAnalytics',a)),ctx);
 return {ctx,c,fields};
}
const response=(status,data)=>({status,ok:status===200,json:async()=>data});
for(const path of ['main.js','frontend/main.js']){
 test(path+': waits, deduplicates, then commits server values once',async()=>{
 let resolve;const {ctx,c}=form(path,()=>new Promise(r=>resolve=r));
 const p=ctx.saveSettings();await ctx.saveSettings();
 assert.equal(c.requests,1);assert.equal(c.closed.length,0);assert.equal(c.saved.length,0);assert.equal(ctx.user.name,'Before');
 resolve(response(200,{ok:true,id:7,company_name:'Server name',phone:'confirmed',inn:'123456789',org_type:'LLC',city:'Tbilisi'}));await p;
 assert.equal(ctx.user.name,'Server name');assert.equal(ctx.user.phone,'confirmed');assert.equal(c.closed.length,1);assert.equal(c.saved.length,1);assert.equal(c.notifs.length,1);
 });
 for(const mode of ['edit','reopen','closed'])test(path+': late success preserves '+mode+' form',async()=>{
 let resolve;const {ctx,c,fields}=form(path,()=>new Promise(r=>resolve=r));const p=ctx.saveSettings();
 if(mode==='edit')fields.sName.value='New draft';
 if(mode==='reopen')ctx.openSettings.revision=1;
 if(mode==='closed')fields.settingsOverlay.classList.contains=()=>false;
 resolve(response(200,{ok:true,id:7,company_name:'Saved A'}));await p;
 assert.equal(c.saved.length,1);assert.equal(c.closed.length,0);assert.equal(c.notifs.length,0);
 if(mode==='edit')assert.equal(fields.sName.value,'New draft');
 });
 for(const mode of ['edit','reopen','closed','session'])test(path+': late validation ignores '+mode+' form',async()=>{
 let resolve;const {ctx,c,fields}=form(path,()=>new Promise(r=>resolve=r));const p=ctx.saveSettings();
 if(mode==='edit')fields.sName.value='New draft';if(mode==='reopen')ctx.openSettings.revision=1;
 if(mode==='closed')fields.settingsOverlay.classList.contains=()=>false;if(mode==='session')ctx.token='different';
 resolve(response(422,{detail:[{loc:['body','inn'],msg:'Old validation'}]}));await p;
 assert.equal(c.saved.length,0);assert.equal(c.warnings.length,0);assert.equal(c.highlight,undefined);assert.equal(c.focus,undefined);
 });
 for(const status of [401,403,500,422])test(path+': preserves draft on '+status,async()=>{
 const {ctx,c,fields}=form(path,response(status,{detail:[{loc:['body','inn'],msg:'Invalid INN'}]}));
 await ctx.saveSettings();assert.equal(ctx.user.name,'Before');assert.equal(c.closed.length,0);assert.equal(c.saved.length,0);assert.equal(c.notifs.length,0);assert.equal(c.warnings.length,1);assert.equal(fields.sInnAll.value,'12345');assert.equal(ctx.saveSettings.pending,false);
 if(status===422){assert.equal(c.highlight,'sInnAll');assert.equal(c.focus,'sInnAll');}
 });
 test(path+': network failure permits retry',async()=>{
 const {ctx,c}=form(path,()=>{throw Error('offline')});await ctx.saveSettings();await ctx.saveSettings();
 assert.equal(c.requests,2);assert.equal(c.closed.length,0);assert.equal(c.saved.length,0);assert.equal(c.warnings.length,2);
 });
 test(path+': rejects malformed success',async()=>{const {ctx,c}=form(path,response(200,{}));await ctx.saveSettings();assert.equal(c.closed.length,0);assert.equal(c.saved.length,0);assert.equal(c.warnings.length,1);});
 test(path+': no token means no request',async()=>{const {ctx,c}=form(path,response(200,{}));ctx.token=null;await ctx.saveSettings();assert.equal(c.requests,0);assert.equal(c.saved.length,0);});
 test(path+': old session cannot update profile',async()=>{let resolve;const {ctx,c}=form(path,()=>new Promise(r=>resolve=r));const p=ctx.saveSettings();ctx.token='new-token';resolve(response(200,{ok:true,id:7}));await p;assert.equal(c.saved.length,0);assert.equal(c.closed.length,0);});
}
