/* Address publication through real local routers and deterministic map SDK.
 * Run node tests/browser/address_journey.cjs --spawn-server with PYTHON and
 * CARRIER_BROWSER_CHROMIUM_EXECUTABLE_PATH set. Never reuses a user profile.
 * Default port8892 is independent of the review fixture on8765.
 */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {spawn}=require('node:child_process');
const ROOT=path.resolve(process.env.CARRIER_PROFILE_REPO_ROOT||path.join(__dirname,'../..'));
const PORT=Number(process.env.CARRIER_BROWSER_PORT||8892);
assert.ok(Number.isInteger(PORT)&&PORT>=1024&&PORT<=65535);
const BASE=new URL('http://127.0.0.1:'+PORT);
const ARTIFACTS=path.resolve(process.env.ADDRESS_BROWSER_ARTIFACTS||path.join(ROOT,'artifacts/address-journey'));
const {chromium}=require(require.resolve('playwright',{paths:[ROOT,__dirname]}));
const SDK=fs.readFileSync(path.join(__dirname,'address_map_sdk.js'),'utf8');
fs.mkdirSync(ARTIFACTS,{recursive:true});
const results=[],diagnostics={productionApiAttempts:0,unexpectedExternalRequests:[],pageErrors:[],dialogs:[],mutations:[]};
let browser,server,serverError;
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function ready(){
 const deadline=Date.now()+60000;
 while(Date.now()<deadline){
  if(serverError)throw serverError;
  if(server&&server.exitCode!==null)throw Error('Address fixture exited before ready');
  try{
   const r=await fetch(new URL('/__test__/ready',BASE),{signal:AbortSignal.timeout(1500)}),d=await r.json();
   assert.equal(r.headers.get('x-carrier-test-only'),'1');
   for(const name of ['test_only','isolated_sqlite','actual_profile_routers','pilot_test','actual_location_routers','address_test','ready'])assert.equal(d[name],true,name);
   assert.equal(d.origin,BASE.origin);
   const spec=await(await fetch(new URL('/openapi.json',BASE))).json();
   for(const endpoint of ['/api/loads/','/api/transport/','/api/locations/resolve'])assert.ok(spec.paths[endpoint]?.post,'Actual route required:'+endpoint);
   assert.ok(spec.paths['/api/locations/suggest']?.get);
   diagnostics.fixture=d;return;
  }catch{await delay(250);}
 }
 throw Error('No verified isolated address fixture');
}
async function api(page,method,endpoint,body){
 assert.equal(new URL(page.url()).origin,BASE.origin);
 const out=await page.evaluate(async({origin,method,endpoint,body})=>{
  const r=await fetch(origin+endpoint,{method,headers:{Authorization:'Bearer '+localStorage.getItem('ch_token'),...(body?{'Content-Type':'application/json'}:{})},body:body?JSON.stringify(body):undefined});
  return{status:r.status,marker:r.headers.get('x-carrier-test-only'),data:await r.json()};
 },{origin:BASE.origin,method,endpoint,body});
 assert.equal(out.marker,'1');return out;
}
async function clickRequest(page,selector,endpoint,method,status){
 const pending=page.waitForResponse(r=>r.url().split('?')[0]===new URL(endpoint,BASE).href&&r.request().method()===method);
 await page.locator(selector).click();const r=await pending,d=await r.json();
 assert.equal(r.headers()['x-carrier-test-only'],'1');assert.equal(r.status(),status,endpoint+':'+JSON.stringify(d));return d;
}
function day(offset){return new Date(Date.now()+offset*86400000).toISOString().slice(0,10);}
async function context(configuration,{sdk=true,reverseFails=false,reverseAddress=null,storageState}={}){
 const context=await browser.newContext({viewport:{width:configuration.width,height:configuration.height},isMobile:configuration.mobile,hasTouch:configuration.mobile,serviceWorkers:'block',locale:'ru-RU',storageState});
 await context.addInitScript(()=>localStorage.setItem('ch_lang','ru'));
 await context.route('**/*',async route=>{
  const req=route.request(),url=new URL(req.url());
  if(url.origin===BASE.origin){if(['POST','PUT','PATCH','DELETE'].includes(req.method()))diagnostics.mutations.push({method:req.method(),path:url.pathname});return route.continue();}
  if(url.hostname==='api-production-f3ea.up.railway.app')diagnostics.productionApiAttempts++;
  if(url.hostname==='api-maps.yandex.ru'&&url.pathname.startsWith('/2.1/')){
   if(sdk)return route.fulfill({status:200,contentType:'application/javascript',body:SDK.replace('__REVERSE_FAILS__',String(reverseFails)).replace('__MAP_SCALE__','0.005').replace('__REVERSE_ADDRESS__',JSON.stringify(reverseAddress))});
   return route.abort('blockedbyclient');
  }
  diagnostics.unexpectedExternalRequests.push(url.hostname);return route.abort('blockedbyclient');
 });
 const page=await context.newPage();page.setDefaultTimeout(15000);page.on('pageerror',error=>diagnostics.pageErrors.push({viewport:configuration.name,error:error.message}));
 page.on('dialog',async dialog=>{diagnostics.dialogs.push(dialog.message());await dialog.dismiss();});
 return{context,page};
}
async function register(page,configuration){
 await page.goto(BASE.href,{waitUntil:'domcontentloaded'});await page.locator('#btnReg').click();await page.locator('#rtCarrier').click();
 await page.locator('#regName').fill('Isolated address '+configuration.name);
 await page.locator('#regPhone').fill(configuration.mobile?'+995599930002':'+995599930001');
 await page.locator('#regEmail').fill('address.'+configuration.name+'.'+Date.now()+'@example.test');
 await page.locator('#regInn').fill('404123456');await page.locator('#regOrgType').selectOption('ООО');await page.locator('#regCity').fill('Тбилиси');
 await page.locator('#regTruckType').selectOption('tent');await page.locator('#regTonnage').fill('10');await page.locator('#regPass').fill('AddressBrowser39!');await page.locator('#regAgree').check();
 const d=await clickRequest(page,'#formRegister button[onclick="doRegister()"]','/api/auth/register','POST',200);
 await page.locator('#authOverlay').waitFor({state:'hidden'});return d.user_id;
}
async function openCargo(page,configuration){await page.locator((configuration.mobile?'.bitem':'.nav-tab')+'[onclick*="showSection(\'loads\'"]').first().click();await page.locator('#sec-loads.active').waitFor({state:'visible'});await page.locator(configuration.mobile?'.bitem-post':'.load-post-btn').click();await page.locator('#postOverlay').waitFor({state:'visible'});}
async function fillCargo(page,label){await page.locator('#pToAddr').fill('Тбилиси');await page.locator('#pWeight').fill('1500');await page.locator('#pPrice').fill('350');await page.locator('#pTruck').selectOption('evacuator');await page.locator('#pDate').fill(day(1));await page.locator('#pDate2').fill(day(3));await page.locator('#pDesc').fill(label);}
async function saveCargo(page){const d=await clickRequest(page,'#postOverlay .btn-primary','/api/loads/','POST',200);await page.locator('#postSuccess').waitFor({state:'visible'});await page.locator('#postOverlay').waitFor({state:'hidden'});return d;}
async function chooseSuggestion(page,field,query,text){
 await page.locator('#'+field).fill(query);
 const drop=field==='pFromAddr'?'#dropPFrom':field==='pToAddr'?'#dropPTo':field==='ptFrom'?'#dropPtFrom':'#dropPtTo';
 const option=page.locator(drop+' .addr-item').filter({hasText:text}).first();
 await option.waitFor({state:'visible'});await option.click();
 await page.waitForFunction(id=>document.getElementById(id).getAttribute('aria-busy')!=='true',field);
}
async function openPicker(page,field){await page.locator('[data-location-field="'+field+'"]').click();await page.locator('#locationPickerOverlay').waitFor({state:'visible'});await page.locator('#locationPickerMap [data-test-map-surface]').waitFor({state:'visible'});}

