import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return{promise,resolve};};
const reply=(body,ok=true)=>({ok,json:async()=>body});
const drain=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
function telegram(path){
 const elements={tgConnectBtn:{disabled:false,textContent:'Connect',style:{display:'block'}},tgLinkedBlock:{style:{display:'none'}}};
 const calls={requests:[],opened:[],warnings:[],acks:[],intervals:new Map(),confirms:0};let timer=0;
 const context={user:{userId:7},token:'token-a',lang:'ru',URL,API_BASE:'https://local.test',
  getToken:()=>context.token,document:{getElementById:id=>elements[id]||null},
  window:{open:(...args)=>calls.opened.push(args)},confirm:()=>{calls.confirms++;return true;},
  showToastWarn:value=>calls.warnings.push(value),pushNotif:(...args)=>calls.acks.push(args),
  fetch:(url,options)=>{calls.requests.push({url,options});return context.respond(url,options);},
  respond:async()=>reply({linked:false}),
  setInterval:(fn,ms)=>{const id=++timer;calls.intervals.set(id,{fn,ms});return id;},
  clearInterval:id=>calls.intervals.delete(id)};
 vm.createContext(context);const source=readFileSync(new URL('../../../'+path,import.meta.url),'utf8');
 const start=source.indexOf('// ── TELEGRAM CONNECT'),end=source.indexOf('// Язык восстанавливается раньше',start);
 assert.ok(start>=0&&end>start);vm.runInContext(source.slice(start,end),context);
 return{context,calls,elements,async poll(){const fn=[...calls.intervals.values()][0]?.fn;assert.ok(fn);await fn();}};
}
for(const path of ['main.js','frontend/main.js']){
 test(path+': Telegram buttons and initial status do not request anything without authentication',async()=>{
  const h=telegram(path);h.context.user=null;h.context.token=null;
  await h.context.connectTelegram();await h.context.unlinkTelegram();await h.context._initTgStatus();
  assert.equal(h.calls.requests.length,0);assert.equal(h.calls.confirms,0);assert.equal(h.calls.opened.length,0);
 });
 test(path+': existing connect flow uses one authenticated POST, bounded GET poll and the actual linked UI',async()=>{
  const h=telegram(path),held=deferred();h.context.respond=()=>held.promise;
  const pending=h.context.connectTelegram();await h.context.connectTelegram();
  assert.equal(h.calls.requests.length,1);assert.equal(h.elements.tgConnectBtn.disabled,true);
  assert.equal(h.calls.requests[0].url,'https://local.test/api/tg/generate-link');assert.equal(h.calls.requests[0].options.method,'POST');
  assert.equal(h.calls.requests[0].options.headers.Authorization,'Bearer token-a');
  held.resolve(reply({link:'https://t.me/qa_example_bot?start=local-only',token:'local-only'}));await pending;
  assert.deepEqual(h.calls.opened,[['https://t.me/qa_example_bot?start=local-only','_blank']]);
  assert.equal(h.elements.tgConnectBtn.disabled,false);assert.equal([...h.calls.intervals.values()][0].ms,3000);
  h.context.respond=async()=>reply({linked:true,telegram_id:'synthetic-local-chat'});await h.poll();
  assert.equal(h.calls.requests.at(-1).url,'https://local.test/api/tg/status');assert.equal(h.calls.requests.at(-1).options.method,'GET');
  assert.equal(h.elements.tgConnectBtn.style.display,'none');assert.equal(h.elements.tgLinkedBlock.style.display,'flex');
  assert.equal(h.calls.acks.length,1);assert.equal(h.calls.intervals.size,0);
 });
 test(path+': malformed successful link payloads and unsafe links never open or start polling',async()=>{
  for(const body of [{},{link:'javascript:bad()'},{link:'https://evil.test/qa?start=local'}]){
   const h=telegram(path);h.context.respond=async()=>reply(body);await h.context.connectTelegram();
   assert.equal(h.calls.opened.length,0);assert.equal(h.calls.intervals.size,0);assert.equal(h.calls.warnings.length,1);
   assert.equal(h.elements.tgConnectBtn.disabled,false);
  }
 });
 test(path+': a failed link request restores the button and exposes a failure without fictional success',async()=>{
  for(const respond of [async()=>reply({detail:'Denied'},false),async()=>{throw Error('offline');}]){
   const h=telegram(path);h.context.respond=respond;await h.context.connectTelegram();
   assert.equal(h.elements.tgConnectBtn.disabled,false);assert.equal(h.calls.opened.length,0);assert.equal(h.calls.acks.length,0);
   assert.equal(h.calls.warnings.length,1);
  }
 });
 test(path+': late connect responses cannot open Telegram or leave controls pending for the next account',async()=>{
  const h=telegram(path),held=deferred();h.context.respond=()=>held.promise;
  const pending=h.context.connectTelegram();h.context.user={userId:8};h.context.token='token-b';h.context._stopTelegramPolling();
  held.resolve(reply({link:'https://t.me/qa_example_bot?start=old-account'}));await pending;
  assert.equal(h.calls.opened.length,0);assert.equal(h.calls.intervals.size,0);assert.equal(h.calls.acks.length,0);
  assert.equal(h.elements.tgConnectBtn.disabled,false);
 });
 test(path+': status reads arriving after logout cannot render the previous account as linked',async()=>{
  const h=telegram(path),held=deferred();h.context.respond=()=>held.promise;
  const pending=h.context._initTgStatus();h.context.user=null;h.context.token=null;h.context._stopTelegramPolling();
  held.resolve(reply({linked:true}));await pending;
  assert.equal(h.elements.tgLinkedBlock.style.display,'none');assert.equal(h.calls.acks.length,0);
 });
 test(path+': existing unlink uses authenticated DELETE and only commits a valid ok response',async()=>{
  const h=telegram(path);h.elements.tgConnectBtn.style.display='none';h.elements.tgLinkedBlock.style.display='flex';
  h.context.respond=async()=>reply({ok:true});await h.context.unlinkTelegram();
  assert.equal(h.calls.requests[0].url,'https://local.test/api/tg/unlink');assert.equal(h.calls.requests[0].options.method,'DELETE');
  assert.equal(h.calls.requests[0].options.headers.Authorization,'Bearer token-a');
  assert.equal(h.elements.tgLinkedBlock.style.display,'none');assert.equal(h.elements.tgConnectBtn.style.display,'block');assert.equal(h.calls.acks.length,1);
  for(const body of [{},{ok:false}]){
   const failed=telegram(path);failed.elements.tgLinkedBlock.style.display='flex';failed.context.respond=async()=>reply(body);
   await failed.context.unlinkTelegram();assert.equal(failed.elements.tgLinkedBlock.style.display,'flex');
   assert.equal(failed.calls.acks.length,0);assert.equal(failed.calls.warnings.length,1);
  }
 });
 test(path+': late unlink success and errors cannot update a different logged-in account',async()=>{
  for(const success of [true,false]){
   const h=telegram(path),held=deferred();h.context.respond=()=>held.promise;
   const pending=h.context.unlinkTelegram();h.context.user={userId:8};h.context.token='token-b';h.context._stopTelegramPolling();
   h.elements.tgLinkedBlock.style.display='flex';
   held.resolve(reply(success?{ok:true}:{detail:'Old error'},success));await pending;
   assert.equal(h.elements.tgLinkedBlock.style.display,'flex');assert.equal(h.calls.acks.length,0);assert.equal(h.calls.warnings.length,0);
  }
 });
 test(path+': the existing status polling expires after at most twenty checks and ignores late linked responses',async()=>{
  const h=telegram(path);h.context.respond=async()=>reply({link:'https://t.me/qa_example_bot?start=local-only'});
  await h.context.connectTelegram();h.context.respond=async()=>reply({linked:false});
  for(let i=0;i<21;i++)await h.poll();
  assert.equal(h.calls.intervals.size,0);assert.equal(h.calls.requests.filter(x=>x.options.method==='GET').length,20);
  assert.equal(h.calls.acks.length,0);
 });
}
