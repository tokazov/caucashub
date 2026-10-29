import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import vm from 'node:vm';
const require=createRequire(import.meta.url),{JSDOM}=require('jsdom');
const source=readFileSync(new URL('../../../frontend/locations.js',import.meta.url),'utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const catalog=[{kind:'border_checkpoint',key:'ge:checkpoint:dariali',label:'КПП Дарьял',name_ru:'КПП Дарьял',name_ge:'დარიალის გამშვები პუნქტი',name_en:'Dariali checkpoint',lat:42.735,lon:44.624,country_iso:'GE',address:'Грузия, КПП Дарьял',aliases:['Дарьял','Дариали','Dariali','დარიალი']},
{kind:'border_checkpoint',key:'ru:checkpoint:upper-lars',label:'КПП Верхний Ларс',name_ru:'КПП Верхний Ларс',name_ge:'ზემო ლარსის პუნქტი',name_en:'Upper Lars checkpoint',lat:42.763,lon:44.628,country_iso:'RU',address:'Россия, Верхний Ларс',aliases:['Верхний Ларс','Upper Lars']},
{kind:'settlement',key:'ge:tbilisi',settlement_key:'ge:tbilisi',settlement_id:1,label:'Тбилиси',name_ru:'Тбилиси',name_ge:'თბილისი',name_en:'Tbilisi',lat:41.6941,lon:44.8337,country_iso:'GE',aliases:['Tbilisi','თბილისი','Тбилиси']}];
function harness(t,{mobile=false,locale='ru',provider=true,resolveError=null}={}){
 const html='<button data-location-field="pFrom">Map</button>'+['pFrom','pTo','ptFrom','ptTo'].map(field=>{const input=field.startsWith('pF')||field==='pTo'?field+'Addr':field;const suffix={pFrom:'PFrom',pTo:'PTo',ptFrom:'PtFrom',ptTo:'PtTo'}[field];return '<input id="'+input+'"><div id="drop'+suffix+'"></div><div id="coords'+suffix+'"></div>';}).join('')+
 '<div id="locationPickerOverlay" hidden><div><h2 id="locationPickerTitle"></h2><button id="locationPickerCancel">Cancel</button><p id="locationPickerInstruction"></p><div id="locationPickerMap"></div><div id="locationPickerPin" hidden></div><label id="locationPickerLabelCaption"></label><input id="locationPickerLabel"><div id="locationPickerAddress"></div><div id="locationPickerCoordinates"></div><div id="locationPickerError" hidden></div><button id="locationPickerConfirm"></button></div></div>';
 const dom=new JSDOM(html,{url:'http://localhost/',runScripts:'outside-only'}),w=dom.window;
 t.after(()=>w.close());w.lang=locale;w.scope='local';w.API_BASE='';w.CITIES=[];w.AbortController=AbortController;
 Object.defineProperty(w,'innerWidth',{value:mobile?390:1280});
 const calls={requests:[],maps:[],geocodes:[],sdk:0};
 class Emitter{constructor(){this.handlers={};}add(name,callback){(this.handlers[name]??=[]).push(callback);}emit(name,value){for(const callback of this.handlers[name]||[])callback({get:key=>value[key]});}}
 class Map{constructor(id,options){this.center=options.center;this.events=new Emitter();this.geoObjects={add(){}};this.container={fitToViewport(){}};this.destroyed=false;calls.maps.push(this);}getCenter(){return this.center;}setCenter(coords){this.center=coords;this.events.emit('boundschange',{newCenter:coords});}destroy(){this.destroyed=true;}}
 class Placemark{constructor(coords){this.coords=coords;this.events=new Emitter();this.geometry={setCoordinates:value=>this.coords=value,getCoordinates:()=>this.coords};}}
 w.loadYmapsLazy=(ready,error)=>{calls.sdk++;if(provider)ready();else error?.('Unavailable');};
 w.ymaps={ready:callback=>callback(),Map,Placemark,geocode:async value=>{calls.geocodes.push(value);return{geoObjects:{get:()=>({getAddressLine:()=> 'С-3',getLocalities:()=>[],properties:{get:()=> 'С-3'},geometry:{getCoordinates:()=>Array.isArray(value)?value:[41.708123,44.812345]}}),each(){}}};}};
 w.fetch=async(url,options={})=>{calls.requests.push({url,options,body:options.body?JSON.parse(options.body):null});
  if(url.includes('/suggest'))return{ok:true,json:async()=>({results:catalog})};
  if(resolveError)return{ok:false,json:async()=>({detail:resolveError})};
  const body=JSON.parse(options.body);return{ok:true,json:async()=>({location:{...body,country_iso:'GE',resolution_token:'signed-fixture-token'}})};
 };
 w.eval(source);w.document.dispatchEvent(new w.Event('DOMContentLoaded'));return{w,calls,api:w.CaucasLocations,node:id=>w.document.getElementById(id)};
}
for(const text of ['Дарьял','Дариали','Dariali','დარიალი'])test('own checkpoint suggestion works without map provider: '+text,async t=>{
 const h=harness(t,{provider:false});await h.api.preload();h.node('pFromAddr').value=text;h.api.search('pFrom',text);
 const option=h.w.document.querySelector('[data-location-key="ge:checkpoint:dariali"]');assert.ok(option);option.click();await tick();
 const endpoint=h.api.read('pFrom','КПП Дарьял');assert.equal(endpoint.location.key,'ge:checkpoint:dariali');assert.equal(h.calls.requests.filter(x=>x.url.includes('/resolve')).length,0);
});
test('mobile pan preserves exact point and editable label even when reverse lookup returns road without locality',async t=>{
 const h=harness(t,{mobile:true});await h.api.preload();await h.api.open('pFrom');assert.equal(h.node('locationPickerPin').hidden,false);
 h.calls.maps[0].setCenter([42.701234,44.601234]);h.node('locationPickerLabel').value='Мой склад у трассы';h.node('locationPickerConfirm').click();await tick();
 const location=h.api.read('pFrom','Мой склад у трассы').location;assert.equal(location.lat,42.701234);assert.equal(location.lon,44.601234);assert.equal(location.label,'Мой склад у трассы');assert.equal(location.resolution_token,'signed-fixture-token');assert.equal(h.node('locationPickerOverlay').hidden,true);
});
test('desktop click sets point and cancel never commits a draft',async t=>{
 const h=harness(t);await h.api.preload();await h.api.open('pFrom');assert.equal(h.node('locationPickerPin').hidden,true);
 h.calls.maps[0].events.emit('click',{coords:[41.7,44.8]});h.node('locationPickerCancel').click();assert.equal(h.api.read('pFrom','Точка на карте'),null);assert.equal(h.calls.maps[0].destroyed,true);
});
test('country resolution failure keeps picker open without false field success',async t=>{
 const h=harness(t,{resolveError:'Уточните сторону границы'});await h.api.preload();await h.api.open('pFrom');h.node('locationPickerLabel').value='Пограничная точка';h.node('locationPickerConfirm').click();await tick();
 assert.equal(h.node('locationPickerOverlay').hidden,false);assert.match(h.node('locationPickerError').textContent,/сторону границы/);assert.equal(h.api.read('pFrom','Пограничная точка'),null);assert.equal(h.node('locationPickerConfirm').disabled,false);
});
test('manual edit drops restored coordinate selection and typed point token',async t=>{
 const h=harness(t);h.api.restore('pFrom',{kind:'point',label:'Склад',lat:41.708123,lon:44.812345,country_iso:'GE',address:'Полный адрес'});
 assert.equal(h.api.read('pFrom','Склад').location.lat,41.708123);h.node('pFromAddr').value='Другое место';h.api.search('pFrom','Другое место');await tick();assert.equal(h.api.read('pFrom','Другое место'),null);assert.equal(h.api.read('pFrom','Склад'),null);
});
test('restored server point keeps coordinates and excludes internal catalogue fields from write payload',async t=>{
 const h=harness(t);h.api.restore('pTo',{kind:'point',label:'Склад',lat:41.708123,lon:44.812345,country_iso:'GE',address:'Улица 7',source:'server',aliases:['Склад']});const endpoint=h.api.read('pTo','Склад');assert.equal(endpoint.location.lon,44.812345);assert.equal(endpoint.location.source,undefined);assert.equal(endpoint.location.aliases,undefined);assert.equal(endpoint.location.resolution_token,undefined);
});
test('Georgian picker keeps its local language and no-city point remains allowed',async t=>{
 const h=harness(t,{locale:'ge'});await h.api.open('pTo');assert.equal(h.node('locationPickerTitle').textContent,'მიწოდების ადგილი');assert.equal(h.node('locationPickerConfirm').textContent,'ამ წერტილის არჩევა');
 h.node('locationPickerLabel').value='საწყობი';h.node('locationPickerConfirm').click();await tick();assert.equal(h.api.read('pTo','საწყობი').location.kind,'point');
});
test('unavailable SDK displays a finite error and still permits own catalogue selection',async t=>{
 const h=harness(t,{provider:false});await h.api.preload();await h.api.open('pFrom');assert.match(h.node('locationPickerError').textContent,/Карта недоступна/);assert.equal(h.node('locationPickerConfirm').disabled,true);h.node('locationPickerCancel').click();await h.api.choose('pFrom',catalog[0]);assert.equal(h.api.read('pFrom','КПП Дарьял').location.key,'ge:checkpoint:dariali');
});
test('late map initialization cannot reopen a cancelled picker',async t=>{
 const h=harness(t);let ready;h.w.loadYmapsLazy=callback=>{ready=callback;};const opening=h.api.open('pFrom');h.api.close();ready();await opening;assert.equal(h.node('locationPickerOverlay').hidden,true);assert.equal(h.calls.maps.length,0);
});

