/* Separate localhost-only trade journey. Not part of the carrier-profile release job.
 * Run after a checkout includes tests/browser/carrier_profile_server.py:
 * CARRIER_PROFILE_REPO_ROOT=/path/to/checkout node publication_journey.cjs --spawn-server
 * --audit-contacts records the known UI gap without claiming contacts passed.
 */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {spawn}=require('node:child_process');
const BASE=new URL('http://127.0.0.1:8765');
const ROOT=path.resolve(process.env.CARRIER_PROFILE_REPO_ROOT||path.join(__dirname,'../..'));
const {chromium}=require(require.resolve('playwright',{paths:[ROOT,__dirname]}));
const ARTIFACTS=path.resolve(process.env.CARRIER_PUBLICATION_ARTIFACTS||path.join(ROOT,'artifacts/publication-journey'));
const auditContacts=process.argv.includes('--audit-contacts');
const completionEnabled=process.env.CARRIER_BROWSER_COMPLETION==='1';
const results=[],diagnostics={productionApiAttempts:0,blockedHosts:[],pages:[],mutations:[]};
const blocked=new Set();
let browser,server,serverError;
fs.mkdirSync(ARTIFACTS,{recursive:true});
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));

async function ready(){
 const deadline=Date.now()+60000;
 while(Date.now()<deadline){
  if(serverError)throw serverError;
  if(server&&server.exitCode!==null)throw Error('Local publication fixture exited');
  try{
   const r=await fetch(new URL('/__test__/ready',BASE),{signal:AbortSignal.timeout(1000)});
   const data=await r.json();
   assert.equal(r.headers.get('x-carrier-test-only'),'1');
   assert.equal(data.test_only,true);assert.equal(data.isolated_sqlite,true);
   assert.equal(data.actual_profile_routers,true);assert.equal(data.origin,BASE.origin);assert.equal(data.ready,true);
   const spec=await(await fetch(new URL('/openapi.json',BASE))).json();
   for(const endpoint of ['/api/loads/','/api/transport/','/api/responses/load/{load_id}','/api/transport-requests/{req_id}/accept'])
    assert.ok(spec.paths[endpoint]?.post,'Opt-in real trade router required: '+endpoint);
   return;
  }catch{await delay(250);}
 }
 throw Error('No verified isolated publication fixture with real trade routers');
}
async function clickRequest(page,selector,endpoint,method,status){
 const pending=page.waitForResponse(r=>r.url().split('?')[0]===new URL(endpoint,BASE).href&&r.request().method()===method);
 await page.locator(selector).click();
 const r=await pending,data=await r.json();
 assert.equal(r.status(),status,endpoint+': '+JSON.stringify(data));
 assert.equal(r.headers()['x-carrier-test-only'],'1');
 return data;
}
async function readApi(page,endpoint){
 const r=await page.evaluate(async({origin,endpoint})=>{
  const response=await fetch(origin+endpoint,{headers:{Authorization:'Bearer '+localStorage.getItem('ch_token')}});
  return{status:response.status,marker:response.headers.get('x-carrier-test-only'),data:await response.json()};
 },{origin:BASE.origin,endpoint});
 assert.equal(r.status,200,endpoint);assert.equal(r.marker,'1');return r.data;
}
async function register(page,role,label,number){
 await page.goto(BASE.href,{waitUntil:'domcontentloaded'});
 await page.locator('#btnReg').click();
 await page.locator(role==='carrier'?'#rtCarrier':'#rtShipperCo').click();
 const email='journey.'+label+'.'+Date.now()+'@example.test';
 await page.locator('#regName').fill('Isolated '+label);
 await page.locator('#regPhone').fill('+9955999200'+String(number).padStart(2,'0'));
 await page.locator('#regEmail').fill(email);
 await page.locator('#regInn').fill('404123456');
 await page.locator('#regOrgType').selectOption('ООО');
 await page.locator('#regCity').fill('Тбилиси');
 if(role==='carrier'){
  await page.locator('#regTruckType').selectOption('tent');
  await page.locator('#regTonnage').fill('10');
 }
 await page.locator('#regPass').fill('PublicationBrowser39!');
 assert.equal(new URL(page.url()).origin,BASE.origin);
 await page.locator('#regAgree').check();
 const data=await clickRequest(page,'#formRegister button[onclick="doRegister()"]','/api/auth/register','POST',200);
 await page.locator('#authOverlay').waitFor({state:'hidden'});
 const profile=await readApi(page,'/api/users/me');
 assert.equal(profile.id,data.user_id);
 return{...profile,email};
}
async function tab(page,configuration,name){
 const selector=(configuration.mobile?'.bitem':'.nav-tab')+'[onclick*="showSection(\''+name+'\'"]';
 await page.locator(selector).first().click();
 await page.locator('#sec-'+(name==='orders'?'orders':name)+'.active').waitFor({state:'visible'});
}
async function cabinetTab(page,configuration,name){
 await tab(page,configuration,'orders');
 await page.locator('.cab-tab[onclick*="switchCabTab(\''+name+'\'"]').first().click();
 await page.locator('#cabTab-'+name).waitFor({state:'visible'});
}
function day(offset){
 const d=new Date(Date.now()+offset*86400000);
 return d.toISOString().slice(0,10);
}
async function publishLoad(page,configuration,label){
 const button=configuration.mobile?'.bitem-post':'.load-post-btn';
 await page.locator(button).click();
 await page.locator('#postOverlay').waitFor({state:'visible'});
 await page.locator('#pFromAddr').fill('Тбилиси');
 await page.locator('#pToAddr').fill('Батуми');
 await page.locator('#pWeight').fill('3000');
 await page.locator('#pPrice').fill('500');
 await page.locator('#pTruck').selectOption('tent');
 await page.locator('#pDate').fill(day(1));
 await page.locator('#pDate2').fill(day(3));
 await page.locator('#pDesc').fill(label);
 const load=await clickRequest(page,'#postOverlay .btn-primary','/api/loads/','POST',200);
 assert.ok(load.id);
 await page.locator('#postSuccess').waitFor({state:'visible'});
 await page.locator('#postOverlay').waitFor({state:'hidden'});
 const mine=await readApi(page,'/api/loads/my/loads');
 assert.ok(mine.loads.some(row=>row.id===load.id));
 return load;
}
async function searchLoadAndRespond(page,configuration,load,label){
 await page.reload({waitUntil:'domcontentloaded'});
 await page.locator('#userAvatar').waitFor({state:'visible'});
 await page.locator('#fFrom').click();
 await page.locator('#fFrom').fill('თბილისი');
 await page.locator('#fTo').click();
 await page.locator('#fTo').fill('Батуми');
 await page.locator('#fType').selectOption('tent');
 await page.locator('#loadSearchBtn').click();
 const card=page.locator('#cargoList .card-load').first();
 await card.waitFor({state:'visible'});await card.click();
 await page.locator('#cargoOverlay').waitFor({state:'visible'});
 await page.locator('#mDesc').filter({hasText:label}).waitFor({state:'visible'});
 assert.equal(await page.locator('#mOwnerContacts a[href^="tel:"]:visible').count(),0);
 await page.locator('#respondPrice').fill('500');
 const response=await clickRequest(page,'#btnRespond','/api/responses/load/'+load.id,'POST',200);
 assert.ok(response.response_id);
 await page.locator('#respondSuccess').waitFor({state:'visible'});
 await page.locator('#cargoOverlay button.close-btn').click();
 return response;
}
async function dealContactCheck(page,configuration,dealId,counterparty){
 await cabinetTab(page,configuration,'deals');
 const data=await readApi(page,'/api/deals/my');
 const deal=data.deals.find(row=>row.id===dealId);assert.ok(deal,'Accepted deal must exist');
 assert.equal(deal.load_from,'Тбилиси');assert.equal(deal.load_to,'Батуми');assert.equal(deal.load_kg,3000);
 const card=page.locator('#myDealsList .cab-deal-card').filter({hasText:deal.deal_number}).first();
 await card.waitFor({state:'visible'});
 const wantedPhone='tel:'+String(counterparty.phone).replace(/[^\d+]/g,'');
 const phones=await card.locator('a[href^="tel:"]').evaluateAll(nodes=>nodes.map(n=>({href:n.getAttribute('href'),visible:!!n.getClientRects().length})));
 const emails=await card.locator('a[href^="mailto:"]').evaluateAll(nodes=>nodes.map(n=>({href:n.getAttribute('href'),visible:!!n.getClientRects().length})));
 const phoneVisible=phones.some(link=>link.visible&&link.href===wantedPhone);
 const emailVisible=emails.some(link=>link.visible&&decodeURIComponent(link.href.slice(7))===counterparty.email);
 if(!auditContacts){assert.ok(phoneVisible,'Accepted deal must show counterparty phone');assert.ok(emailVisible,'Accepted deal must show counterparty email');}
 return{phoneVisible,emailVisible,dealId,source:deal.deal_source};
}
async function cargoPath(shipper,carrier,configuration,accounts,label){
 const load=await publishLoad(shipper,configuration,label);
 const response=await searchLoadAndRespond(carrier,configuration,load,label);
 await cabinetTab(shipper,configuration,'loads');
 const card=shipper.locator('#myLoadsList .cab-load-card').first();
 await card.locator('.cab-accept-btn').waitFor({state:'visible'});
 assert.equal(await card.locator('a[href^="tel:"]:visible').count(),0,'No phone before acceptance');
 const accepted=await clickRequest(shipper,'#myLoadsList .cab-accept-btn','/api/responses/accept/'+response.response_id,'POST',200);
 assert.ok(accepted.deal_id);
 // Existing accepted-response path also exposes the carrier phone to the shipper.
 await cabinetTab(shipper,configuration,'loads');
 await card.locator('a[href^="tel:"]').waitFor({state:'visible'});
 const contacts=[
  await dealContactCheck(shipper,configuration,accepted.deal_id,accounts.carrier),
  await dealContactCheck(carrier,configuration,accepted.deal_id,accounts.shipper)
 ];
 assert.ok(contacts.every(result=>result.source==='cargo'));
 return{loadId:load.id,responseId:response.response_id,contacts};
}
async function transportPath(shipper,carrier,configuration,accounts,label){
 await tab(carrier,configuration,'trucks');
 await carrier.locator('#btnOfferTransport').click();
 await carrier.locator('#postTransportOverlay').waitFor({state:'visible'});
 for(const[id,value]of Object.entries({ptFrom:'Тбилиси',ptTo:'Батуми',ptCapacity:'10000',ptDateFrom:day(1),ptPrice:'500',ptNotes:label}))
  await carrier.locator('#'+id).fill(value);
 await carrier.locator('#ptTruckType').selectOption('tent');
 const created=await clickRequest(carrier,'#postTransportOverlay .btn-primary','/api/transport/','POST',201);
 assert.ok(created.offer?.id);
 await carrier.locator('#postTransportOverlay').waitFor({state:'hidden'});
 await tab(shipper,configuration,'trucks');
 await shipper.locator('#tFilterFrom').fill('Тбилиси');
 await shipper.locator('#tFilterTo').fill('Батуми');
 await shipper.locator('#tFilterType').selectOption('tent');
 await shipper.locator('#btnFindTransport').click();
 const card=shipper.locator('#transportList .transport-card:visible, #transportList .tr-row:visible, #transportList .tr-card:visible')
  .filter({hasText:accounts.carrier.company_name}).first();
 await card.waitFor({state:'visible'});await card.click();
 await shipper.locator('#transportRequestOverlay').waitFor({state:'visible'});
 await shipper.locator('#trDesc').fill(label+' cargo');
 await shipper.locator('#trWeight').fill('3000');
 await shipper.locator('#trMsg').fill('Disposable UI request');
 const requested=await clickRequest(shipper,'#transportRequestOverlay .btn-primary','/api/transport/'+created.offer.id+'/request','POST',201);
 await shipper.locator('#transportRequestOverlay').waitFor({state:'hidden'});
 await cabinetTab(carrier,configuration,'transport-requests-in');
 const incoming=carrier.locator('#myTransportRequestsIn > div').filter({hasText:label+' cargo'}).first();
 await incoming.locator('button[onclick^="acceptTransportReq("]').waitFor({state:'visible'});
 assert.equal(await incoming.locator('a[href^="tel:"]:visible').count(),0);
 const accepted=await clickRequest(carrier,'#myTransportRequestsIn button[onclick^="acceptTransportReq("]','/api/transport-requests/'+requested.request.id+'/accept','POST',200);
 assert.ok(accepted.deal_id);
 await incoming.locator('a[href^="tel:"]').waitFor({state:'visible'});
 const contacts=[
  await dealContactCheck(shipper,configuration,accepted.deal_id,accounts.carrier),
  await dealContactCheck(carrier,configuration,accepted.deal_id,accounts.shipper)
 ];
 assert.ok(contacts.every(result=>result.source==='transport'));
 return{offerId:created.offer.id,requestId:requested.request.id,contacts};
}
async function contextPage(configuration,role){
 const context=await browser.newContext({viewport:{width:configuration.width,height:configuration.height},isMobile:configuration.mobile,hasTouch:configuration.mobile,serviceWorkers:'block',locale:'ru-RU'});
 await context.addInitScript(()=>{localStorage.setItem('ch_lang','ru');localStorage.setItem('pwa_dismissed','1');});
 await context.route('**/*',async route=>{
  const request=route.request(),url=new URL(request.url());
  if(url.origin===BASE.origin){
   if(!['GET','HEAD','OPTIONS'].includes(request.method()))diagnostics.mutations.push({method:request.method(),path:url.pathname});
   return route.continue();
  }
  blocked.add(url.hostname||url.protocol);
  if(url.hostname==='api-production-f3ea.up.railway.app')diagnostics.productionApiAttempts++;
  return route.abort('blockedbyclient');
 });
 const page=await context.newPage();page.setDefaultTimeout(15000);
 const log={viewport:configuration.name,role,pageErrors:[],dialogs:[]};diagnostics.pages.push(log);
 page.on('pageerror',error=>log.pageErrors.push(error.stack||error.message));
 page.on('dialog',async dialog=>{log.dialogs.push({type:dialog.type(),message:dialog.message()});await dialog.dismiss();});
 return{context,page,log};
}
async function run(configuration,index){
 const sh=await contextPage(configuration,'shipper'),ca=await contextPage(configuration,'carrier');
 const suffix=configuration.name+'.'+Date.now();
 try{
  const accounts={shipper:await register(sh.page,'shipper','shipper.'+suffix,index*2+1),carrier:await register(ca.page,'carrier','carrier.'+suffix,index*2+2)};
  const cargo=await cargoPath(sh.page,ca.page,configuration,accounts,'QA cargo '+suffix);
  const transport=await transportPath(sh.page,ca.page,configuration,accounts,'QA transport '+suffix);
  let completion=[];
  if(completionEnabled){
   const complete=require('./deal_completion_steps.cjs');
   for(const[source,journey,first]of[['cargo',cargo,'carrier'],['transport',transport,'shipper']]){
    completion.push(await complete({shipper:sh.page,carrier:ca.page,configuration,accounts,dealId:journey.contacts[0].dealId,source,first,readApi,cabinetTab,clickRequest,artifacts:ARTIFACTS}));
   }
  }
  for(const account of[sh,ca]){
   await account.page.screenshot({path:path.join(ARTIFACTS,configuration.name+'-'+account.log.role+'.png'),fullPage:true});
   assert.deepEqual(account.log.pageErrors,[]);assert.deepEqual(account.log.dialogs,[]);
  }
  const contactsComplete=[...cargo.contacts,...transport.contacts].every(result=>result.phoneVisible&&result.emailVisible);
  console.log(configuration.name+': cargo and transport publication, response, acceptance and both participants contacts '+(contactsComplete?'passed':'incomplete'));
  results.push({viewport:configuration.name,status:contactsComplete?'passed':'core-passed-contact-gap',contactsComplete,cargo,transport,completion});
 }catch(error){
  for(const account of[sh,ca])await account.page.screenshot({path:path.join(ARTIFACTS,configuration.name+'-'+account.log.role+'-failure.png'),fullPage:true}).catch(()=>{});
  results.push({viewport:configuration.name,status:'failed',error:error.message});throw error;
 }finally{await sh.context.close();await ca.context.close();}
}
(async()=>{
 try{
  if(process.argv.includes('--spawn-server')){
   const log=fs.createWriteStream(path.join(ARTIFACTS,'server.log'));
   server=spawn(process.env.PYTHON||'python',[path.join(ROOT,'tests/browser/carrier_profile_server.py')],{cwd:ROOT,env:{...process.env,PYTHONUNBUFFERED:'1',CARRIER_BROWSER_PUBLICATION:'1'},stdio:['ignore','pipe','pipe']});
   server.stdout.pipe(log,{end:false});server.stderr.pipe(log,{end:false});
   server.once('error',error=>{serverError=error;});server.once('close',()=>log.end());
  }
  await ready();
  browser=await chromium.launch({headless:true,args:['--disable-background-networking','--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1']});
  for(const[index,configuration]of[{name:'desktop',width:1280,height:900,mobile:false},{name:'mobile',width:390,height:844,mobile:true}].entries()){
   try{await run(configuration,index);}catch(error){console.error(error.stack||error);process.exitCode=1;}
  }
  assert.equal(diagnostics.productionApiAttempts,0,'Temporary frontend must rewrite every production API origin');
 }catch(error){console.error(error.stack||error);process.exitCode=1;}
 finally{
  if(browser)await browser.close().catch(()=>{});
  if(server&&server.exitCode===null)server.kill('SIGTERM');
  diagnostics.blockedHosts=[...blocked].sort();
  fs.writeFileSync(path.join(ARTIFACTS,'results.json'),JSON.stringify({auditContacts,results,diagnostics},null,2));
 }
})();
