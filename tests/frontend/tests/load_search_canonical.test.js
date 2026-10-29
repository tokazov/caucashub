import {test} from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';

const main=readFileSync(new URL('../../../frontend/main.js',import.meta.url),'utf8');
const api=readFileSync(new URL('../../../frontend/api.js',import.meta.url),'utf8');
const ids=rows=>Array.from(rows,row=>row.id);
const city=(id,key,ru,en,ge)=>({id,key,aliases:[ru,en,ge]});
const tbilisi=city(1,'ge:tbilisi','Тбилиси','Tbilisi','თბილისი');
const batumi=city(2,'ge:batumi','Батуми','Batumi','ბათუმი');
const kutaisi=city(3,'ge:kutaisi','Кутаиси','Kutaisi','ქუთაისი');
const rows=[
 {id:11,from:'Tbilisi',to:'ბათუმი',origin:tbilisi,destination:batumi},
 {id:12,from:'თბილისი',to:'Batumi',origin:tbilisi,destination:batumi},
 {id:13,from:'Батуми',to:'Тбилиси',origin:batumi,destination:tbilisi},
 {id:14,from:'Kutaisi',to:'Tbilisi',origin:kutaisi,destination:tbilisi},
].map(({origin,destination,...row})=>({...row,
 from_city_id:origin.id,from_city_key:origin.key,from_city_aliases:origin.aliases,
 to_city_id:destination.id,to_city_key:destination.key,to_city_aliases:destination.aliases}));

function environment(){
 const fields={};
 for(const id of ['fFrom','fTo','fType','fWeight','fPrice','fDate','fDateFrom','fDateTo','fCountry','fcount','dropFrom','dropTo']){
  fields[id]={value:'',dataset:{},classList:{add(){},remove(){}}};
 }
 const ctx={window:null,document:{getElementById:id=>fields[id]},scope:'local',lang:'ru',
  selectedFrom:null,selectedTo:null,LOCAL:rows,INTL:[],filterLoadingDates:data=>data,loadingDateRange:()=>null,
  TRANSLATIONS:{ru:{fcount_suffix:'loads'}},renderLoads(){},showRouteMap(){},esc:value=>String(value),
  _fetchCitySuggestions(){throw Error('Unexpected search geocode');},
  setTimeout:callback=>{ctx.timer=callback;return 1;},clearTimeout(){}};
 ctx.window=ctx;vm.createContext(ctx);
 const cities=main.indexOf('const CITIES = [');
 vm.runInContext(main.slice(cities,main.indexOf('// Получить наиболее конкретный город',cities)),ctx);
 const countries=main.indexOf('const COUNTRY_FLAGS=');
 vm.runInContext(main.slice(countries,main.indexOf('// Показываем/скрываем фильтр стран',countries)),ctx);
 const start=main.indexOf('function _loadFilterKey(');
 vm.runInContext(main.slice(start,main.indexOf('// ═══ КАБИНЕТ',start)),ctx);
 const autocomplete=main.indexOf('const _filterCityTimers =');
 vm.runInContext(main.slice(autocomplete,main.indexOf('// ── YANDEX MAP',autocomplete)),ctx);
 return {ctx,fields,search:()=>ctx.filterLoadData(rows),selected:side=>vm.runInContext(side==='to'?'selectedTo':'selectedFrom',ctx)};
}

test('cargo manual RU / EN / KA names match the same canonical IDs in each direction',()=>{
 const h=environment();
 for(const from of tbilisi.aliases)for(const to of batumi.aliases){
  h.fields.fFrom.value=from;h.fields.fTo.value=to;
  assert.deepEqual(ids(h.search()),[11,12],from+' → '+to);
 }
 for(const from of batumi.aliases)for(const to of tbilisi.aliases){
  h.fields.fFrom.value=from;h.fields.fTo.value=to;
  assert.deepEqual(ids(h.search()),[13],from+' → '+to);
 }
 for(const alias of kutaisi.aliases){h.fields.fFrom.value=alias;h.fields.fTo.value='';assert.deepEqual(ids(h.search()),[14]);}
});

test('canonical autocomplete selection retains registry ID/key in the selection and input',()=>{
 const h=environment();
 h.ctx.selectCity('from','Тбилиси',41.7,44.8,false,'Тбилиси','1','ge:tbilisi');
 h.fields.fTo.value='Batumi';
 assert.equal(h.selected().city_id,1);assert.equal(h.selected().canonical_key,'ge:tbilisi');
 assert.equal(h.fields.fFrom.dataset.cityId,'1');assert.equal(h.fields.fFrom.dataset.cityKey,'ge:tbilisi');
 assert.equal(h.fields.fFrom.dataset.cityLabel,'Тбилиси');
 assert.deepEqual(ids(h.search()),[11,12]);
});

test('edited manual city text cannot reuse a previous canonical selection or input ID',()=>{
 const h=environment();h.ctx.selectCity('from','Тбилиси',null,null,false,'Тбилиси','1','ge:tbilisi');
 h.fields.fFrom.value='Batumi';
 // Matching also protects programmatic edits that have not emitted an input event.
 assert.deepEqual(ids(h.search()),[13]);
 h.ctx.filterCity('from','Batumi');
 assert.equal(h.selected(),null);assert.equal(h.fields.fFrom.dataset.cityId,undefined);
 assert.equal(h.fields.fFrom.dataset.cityKey,undefined);assert.equal(h.fields.fFrom.dataset.cityLabel,undefined);
});

