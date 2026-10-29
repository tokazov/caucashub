import {test} from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';

const main=readFileSync(new URL('../../../frontend/main.js',import.meta.url),'utf8');
const api=readFileSync(new URL('../../../frontend/api.js',import.meta.url),'utf8');
const fromAddress='Грузия, Тбилиси, улица Серго Закариадзе';
const toAddress='Грузия, Батуми, улица Горгиладзе, 10';

function environment({reply}={}){
 const fields={};
 for(const id of ['pFromAddr','pToAddr','dropPFrom','dropPTo','coordsPFrom','coordsPTo',
  'pWeight','pPrice','pTruck','pDesc','pPay','pUrgent','pDate','pDate2','postSuccess','fcount']){
  fields[id]={value:'',style:{display:'none'},classList:{remove(){},add(){}}};
 }
 Object.assign(fields.pWeight,{value:'1000'});Object.assign(fields.pPrice,{value:'350'});
 Object.assign(fields.pTruck,{value:'tent',selectedIndex:0,options:[{text:'Тент'}]});
 fields.pDate.value='2030-10-30';fields.pToAddr.value='Батуми';
 const button={disabled:false},calls={requests:[],warnings:[],geocodes:[],timers:[]};
 const ctx={window:null,document:{getElementById:id=>fields[id],querySelector:()=>button},
  scope:'local',lang:'ru',TRANSLATIONS:{ru:{}},selectedFrom:null,selectedTo:null,
  CITIES:[{name:'Тбилиси'},{name:'Батуми'},{name:'Кутаиси'}],
  user:{name:'Test shipper',email:'shipper@example.test'},currentUserId:7,
  LOCAL:[],INTL:[],_myLoads:[],_editingLoadId:null,_postLoadSubmitting:false,_postLoadIdempotencyKey:'key',
  _genUUID:()=> 'new-key',getToken:()=> 'token',persistMyLoads(){},renderLoads(){},closeModal(){},
  showToastWarn:text=>calls.warnings.push(text),openAuth(){},esc:String,
  setTimeout:callback=>{calls.timers.push(callback);return calls.timers.length;},clearTimeout(){},
  loadYmapsLazy:callback=>callback(),
  ymaps:{ready:callback=>callback(),geocode:async query=>{
   calls.geocodes.push(query);return{geoObjects:{getLength:()=>ctx.results.length,each:callback=>ctx.results.forEach(callback)}};
  }},results:[],mapServerLoad:row=>({...row,serverId:row.id,scope:row.route_scope||'local'}),
  apiRequest:async(method,path,body)=>{
   calls.requests.push({method,path,body});
   return reply||{ok:true,data:{id:501,from:body.from_city,to:body.to_city,route_scope:'local'}};
  }};
 ctx.window=ctx;ctx.addMyLoad=load=>ctx._myLoads.unshift(load);vm.createContext(ctx);
 const address=main.indexOf('let addrTimers=');
 vm.runInContext(main.slice(address,main.indexOf('// ── CITIES',address)),ctx);
 const dates=api.indexOf('// Calendar days in Georgia');
 vm.runInContext(api.slice(dates,api.indexOf('// ── AUTH',dates)),ctx);
 const client=api.indexOf('const CaucasAPI =');
 vm.runInContext(api.slice(client,api.indexOf('\n};',client)+3),ctx);
 const read=main.indexOf('function readPostLoadingDates()');
 vm.runInContext(main.slice(read,main.indexOf('function openPostLoad(',read)),ctx);
 const publish=main.indexOf('async function doPostLoad()');
 vm.runInContext(main.slice(publish,main.indexOf('// Массив своих грузов',publish)),ctx);
 const editor=main.indexOf('async function saveEditedLoad()');
 vm.runInContext(main.slice(editor,main.indexOf('// ── FILTER',editor)),ctx);
 return{ctx,fields,button,calls,selection:field=>vm.runInContext('addrSelected.'+field,ctx)};
}
const yandex=(name,city,addr=fromAddress)=>({
 getAddressLine:()=>addr,getLocalities:()=>city?[city]:[],
 properties:{get:path=>path==='name'?name:null},geometry:{getCoordinates:()=>[41.7,44.8]},
});

for(const road of ['С-3','улица Серго Закариадзе'])test('geocoder '+road+' publishes its actual locality and full address separately',async()=>{
 const h=environment();h.ctx.results=[yandex(road,'Тбилиси')];
 h.fields.pFromAddr.value=road;h.ctx.addrSearch('pFrom',road);h.calls.timers.shift()();
 await new Promise(setImmediate);
 const [key]=Object.keys(h.ctx._addrCache);
 assert.equal(h.ctx._addrCache[key].city,'Тбилиси');assert.equal(h.ctx._addrCache[key].addr,fromAddress);
 h.ctx.selectAddrByKey('pFrom',key);
 assert.equal(h.fields.pFromAddr.value,fromAddress);assert.equal(h.selection('pFrom').city,'Тбилиси');
 await h.ctx.doPostLoad();
 assert.equal(h.calls.requests.length,1);assert.equal(h.calls.requests[0].body.from_city,'Тбилиси');
 assert.equal(h.calls.requests[0].body.from_address,fromAddress);
 assert.equal(h.fields.postSuccess.style.display,'block');
});

