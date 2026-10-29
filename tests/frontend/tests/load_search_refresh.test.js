import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
function sync(path,server,initial=[]){
 const nodes={fcount:{textContent:'before'},statLoads:{textContent:'snapshot'},cargoList:{innerHTML:''}},renders=[];
 const ctx={window:null,LOCAL:initial,INTL:[],scope:'local',currentUserId:null,_myLoads:[],
 getToken:()=>null,mapServerLoad:x=>({...x,fromServer:true}),
 CaucasAPI:{getLoads:async options=>{if(server instanceof Error)throw server;return typeof server==='function'?server(options):server;}},
 document:{getElementById:id=>nodes[id],querySelector:()=>null},
 console:{warn:()=>{},log:()=>{}},localStorage:{getItem:()=>null},filterLoadData:rows=>rows.filter(x=>x.matches),
 renderLoads:rows=>{const filtered=ctx.filterLoadData(rows);renders.push({loading:ctx._loadsLoading,ids:filtered.map(x=>x.id)});
 nodes.fcount.textContent=String(filtered.length);nodes.cargoList.innerHTML=ctx._loadsLoading&&!filtered.length?'loading':filtered.length?'results':'empty';}};
 ctx.window=ctx;ctx._tabRestored=true;vm.createContext(ctx);
 const code=readFileSync(new URL('../../../'+path,import.meta.url),'utf8'),a=code.indexOf('async function syncLoadsFromServer(){');
 vm.runInContext(code.slice(a,code.indexOf('function mapServerLoad',a)),ctx);
 return{ctx,nodes,renders};
}
const defer=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return{promise,resolve,reject};};
test('frontend: authoritative empty refresh removes old public results and unsent drafts',async()=>{
 const old=[{id:1,fromServer:true,matches:true},{id:'draft',matches:true}];
 const h=sync('frontend/api.js',[],old);h.ctx.INTL.push({id:8,fromServer:true,matches:true});
 h.ctx._myLoads.push({id:'private-draft'});
 await h.ctx.syncLoadsFromServer();
 assert.equal(h.ctx.LOCAL.length,0);assert.equal(h.nodes.cargoList.innerHTML,'empty');
 assert.deepEqual(Array.from(h.ctx.allLoads,x=>x.id),[8]);
 assert.equal(h.ctx._myLoads[0].id,'private-draft');
 assert.equal(h.ctx._serverTotal,0);
});
for(const staleFails of [false,true])test('frontend: stale '+(staleFails?'error':'success')+' cannot finish a newer scope request',async()=>{
 const old=defer(),latest=defer(),requests=[];
 const h=sync('frontend/api.js',({scope})=>{requests.push(scope);return requests.length===1?old.promise:latest.promise;});
 const first=h.ctx.syncLoadsFromServer();h.ctx.scope='intl';const second=h.ctx.syncLoadsFromServer();
 if(staleFails)old.reject(Error('old local failure'));else old.resolve([{id:1,matches:true}]);
 await first;
 assert.deepEqual(requests,['local','intl']);assert.equal(h.ctx._loadsLoading,true);
 assert.equal(h.renders.length,0);assert.equal(h.nodes.cargoList.innerHTML,'');
 latest.resolve([{id:2,matches:true}]);await second;
 assert.equal(h.ctx._loadsLoading,false);assert.deepEqual(Array.from(h.ctx.INTL,x=>x.id),[2]);
 assert.equal(h.ctx.LOCAL.length,0);assert.equal(h.nodes.cargoList.innerHTML,'results');
});
for(const staleFails of [false,true])test('frontend: late '+(staleFails?'failure':'response')+' cannot replace the current same-scope result',async()=>{
 const old=defer(),latest=defer();let calls=0;
 const h=sync('frontend/api.js',()=>++calls===1?old.promise:latest.promise);
 const first=h.ctx.syncLoadsFromServer(),second=h.ctx.syncLoadsFromServer();
 latest.resolve([]);await second;const renders=h.renders.length;
 if(staleFails)old.reject(Error('late failure'));else old.resolve([{id:3,matches:true}]);
 await first;
 assert.equal(h.ctx.LOCAL.length,0);assert.equal(h.nodes.cargoList.innerHTML,'empty');
 assert.equal(h.renders.length,renders);assert.equal(h.ctx._loadsLoading,false);
});
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
 assert.equal(h.nodes.statLoads.textContent,path==='frontend/api.js'?'snapshot':2); // The dated global snapshot is not a filtered page length.
 assert.equal(h.nodes.fcount.textContent,'1');assert.equal(h.nodes.cargoList.innerHTML,'results');
 });
 test(path+': thrown synchronization error keeps the error message',async()=>{
 const h=sync(path,new Error('offline'));await h.ctx.syncLoadsFromServer();
 assert.equal(h.ctx._loadsLoading,false);assert.match(h.nodes.cargoList.innerHTML,/Нет данных/);assert.equal(h.renders.length,0);
 });
}