async function renameCatalogPoint(page,field,label){
 await openPicker(page,field);await page.locator('#locationPickerLabel').fill(label);
 await page.screenshot({path:path.join(ARTIFACTS,'checkpoint-label-picker-'+Date.now()+'.png')});
 await page.locator('#locationPickerConfirm').click();await page.locator('#locationPickerOverlay').waitFor({state:'hidden'});
 assert.equal(await page.locator('#'+(field==='pFrom'?'pFromAddr':'ptFrom')).inputValue(),label);
}

async function choosePin(page,configuration,label){
 const surface=page.locator('#locationPickerMap [data-test-map-surface]'),box=await surface.boundingBox();assert.ok(box);
 if(configuration.mobile){await page.mouse.move(box.x+box.width*.5,box.y+box.height*.5);await page.mouse.down();await page.mouse.move(box.x+box.width*.5+4,box.y+box.height*.5+4,{steps:4});await page.mouse.up();}
 else await surface.click({position:{x:box.width*.5+4,y:box.height*.5-4}});
 await page.locator('#locationPickerLabel').fill(label);
 await page.screenshot({path:path.join(ARTIFACTS,configuration.name+'-'+label.replace(/[^a-z0-9]/gi,'_')+'-picker.png')});
 const pending=page.waitForResponse(r=>r.url().split('?')[0]===new URL('/api/locations/resolve',BASE).href&&r.request().method()==='POST');
 await page.locator('#locationPickerConfirm').click();const r=await pending,d=await r.json();assert.equal(r.status(),200,JSON.stringify(d));assert.equal(r.headers()['x-carrier-test-only'],'1');
 await page.locator('#locationPickerOverlay').waitFor({state:'hidden'});assert.equal(d.location.label,label);return d.location;
}
async function ownCargo(page,id){const r=await api(page,'GET','/api/loads/my/loads');assert.equal(r.status,200);const row=r.data.loads.find(x=>x.id===id);assert.ok(row);return row;}
async function editCargo(page,configuration,id,label){
 await page.locator((configuration.mobile?'.bitem':'.nav-tab')+'[onclick*="showSection(\'orders\'"]').first().click();
 await page.locator('.cab-tab[onclick*="switchCabTab(\'loads\'"]').first().click();
 await page.locator('button[onclick="editMyLoad('+id+')"]').first().click();await page.locator('#postOverlay').waitFor({state:'visible'});
 await page.waitForFunction(value=>document.getElementById('pDesc').value===value,label);
 await openPicker(page,'pFrom');
 const center=JSON.parse(await page.locator('#locationPickerMap').getAttribute('data-test-map-center'));
 await page.locator('#locationPickerLabel').fill(label+' edited');
 const saved=await choosePin(page,configuration,label+' edited');
 const result=await clickRequest(page,'#postOverlay .btn-primary','/api/loads/'+id,'PUT',200);await page.locator('#postOverlay').waitFor({state:'hidden'});return{center,saved,result};
}



