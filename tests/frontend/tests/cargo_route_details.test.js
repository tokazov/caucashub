import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),{JSDOM}=require('jsdom');
const main=readFileSync(new URL('../../../frontend/main.js',import.meta.url),'utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function harness(t,{locale='ru',lazy=false}={}){
 const dom=new JSDOM('<div id="details"></div><div id="row"><span data-road-distance></span></div><div id="mKm"></div>',{runScripts:'outside-only',url:'http://localhost/'}),w=dom.window;
 t.after(()=>w.close());w.lang=locale;w.translateCity=(name,location)=>location?.kind==='border_checkpoint'?(locale==='ge'?location.name_ge:location.name_ru)||location.label||name:name;
 const calls=[],pending=new Map(),observers=[];
 w.CaucasRouteDistance={key:load=>load.route||null,peek:()=>null,getDistance:load=>{calls.push(load.route);return new Promise(resolve=>pending.set(load.route,resolve));}};
 if(lazy)w.IntersectionObserver=class{constructor(callback){this.callback=callback;this.targets=new Set();observers.push(this);}observe(target){this.targets.add(target);}unobserve(target){this.targets.delete(target);}disconnect(){this.targets.clear();}show(target){this.callback([{target,isIntersecting:true}]);}};
 const escapeStart=main.indexOf('function esc(s) {');w.eval(main.slice(escapeStart,main.indexOf('// ── SAFE LOCALSTORAGE',escapeStart)));
 const start=main.indexOf('function cargoEndpointLabel(');assert.ok(start>=0);w.eval(main.slice(start,main.indexOf('function renderLoads(',start)));
 return{w,calls,pending,observers,node:id=>w.document.getElementById(id),finish:(key,meters)=>pending.get(key)(meters==null?null:{km:meters/1000,meters,source:'yandex_auto',precision:'exact'})};
}

test('cargo details show the chosen point name before its separate postal address, including a point inside a known city',t=>{
 const h=harness(t),load={from:'Тбилиси',from2:'Только старый район',from_location:{kind:'point',label:'Ворота склада №2',address:'Грузия, Тбилиси, Складская, 7',settlement_key:'ge:tbilisi'}};
 h.node('details').innerHTML=h.w.cargoEndpointDetails(load,'from');assert.equal(h.node('details').children[0].textContent,'Ворота склада №2');assert.equal(h.node('details').children[1].textContent,load.from_location.address);assert.equal(h.node('details').textContent.includes(load.from2),false);
});
test('cargo route names and postal addresses remain text when they contain markup',t=>{
 const h=harness(t),label='<img src=x onerror="alert(1)">',address='<script>unsafe()</script> & склад';h.node('details').innerHTML=h.w.cargoEndpointDetails({from_location:{kind:'point',label,address}},'from');
 assert.equal(h.node('details').children[0].textContent,label);assert.equal(h.node('details').children[1].textContent,address);assert.equal(h.node('details').querySelector('img,script'),null);
});
test('duplicate addresses are omitted and explicit custom checkpoint names remain primary',t=>{
 const h=harness(t,{locale:'ge'}),location={kind:'border_checkpoint',name_ru:'КПП Дарьял',name_ge:'დარიალი',label:'Мои ворота у КПП',label_mode:'custom',address:'Мои ворота у КПП'};
 h.node('details').innerHTML=h.w.cargoEndpointDetails({from:'Дарьял',from_location:location},'from');assert.equal(h.node('details').children.length,1);assert.equal(h.node('details').textContent,location.label);
});
test('late distance for cargo A cannot replace cargo B in a reused modal',async t=>{
 const h=harness(t),node=h.node('mKm');h.w.bindCargoRoadDistance({route:'A'},[node]);h.w.bindCargoRoadDistance({route:'B'},[node]);assert.equal(node.dataset.roadDistanceStatus,'loading');
 h.finish('B',167170.752);await tick();const text=node.textContent;assert.equal(node.dataset.roadDistanceMeters,'167170.752');assert.match(text,/167/);
 h.finish('A',999000);await tick();assert.equal(node.textContent,text);assert.equal(node.dataset.roadDistanceMeters,'167170.752');assert.equal(node.dataset.roadDistanceKey,'B');
});
test('failed road routing clears an older result and never paints a fabricated zero distance',async t=>{
 const h=harness(t),node=h.node('mKm');h.w.bindCargoRoadDistance({route:'ready'},[node]);h.finish('ready',167170.752);await tick();assert.equal(node.dataset.roadDistanceStatus,'ready');
 h.w.bindCargoRoadDistance({route:'failed'},[node]);assert.equal(node.dataset.roadDistanceMeters,undefined);h.finish('failed',null);await tick();assert.equal(node.dataset.roadDistanceStatus,'unavailable');assert.equal(node.dataset.roadDistanceMeters,undefined);assert.match(node.textContent,/Не рассчитано/);assert.doesNotMatch(node.textContent,/0\s*км/);
});
test('missing exact endpoint skips routing and removes stale distance values',t=>{
 const h=harness(t),node=h.node('mKm');node.textContent='≈999 км';node.dataset.roadDistanceMeters='999000';h.w.bindCargoRoadDistance({},[node]);assert.equal(h.calls.length,0);assert.equal(node.dataset.roadDistanceStatus,'unavailable');assert.equal(node.dataset.roadDistanceMeters,undefined);assert.match(node.title,/точки/);
});
test('removed card nodes ignore a later routing result',async t=>{
 const h=harness(t),node=h.node('row').firstElementChild;h.w.bindCargoRoadDistance({route:'removed'},[node]);const text=node.textContent;node.remove();h.finish('removed',167170.752);await tick();assert.equal(node.textContent,text);assert.equal(node.dataset.roadDistanceMeters,undefined);
});
test('card routing waits until visible and resetting the list cancels unstarted old targets',async t=>{
 const h=harness(t,{lazy:true}),row=h.node('row'),node=row.firstElementChild;h.w.bindCargoRoadDistance({route:'visible'},[node],row);assert.equal(h.calls.length,0);h.observers[0].show(row);assert.deepEqual(h.calls,['visible']);h.finish('visible',167170.752);await tick();assert.equal(node.dataset.roadDistanceStatus,'ready');
 h.w.bindCargoRoadDistance({route:'discarded'},[node],row);h.w.resetCargoRoadObserver();h.observers[0].show(row);assert.deepEqual(h.calls,['visible']);
});