test('city, town and village structured metadata are used instead of the street name',()=>{
 const h=environment();
 for(const field of ['city','town','village']){
  const result=h.ctx.geocodedPublicationAddress({name:'С-3',address:{[field]:'Реальный населённый пункт'},display_name:'Полный адрес'});
  assert.equal(result.city,'Реальный населённый пункт');assert.equal(result.addr,'Полный адрес');
 }
 const metadata={Address:{Components:[{kind:'street',name:'С-3'},{kind:'locality',name:'Тбилиси'}]}};
 const result=h.ctx.geocodedPublicationAddress({getAddressLine:()=>fromAddress,
  properties:{get:()=>metadata},getLocalities:()=>[]});
 assert.equal(result.city,'Тбилиси');
});

test('address with no populated locality is blocked before sending a street as its city',async()=>{
 const h=environment();const address=h.ctx.geocodedPublicationAddress(yandex('С-3',null));
 assert.equal(address.city,'');
 h.ctx._addrCache={road:{...address,name:'С-3',lat:41.7,lng:44.8}};
 h.ctx.selectAddrByKey('pFrom','road');await h.ctx.doPostLoad();
 assert.equal(h.calls.requests.length,0);assert.match(h.calls.warnings[0],/определить город/);
 assert.equal(h.fields.postSuccess.style.display,'none');assert.equal(h.ctx.LOCAL.length,0);
});

test('canonical selected address IDs survive publication and update payloads',async()=>{
 const h=environment();h.ctx._addrCache={
  from:{name:'улица',addr:fromAddress,city:'Тбилиси',city_id:1,canonical_key:'ge:tbilisi',lat:41.7,lng:44.8},
  to:{name:'улица',addr:toAddress,city:'Батуми',city_id:2,canonical_key:'ge:batumi',lat:41.6,lng:41.6},
 };
 h.ctx.selectAddrByKey('pFrom','from');h.ctx.selectAddrByKey('pTo','to');await h.ctx.doPostLoad();
 const body=h.calls.requests[0].body;
 assert.equal(body.from_city_id,1);assert.equal(body.from_city_key,'ge:tbilisi');
 assert.equal(body.to_city_id,2);assert.equal(body.to_city_key,'ge:batumi');
 assert.equal(body.to_address,toAddress);
 h.ctx._editingLoadId=501;h.button.disabled=false;await h.ctx.saveEditedLoad();
 assert.equal(h.calls.requests[1].method,'PUT');assert.equal(h.calls.requests[1].body.from_city_id,1);
 assert.equal(h.calls.requests[1].body.from_address,fromAddress);
});

test('manual address edits cannot reuse stale selected city, coordinates or registry ID',async()=>{
 const h=environment();h.ctx.selectAddr('pFrom',fromAddress,41.7,44.8,{city:'Тбилиси',city_id:1,canonical_key:'ge:tbilisi'});
 h.fields.pFromAddr.value='Кутаиси';
 const endpoint=h.ctx.readPublicationEndpoint('pFrom','Кутаиси');
 assert.equal(endpoint.city,'Кутаиси');assert.equal(endpoint.city_id,undefined);assert.equal(endpoint.lat,undefined);
 h.ctx.addrSearch('pFrom','Кутаиси');assert.equal(h.selection('pFrom'),null);
 await h.ctx.doPostLoad();
 assert.equal(h.calls.requests[0].body.from_city,'Кутаиси');assert.equal(h.calls.requests[0].body.from_city_id,undefined);
});

test('unknown locality 422 preserves the address draft and never creates local success',async()=>{
 const message='Населённый пункт не найден в справочнике. Уточните город.';
 const h=environment({reply:{ok:false,status:422,data:{detail:message}}});
 h.ctx.selectAddr('pFrom',fromAddress,41.7,44.8,{city:'Неизвестный населённый пункт'});
 await h.ctx.doPostLoad();
 assert.equal(h.calls.requests.length,1);assert.equal(h.calls.warnings[0],message);
 assert.equal(h.fields.pFromAddr.value,fromAddress);assert.equal(h.fields.postSuccess.style.display,'none');
 assert.equal(h.ctx.LOCAL.length+h.ctx.INTL.length+h.ctx._myLoads.length,0);assert.equal(h.button.disabled,false);
});

test('server-recognized international route cannot be temporarily inserted into Local',async()=>{
 const h=environment({reply:{ok:true,data:{id:502,from:'Тбилиси',to:'Владикавказ',route_scope:'intl'}}});
 h.fields.pFromAddr.value='Тбилиси';h.fields.pToAddr.value='Владикавказ';await h.ctx.doPostLoad();
 assert.equal(h.ctx.LOCAL.length,0);assert.equal(h.ctx.INTL.length,1);assert.equal(h.ctx.INTL[0].id,502);
});

test('international address geocoding is not forced to append Georgia',async()=>{
 const h=environment();h.ctx.scope='intl';h.fields.pFromAddr.value='Ереван';
 h.ctx.addrSearch('pFrom','Ереван');h.calls.timers.shift()();await new Promise(setImmediate);
 assert.equal(h.calls.geocodes[0],'Ереван');
});

test('route detail title uses its locality rather than the full address trailing house number',()=>{
 const ctx={};vm.createContext(ctx);
 const start=main.indexOf('function _cityShort(');
 vm.runInContext(main.slice(start,main.indexOf('// ── Q-014',start)),ctx);
 assert.equal(ctx._cityShort(toAddress,'Батуми'),'Батуми');
});