async function nearbyCheckpointCargo(page,configuration){
 await openCargo(page,configuration);await page.locator('#pFromAddr').fill('');await openPicker(page,'pFrom');
 const catalogue=await api(page,'GET','/api/locations/suggest?q=Dariali');assert.equal(catalogue.status,200);const cp=catalogue.data.results.find(row=>row.key==='ge:dariali-checkpoint');assert.ok(cp);
 const center=JSON.parse(await page.locator('#locationPickerMap').getAttribute('data-test-map-center'));assert.ok(Math.abs(center[0]-cp.lat)>.1,'Picker starts on neutral map, not selected checkpoint');
 const surface=page.locator('#locationPickerMap [data-test-map-surface]'),box=await surface.boundingBox();assert.ok(box);
 const scale=Number(await page.locator('#locationPickerMap').getAttribute('data-test-map-scale')),target=[cp.lat+.00036,cp.lon];
 const start={x:box.x+box.width*.5,y:box.y+box.height*.25},dx=(center[1]-target[1])/scale,dy=(target[0]-center[0])/scale;
 await page.mouse.move(start.x,start.y);await page.mouse.down();await page.mouse.move(start.x+dx,start.y+dy,{steps:12});await page.mouse.up();
 if(!configuration.mobile)await surface.click({position:{x:box.width*.5,y:box.height*.5}});
 const nearby=page.locator('#locationPickerNearby button[data-nearby-location-key="ge:dariali-checkpoint"]');await nearby.waitFor({state:'visible'});
 const label='КПП Дарьял, место погрузки '+configuration.name;await page.locator('#locationPickerLabel').fill(label);
 const resolveBefore=diagnostics.mutations.filter(x=>x.path==='/api/locations/resolve').length;
 await nearby.click();const chosen=JSON.parse(await page.locator('#locationPickerMap').getAttribute('data-test-map-center'));assert.deepEqual(chosen,[cp.lat,cp.lon]);
 await page.screenshot({path:path.join(ARTIFACTS,configuration.name+'-nearby-checkpoint-picker.png')});
 await page.locator('#locationPickerConfirm').click();await page.locator('#locationPickerOverlay').waitFor({state:'hidden'});
 assert.equal(diagnostics.mutations.filter(x=>x.path==='/api/locations/resolve').length,resolveBefore,'Known explicit checkpoint must not need ambiguous reverse-country resolve');
 await fillCargo(page,'Address checkpoint '+configuration.name);const saved=await saveCargo(page);assert.equal(saved.from_location.key,cp.key);assert.equal(saved.from_location.lat,cp.lat);assert.equal(saved.from_location.lon,cp.lon);return saved;
}