test('renaming a verified checkpoint without moving preserves its key and avoids ambiguous country resolution',async t=>{
 const h=harness(t);await h.api.preload();await h.api.choose('pFrom',catalog[0]);await h.api.open('pFrom');h.node('locationPickerLabel').value='Дарьял — площадка у КПП';h.node('locationPickerConfirm').click();await tick();const endpoint=h.api.read('pFrom','Дарьял — площадка у КПП');assert.equal(endpoint.location.key,'ge:checkpoint:dariali');assert.equal(endpoint.location.kind,'border_checkpoint');assert.equal(endpoint.location.lat,catalog[0].lat);assert.equal(h.calls.requests.filter(x=>x.url.includes('/resolve')).length,0);
});
test('submission waits for a point country resolution instead of treating its label as raw city',async t=>{
 const h=harness(t);const fetch=h.w.fetch;let finish;h.w.fetch=(url,options)=>url.includes('/resolve')?new Promise(resolve=>{finish=()=>fetch(url,options).then(resolve);}):fetch(url,options);
 h.node('pFromAddr').value='Склад';const pending=h.api.choose('pFrom',{kind:'point',label:'Склад',address:'',lat:41.7,lon:44.8});assert.throws(()=>h.api.read('pFrom','Склад'),/Дождитесь подтверждения/);finish();await pending;assert.equal(h.api.read('pFrom','Склад').location.address,'Склад');
});