test('a free-text selection clears a previous registry identity',()=>{
 const h=environment();h.ctx.selectCity('from','Тбилиси',null,null,false,'Тбилиси','1','ge:tbilisi');
 h.ctx.selectCity('from','Unknown location',null,null);
 assert.equal(h.selected().city_id,undefined);assert.equal(h.selected().canonical_key,undefined);
 assert.equal(h.fields.fFrom.dataset.cityId,undefined);assert.equal(h.fields.fFrom.dataset.cityKey,undefined);
});

test('autocomplete renders canonical identity and ignores a result after the text or scope changes',()=>{
 const h=environment();let callback;
 h.ctx._fetchCitySuggestionsFiltered=(query,lang,done)=>{callback=done;};
 h.fields.fFrom.value='Tb';h.ctx.filterCity('from','Tb');h.ctx.timer();
 callback([{id:1,canonical_key:'ge:tbilisi',name_ru:'Тбилиси',display_name:'Tbilisi',lat:41.7,lon:44.8}]);
 assert.match(h.fields.dropFrom.innerHTML,/data-city-id="1"/);
 assert.match(h.fields.dropFrom.innerHTML,/data-city-key="ge:tbilisi"/);
 h.fields.fFrom.value='Ba';h.ctx.filterCity('from','Ba');h.ctx.timer();
 const before=h.fields.dropFrom.innerHTML;h.ctx.scope='intl';
 callback([{id:2,canonical_key:'ge:batumi',name_ru:'Батуми',display_name:'Batumi'}]);
 assert.equal(h.fields.dropFrom.innerHTML,before);
});

test('route map rendering keeps an existing canonical selection',()=>{
 const h=environment();h.ctx.selectCity('from','Тбилиси',41.7,44.8,false,'Тбилиси','1','ge:tbilisi');
 h.ctx.selectCity('to','Батуми',41.6,41.6,false,'Батуми','2','ge:batumi');
 h.ctx.filterLoads();
 assert.equal(h.selected().canonical_key,'ge:tbilisi');assert.equal(h.selected('to').city_id,2);
});

function getLoads(request){
 const ctx={URLSearchParams,apiRequest:request};vm.createContext(ctx);
 const start=api.indexOf('  async getLoads('),end=api.indexOf('  async getMyLoads(',start);
 vm.runInContext('var client={'+api.slice(start,end)+'};',ctx);
 return options=>ctx.client.getLoads(options);
}
test('scoped sync includes matching loads beyond 100 and preserves filters on every page',async()=>{
 const requests=[];
 const all=Array.from({length:215},(_,i)=>({id:i+1,from:i===214?'თბილისი':'Kutaisi'}));
 const fetch=getLoads(async(method,url)=>{
  const params=new URL(url,'https://test.invalid').searchParams;requests.push(params);
  const offset=Number(params.get('offset')||0);
  return{ok:true,data:{loads:all.slice(offset,offset+100),total:all.length}};
 });
 const result=await fetch({scope:'local',from_city_key:'ge:tbilisi',to_city_id:2,truck_type:'tent'});
 assert.equal(result.length,215);assert.equal(result.at(-1).id,215);assert.equal(requests.length,3);
 assert.deepEqual(requests.map(p=>p.get('offset')||'0'),['0','100','200']);
 for(const params of requests){assert.equal(params.get('scope'),'local');assert.equal(params.get('from_city_key'),'ge:tbilisi');assert.equal(params.get('to_city_id'),'2');assert.equal(params.get('truck_type'),'tent');}
});
test('pagination deduplicates overlapping pages while completing the public result',async()=>{
 const pages=[[{id:1},{id:2}],[{id:2},{id:3}]];let calls=0;
 const fetch=getLoads(async()=>({ok:true,data:{loads:pages[calls++],total:3}}));
 assert.deepEqual(ids(await fetch()),[1,2,3]);assert.equal(calls,2);
});
test('client cargo search can find a canonical multilingual route after the first 100 scoped loads',async()=>{
 const all=Array.from({length:215},(_,index)=>({...rows[index===214?0:3],id:index+1}));
 const fetch=getLoads(async(method,url)=>{
  const offset=Number(new URL(url,'https://test.invalid').searchParams.get('offset')||0);
  return{ok:true,data:{loads:all.slice(offset,offset+100),total:all.length}};
 });
 const result=await fetch({scope:'local'}),h=environment();
 for(const from of tbilisi.aliases)for(const to of batumi.aliases){
  h.fields.fFrom.value=from;h.fields.fTo.value=to;
  assert.deepEqual(ids(h.ctx.filterLoadData(result)),[215]);
 }
});
test('broken or incomplete pagination fails instead of publishing partial results',async()=>{
 for(const pages of [
  [{ok:true,data:{loads:[{id:1}],total:2}},{ok:false}],
  [{ok:true,data:{loads:[{id:1}],total:2}},{ok:true,data:{loads:[],total:2}}],
  [{ok:true,data:{loads:[{id:1}],total:2}},{ok:true,data:{loads:[{id:1}],total:2}}],
 ]){
  let calls=0;const fetch=getLoads(async()=>pages[calls++]);
  await assert.rejects(fetch());assert.equal(calls,2);
 }
});
test('pagination has a fixed request bound against a constantly growing server total',async()=>{
 let calls=0;const fetch=getLoads(async()=>({ok:true,data:{loads:[{id:++calls}],total:10000}}));
 await assert.rejects(fetch(),/Too many loads/);assert.equal(calls,50);
});
test('a valid empty server page is authoritative and a malformed response is an error',async()=>{
 assert.equal((await getLoads(async()=>({ok:true,data:{loads:[],total:0}}))()).length,0);
 for(const response of [{ok:false},{ok:true,data:{}},{ok:true,data:{loads:[{}],total:1}}]){
  await assert.rejects(getLoads(async()=>response)());
 }
});