async function warehouseWithPendingGuard(page,configuration){
 await openCargo(page,configuration);await fillCargo(page,'Address warehouse '+configuration.name);
 await page.locator('#pFromAddr').fill('склад тест');
 const option=page.locator('#dropPFrom .addr-item').filter({hasText:'Складская'}).first();await option.waitFor({state:'visible'});
 const routePattern='**/api/locations/resolve';const delayed=async route=>{await delay(1000);await route.continue();};await page.route(routePattern,delayed);
 try{
  const before=diagnostics.mutations.filter(x=>x.method==='POST'&&x.path==='/api/loads/').length;
  await option.click();assert.equal(await page.locator('#pFromAddr').getAttribute('aria-busy'),'true');
  await page.locator('#postOverlay .btn-primary').click();await delay(180);
  assert.equal(diagnostics.mutations.filter(x=>x.method==='POST'&&x.path==='/api/loads/').length,before,'Pending address must not send a raw/ghost publication');
  await page.waitForFunction(()=>document.getElementById('pFromAddr').getAttribute('aria-busy')!=='true');
  const saved=await saveCargo(page);assert.equal(saved.from,'Тбилиси');assert.match(saved.from2,/Складская/);assert.equal(saved.from_location.lat,41.708123);assert.equal(saved.from_location.lon,44.812345);
  return{kind:'warehouse',id:saved.id,pendingSubmitBlocked:true,location:saved.from_location};
 }finally{await page.unroute(routePattern,delayed);}
}

