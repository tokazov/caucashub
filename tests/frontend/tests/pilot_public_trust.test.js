import {test} from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';

const read=path=>readFileSync(new URL('../../../'+path,import.meta.url),'utf8');
const main=read('frontend/main.js'),api=read('frontend/api.js'),html=read('frontend/index.html');
const slice=(source,from,to)=>source.slice(source.indexOf(from),source.indexOf(to,source.indexOf(from)));
const escape=value=>String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;');
const settle=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};

function transportHarness(){
 const nodes={transportList:{innerHTML:''},transportCount:{textContent:''},
  'sec-trucks':{classList:{contains:()=>true}},tFilterFrom:{value:'',dataset:{}},tFilterTo:{value:'',dataset:{}}};
 const requests=[],context={window:null,document:{getElementById:id=>nodes[id]},lang:'ru',scope:'local',
  TRANSLATIONS:{ru:{transport_count_suffix:'offers'}},URLSearchParams,AbortController,
  API_BASE:'https://api.test',getToken:()=>null,getTypeLabel:()=> 'Van',esc:escape,
  setTimeout,clearTimeout,requestAnimationFrame:fn=>{fn();return null;},cancelAnimationFrame:()=>{},
  fetch:async url=>{requests.push(new URL(url));return {ok:true,status:200,json:async()=>({offers:[],total:0})};}};
 context.window=context;vm.createContext(context);
 vm.runInContext(slice(main,'function esc(s) {','// ── SAFE LOCALSTORAGE'),context);
 vm.runInContext(slice(main,'var _transportOffers = []','// Открыть модалку отклика'),context);
 return {context,nodes,requests};
}

test('a carrier has a public score only with verified reviews and an explicit count',()=>{
 const {context:c}=transportHarness();
 for(const record of [{},{rating:5},{rat:'5.0',review_count:0},{rating:5,review_count:2},
  {rating:5,review_count:2,rating_verified:false},{rating:9,review_count:2,rating_verified:true},
  {rating:5,review_count:-1,rating_verified:true}]){
  assert.equal(c.publicRatingLabel(record),'Новый перевозчик');
 }
 assert.equal(c.publicRatingLabel({rating:4.5,review_count:2,rating_verified:true}),'⭐ 4.5 · 2 отзывов');
});

test('availability distinguishes legacy, stale and expired offers and shows a real confirmation date',()=>{
 const {context:c,nodes}=transportHarness();
 assert.equal(c.transportAvailabilityLabel({}),'Доступность не подтверждена');
 assert.match(c.transportAvailabilityLabel({availability_status:'stale'}),/давно не подтверждалась/);
 assert.match(c.transportAvailabilityLabel({dates_expired:true}),/истёк/);
 assert.match(c.transportAvailabilityLabel({availability_status:'confirmed',last_confirmed_at:'2026-10-28T21:00:00Z'}),/29.10.2026/);
 assert.doesNotMatch(c.transportAvailabilityLabel({last_confirmed_at:'invalid'}),/Invalid/);
 c._transportOffers=[{id:1,company_name:'<carrier>',capacity_kg:100000,capacity_valid:false,availability_status:'unconfirmed',urgent:true}];
 c.renderTransportOffers();
 assert.match(nodes.transportList.innerHTML,/Параметры транспорта требуют проверки/);
 assert.match(nodes.transportList.innerHTML,/Доступность не подтверждена/);
 assert.match(nodes.transportList.innerHTML,/&lt;carrier&gt;/);
 assert.doesNotMatch(nodes.transportList.innerHTML,/badge-urgent-new|⭐ 5/);
});

test('empty public lists offer the appropriate own posting and assistance without sample listings',()=>{
 const {context:c}=transportHarness();
 assert.match(c.publicListingEmpty('transport'),/onclick="openPostLoad\(\)"/);
 assert.match(c.publicListingEmpty('loads'),/onclick="openPostTransportOffer\(\)"/);
 for(const kind of ['loads','transport'])assert.match(c.publicListingEmpty(kind),/onclick="toggleAI\(\)"/);
 assert.match(main,/const TRUCKS = \[\];/);
 const rates=slice(html,'id="sec-rates"','id="sec-cabinet"');
 assert.match(rates,/rates_unavailable/);
 assert.doesNotMatch(rates,/\$0\.85|\+8%|47 рейсов|38 рейсов/);
 // Commercial values and activation handlers remain owner-controlled.
 assert.match(html,/Купить за ₾49/);assert.match(html,/Купить за ₾149/);
 assert.doesNotMatch(html,/Все функции бесплатны|Первая биржа грузов Кавказа(?=<\/span>)/);
});

