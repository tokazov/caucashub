import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
function loader(path,{token='test-token',legacy=false,failed=false}={}){
 const calls={fetches:[],renders:0},elements=legacy?{dealsLoading:{style:{}},dealsList:{innerHTML:'before'}}:{};
 const context={user:{userId:7},API_BASE:'http://127.0.0.1:8765',getToken:()=>token,dealsData:[],
  document:{getElementById:id=>elements[id]||null},
  fetch:async(url,options)=>{calls.fetches.push({url,options});if(failed)throw Error('offline');return{ok:true,json:async()=>({deals:[{id:31}]})};},
  renderDeals:()=>calls.renders++};
 vm.createContext(context);
 const source=readFileSync(new URL('../../../'+path,import.meta.url),'utf8');
 // The later declaration replaces the earlier one in the real loaded script.
 const start=source.lastIndexOf('async function loadDeals(){'),end=source.indexOf('function renderDeals(){',start);
 assert.ok(start>=0&&end>start);
 vm.runInContext(source.slice(start,end),context);
 return{context,calls,elements};
}
for(const path of ['main.js','frontend/main.js']){
 test(path+': login deal hydration does not reject when legacy containers are absent',async()=>{
  const h=loader(path);await assert.doesNotReject(h.context.loadDeals());
  assert.equal(h.calls.fetches.length,1);assert.equal(h.calls.fetches[0].url,'http://127.0.0.1:8765/api/deals/my');
  assert.equal(h.calls.fetches[0].options.headers.Authorization,'Bearer test-token');
  assert.equal(h.context.dealsData[0].id,31);assert.equal(h.calls.renders,1);
 });
 test(path+': signed-out page without a legacy spinner makes no deal request',async()=>{
  const h=loader(path,{token:null});await assert.doesNotReject(h.context.loadDeals());
  assert.equal(h.calls.fetches.length,0);assert.equal(h.calls.renders,0);
 });
 test(path+': existing legacy containers retain loading and render behavior',async()=>{
  const h=loader(path,{legacy:true});const pending=h.context.loadDeals();
  assert.equal(h.elements.dealsLoading.style.display,'block');assert.equal(h.elements.dealsList.innerHTML,'');
  await pending;assert.equal(h.elements.dealsLoading.style.display,'none');assert.equal(h.calls.renders,1);
 });
 test(path+': failed hydration still hides an optional legacy spinner',async()=>{
  const h=loader(path,{legacy:true,failed:true});await assert.doesNotReject(h.context.loadDeals());
  assert.equal(h.elements.dealsLoading.style.display,'none');assert.equal(h.calls.renders,0);
 });
}