async function transportPoint(page,configuration){
 await page.locator((configuration.mobile?'.bitem':'.nav-tab')+'[onclick*="showSection(\'trucks\'"]').first().click();
 await page.locator('#btnOfferTransport').click();await page.locator('#postTransportOverlay').waitFor({state:'visible'});
 await openPicker(page,'ptFrom');const point=await choosePin(page,configuration,'Transport pin '+configuration.name);
 for(const[id,value]of Object.entries({ptTo:'Батуми',ptCapacity:'10000',ptDateFrom:day(1),ptDateTo:day(3),ptPrice:'500',ptNotes:'Address QA transport '+configuration.name}))await page.locator('#'+id).fill(value);
 await page.locator('#ptTruckType').selectOption('tent');
 const created=await clickRequest(page,'#postTransportOverlay .btn-primary','/api/transport/','POST',201);await page.locator('#postTransportOverlay').waitFor({state:'hidden'});
 assert.equal(created.offer.from_location.label,point.label);assert.equal(created.offer.from_location.lat,point.lat);assert.equal(created.offer.from_location.lon,point.lon);assert.equal(created.offer.route_scope,'local');
 await page.reload({waitUntil:'domcontentloaded'});await page.locator('#userAvatar').waitFor({state:'visible'});
 const mine=await api(page,'GET','/api/transport/my');assert.equal(mine.status,200);const row=mine.data.offers.find(x=>x.id===created.offer.id);assert.ok(row);assert.deepEqual(row.from_location,created.offer.from_location);
 return{kind:'transport_pin',id:created.offer.id,persisted:true,location:row.from_location};
}

async function transportInternational(page,configuration){
 await page.locator('#sIntl').click();await page.locator('#btnOfferTransport').click();await page.locator('#postTransportOverlay').waitFor({state:'visible'});
 await chooseSuggestion(page,'ptFrom','Дарьял',/Дар|დარ|Darial/i);await chooseSuggestion(page,'ptTo','Верхний Ларс',/Ларс|Lars/i);
 for(const[id,value]of Object.entries({ptCapacity:'10000',ptDateFrom:day(1),ptDateTo:day(3),ptPrice:'500',ptNotes:'International checkpoint '+configuration.name}))await page.locator('#'+id).fill(value);
 await page.locator('#ptTruckType').selectOption('tent');const created=await clickRequest(page,'#postTransportOverlay .btn-primary','/api/transport/','POST',201);await page.locator('#postTransportOverlay').waitFor({state:'hidden'});
 const offer=created.offer;assert.equal(offer.from_location.key,'ge:dariali-checkpoint');assert.equal(offer.to_location.key,'ru:upper-lars-checkpoint');assert.equal(offer.route_scope,'intl');
 for(const scope of ['local','intl']){const r=await api(page,'GET','/api/transport/?scope='+scope+'&from_city='+encodeURIComponent('Dariali'));assert.equal(r.status,200);assert.equal(r.data.offers.some(row=>row.id===offer.id),scope==='intl');}
 await page.locator('#sLocal').click();
 return{kind:'international_checkpoints',id:offer.id,route_scope:offer.route_scope,from_country:offer.from_country_iso,to_country:offer.to_country_iso};
}

async function providerFailure(configuration,storageState){
 const env=await context(configuration,{reverseFails:true,storageState});
 try{const page=env.page;await page.goto(BASE.href,{waitUntil:'domcontentloaded'});await page.locator('#userAvatar').waitFor({state:'visible'});await openCargo(page,configuration);await openPicker(page,'pFrom');
  const label='Reverse unavailable '+configuration.name,point=await choosePin(page,configuration,label);await fillCargo(page,label);const created=await saveCargo(page);
  assert.equal(created.from_location.label,label);assert.equal(created.from_location.lat,point.lat);assert.equal(created.from_location.lon,point.lon);
  return{kind:'reverse_provider_unavailable',id:created.id,persisted:true};
 }finally{await env.context.close();}
}
async function mapUnavailable(configuration,storageState){
 const env=await context(configuration,{sdk:false,storageState});
 try{const page=env.page;await page.goto(BASE.href,{waitUntil:'domcontentloaded'});await page.locator('#userAvatar').waitFor({state:'visible'});await openCargo(page,configuration);
  const started=Date.now();await chooseSuggestion(page,'pFromAddr','Dariali',/Дар|დარ|Darial/i);const elapsed=Date.now()-started;
  await fillCargo(page,'SDK unavailable '+configuration.name);const created=await saveCargo(page);assert.equal(created.from_location.kind,'border_checkpoint');
  return{kind:'map_sdk_unavailable_catalog_works',id:created.id,catalogSuggestionMs:elapsed};
 }finally{await env.context.close();}
}