test('transport queries always send the selected scope and only a matching city identity',async()=>{
 const {context:c,nodes,requests}=transportHarness();
 nodes.tFilterFrom.value='Тбилиси';nodes.tFilterFrom.dataset={cityLabel:'Тбилиси',cityId:'1',cityKey:'ge:tbilisi'};
 nodes.tFilterTo.value='ბათუმი';nodes.tFilterTo.dataset={cityLabel:'ბათუმი',cityKey:'ge:batumi'};
 await c.filterAndLoadTransport();
 assert.equal(requests[0].searchParams.get('scope'),'local');
 assert.equal(requests[0].searchParams.get('from_city_id'),'1');
 assert.equal(requests[0].searchParams.get('to_city_key'),'ge:batumi');
 nodes.tFilterFrom.value='Kutaisi';c.scope='intl';await c.filterAndLoadTransport();
 assert.equal(requests[1].searchParams.get('scope'),'intl');
 assert.equal(requests[1].searchParams.get('from_city'),'Kutaisi');
 assert.equal(requests[1].searchParams.has('from_city_id'),false);
});

test('city autocomplete clears a prior identity on editing and escapes suggestion attributes',()=>{
 const events={},dropdown={style:{},innerHTML:'',querySelectorAll:()=>[]};let callback,timer;
 const input={value:'Tbilisi',dataset:{cityId:'1',cityKey:'ge:tbilisi',cityLabel:'Тбилиси'},
  parentElement:{style:{},appendChild:()=>{}},addEventListener:(type,fn)=>events[type]=fn};
 const c={lang:'ge',esc:escape,document:{getElementById:()=>input,createElement:()=>dropdown,addEventListener:()=>{}},
  setTimeout:fn=>{timer=fn;},clearTimeout:()=>{},_fetchCitySuggestions:(q,l,fn)=>{assert.equal(l,'ge');callback=fn;}};
 vm.createContext(c);vm.runInContext(slice(main,'function _setupCityAutocomplete','function _fetchCitySuggestions'),c);
 c._setupCityAutocomplete('tFilterFrom',{});events.input.call(input);timer();
 assert.equal(input.dataset.cityId,undefined);assert.equal(input.dataset.cityKey,undefined);
 callback([{id:1,canonical_key:'ge:tbilisi',name_ru:'Тбилиси',name_ge:'თბილისი',display_name:'"><img src=x>'}]);
 assert.match(dropdown.innerHTML,/data-city-id="1" data-city-key="ge:tbilisi"/);
 assert.match(dropdown.innerHTML,/&quot;&gt;&lt;img src=x&gt;/);assert.doesNotMatch(dropdown.innerHTML,/<img/);
 input.value='Batumi';callback([{name_ru:'Тбилиси'}]);
 assert.match(dropdown.innerHTML,/ge:tbilisi/); // A late response cannot overwrite the newer draft.
});

test('/ka/ direct entry overrides a saved Russian preference before the first render',()=>{
 for(const pathname of ['/ka','/ka/']){
  const calls=[],c={location:{pathname},localStorage:{getItem:()=> 'ru'},navigator:{language:'ru-RU'},
   document:{querySelector:()=>null},setLang:l=>calls.push(l)};
  vm.createContext(c);vm.runInContext(slice(main,'// Always restore a supported language','if(document.readyState'),c);
  assert.deepEqual(calls,['ge']);
 }
 assert.match(slice(main,'function setLang(l, btn)','// ──'),/documentElement\.lang=l==='ge'\?'ka':'ru'/);
});

function statsHarness(response){
 const ids=['statTrucks','statCompanies','statLoads','statUsers','statOnlineUsers','statsDataStatus'];
 const nodes=Object.fromEntries(ids.map(id=>[id,{textContent:'',title:''}]));let refresh;
 const c={document:{getElementById:id=>nodes[id]},lang:'ru',API_BASE:'https://api.test',AbortSignal,
  setInterval:fn=>{refresh=fn;},fetch:async()=>{if(response instanceof Error)throw response;return response;}};
 vm.createContext(c);vm.runInContext(api.slice(api.indexOf('// ── Public counters:')),c);
 return {nodes,refresh:()=>refresh()};
}

test('failed and malformed counter snapshots stay unknown, not fabricated zeros',async()=>{
 for(const response of [new Error('offline'),{ok:false},{ok:true,json:async()=>null},{ok:true,json:async()=>[]}]){
  const h=statsHarness(response);await settle();
  for(const id of ['statTrucks','statCompanies','statLoads','statUsers','statOnlineUsers'])assert.equal(h.nodes[id].textContent,'—');
  assert.match(h.nodes.statsDataStatus.textContent,/временно недоступны/);
 }
});

test('counter snapshot preserves real zero and labels registered profiles with the source date',async()=>{
 const h=statsHarness({ok:true,json:async()=>({online_trucks:0,registered_profiles:7,companies:99,active_loads:0,total_users:9,online_users:1,as_of:'2026-10-29T10:30:00Z'})});
 await settle();assert.equal(h.nodes.statTrucks.textContent,'0');assert.equal(h.nodes.statCompanies.textContent,'7');
 assert.equal(h.nodes.statLoads.textContent,'0');assert.match(h.nodes.statsDataStatus.textContent,/API · данные на 29.10.2026, 14:30/);
 assert.match(h.nodes.statsDataStatus.title,/не число проверенных юридических лиц/);
});
