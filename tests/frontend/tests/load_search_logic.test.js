import {test} from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
const source=p=>readFileSync(new URL('../../../'+p,import.meta.url),'utf8');
function env(path){
 const fields={};
 for(const id of ['fFrom','fTo','fType','fWeight','fPrice','fDate','fDateFrom','fDateTo','fCountry','fcount'])fields[id]={value:'',textContent:''};
 const calls={rendered:[],maps:0,geocodes:[]};
 const context={document:{getElementById:id=>fields[id]},scope:'local',lang:'ru',TRANSLATIONS:{ru:{fcount_suffix:'loads'},ge:{fcount_suffix:'ტვირთი'}},
  LOCAL:[],INTL:[],selectedFrom:null,selectedTo:null,renderLoads:data=>calls.rendered.push(data),
  showRouteMap:()=>calls.maps++,_fetchCitySuggestions:(query,lang,callback)=>calls.geocodes.push({query,callback})};
 vm.createContext(context);const code=source(path),cities=code.indexOf('const CITIES = [');
 vm.runInContext(code.slice(cities,code.indexOf('// Получить наиболее конкретный город',cities)),context);
 const countries=code.indexOf('const COUNTRY_FLAGS=');
 vm.runInContext(code.slice(countries,code.indexOf('// Показываем/скрываем фильтр стран',countries)),context);
 const api=source('frontend/api.js'),dates=api.indexOf('// Calendar days in Georgia');
 vm.runInContext(api.slice(dates,api.indexOf('// ── AUTH',dates)),context);
 const dateRange=code.indexOf('function loadingDateRange()');
 vm.runInContext(code.slice(dateRange,code.indexOf('function filterByDate(',dateRange)),context);
 const start=code.indexOf('function _loadFilterKey(');
 vm.runInContext(code.slice(start,code.indexOf('// ═══ КАБИНЕТ',start)),context);
 return{context,fields,calls,run:data=>context.filterLoadData(data)};
}
const rows=[
 {id:1,from:'Тбилиси',to:'Батуми',type:'tent',typeLabel:'Тент',kg:1000,price:100,date:'2030-01-01',date2:'2030-01-04'},
 {id:2,from:'თბილისი',to:'ბათუმი',type:'ref',typeLabel:'Рефриж.',kg:5000,price:500,date:'2030-01-05'},
 {id:3,from:'Батуми',to:'Тбилиси',type:'tent',kg:2000,price:200,date:'2030-01-01'},
 {id:4,from:'Тбилиси',to:'Батуми',type:'tent',kg:1000,price:100,date:'2030-01-01',status:'taken'},
];
const ids=data=>Array.from(data,row=>row.id);
for(const path of ['main.js','frontend/main.js']){
 test(path+': canonical body code works without a label and keeps taken out',()=>{
  const h=env(path);h.fields.fType.value='tent';assert.deepEqual(ids(h.run(rows)),[1,3]);
  h.fields.fType.value='ref';assert.deepEqual(ids(h.run(rows)),[2]);
 });
 test(path+': RU and GE routes match in their own direction',()=>{
  const h=env(path);h.fields.fFrom.value=' თბილისი ';h.fields.fTo.value='Батуми';
  assert.deepEqual(ids(h.run(rows)),[1,2]);
  h.fields.fFrom.value='Батуми';h.fields.fTo.value='თბილისი';assert.deepEqual(ids(h.run(rows)),[3]);
 });
 test(path+': unknown route remains a directional substring',()=>{
  const h=env(path);h.context.scope='intl';h.fields.fFrom.value='Неизвест';
  assert.deepEqual(ids(h.run([{id:1,from:'Неизвестный город',to:'Батуми'},{id:2,from:'Батуми',to:'Неизвестный город'}])),[1]);
 });
 test(path+': country aliases work without undefined helpers or empty-name matches',()=>{
  const h=env(path);h.context.scope='intl';
  for(const alias of ['RU','🇷🇺','Россия','რუსეთი'])assert.equal(h.context.findCountryCode(alias),'RU');
  for(const alias of ['KZ','Казахстан','ყაზახეთი','🇰🇿'])assert.equal(h.context.findCountryCode(alias),'KZ');
  const data=[{id:1,from:'🇷🇺 Москва',to:'🇬🇪 Тбилиси'},{id:2,from:'🇬🇪 Тбилиси',to:'Россия Москва'},{id:3,from:'Unknown',to:'Unknown'}];
  h.fields.fFrom.value='რუსეთი';h.fields.fTo.value='GE';assert.deepEqual(ids(h.run(data)),[1]);
  h.fields.fFrom.value='';h.fields.fTo.value='';h.fields.fCountry.value='RU';assert.deepEqual(ids(h.run(data)),[1,2]);
  h.fields.fCountry.value='ZZ';assert.deepEqual(ids(h.run(data)),[]);
 });
 test(path+': weight price and period overlap stay inclusive and combine',()=>{
  const h=env(path);h.fields.fWeight.value='1000-2000';h.fields.fPrice.value='100-200';
  h.fields.fDate.value='pick_range';h.fields.fDateFrom.value='2030-01-03';h.fields.fDateTo.value='2030-01-04';
  assert.deepEqual(ids(h.run(rows)),[1]);
 });
 test(path+': compute helper does not render geocode mutate records or inputs',()=>{
  const h=env(path);h.fields.fFrom.value='თბილისი';h.fields.fTo.value='Батуми';
  const original=JSON.stringify(rows),before=JSON.stringify(h.fields);h.run(rows);
  assert.equal(JSON.stringify(rows),original);assert.equal(JSON.stringify(h.fields),before);
  assert.equal(h.calls.rendered.length,0);assert.equal(h.calls.geocodes.length,0);assert.equal(h.calls.maps,0);
 });
 test(path+': count agrees with rendered non-taken results',()=>{
  const h=env(path);h.context.LOCAL=rows;h.context.filterLoads();
  assert.deepEqual(ids(h.calls.rendered[0]),[1,2,3]);assert.equal(h.fields.fcount.textContent,'3 loads');
 });
 test(path+': reset or a new query prevents late map updates',()=>{
  const h=env(path);h.context.LOCAL=rows;h.fields.fFrom.value='Unknown origin';h.fields.fTo.value='Unknown destination';
  h.context.filterLoads();assert.equal(h.calls.geocodes.length,1);
  h.fields.fFrom.value='';h.fields.fTo.value='';h.calls.geocodes[0].callback([{lat:1,lon:2}]);
  assert.equal(h.calls.geocodes.length,1);assert.equal(h.calls.maps,0);
 });
 test(path+': second late geocoder callback cannot reopen a reset map',()=>{
  const h=env(path);h.fields.fFrom.value='Unknown origin';h.fields.fTo.value='Unknown destination';
  h.context.filterLoads();h.calls.geocodes[0].callback([{lat:1,lon:2}]);assert.equal(h.calls.geocodes.length,2);
  h.fields.fTo.value='Changed';h.calls.geocodes[1].callback([{lat:3,lon:4}]);assert.equal(h.calls.maps,0);
 });
}