// Focused regression: reverse address becomes the unedited label, while a custom
// label typed before the delayed reverse result must remain unchanged.
async function reverseAddressLabelJourney(configuration,storageState){
 const address='Грузия, Тбилиси, улица Серго Закариадзе, 5';
 const env=await context(configuration,{reverseAddress:address,storageState});
 const cases=[];
 try{
  const page=env.page;await page.goto(BASE.href,{waitUntil:'domcontentloaded'});await page.locator('#userAvatar').waitFor({state:'visible'});
  for(const custom of [false,true]){
   await openCargo(page,configuration);await fillCargo(page,'Reverse address label '+configuration.name+' '+custom);
   await page.locator('#pFromAddr').fill('');await openPicker(page,'pFrom');
   const target=[41.708123+(custom ? 0.0001 : 0),44.812345+(custom ? 0.0001 : 0)];
   const surface=page.locator('#locationPickerMap [data-test-map-surface]'),box=await surface.boundingBox();assert.ok(box);
   const center=JSON.parse(await page.locator('#locationPickerMap').getAttribute('data-test-map-center'));
   const scale=Number(await page.locator('#locationPickerMap').getAttribute('data-test-map-scale'));
   const start={x:box.x+box.width*.5,y:box.y+box.height*.25},dx=(center[1]-target[1])/scale,dy=(target[0]-center[0])/scale;
   await page.mouse.move(start.x,start.y);await page.mouse.down();await page.mouse.move(start.x+dx,start.y+dy,{steps:12});await page.mouse.up();
   await surface.click({position:{x:box.width*.5,y:box.height*.5}});
   const chosen=JSON.parse(await page.locator('#locationPickerMap').getAttribute('data-test-map-center'));
   assert.ok(Math.abs(chosen[0]-target[0])<.01&&Math.abs(chosen[1]-target[1])<.01,'Test gesture must select the intended Tbilisi area');
   const expectedLabel=custom?'Мой въезд к складу '+configuration.name:address;
   if(custom)await page.locator('#locationPickerLabel').fill(expectedLabel);
   await page.waitForFunction(expected=>document.getElementById('locationPickerAddress').textContent===expected,address);
   assert.equal(await page.locator('#locationPickerLabel').inputValue(),expectedLabel,'Reverse result must fill only an unedited label');
   await page.screenshot({path:path.join(ARTIFACTS,configuration.name+'-reverse-'+(custom?'custom':'automatic')+'-label.png')});
   const resolution=await clickRequest(page,'#locationPickerConfirm','/api/locations/resolve','POST',200);
   await page.locator('#locationPickerOverlay').waitFor({state:'hidden'});
   assert.equal(resolution.location.label,expectedLabel);assert.equal(resolution.location.address,address);
   assert.equal(await page.locator('#pFromAddr').inputValue(),expectedLabel,'Confirmed point must fill the main form');
   const posting=page.waitForResponse(response=>response.url().split('?')[0]===new URL('/api/loads/',BASE).href&&response.request().method()==='POST');
   const created=await saveCargo(page),response=await posting,payload=response.request().postDataJSON();
   for(const location of [payload.from_location,created.from_location]){
    assert.equal(location.label,expectedLabel);assert.equal(location.address,address);assert.ok(Math.abs(location.lat-chosen[0])<1e-8);assert.ok(Math.abs(location.lon-chosen[1])<1e-8);
   }
   assert.equal(payload.from_address,address);assert.equal(created.from_country_iso,'GE');
   await page.reload({waitUntil:'domcontentloaded'});await page.locator('#userAvatar').waitFor({state:'visible'});
   const stored=await ownCargo(page,created.id);assert.deepEqual(stored.from_location,created.from_location);
   await page.locator((configuration.mobile?'.bitem':'.nav-tab')+'[onclick*="showSection(\'orders\'"]').first().click();
   await page.locator('.cab-tab[onclick*="switchCabTab(\'loads\'"]').first().click();
   await page.locator('button[onclick="editMyLoad('+created.id+')"]').first().click();await page.locator('#postOverlay').waitFor({state:'visible'});
   await page.waitForFunction(expected=>document.getElementById('pFromAddr').value===expected,expectedLabel);
   assert.equal(await page.locator('#pFromAddr').inputValue(),expectedLabel,'Reloaded edit form must retain the confirmed label');
   await page.locator('#postOverlay .close-btn').click();await page.locator('#postOverlay').waitFor({state:'hidden'});
   // These newly-created disposable records have no deals. Withdraw them after
   // verifying persistence so the unchanged Free5 quota remains tested normally.
   const withdrawn=await api(page,'DELETE','/api/loads/'+created.id);assert.equal(withdrawn.status,200);assert.equal(withdrawn.data.ok,true);
   cases.push({kind:custom?'reverse_address_custom_label_preserved':'reverse_address_auto_label',id:created.id,persisted:true,mainFormFilled:true,postPayloadVerified:true,reloadedEditLabelVerified:true,withdrawnAfterVerification:true,selectedPoint:chosen,label:expectedLabel,address,location:stored.from_location});
  }
  return cases;
 }finally{await env.context.close();}
}