test('exact own checkpoint match stays immediate and never launches provider address lookup',async t=>{
 const h=harness(t);await h.api.preload();h.node('pFromAddr').value='Дарьял';h.api.search('pFrom','Дарьял');assert.ok(h.w.document.querySelector('[data-location-key="ge:checkpoint:dariali"]'));await new Promise(resolve=>setTimeout(resolve,320));assert.equal(h.calls.geocodes.length,0);
});
test('repeating the same address reuses bounded session result instead of calling provider again',async t=>{
 const h=harness(t);await h.api.preload();h.node('pFromAddr').value='Склад на Складской';h.api.search('pFrom','Склад на Складской');await new Promise(resolve=>setTimeout(resolve,320));assert.equal(h.calls.geocodes.length,1);h.api.search('pFrom','Склад на Складской');await new Promise(resolve=>setTimeout(resolve,320));assert.equal(h.calls.geocodes.length,1);
});

test('reopening saved cargo route uses stored exact coordinates without re-geocoding the road label',async()=>{
 const main=readFileSync(new URL('../../../frontend/main.js',import.meta.url),'utf8'),start=main.indexOf('window.openRouteMap = function()');
 const nodes={routeMapBlock:{style:{display:'none'}},routeMapModal:{innerHTML:''}},calls={geocode:0,routes:[]};
 const ctx={window:null,_routeMap:null,currentCargoId:1,allLoads:[{id:1,from:'С-3',from2:'С-3',to:'Склад',to2:'Склад',from_location:{lat:41.708123,lon:44.812345},to_location:{lat:41.65321,lon:41.65321}}],
  document:{getElementById:id=>nodes[id],querySelector:()=>({textContent:''}),querySelectorAll:()=>[]},TRANSLATIONS:{ru:{}},lang:'ru',alert:()=>assert.fail('Route unexpectedly absent'),loadYmapsLazy:callback=>callback(),
  ymaps:{ready:callback=>callback(),Map:function(){this.geoObjects={add(){}};},geocode(){calls.geocode++;throw Error('Stored point must not be replaced');},multiRouter:{MultiRoute:function(data){calls.routes.push(data.referencePoints);this.model={events:{add(){}}};}}}};
 ctx.window=ctx;vm.createContext(ctx);vm.runInContext(main.slice(start,main.indexOf('// Явно регистрируем',start)),ctx);ctx.openRouteMap();await tick();assert.equal(calls.geocode,0);assert.deepEqual(JSON.parse(JSON.stringify(calls.routes)),[[[41.708123,44.812345],[41.65321,41.65321]]]);
});

