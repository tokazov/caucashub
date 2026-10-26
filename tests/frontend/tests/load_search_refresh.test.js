import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
function sync(path,server,initial=[]){
 const nodes={fcount:{textContent:'before'},statLoads:{},cargoList:{innerHTML:''}},renders=[];
 const ctx={window:null,LOCAL:initial,INTL:[],scope:'local',currentUserId:null,_myLoads:[],
 getToken:()=>null,mapServerLoad:x=>({...x,fromServer:true}),
 CaucasAPI:{getLoads:async()=>{if(server instanceof Error)throw server;return server;}},
 document:{getElementById:id=>nodes[id],querySelector:()=>null},
 console:{warn:()=>{}},localStorage:{getItem:()=>null},filterLoadData:rows=>rows.filter(x=>x.matches),
 renderLoads:rows=>{const filtered=ctx.filterLoadData(rows);renders.push({loading:ctx._loadsLoading,ids:filtered.map(x=>x.id)});
 nodes.fcount.textContent=String(filtered.length);nodes.cargoList.innerHTML=ctx._loadsLoading&&!filtered.length?'loading':filtered.length?'results':'empty';}};
 ctx.window=ctx;ctx._tabRestored=true;vm.createContext(ctx);
 const code=readFileSync(new URL('../../../'+path,import.meta.url),'utf8'),a=code.indexOf('async function syncLoadsFromServer(){');
 vm.runInContext(code.slice(a,code.indexOf('function mapServerLoad',a)),ctx);
 return{ctx,nodes,renders};
}
for(const path of ['api.js','frontend/api.js']){
 test(path+': valid empty response finishes the loading state',async()=>{
 const h=sync(path,[]);await h.ctx.syncLoadsFromServer();
 assert.equal(h.ctx._loadsLoading,false);assert.equal(h.nodes.cargoList.innerHTML,'empty');
 assert.equal(h.nodes.fcount.textContent,'0');assert.equal(h.renders.at(-1).loading,false);
 });
 test(path+': zero filtered matches finish loading even when source has loads',async()=>{
 const h=sync(path,[{id:1,matches:false}]);await h.ctx.syncLoadsFromServer();
 assert.equal(h.ctx.LOCAL.length,1);assert.equal(h.nodes.cargoList.innerHTML,'empty');assert.equal(h.renders.at(-1).loading,false);
 });
 test(path+': refresh does not replace filtered result count with server total',async()=>{
 const h=sync(path,[{id:1,matches:true},{id:2,matches:false}]);await h.ctx.syncLoadsFromServer();
 assert.equal(h.nodes.statLoads.textContent,2);assert.equal(h.nodes.fcount.textContent,'1');assert.equal(h.nodes.cargoList.innerHTML,'results');
 });
 test(path+': thrown synchronization error keeps the error message',async()=>{
 const h=sync(path,new Error('offline'));await h.ctx.syncLoadsFromServer();
 assert.equal(h.ctx._loadsLoading,false);assert.match(h.nodes.cargoList.innerHTML,/Нет данных/);assert.equal(h.renders.length,0);
 });
}