async function run(configuration){
 const env=await context(configuration),{page}=env;
 try{
  const userId=await register(page,configuration);const out={viewport:configuration.name,userId,scenarios:[]};
  // The own checkpoint catalog must work in RU/EN/KA without relying on map POIs.
  const keys=[];for(const q of ['Дарьял','Dariali','დარიალი']){const r=await api(page,'GET','/api/locations/suggest?q='+encodeURIComponent(q));assert.equal(r.status,200);const rows=r.data.locations||r.data.results;assert.ok(Array.isArray(rows));const cp=rows.find(x=>x.kind==='border_checkpoint'&&x.country_iso==='GE');assert.ok(cp,'Dariali suggestion '+q);keys.push(cp.key);}assert.equal(new Set(keys).size,1);
  const checkpoint=await nearbyCheckpointCargo(page,configuration);assert.equal(checkpoint.from_location.kind,'border_checkpoint');assert.equal(checkpoint.from_location.key,keys[0]);assert.equal(checkpoint.from_location.label,'КПП Дарьял, место погрузки '+configuration.name);assert.equal(checkpoint.route_scope||checkpoint.scope,'local');out.scenarios.push({kind:'checkpoint',id:checkpoint.id,key:keys[0],aliases:3,customLabelPreserved:true,nearbyExplicitChoice:true});console.log(configuration.name+': checkpoint RU/EN/KA + Local publish passed');
  out.scenarios.push(await warehouseWithPendingGuard(page,configuration));console.log(configuration.name+': full warehouse address + canonical city + exactpoint + pending guard passed');
  await openCargo(page,configuration);const beforeCancel=await page.locator('#pFromAddr').inputValue();await openPicker(page,'pFrom');await page.locator('#locationPickerCancel').click();await page.locator('#locationPickerOverlay').waitFor({state:'hidden'});assert.equal(await page.locator('#pFromAddr').inputValue(),beforeCancel);await openPicker(page,'pFrom');const pinLabel='Isolated pin '+configuration.name;const pin=await choosePin(page,configuration,pinLabel);await fillCargo(page,pinLabel);const pointLoad=await saveCargo(page);assert.equal(pointLoad.from_location.label,pinLabel);assert.equal(pointLoad.from_location.lat,pin.lat);assert.equal(pointLoad.from_location.lon,pin.lon);assert.equal(pointLoad.from_location.settlement_id,null);assert.equal(pointLoad.route_scope||pointLoad.scope,'local');
  await page.reload({waitUntil:'domcontentloaded'});await page.locator('#userAvatar').waitFor({state:'visible'});const persisted=await ownCargo(page,pointLoad.id);assert.deepEqual(persisted.from_location,pointLoad.from_location);const edited=await editCargo(page,configuration,pointLoad.id,pinLabel);assert.deepEqual(edited.center,[pin.lat,pin.lon]);assert.equal(edited.result.from_location.label,pinLabel+' edited');assert.equal(edited.result.from_location.lat,edited.saved.lat);assert.equal(edited.result.from_location.lon,edited.saved.lon);out.scenarios.push({kind:'arbitrary_pin',id:pointLoad.id,persisted:true,edited:true,cancelUnchanged:true,location:edited.result.from_location});console.log(configuration.name+': map exactpoint publish, reload, cancel and edit passed');
  out.scenarios.push(await transportPoint(page,configuration));out.scenarios.push(await transportInternational(page,configuration));
  const storage=await env.context.storageState();out.scenarios.push(...await reverseAddressLabelJourney(configuration,storage));console.log(configuration.name+': reverse-address autofill and custom-label preservation publish/reload passed');out.scenarios.push(await providerFailure(configuration,storage));out.scenarios.push(await mapUnavailable(configuration,storage));
  await page.getByRole('button',{name:'GE',exact:true}).click();await openCargo(page,configuration);await openPicker(page,'pFrom');
  assert.equal(await page.locator('#locationPickerTitle').textContent(),'გაგზავნის ადგილი');assert.equal(await page.locator('#locationPickerConfirm').textContent(),'ამ წერტილის არჩევა');
  await page.screenshot({path:path.join(ARTIFACTS,configuration.name+'-georgian-picker.png')});await page.locator('#locationPickerCancel').click();out.georgianPicker=true;

  await page.screenshot({path:path.join(ARTIFACTS,configuration.name+'-address-results.png'),fullPage:true});results.push({...out,status:'passed'});console.log(configuration.name+': transport points, Local/Intl and providerfailure cases passed');
 }catch(error){await page.screenshot({path:path.join(ARTIFACTS,configuration.name+'-failure.png'),fullPage:true}).catch(()=>{});results.push({viewport:configuration.name,status:'failed',error:error.message});throw error;}
 finally{await env.context.close();}
}
(async()=>{try{
 if(process.argv.includes('--spawn-server')){const log=fs.createWriteStream(path.join(ARTIFACTS,'server.log'));server=spawn(process.env.PYTHON||'python',[path.join(ROOT,'tests/browser/carrier_profile_server.py')],{cwd:ROOT,env:{...process.env,PYTHONUNBUFFERED:'1',CARRIER_PROFILE_REPO_ROOT:ROOT,CARRIER_BROWSER_PORT:String(PORT),CARRIER_BROWSER_TEMP_ROOT:path.join(ARTIFACTS,'.fixture'),CARRIER_BROWSER_PUBLICATION:'1',CARRIER_BROWSER_PILOT:'1',CARRIER_BROWSER_ADDRESS:'1',CARRIER_BROWSER_NOTIFICATIONS:'0',CARRIER_BROWSER_AUTH:'0'},stdio:['ignore','pipe','pipe']});server.stdout.pipe(log,{end:false});server.stderr.pipe(log,{end:false});server.once('error',e=>serverError=e);server.once('close',()=>log.end());}
 await ready();browser=await chromium.launch({headless:true,executablePath:process.env.CARRIER_BROWSER_CHROMIUM_EXECUTABLE_PATH||undefined,args:['--disable-background-networking','--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1']});
 for(const configuration of [{name:'desktop',width:1280,height:900,mobile:false},{name:'mobile',width:390,height:844,mobile:true}])try{await run(configuration);}catch(error){console.error(error.stack||error);process.exitCode=1;}
 assert.equal(diagnostics.productionApiAttempts,0);assert.equal(diagnostics.pageErrors.length,0);assert.equal(diagnostics.dialogs.length,0);
}catch(error){console.error(error.stack||error);process.exitCode=1;}finally{if(browser)await browser.close().catch(()=>{});if(server&&server.exitCode===null)server.kill();fs.writeFileSync(path.join(ARTIFACTS,'results.json'),JSON.stringify({results,diagnostics},null,2));}})();
