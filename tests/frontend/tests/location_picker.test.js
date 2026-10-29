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
function harness(t,{mobile=false,locale='ru',provider=true,resolveError=null,reverseAddress='С-3',reverseResponder=null}={}){
 const html='<button data-location-field="pFrom">Map</button>'+['pFrom','pTo','ptFrom','ptTo'].map(field=>{const input=field.startsWith('pF')||field==='pTo'?field+'Addr':field;const suffix={pFrom:'PFrom',pTo:'PTo',ptFrom:'PtFrom',ptTo:'PtTo'}[field];return '<input id="'+input+'"><div id="drop'+suffix+'"></div><div id="coords'+suffix+'"></div>';}).join('')+
 '<div id="locationPickerOverlay" hidden><div><h2 id="locationPickerTitle"></h2><button id="locationPickerCancel">Cancel</button><p id="locationPickerInstruction"></p><div id="locationPickerMap"></div><div id="locationPickerPin" hidden></div><label id="locationPickerLabelCaption"></label><input id="locationPickerLabel"><div id="locationPickerAddress"></div><div id="locationPickerCoordinates"></div><div id="locationPickerError" hidden></div><button id="locationPickerConfirm"></button></div></div>';
 const dom=new JSDOM(html,{url:'http://localhost/',runScripts:'outside-only'}),w=dom.window;
 t.after(()=>w.close());w.lang=locale;w.scope='local';w.API_BASE='';w.CITIES=[];w.AbortController=AbortController;
 Object.defineProperty(w,'innerWidth',{value:mobile?390:1280});
 const calls={requests:[],maps:[],geocodes:[],projections:[],sdk:0};
 class Emitter{constructor(){this.handlers={};}add(name,callback){(this.handlers[name]??=[]).push(callback);}emit(name,value){for(const callback of this.handlers[name]||[])callback({get:key=>value[key]});}}
 class DataManager{constructor(data){this.data=data;}get(key){return this.data[key];}getAll(){return this.data;}}
 class Map{constructor(id,state,options={}){this.center=state.center;this.zoom=state.zoom;this.events=new Emitter();this.geoObjects={add(){}};this.container={fitToViewport(){}};this.destroyed=false;
   this.projection={fromGlobalPixels:(position,zoom)=>{calls.projections.push({position,zoom});return[position[1]/1000000,position[0]/1000000];}};
   this.options={get:key=>key==='projection'?this.projection:options[key],set:(key,value)=>{options[key]=value;}};
   this.balloon={events:new Emitter(),data:null,position:null,opened:false,getData(){return this.data;},getPosition(){return this.position;},isOpen(){return this.opened;},close(){this.opened=false;this.events.emit('close',{});return Promise.resolve();}};
   calls.maps.push(this);
  }getCenter(){return this.center;}getZoom(){return this.zoom;}setCenter(coords){this.center=coords;this.events.emit('boundschange',{newCenter:coords});}
  openNativePoi({coords,properties,position=coords?[coords[1]*1000000,coords[0]*1000000]:null}){this.balloon.data={properties:new DataManager(properties),map:this,layer:{},options:{}};this.balloon.position=position;this.balloon.opened=true;this.balloon.events.emit('open',{target:this});}
  nativeAutoPan(coords){if(this.balloon.isOpen())this.setCenter(coords);}
  destroy(){this.destroyed=true;}
 }
 class Placemark{constructor(coords){this.coords=coords;this.events=new Emitter();this.geometry={setCoordinates:value=>this.coords=value,getCoordinates:()=>this.coords};}}
 w.loadYmapsLazy=(ready,error)=>{calls.sdk++;if(provider)ready();else error?.('Unavailable');};
 function reverseResult(coords,address=reverseAddress){return{geoObjects:{get:()=>({getAddressLine:()=>address,getLocalities:()=>[],properties:{get:()=>address},geometry:{getCoordinates:()=>coords}}),each(){}}};}
 w.ymaps={ready:callback=>callback(),Map,Placemark,geocode:async value=>{calls.geocodes.push(value);if(Array.isArray(value)&&reverseResponder)return reverseResponder(value,reverseResult);return reverseResult(Array.isArray(value)?value:[41.708123,44.812345]);}};
 w.fetch=async(url,options={})=>{calls.requests.push({url,options,body:options.body?JSON.parse(options.body):null});
  if(url.includes('/suggest'))return{ok:true,json:async()=>({results:catalog})};
  if(resolveError)return{ok:false,json:async()=>({detail:resolveError})};
  const body=JSON.parse(options.body);return{ok:true,json:async()=>({location:{...body,country_iso:'GE',resolution_token:'signed-fixture-token'}})};
 };
 w.eval(source);w.document.dispatchEvent(new w.Event('DOMContentLoaded'));return{w,calls,api:w.CaucasLocations,reverseResult,node:id=>w.document.getElementById(id)};
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


async function until(predicate,message='Expected asynchronous picker state'){
 const deadline=Date.now()+1500;while(Date.now()<deadline){if(predicate())return;await new Promise(resolve=>setTimeout(resolve,10));}assert.fail(message);
}
const resolvedRu='Грузия, Тбилиси, улица Серго Закариадзе, 5';
for(const[locale,address]of[['ru',resolvedRu],['ge','საქართველო, თბილისი, სერგო ზაქარიაძის ქუჩა, 5']])test('automatic map name follows resolved address and transfers to saved endpoint: '+locale,async t=>{
 const h=harness(t,{mobile:true,locale,reverseAddress:address});await h.api.open('pFrom');
 await until(()=>h.node('locationPickerAddress').textContent===address);
 assert.equal(h.node('locationPickerLabel').value,address);h.node('locationPickerConfirm').click();await tick();
 assert.equal(h.node('pFromAddr').value,address);const endpoint=h.api.read('pFrom',address);
 assert.equal(endpoint.location.label,address);assert.equal(endpoint.location.address,address);assert.equal(h.calls.requests.find(x=>x.url.includes('/resolve')).body.label,address);
});
test('manual name typed while reverse request is pending survives its response',async t=>{
 const pending=[],h=harness(t,{mobile:true,reverseResponder:(coords,result)=>new Promise(resolve=>pending.push(()=>resolve(result(coords,resolvedRu))))});await h.api.open('pFrom');await until(()=>pending.length===1);
 h.node('locationPickerLabel').value='Склад Ираклия';h.node('locationPickerLabel').dispatchEvent(new h.w.Event('input',{bubbles:true}));pending[0]();await tick();
 assert.equal(h.node('locationPickerLabel').value,'Склад Ираклия');assert.equal(h.node('locationPickerAddress').textContent,resolvedRu);
 h.node('locationPickerConfirm').click();await tick();assert.equal(h.api.read('pFrom','Склад Ираклия').location.label,'Склад Ираклия');
});
test('restored generic point name heals from its resolved full address',async t=>{
 const h=harness(t,{reverseAddress:resolvedRu});h.api.restore('pFrom',{kind:'point',label:'Точка на карте',lat:41.7,lon:44.8,country_iso:'GE',address:'Предыдущий адрес'});await h.api.open('pFrom');await until(()=>h.node('locationPickerAddress').textContent===resolvedRu);assert.equal(h.node('locationPickerLabel').value,resolvedRu);
});
test('moving a restored automatic address updates name and keeps exact new coordinates',async t=>{
 const oldAddress='Грузия, Тбилиси, Старый адрес, 1',h=harness(t,{mobile:true,reverseAddress:resolvedRu});h.api.restore('pFrom',{kind:'point',label:oldAddress,lat:41.7,lon:44.8,country_iso:'GE',address:oldAddress});await h.api.open('pFrom');h.calls.maps[0].setCenter([41.711234,44.822345]);await until(()=>h.node('locationPickerAddress').textContent===resolvedRu);assert.equal(h.node('locationPickerLabel').value,resolvedRu);
 h.node('locationPickerConfirm').click();await tick();const endpoint=h.api.read('pFrom',resolvedRu);assert.equal(endpoint.location.lat,41.711234);assert.equal(endpoint.location.lon,44.822345);assert.equal(endpoint.location.label,resolvedRu);
});
test('older reverse reply cannot replace newer automatic address or name',async t=>{
 const pending=[],h=harness(t,{mobile:true,reverseResponder:(coords,result)=>new Promise(resolve=>pending.push({coords,finish:address=>resolve(result(coords,address))}))});await h.api.open('pFrom');h.calls.maps[0].setCenter([41.71,44.81]);await until(()=>pending.length===1);h.calls.maps[0].setCenter([41.72,44.82]);await until(()=>pending.length===2);
 pending[1].finish('Новый адрес B');await tick();pending[0].finish('Старый адрес A');await tick();assert.equal(h.node('locationPickerAddress').textContent,'Новый адрес B');assert.equal(h.node('locationPickerLabel').value,'Новый адрес B');
 h.node('locationPickerConfirm').click();await tick();const endpoint=h.api.read('pFrom','Новый адрес B');assert.equal(endpoint.location.lat,41.72);assert.equal(endpoint.location.lon,44.82);
});
test('restored custom point name stays intact when moved and reverse address changes',async t=>{
 const h=harness(t,{mobile:true,reverseAddress:resolvedRu});h.api.restore('pFrom',{kind:'point',label:'Ворота склада Ираклия',lat:41.7,lon:44.8,country_iso:'GE',address:'Старый почтовый адрес'});await h.api.open('pFrom');h.calls.maps[0].setCenter([41.72,44.82]);await until(()=>h.node('locationPickerAddress').textContent===resolvedRu);assert.equal(h.node('locationPickerLabel').value,'Ворота склада Ираклия');
});
test('verified checkpoint name and key are never replaced by reverse road address',async t=>{
 const h=harness(t,{reverseAddress:resolvedRu});await h.api.preload();await h.api.choose('pFrom',catalog[0]);await h.api.open('pFrom');await new Promise(resolve=>setTimeout(resolve,360));assert.equal(h.node('locationPickerLabel').value,'КПП Дарьял');assert.equal(h.calls.geocodes.length,0);h.node('locationPickerConfirm').click();await tick();const endpoint=h.api.read('pFrom','КПП Дарьял');assert.equal(endpoint.location.key,catalog[0].key);assert.equal(endpoint.location.kind,'border_checkpoint');
});


test('reverse address arriving during pending country resolution reaches the selected field and payload for the same point',async t=>{
 const reverse=[],h=harness(t,{mobile:true,reverseResponder:(coords,result)=>new Promise(resolve=>reverse.push(()=>resolve(result(coords,resolvedRu))))});
 const originalFetch=h.w.fetch;let finishResolve;h.w.fetch=(url,options)=>url.includes('/resolve')?new Promise(resolve=>{finishResolve=()=>originalFetch(url,options).then(resolve);}):originalFetch(url,options);
 await h.api.open('pFrom');const coordinates=Array.from(h.calls.maps[0].getCenter(),Number);h.node('locationPickerConfirm').click();await until(()=>!!finishResolve);await until(()=>reverse.length===1);
 reverse[0]();await until(()=>h.node('locationPickerLabel').value===resolvedRu);assert.equal(h.node('locationPickerOverlay').hidden,false);finishResolve();await tick();
 assert.equal(h.node('pFromAddr').value,resolvedRu);const endpoint=h.api.read('pFrom',resolvedRu);assert.equal(endpoint.location.label,resolvedRu);assert.equal(endpoint.location.address,resolvedRu);assert.equal(endpoint.location.lat,coordinates[0]);assert.equal(endpoint.location.lon,coordinates[1]);
});
test('automatic names respect100characters while retaining full address and remain automatic after restore',async t=>{
 const oldAddress='Грузия, Тбилиси, Старый длинный адрес, '.repeat(4),address='Грузия, Тбилиси, улица Серго Закариадзе, дом 5, корпус 2, помещение склада у северного въезда, зона разгрузки и площадка ожидания для грузовых автомобилей';
 const h=harness(t,{mobile:true,reverseAddress:address});h.api.restore('pFrom',{kind:'point',label:oldAddress.slice(0,100),lat:41.7,lon:44.8,country_iso:'GE',address:oldAddress});await h.api.open('pFrom');h.calls.maps[0].setCenter([41.711234,44.822345]);await until(()=>h.node('locationPickerAddress').textContent===address);
 const label=address.slice(0,100).trim();assert.equal(h.node('locationPickerLabel').value.trim(),label);assert.ok(h.node('locationPickerLabel').value.length<=100);h.node('locationPickerConfirm').click();await tick();const endpoint=h.api.read('pFrom',label);assert.equal(endpoint.location.label,label);assert.ok(endpoint.location.label.length<=100);assert.equal(endpoint.location.address,address);assert.equal(h.calls.requests.find(row=>row.url.includes('/resolve')).body.address,address);
});


test('a custom renamed settlement remains custom when its picker is reopened',async t=>{
 const h=harness(t,{reverseAddress:resolvedRu});await h.api.preload();const city=catalog.find(row=>row.kind==='settlement');await h.api.choose('pFrom',{...city,label:'Моя площадка у Тбилиси',address:'Тбилиси'});await h.api.open('pFrom');await until(()=>h.node('locationPickerAddress').textContent===resolvedRu);assert.equal(h.node('locationPickerLabel').value,'Моя площадка у Тбилиси');
});


test('moving the pin during country resolution rejects the old point and requires a fresh confirmation',async t=>{
 const h=harness(t,{mobile:true}),originalFetch=h.w.fetch,pending=[];h.w.fetch=(url,options)=>url.includes('/resolve')?new Promise(resolve=>pending.push(()=>originalFetch(url,options).then(resolve))):originalFetch(url,options);
 await h.api.open('pFrom');h.node('locationPickerConfirm').click();await until(()=>pending.length===1);h.calls.maps[0].setCenter([41.711234,44.822345]);pending[0]();await tick();
 assert.equal(h.node('locationPickerOverlay').hidden,false);assert.equal(h.node('locationPickerConfirm').disabled,false);assert.equal(h.node('locationPickerError').hidden,false);assert.ok(h.node('locationPickerError').textContent.trim());assert.equal(h.node('pFromAddr').value,'');assert.equal(h.api.read('pFrom','Точка на карте'),null);
 h.node('locationPickerConfirm').click();await until(()=>pending.length===2);pending[1]();await tick();assert.equal(h.node('locationPickerOverlay').hidden,true);const selected=h.api.read('pFrom',h.node('pFromAddr').value);assert.equal(selected.location.lat,41.711234);assert.equal(selected.location.lon,44.822345);
});
test('manual rename during country resolution keeps the latest name for the unchanged point',async t=>{
 const h=harness(t,{mobile:true}),originalFetch=h.w.fetch;let finish;h.w.fetch=(url,options)=>url.includes('/resolve')?new Promise(resolve=>{finish=()=>originalFetch(url,options).then(resolve);}):originalFetch(url,options);
 await h.api.open('pFrom');const coordinates=Array.from(h.calls.maps[0].getCenter(),Number);h.node('locationPickerConfirm').click();await until(()=>!!finish);h.node('locationPickerLabel').value='Склад Серго, ворота 5';h.node('locationPickerLabel').dispatchEvent(new h.w.Event('input',{bubbles:true}));finish();await tick();
 assert.equal(h.node('locationPickerOverlay').hidden,true);assert.equal(h.node('pFromAddr').value,'Склад Серго, ворота 5');const selected=h.api.read('pFrom','Склад Серго, ворота 5');assert.equal(selected.location.label,'Склад Серго, ворота 5');assert.equal(selected.location.lat,coordinates[0]);assert.equal(selected.location.lon,coordinates[1]);
});

// Native basemap objects consume the ordinary Map.click. Their balloon exposes
// a properties manager and global-pixel position; neither is a geocoder result.
const nativePlaces=[
 // Schema and first feature observed through the live SDK's public getters.
 {id:'28857729343',name:'Дарьяльский монастырь',description:'край Мцхета-Мтианети, Казбегский муниципалитет',coords:[42.735488913518935,44.63132098317131]},
 {name:'სურსათის მაღაზია',description:'საქართველო, თბილისი, საწყობის ქუჩა, 7',coords:[41.708123,44.812345]}
];
for(const place of nativePlaces)test('native POI balloon transfers its own name and projected exact coordinates without a map click: '+place.name,async t=>{
 const h=harness(t);await h.api.open('pFrom');const map=h.calls.maps[0];map.openNativePoi({coords:place.coords,properties:{id:place.id,name:place.name,description:place.description,address:place.description}});
 assert.equal(h.node('locationPickerLabel').value,place.name);assert.equal(h.node('locationPickerAddress').textContent,place.description);assert.equal(map.balloon.isOpen(),false);
 assert.equal(h.calls.projections.length,1);assert.equal(h.calls.projections[0].zoom,map.getZoom());assert.ok(h.calls.projections[0].position.every(value=>value>180),'Balloon pixels must not be mistaken for lat/lon');
 h.node('locationPickerConfirm').click();await tick();const endpoint=h.api.read('pFrom',place.name);assert.ok(endpoint);assert.equal(endpoint.location.label,place.name);assert.equal(endpoint.location.address,place.description);assert.equal(endpoint.location.lat,place.coords[0]);assert.equal(endpoint.location.lon,place.coords[1]);
 const body=h.calls.requests.find(row=>row.url.includes('/resolve')).body;assert.equal(body.lat,place.coords[0]);assert.equal(body.lon,place.coords[1]);assert.equal(body.label,place.name);
 // A server round trip may recreate the endpoint object. Restore must retain
 // the same point and display name rather than geocoding its nearest road.
 h.api.restore('pFrom',JSON.parse(JSON.stringify(endpoint.location)));assert.equal(h.node('pFromAddr').value,place.name);assert.equal(h.api.read('pFrom',place.name).location.lat,place.coords[0]);
});

test('native POI preserves a manually entered loading-gate name while updating actual coordinates and address',async t=>{
 const h=harness(t);await h.api.open('pFrom');h.node('locationPickerLabel').value='Ворота №2, позвонить охране';h.node('locationPickerLabel').dispatchEvent(new h.w.Event('input',{bubbles:true}));
 const place=nativePlaces[1];h.calls.maps[0].openNativePoi({coords:place.coords,properties:{name:place.name,description:place.description}});assert.equal(h.node('locationPickerLabel').value,'Ворота №2, позвонить охране');assert.equal(h.node('locationPickerAddress').textContent,place.description);
 h.node('locationPickerConfirm').click();await tick();const location=h.api.read('pFrom','Ворота №2, позвонить охране').location;assert.equal(location.label,'Ворота №2, позвонить охране');assert.equal(location.lat,place.coords[0]);assert.equal(location.lon,place.coords[1]);
});

test('a native balloon from a closed map cannot mutate a newly opened picker',async t=>{
 const h=harness(t);await h.api.open('pFrom');const oldMap=h.calls.maps[0];h.api.close();await h.api.open('pTo');const before=h.node('locationPickerLabel').value;
 const place=nativePlaces[0];oldMap.openNativePoi({coords:place.coords,properties:{name:place.name,description:place.description}});assert.equal(h.node('locationPickerLabel').value,before);assert.equal(h.calls.projections.length,0);assert.equal(h.node('pFromAddr').value,'');assert.equal(h.node('pToAddr').value,'');
});

test('native balloons without finite geometry do not apply a name or fabricate a point',async t=>{
 const h=harness(t);await h.api.open('pFrom');const before=h.node('locationPickerLabel').value,map=h.calls.maps[0];
 for(const position of[null,[Infinity,123],[NaN,123]])map.openNativePoi({position,properties:{name:'Объект без координат',description:'Неизвестное положение'}});
 assert.equal(h.node('locationPickerLabel').value,before);assert.equal(h.node('pFromAddr').value,'');assert.equal(h.calls.projections.length,0);assert.equal(h.calls.requests.filter(row=>row.url.includes('/resolve')).length,0);
});

test('late reverse geocoding of C-3 cannot replace a selected native POI name or coordinates',async t=>{
 const pending=[],h=harness(t,{reverseResponder:(coords,result)=>new Promise(resolve=>pending.push(()=>resolve(result(coords,'С-3'))))});await h.api.open('pFrom');await until(()=>pending.length===1);
 const place=nativePlaces[0];h.calls.maps[0].openNativePoi({coords:place.coords,properties:{name:place.name,description:place.description}});pending[0]();await tick();await new Promise(resolve=>setTimeout(resolve,330));
 assert.equal(h.node('locationPickerLabel').value,place.name);assert.equal(h.node('locationPickerAddress').textContent,place.description);h.node('locationPickerConfirm').click();await tick();const location=h.api.read('pFrom',place.name).location;assert.equal(location.lat,place.coords[0]);assert.equal(location.lon,place.coords[1]);assert.equal(location.address,place.description);
});

test('mobile native balloon auto-pan cannot substitute viewport center for the selected POI',async t=>{
 const h=harness(t,{mobile:true});await h.api.open('pFrom');const map=h.calls.maps[0],place=nativePlaces[1];map.openNativePoi({coords:place.coords,properties:{name:place.name,description:place.description}});
 assert.equal(map.options.get('balloonAutoPan'),false);map.nativeAutoPan([41.723456,44.834567]);assert.equal(h.node('locationPickerLabel').value,place.name);assert.equal(map.balloon.isOpen(),false);
 h.node('locationPickerConfirm').click();await tick();const location=h.api.read('pFrom',place.name).location;assert.equal(location.lat,place.coords[0]);assert.equal(location.lon,place.coords[1]);assert.equal(location.label,place.name);
});

test('a valid background click recovers confirmation after a native POI has invalid pixels',async t=>{
 const h=harness(t);await h.api.open('pFrom');const map=h.calls.maps[0];map.openNativePoi({position:[Infinity,123],properties:{name:'Нечитаемый объект'}});
 assert.equal(h.node('locationPickerConfirm').disabled,true);assert.equal(h.node('locationPickerError').hidden,false);assert.equal(h.node('pFromAddr').value,'');
 const coords=[41.712345,44.823456];map.events.emit('click',{coords});assert.equal(h.node('locationPickerConfirm').disabled,false);assert.equal(h.node('locationPickerError').hidden,true);
 h.node('locationPickerLabel').value='Корректная точка рядом';h.node('locationPickerLabel').dispatchEvent(new h.w.Event('input',{bubbles:true}));h.node('locationPickerConfirm').click();await tick();
 assert.equal(h.node('locationPickerOverlay').hidden,true);const location=h.api.read('pFrom','Корректная точка рядом').location;assert.equal(location.lat,coords[0]);assert.equal(location.lon,coords[1]);
});

test('an invalid native POI arriving during country resolution cannot confirm the previous point',async t=>{
 const h=harness(t),originalFetch=h.w.fetch;let finishResolve;h.w.fetch=(url,options)=>url.includes('/resolve')?new Promise(resolve=>{finishResolve=()=>originalFetch(url,options).then(resolve);}):originalFetch(url,options);
 await h.api.open('pFrom');h.node('locationPickerConfirm').click();await until(()=>!!finishResolve);h.calls.maps[0].openNativePoi({position:[NaN,123],properties:{name:'Неопределённое место'}});finishResolve();await tick();
 assert.equal(h.node('locationPickerOverlay').hidden,false);assert.equal(h.node('locationPickerConfirm').disabled,true);assert.equal(h.node('locationPickerError').hidden,false);assert.equal(h.node('pFromAddr').value,'');assert.equal(h.api.read('pFrom','Точка на карте'),null);
});

test('a canonical checkpoint used as the viewport seed yields its default name and key to a newly selected native POI',async t=>{
 const h=harness(t);await h.api.preload();await h.api.choose('pFrom',catalog[0]);await h.api.open('pFrom');assert.equal(h.node('locationPickerLabel').value,catalog[0].label);
 const place=nativePlaces[0];h.calls.maps[0].openNativePoi({coords:place.coords,properties:{name:place.name,address:place.description}});assert.equal(h.node('locationPickerLabel').value,place.name);h.node('locationPickerConfirm').click();await tick();
 const location=h.api.read('pFrom',place.name).location;assert.equal(location.kind,'point');assert.equal(location.key??null,null);assert.equal(location.label,place.name);assert.equal(location.lat,place.coords[0]);assert.equal(location.lon,place.coords[1]);assert.equal(h.calls.requests.filter(row=>row.url.includes('/resolve')).length,1);
});
