/* Actual-router public profile/privacy journey; disposable localhost only.
 * node tests/browser/public_profile_journey.cjs --spawn-server
 * Optional: --seed-review against an already verified mock-map fixture on8895.
 */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{spawn}=require('node:child_process');
const ROOT=path.resolve(process.env.CARRIER_PROFILE_REPO_ROOT||path.join(__dirname,'../..'));
const PORT=Number(process.env.PUBLIC_PROFILE_BROWSER_PORT||8896);assert.ok(Number.isInteger(PORT)&&PORT>=1024&&PORT<=65535);
const BASE='http://127.0.0.1:'+PORT,ART=path.resolve(process.env.PUBLIC_PROFILE_BROWSER_ARTIFACTS||path.join(ROOT,'artifacts/public-profile-journey'));
fs.mkdirSync(ART,{recursive:true});
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms)),day=n=>new Date(Date.now()+n*86400000).toISOString().slice(0,10);
const PASSWORD='LocalProfileReview47!',PRIVATE='PRIVATE NOTE private.contact@example.test +995599001234',PUBLIC='PUBLIC TEST <img src=x onerror=alert(1)> & მადლობა public.contact@example.test +995599009876';
const diagnostics={productionAttempts:0,externalHosts:[],pageErrors:[],dialogs:[],mutations:[],profileRequests:[]},results=[];
let server,browser,readyData,setupData;
async function request(method,endpoint,body,token,status=200){
 assert.ok(endpoint.startsWith('/')&&!endpoint.includes('://'));
 const response=await fetch(BASE+endpoint,{method,redirect:'error',headers:{...(token?{Authorization:'Bearer '+token}:{}),...(body!==undefined?{'Content-Type':'application/json'}:{})},body:body===undefined?undefined:JSON.stringify(body)});
 assert.equal(response.headers.get('x-carrier-test-only'),'1');const text=await response.text();let data;try{data=JSON.parse(text);}catch{throw Error(endpoint+' returned non-JSON '+response.status);}
 if(status!==null)assert.equal(response.status,status,method+' '+endpoint+': '+JSON.stringify(data.detail||data));if(!['GET','HEAD'].includes(method))diagnostics.mutations.push({method,path:endpoint.split('?')[0]});return{status:response.status,data};
}
async function ready(){
 const deadline=Date.now()+60000;while(Date.now()<deadline){try{
  const response=await request('GET','/__test__/ready');const data=response.data;
  for(const key of['test_only','isolated_sqlite','actual_profile_routers','pilot_test','address_test','public_profile_test','ready'])assert.equal(data[key],true,key);assert.equal(data.origin,BASE);
  const spec=(await request('GET','/openapi.json')).data;assert.ok(spec.paths['/api/users/{user_id}/profile']?.get);assert.ok(spec.paths['/api/deals/{deal_id}/review-visibility']?.patch);readyData=data;return;
 }catch(error){if(server?.exitCode!==null&&server)throw error;await wait(200);}}throw Error('No verified local public-profile fixture');
}
async function account(role,label,city='Тбилиси'){
 const email='profile.'+label+'.'+Date.now()+'@example.test',company_name='[TEST] '+label+' <b>literal</b>';
 const result=await request('POST','/api/auth/register',{email,password:PASSWORD,company_name,phone:'+99559994000'+({shipper:1,carrier:2,both:3}[role]),role,lang:'ru',inn:'404123456',org_type:'ООО',city,truck_type:role==='shipper'?null:'tent',tonnage:role==='shipper'?null:10});
 return{id:result.data.user_id,token:result.data.token,email,company_name,role};
}
async function offer(owner,label){return(await request('POST','/api/transport/',{from_city:'Тбилиси',to_city:'Батуми',truck_type:'tent',capacity_kg:10000,available_from:day(1)+'T08:00:00Z',available_to:day(3)+'T08:00:00Z',price:500,notes:label},owner.token,201)).data.offer;}
async function load(owner,label){return(await request('POST','/api/loads/',{from_city:'Тбилиси',to_city:'Батуми',from_address:'Тбилиси',to_address:'Батуми',scope:'local',weight_kg:1500,truck_type:'tent',price_gel:500,cargo_desc:label,load_date:day(1)+'T12:00:00Z',load_date_end:day(3)+'T12:00:00Z'},owner.token)).data;}
async function completedDeal(shipper,carrier,label){
 const source=await offer(carrier,label),asked=await request('POST','/api/transport/'+source.id+'/request',{cargo_description:label,weight_kg:1500,price:500,message:'TEST verified local request'},shipper.token,201);
 const accepted=await request('POST','/api/transport-requests/'+asked.data.request.id+'/accept',{},carrier.token);assert.ok(accepted.data.deal_id);const id=accepted.data.deal_id;
 const first=await request('POST','/api/deals/'+id+'/confirm',{},shipper.token);assert.equal(first.data.shipper_confirmed,true);
 const second=await request('POST','/api/deals/'+id+'/confirm',{},carrier.token);assert.equal(second.data.status,'completed');assert.equal(second.data.shipper_confirmed,true);assert.equal(second.data.carrier_confirmed,true);return{id,source:source.id};
}
async function publicData(id,query=''){return(await request('GET','/api/users/'+id+'/profile'+query)).data;}
function noContactLeaks(data){
 const forbidden=new Set(['email','phone','telegram_id','telegram_username','inn','password','hashed_password','password_hash','token','deal_id','load_id','agreed_price','notes']);
 function scan(value){if(!value||typeof value!=='object')return;for(const[key,item]of Object.entries(value)){assert.equal(forbidden.has(key),false,'Public key leaked: '+key);scan(item);}}scan(data);
 const text=JSON.stringify(data);for(const marker of['private.contact@example.test','public.contact@example.test','+995599001234','+995599009876','HiddenStreet47'])assert.equal(text.includes(marker),false,'Private/contact text leaked: '+marker);
}
async function setup(){
 const shipper=await account('shipper','Shipper'),carrier=await account('carrier','Carrier'),empty=await account('both','No reviews','HiddenStreet47, gate 9');
 const deals=[];for(const viewport of['desktop','mobile'])deals.push(await completedDeal(shipper,carrier,'TEST primary '+viewport));
 for(let i=0;i<11;i++){
  const deal=await completedDeal(shipper,carrier,'TEST pagination '+i),body={score:4,comment:i===0?'LEGACY PRIVATE CANARY':'TEST public page '+i};if(i!==0)body.public_comment=i%2===1;
  const rated=await request('POST','/api/deals/'+deal.id+'/rate',body,shipper.token);assert.equal(rated.data.my_review.public_comment,i!==0&&i%2===1);
 }
 const cargo=await load(shipper,'TEST active cargo profile entry'),carrierOffer=await offer(carrier,'TEST active carrier profile entry'),emptyOffer=await offer(empty,'TEST empty public profile entry');
 return{shipper,carrier,empty,deals,cargo,carrierOffer,emptyOffer};
}
async function context(configuration){
 const ctx=await browser.newContext({viewport:{width:configuration.width,height:configuration.height},isMobile:configuration.mobile,hasTouch:configuration.mobile,locale:'ru-RU',serviceWorkers:'block'});
 await ctx.addInitScript(()=>{if(!localStorage.getItem('ch_lang'))localStorage.setItem('ch_lang','ru');});
 const sdk=fs.readFileSync(path.join(__dirname,'address_map_sdk.js'),'utf8').replace('__REVERSE_FAILS__','true').replace('__MAP_SCALE__','0.005').replace('__REVERSE_ADDRESS__','null').replace('__ROAD_METERS__','0').replace('__ROAD_FAILS__','true').replace('__REVERSE_PROFILES__','[]');
 await ctx.route('**/*',async route=>{const req=route.request(),url=new URL(req.url());
  if(url.origin===BASE){if(/\/api\/users\/\d+\/profile$/.test(url.pathname)){diagnostics.profileRequests.push({path:url.pathname,query:url.search,authorization:!!req.headers().authorization,cookie:!!req.headers().cookie});assert.equal(req.headers().authorization,undefined);assert.equal(req.headers().cookie,undefined);}return route.continue();}
  if(url.hostname==='api-production-f3ea.up.railway.app')diagnostics.productionAttempts++;
  if(url.hostname==='api-maps.yandex.ru'&&url.pathname.startsWith('/2.1/'))return route.fulfill({status:200,contentType:'application/javascript',body:sdk});diagnostics.externalHosts.push(url.hostname);return route.abort('blockedbyclient');
 });
 const page=await ctx.newPage();page.setDefaultTimeout(15000);page.on('pageerror',error=>diagnostics.pageErrors.push(error.message));page.on('dialog',async dialog=>{diagnostics.dialogs.push(dialog.message());await dialog.dismiss();});return{context:ctx,page};
}
async function tab(page,cfg,name){await page.locator((cfg.mobile?'.bitem':'.nav-tab')+'[onclick*="showSection(\''+name+'\'"]').first().click();await page.locator('#sec-'+name+'.active').waitFor({state:'visible'});}
async function login(page,actor){
 await page.goto(BASE+'/',{waitUntil:'domcontentloaded'});await page.locator('#btnLogin').click();await page.locator('#loginEmail').fill(actor.email);await page.locator('#loginPass').fill(PASSWORD);const response=page.waitForResponse(r=>r.url()===BASE+'/api/auth/login'&&r.request().method()==='POST');await page.locator('#formLogin .btn-primary').click();assert.equal((await response).status(),200);await page.locator('#authOverlay').waitFor({state:'hidden'});await page.locator('#userAvatar').waitFor({state:'visible'});
}
async function dealCard(page,cfg,id){
 await tab(page,cfg,'orders');await page.locator('.cab-tab[onclick*="switchCabTab(\'deals\'"]').first().click();
 const data=await page.evaluate(async origin=>{const r=await fetch(origin+'/api/deals/my',{headers:{Authorization:'Bearer '+localStorage.getItem('ch_token')}});return r.json();},BASE);const deal=data.deals.find(row=>row.id===id);assert.ok(deal);const card=page.locator('#myDealsList .cab-deal-card').filter({hasText:deal.deal_number}).first();await card.waitFor({state:'visible'});return card;
}
async function clickResponse(page,selector,path,method){const waiting=page.waitForResponse(r=>r.url().split('?')[0]===BASE+path&&r.request().method()===method);await page.locator(selector).click();const response=await waiting;assert.equal(response.status(),200);assert.equal(response.headers()['x-carrier-test-only'],'1');return response.json();}
async function privateReviewUI(cfg,index){
 const deal=setupData.deals[index],out=[];
 for(const role of['shipper','carrier']){
  const actor=setupData[role],env=await context(cfg);try{const page=env.page;await login(page,actor);const card=await dealCard(page,cfg,deal.id);await card.locator('button[onclick^="rateDealPrompt("]').click();await page.locator('#ratePopup').waitFor({state:'visible'});assert.equal(await page.locator('#ratePublicComment').isChecked(),false);
   await page.locator('#starRow [data-v="'+(role==='shipper'?5:4)+'"]').click();await page.locator('#rateComment').fill(role==='shipper'?PUBLIC:PRIVATE);if(role==='shipper')await page.locator('#ratePublicComment').check();const saved=await clickResponse(page,'#rateSubmit','/api/deals/'+deal.id+'/rate','POST');assert.equal(saved.my_review.public_comment,role==='shipper');assert.equal(saved.my_review.comment,role==='shipper'?PUBLIC:PRIVATE);await page.locator('#ratePopup').waitFor({state:'hidden'});
   if(role==='carrier'){
    const toggle=page.locator('[data-review-visibility-deal="'+deal.id+'"]').first();await toggle.waitFor({state:'visible'});assert.equal(await toggle.getAttribute('aria-pressed'),'false');
    await request('PATCH','/api/deals/'+deal.id+'/review-visibility',{public_comment:true},undefined,403);await request('PATCH','/api/deals/'+deal.id+'/review-visibility',{public_comment:true},setupData.empty.token,403);await request('PATCH','/api/deals/'+deal.id+'/review-visibility',{public_comment:'true'},actor.token,422);await request('PATCH','/api/deals/'+deal.id+'/review-visibility',{public_comment:true,rater_id:actor.id},setupData.shipper.token,422);
    const publicReview=await clickResponse(page,'[data-review-visibility-deal="'+deal.id+'"]','/api/deals/'+deal.id+'/review-visibility','PATCH');assert.equal(publicReview.my_review.public_comment,true);assert.equal(publicReview.my_review.comment,PRIVATE);const profile=await publicData(setupData.shipper.id,'?limit=50');noContactLeaks(profile);assert.ok(profile.reviews.some(review=>review.public_comment&&review.comment?.includes('PRIVATE NOTE')));
    const again=page.locator('[data-review-visibility-deal="'+deal.id+'"]').first();await again.waitFor({state:'visible'});assert.equal(await again.getAttribute('aria-pressed'),'true');const hidden=await clickResponse(page,'[data-review-visibility-deal="'+deal.id+'"]','/api/deals/'+deal.id+'/review-visibility','PATCH');assert.equal(hidden.my_review.public_comment,false);assert.equal(hidden.my_review.comment,PRIVATE);assert.equal((await publicData(setupData.shipper.id,'?limit=50')).reviews.some(review=>review.comment?.includes('PRIVATE NOTE')),false);
   }out.push({role,defaultPrivate:true,explicitPublic:role==='shipper',authorVisibilityRoundTrip:role==='carrier'});
  }finally{await env.context.close();}
 }return out;
}
async function openName(page,id,scope){const link=page.locator((scope?scope+' ':'')+'[data-public-profile-id="'+id+'"]:visible').first();await link.waitFor({state:'visible'});await link.click();await page.locator('#publicProfileOverlay').waitFor({state:'visible'});await page.locator('#publicProfileBody [data-public-profile-role]').waitFor({state:'visible'});return link;}
async function closeProfile(page){await page.locator('#publicProfileClose').click();await page.locator('#publicProfileOverlay').waitFor({state:'hidden'});}
async function changeLanguage(page,language){const count=diagnostics.profileRequests.length;await page.getByRole('button',{name:language==='ge'?'GE':'RU',exact:true}).dispatchEvent('click');await wait(120);assert.equal(diagnostics.profileRequests.length,count,'Language refresh must not refetch profiles');}
async function publicBrowser(cfg){
 const env=await context(cfg),out={viewport:cfg.name,scenarios:[]};try{const page=env.page;await page.goto(BASE+'/',{waitUntil:'domcontentloaded'});await tab(page,cfg,'loads');
  await openName(page,setupData.shipper.id,'#cargoList');assert.equal(await page.locator('#cargoOverlay').isVisible(),false,'Name click must not open cargo');assert.equal(await page.locator('#authOverlay').isVisible(),false);assert.equal(await page.locator('[data-public-profile-role]').getAttribute('data-public-profile-role'),'shipper');assert.equal((await page.locator('#publicProfileBody').textContent()).includes('PRIVATE NOTE'),false);await closeProfile(page);out.scenarios.push('anonymous shipper/name-click isolation');
  await tab(page,cfg,'trucks');await openName(page,setupData.carrier.id,'#transportList');assert.equal(await page.locator('#transportRequestOverlay').isVisible(),false,'Name click must not respond');assert.equal(await page.locator('#authOverlay').isVisible(),false);assert.equal(await page.locator('[data-public-profile-role]').getAttribute('data-public-profile-role'),'carrier');
  assert.equal(await page.locator('[data-public-review-id]').count(),10);await page.locator('[data-public-profile-action="more"]').click();await page.waitForFunction(()=>document.querySelectorAll('[data-public-review-id]').length===13);const ids=await page.locator('[data-public-review-id]').evaluateAll(nodes=>nodes.map(node=>node.dataset.publicReviewId));assert.equal(new Set(ids).size,13);assert.equal(await page.locator('[data-public-review-score]').count(),13);assert.equal(await page.locator('time[data-public-review-date]').count(),13);assert.equal(await page.locator('#publicProfileBody img,#publicProfileBody script,#publicProfileBody [onerror]').count(),0);assert.equal((await page.locator('#publicProfileBody').textContent()).includes('LEGACY PRIVATE CANARY'),false);for(const marker of['public.contact@example.test','+995599009876'])assert.equal((await page.locator('#publicProfileBody').textContent()).includes(marker),false);
  await changeLanguage(page,'ge');assert.equal(await page.locator('[data-public-review-id]').count(),13);await page.screenshot({path:path.join(ART,cfg.name+'-public-carrier-ge.png')});await changeLanguage(page,'ru');await closeProfile(page);out.scenarios.push('carrier verified ratings/pagination/XSS/contact masking/RU-GE');
  await openName(page,setupData.empty.id,'#transportList');assert.equal(await page.locator('[data-public-review-id]').count(),0);assert.match(await page.locator('[data-public-profile-rating]').textContent(),/нет подтверждённых отзывов/);assert.equal((await page.locator('#publicProfileBody').textContent()).includes('HiddenStreet47'),false);await closeProfile(page);out.scenarios.push('no reviews/no fictitious rating/private city omitted');
  const delayed='**/api/users/'+setupData.carrier.id+'/profile**';await page.route(delayed,async route=>{await wait(700);await route.continue().catch(()=>{});});await page.locator('#transportList [data-public-profile-id="'+setupData.carrier.id+'"]:visible').first().click();await page.locator('[data-public-profile-status="loading"]').waitFor({state:'visible'});await page.locator('#transportList [data-public-profile-id="'+setupData.empty.id+'"]').first().dispatchEvent('click');await page.locator('#publicProfileBody [data-public-profile-role="both"]').waitFor({state:'visible'});await wait(850);assert.equal(await page.locator('[data-public-review-id]').count(),0);await closeProfile(page);
  await page.locator('#transportList [data-public-profile-id="'+setupData.carrier.id+'"]:visible').first().click();await page.locator('[data-public-profile-status="loading"]').waitFor({state:'visible'});await closeProfile(page);await wait(850);assert.equal(await page.locator('#publicProfileOverlay').isVisible(),false);await page.unroute(delayed);out.scenarios.push('rapid A-B/close ignores late response');
  const failing='**/api/users/'+setupData.empty.id+'/profile**';await page.route(failing,route=>route.abort('failed'));await page.locator('#transportList [data-public-profile-id="'+setupData.empty.id+'"]:visible').first().click();await page.locator('[data-public-profile-status="unavailable"]').waitFor({state:'visible'});await page.unroute(failing);await page.locator('[data-public-profile-action="retry"]').click();await page.locator('[data-public-profile-role="both"]').waitFor({state:'visible'});await closeProfile(page);out.scenarios.push('network failure/retry');
  for(const flag of['is_active','is_deleted']){
   const state=flag==='is_active'?false:true;await request('PATCH','/__test__/public-profiles/users/'+setupData.carrier.id+'/state',{[flag]:state});await request('GET','/api/users/'+setupData.carrier.id+'/profile',undefined,undefined,404);await page.locator('#transportList [data-public-profile-id="'+setupData.carrier.id+'"]:visible').first().click();await page.locator('[data-public-profile-status="notfound"]').waitFor({state:'visible'});await closeProfile(page);await request('PATCH','/__test__/public-profiles/users/'+setupData.carrier.id+'/state',{[flag]:!state});
  }await request('GET','/api/users/999999/profile',undefined,undefined,404);out.scenarios.push('unknown/blocked/deleted unavailable');
  await request('PATCH','/__test__/public-profiles/users/'+setupData.shipper.id+'/state',{is_active:false});const hiddenAuthors=await publicData(setupData.carrier.id,'?limit=50');assert.equal(hiddenAuthors.total,13);for(const review of hiddenAuthors.reviews){assert.equal(review.author.available,false);assert.equal(review.author.id,null);assert.equal(review.author.role,null);assert.equal(review.comment,null);assert.ok(review.created_at);assert.ok(review.score>=1);}await request('PATCH','/__test__/public-profiles/users/'+setupData.shipper.id+'/state',{is_active:true});out.scenarios.push('unavailable author identity/comment hidden; score/date retained');
  await tab(page,cfg,'loads');await page.locator('#cargoList .card-load .'+(cfg.mobile?'card-route-new':'route')).first().click();await page.locator('#cargoOverlay').waitFor({state:'visible'});await openName(page,setupData.shipper.id,'#mComp');await page.keyboard.press('Escape');await page.locator('#publicProfileOverlay').waitFor({state:'hidden'});assert.equal(await page.locator('#cargoOverlay').isVisible(),true);await page.locator('#cargoOverlay .close-btn').click();out.scenarios.push('Escape closes profile only, preserving parent cargo');
  await tab(page,cfg,'trucks');await openName(page,setupData.empty.id,'#transportList');await page.goBack();await page.locator('#publicProfileOverlay').waitFor({state:'hidden'});out.scenarios.push('browser Back closes profile');
  await page.screenshot({path:path.join(ART,cfg.name+'-public-profile-result.png'),fullPage:true});results.push({...out,status:'passed'});
 }catch(error){await env.page.screenshot({path:path.join(ART,cfg.name+'-failure.png'),fullPage:true}).catch(()=>{});results.push({...out,status:'failed',error:error.message});throw error;}finally{await env.context.close();}
}
async function seedReview(){
 assert.equal(readyData.mock_maps,true);assert.equal((await request('GET','/api/loads/?scope=local')).data.total,0);assert.equal((await request('GET','/api/transport/?scope=local')).data.total,0);
 const shipper=await account('shipper','ТЕСТ грузовладелец'),carrier=await account('carrier','ТЕСТ перевозчик'),deal=await completedDeal(shipper,carrier,'ТЕСТ завершённая сделка');
 await request('POST','/api/deals/'+deal.id+'/rate',{score:5,comment:'ТЕСТ: доставка подтверждена в локальном сценарии. Публичный комментарий автора.',public_comment:true},shipper.token);await request('POST','/api/deals/'+deal.id+'/rate',{score:4,comment:'ТЕСТ: частный комментарий. Публично доступны только оценка и дата.'},carrier.token);
 await load(shipper,'ТЕСТ: нажмите на имя грузовладельца, чтобы открыть публичный профиль. Это не реальная заявка.');await offer(carrier,'ТЕСТ: нажмите на имя перевозчика; это не реальное предложение.');const manifest={url:BASE+'/',testOnly:true,participants:[{id:shipper.id,role:shipper.role},{id:carrier.id,role:carrier.role}],completedDeal:deal.id,publicCommentsExplicitOptIn:true,providers:'disabled',sourceOriginalSha256:readyData.original_source_sha256,backendSha256:readyData.backend_sha256};fs.writeFileSync(path.join(ART,'review-demo.json'),JSON.stringify(manifest,null,2));console.log(JSON.stringify(manifest));
}
(async()=>{try{
 if(process.argv.includes('--spawn-server')){const log=fs.createWriteStream(path.join(ART,'server.log'));server=spawn(process.env.PYTHON||'python',[path.join(ROOT,'tests/browser/carrier_profile_server.py')],{cwd:ROOT,env:{...process.env,PYTHONUNBUFFERED:'1',CARRIER_PROFILE_REPO_ROOT:ROOT,CARRIER_BROWSER_PORT:String(PORT),CARRIER_BROWSER_TEMP_ROOT:path.join(ART,'.fixture'),CARRIER_BROWSER_PUBLICATION:'1',CARRIER_BROWSER_PILOT:'1',CARRIER_BROWSER_ADDRESS:'1',CARRIER_BROWSER_PUBLIC_PROFILES:'1',CARRIER_BROWSER_NOTIFICATIONS:'0',CARRIER_BROWSER_AUTH:'0',CARRIER_BROWSER_MOCK_MAPS:'0'},stdio:['ignore','pipe','pipe']});server.stdout.pipe(log,{end:false});server.stderr.pipe(log,{end:false});server.once('close',()=>log.end());}
 await ready();if(process.argv.includes('--seed-review')){await seedReview();return;}
 const{chromium}=require(require.resolve('playwright',{paths:[ROOT,__dirname]}));browser=await chromium.launch({headless:true,executablePath:process.env.CARRIER_BROWSER_CHROMIUM_EXECUTABLE_PATH||undefined,args:['--disable-background-networking','--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1']});
 setupData=await setup();const configurations=[{name:'desktop',width:1280,height:900,mobile:false},{name:'mobile',width:390,height:844,mobile:true}];
 for(let i=0;i<configurations.length;i++)await privateReviewUI(configurations[i],i);
 const carrier=await publicData(setupData.carrier.id,'?limit=50'),shipper=await publicData(setupData.shipper.id,'?limit=50'),empty=await publicData(setupData.empty.id);for(const data of[carrier,shipper,empty])noContactLeaks(data);assert.equal(carrier.total,13);assert.equal(shipper.total,2);assert.equal(empty.profile.rating,null);assert.equal(empty.profile.review_count,0);assert.equal(empty.profile.city,null);assert.equal(carrier.profile.completed_deals_count,13);assert.equal(carrier.reviews.some(review=>review.comment?.includes('LEGACY PRIVATE CANARY')),false);
 for(const cfg of configurations){await publicBrowser(cfg);console.log(cfg.name+': public profiles, privacy, pagination, races and errors passed');}
 assert.equal(diagnostics.productionAttempts,0);assert.equal(diagnostics.pageErrors.length,0);assert.equal(diagnostics.dialogs.length,0);
}catch(error){console.error(error.stack||error);process.exitCode=1;}finally{if(browser)await browser.close().catch(()=>{});if(server&&server.exitCode===null)server.kill();fs.writeFileSync(path.join(ART,'results.json'),JSON.stringify({results,diagnostics,fixture:readyData},null,2));}})();
