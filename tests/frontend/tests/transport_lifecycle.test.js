import {test} from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};};
const offer=(id,name)=>({id,company_name:name,truck_type:'tent',available_from:'2030-01-01',capacity_kg:20000});
const reply=(offers,total=offers.length)=>({ok:true,status:200,json:async()=>({offers,total})});
const settle=async()=>{for(let i=0;i<8;i++)await Promise.resolve();};
function harness(path){
 let active=true,id=0,commits=0,html='';
 const nodes={transportList:{get innerHTML(){return html},set innerHTML(v){html=v;commits++;}},transportCount:{textContent:''},
 'sec-trucks':{classList:{contains:()=>active}}},requests=[],timers=new Map(),frames=new Map(),history=[];
 const context={window:null,document:{getElementById:id=>nodes[id]},URLSearchParams,AbortController,API_BASE:'https://api.test',
 TRANSLATIONS:{ru:{transport_count_suffix:'offers',transport_timeout:'Timed out'}},lang:'ru',getToken:()=>null,esc:String,getTypeLabel:()=> 'Tent',
 setTimeout:(fn,ms)=>{timers.set(++id,{fn,ms});return id},clearTimeout:key=>timers.delete(key),
 requestAnimationFrame:fn=>{frames.set(++id,fn);history.push(fn);return id},cancelAnimationFrame:key=>frames.delete(key),
 fetch:(url,opts)=>{const d=deferred();requests.push({...d,url,signal:opts?.signal});return d.promise;}};
 context.window=context;vm.createContext(context);
 const src=readFileSync(new URL('../../../'+path,import.meta.url),'utf8'),a=src.indexOf('var _transportOffers = []');
 vm.runInContext(src.slice(a,src.indexOf('// Открыть модалку отклика',a)),context);
 return {context,nodes,requests,timers,frames,history,setActive:v=>active=v,get commits(){return commits},
 flush:()=>{const callbacks=[...frames.values()];frames.clear();callbacks.forEach(fn=>fn());}};
}
for(const path of ['main.js','frontend/main.js']){
 test(path+': stale abort cannot clear a newer loading state',async()=>{
 const h=harness(path),a=h.context.loadTransportOffers('A'),b=h.context.loadTransportOffers('B');
 const e=new Error('aborted');e.name='AbortError';h.requests[0].reject(e);await a;
 assert.equal(h.context._transportLoading,true);assert.match(h.nodes.transportList.innerHTML,/Загружаем/);
 h.requests[1].resolve(reply([offer(2,'Carrier B')]));await b;h.flush();
 assert.match(h.nodes.transportList.innerHTML,/Carrier B/);assert.equal(h.context._transportLoading,false);assert.equal(h.timers.size,0);
 });
 test(path+': stale JSON cannot replace newer data or markup',async()=>{
 const h=harness(path),json=deferred(),a=h.context.loadTransportOffers();
 h.requests[0].resolve({ok:true,status:200,json:()=>json.promise});await settle();
 const b=h.context.loadTransportOffers();h.requests[1].resolve(reply([offer(2,'Latest')]));await b;h.flush();
 json.resolve({offers:[offer(1,'Stale')],total:1});await a;h.flush();
 assert.equal(h.context._transportOffers[0].id,2);assert.match(h.nodes.transportList.innerHTML,/Latest/);assert.doesNotMatch(h.nodes.transportList.innerHTML,/Stale/);assert.equal(h.timers.size,0);
 });
 test(path+': timeout includes JSON body and resets the current request',async()=>{
 const h=harness(path),json=deferred(),p=h.context.loadTransportOffers();
 h.requests[0].resolve({ok:true,status:200,json:()=>json.promise});await settle();
 [...h.timers.values()].find(x=>x.ms===8000).fn();await p;
 assert.equal(h.requests[0].signal.aborted,true);assert.match(h.nodes.transportList.innerHTML,/Timed out/);assert.match(h.nodes.transportList.innerHTML,/filterAndLoadTransport/);
 assert.equal(h.context._transportLoading,false);assert.equal(h.timers.size,0);
 });
 for(const payload of [null,{offers:{}},{offers:[null]},{offers:'bad'}])test(path+': malformed response produces a retry state '+JSON.stringify(payload),async()=>{
 const h=harness(path),p=h.context.loadTransportOffers();h.requests[0].resolve({ok:true,status:200,json:async()=>payload});await p;
 assert.match(h.nodes.transportList.innerHTML,/cab-empty/);assert.equal(h.frames.size,0);assert.equal(h.context._transportLoading,false);
 });
 test(path+': switching away prevents background DOM updates',async()=>{
 const h=harness(path),p=h.context.loadTransportOffers(),loading=h.nodes.transportList.innerHTML;h.setActive(false);
 h.requests[0].resolve(reply([offer(1,'Background')]));await p;h.flush();
 assert.equal(h.nodes.transportList.innerHTML,loading);assert.equal(h.frames.size,0);assert.equal(h.context._transportLoading,false);
 });
 test(path+': coalesces renders and rejects cancelled callbacks',()=>{
 const h=harness(path);h.context._transportOffers=[offer(1,'Old')];h.context.renderTransportOffers();
 const old=h.history[0];h.context._transportOffers=[offer(2,'New')];h.context.renderTransportOffers();
 assert.equal(h.frames.size,1);old();assert.equal(h.commits,0);h.flush();assert.equal(h.commits,1);
 assert.match(h.nodes.transportList.innerHTML,/New/);assert.doesNotMatch(h.nodes.transportList.innerHTML,/Old/);
 });
 test(path+': new request invalidates a pending render',async()=>{
 const h=harness(path);h.context._transportOffers=[offer(1,'Old')];h.context.renderTransportOffers();const old=h.history[0];
 const p=h.context.loadTransportOffers();old();assert.match(h.nodes.transportList.innerHTML,/Загружаем/);
 h.requests[0].resolve(reply([]));await p;assert.match(h.nodes.transportList.innerHTML,/Нет предложений/);assert.equal(h.timers.size,0);
 });
 test(path+': queued render cannot update an inactive section',()=>{
 const h=harness(path);h.context._transportOffers=[offer(1,'Old')];h.context.renderTransportOffers();h.setActive(false);h.flush();assert.equal(h.commits,0);
 });
 for(const status of [401,403,500])test(path+': '+status+' resets loading and preserves retry',async()=>{
 const h=harness(path),p=h.context.loadTransportOffers();h.requests[0].resolve({ok:false,status});await p;
 assert.equal(h.context._transportLoading,false);assert.equal(h.timers.size,0);assert.match(h.nodes.transportList.innerHTML,/filterAndLoadTransport/);
 });
 test(path+': one formatter is reused across repeated renders',()=>{
 const h=harness(path);h.context._transportOffers=[offer(1,'Carrier')];h.context.renderTransportOffers();h.flush();
 const formatter=h.context.renderTransportOffers._dateFormat;h.context.renderTransportOffers();h.flush();assert.equal(h.context.renderTransportOffers._dateFormat,formatter);
 });
}