test('nearby verified checkpoint is an explicit choice with exact catalogue coordinates and preserves owner label',async t=>{
 const h=harness(t,{mobile:true,resolveError:'Уточните сторону границы'});await h.api.preload();await h.api.open('pFrom');
 h.calls.maps[0].setCenter([catalog[0].lat+0.0003,catalog[0].lon]);
 const option=h.w.document.querySelector('[data-nearby-location-key="ge:checkpoint:dariali"]');assert.ok(option);assert.match(option.textContent,/Грузия/);assert.equal(h.node('pFromAddr').value,'');
 h.node('locationPickerLabel').value='Дарьял — въезд к КПП';h.node('locationPickerLabel').dispatchEvent(new h.w.Event('input',{bubbles:true}));option.click();
 assert.deepEqual(Array.from(h.calls.maps[0].getCenter(),Number),[catalog[0].lat,catalog[0].lon]);h.node('locationPickerConfirm').click();await tick();
 const location=h.api.read('pFrom','Дарьял — въезд к КПП').location;assert.equal(location.key,'ge:checkpoint:dariali');assert.equal(location.kind,'border_checkpoint');assert.equal(location.country_iso,'GE');assert.equal(location.lat,catalog[0].lat);assert.equal(h.calls.requests.filter(row=>row.url.includes('/resolve')).length,0);
});
test('opposite Upper Lars side offers its own Russian checkpoint, not Dariali',async t=>{
 const h=harness(t,{mobile:true});await h.api.preload();await h.api.open('pFrom');h.calls.maps[0].setCenter([42.7633,44.628]);
 assert.equal(h.w.document.querySelector('[data-nearby-location-key="ge:checkpoint:dariali"]'),null);
 const russian=h.w.document.querySelector('[data-nearby-location-key="ru:checkpoint:upper-lars"]');assert.ok(russian);assert.match(russian.textContent,/Россия/);
});
test('a point farther than500 metres does not offer to substitute a checkpoint',async t=>{
 const h=harness(t,{mobile:true});await h.api.preload();await h.api.open('pFrom');h.calls.maps[0].setCenter([catalog[0].lat+0.006,catalog[0].lon]);assert.equal(h.w.document.querySelector('[data-nearby-location-key="ge:checkpoint:dariali"]'),null);
});
test('Georgian nearby action names the actual checkpoint and country',async t=>{
 const h=harness(t,{mobile:true,locale:'ge'});await h.api.preload();await h.api.open('pFrom');h.calls.maps[0].setCenter([catalog[0].lat+0.0003,catalog[0].lon]);const text=h.w.document.querySelector('[data-nearby-location-key="ge:checkpoint:dariali"]').textContent;assert.match(text,/საქართველო/);assert.match(text,/პუნქტის არჩევა/);
});
