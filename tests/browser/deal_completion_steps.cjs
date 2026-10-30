/* Real UI completion checks. Called only by the verified localhost trade fixture. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');

module.exports=async function completeDeal(options){
 const{shipper,carrier,configuration,accounts,dealId,source,first,readApi,cabinetTab,clickRequest,artifacts}=options;
 const pages={shipper,carrier};
 const second=first==='shipper'?'carrier':'shipper';
 const label=configuration.name+'-'+source;
 const manifest=[];
 const participantNames={shipper:'შპს სატესტო ტვირთმფლობელი',carrier:'ᲨᲞᲡ ᲡᲐᲢᲔᲡᲢᲝ ᲒᲐᲓᲐᲛᲖᲘᲓᲐᲕᲘ'};
 async function confirmLegalNames(){
  for(const role of['shipper','carrier']){
   assert.ok(accounts[role].email.endsWith('@example.test'),'Only disposable test owners may receive fixture requisites');
   const page=pages[role],origin=new URL(page.url()).origin;assert.ok(['127.0.0.1','localhost'].includes(new URL(origin).hostname));
   const saved=await page.evaluate(async({origin,name})=>{const r=await fetch(origin+'/api/users/me',{method:'PUT',headers:{Authorization:'Bearer '+localStorage.getItem('ch_token'),'Content-Type':'application/json'},body:JSON.stringify({legal_name_ka:name,legal_name_ka_confirmed:true})});return{status:r.status,marker:r.headers.get('x-carrier-test-only'),data:await r.json()};},{origin,name:participantNames[role]});
   assert.equal(saved.status,200);assert.equal(saved.marker,'1');assert.equal(saved.data.legal_name_ka,participantNames[role]);assert.equal(saved.data.legal_name_ka_confirmed,true);
   await page.reload({waitUntil:'domcontentloaded'});await page.locator('#userAvatar').waitFor({state:'visible'});
  }
 }
 async function show(role){
  const page=pages[role];
  await cabinetTab(page,configuration,'deals');
  const response=await readApi(page,'/api/deals/my');
  const deal=response.deals.find(row=>row.id===dealId);
  assert.ok(deal,'The participant must see the deal');
  await page.waitForFunction(expected=>{
   const rows=typeof _deals==='undefined'?[]:_deals;
   const actual=rows.find(row=>row.id===expected.id);
   return actual&&['status','shipper_confirmed','carrier_confirmed','viewer_can_rate','viewer_has_rated','my_review','counterparty_review'].every(key=>JSON.stringify(actual[key])===JSON.stringify(expected[key]));
  },deal);
  const card=page.locator('#myDealsList .cab-deal-card').filter({hasText:deal.deal_number}).first();
  await card.waitFor({state:'visible'});
  return{page,deal,card};
 }
 async function state(role,status){
  const view=await show(role);
  assert.equal(view.deal.status,status);
  return view;
 }
 async function confirm(role,expected){
  const view=await show(role);
  const request=view.page.waitForResponse(r=>r.url().split('?')[0]===new URL('/api/deals/'+dealId+'/confirm',view.page.url()).href&&r.request().method()==='POST');
  await view.card.locator('button[onclick="confirmDelivery('+dealId+')"]').click();
  const response=await request,body=await response.json();
  assert.equal(response.status(),200,JSON.stringify(body));
  assert.equal(body.status,expected);
  assert.equal(body[role+'_confirmed'],true);
  return body;
 }
 async function refresh(role){
  await pages[role].reload({waitUntil:'domcontentloaded'});
  await pages[role].locator('#userAvatar').waitFor({state:'visible'});
  return show(role);
 }
 async function downloadAct(role,language){
  const page=pages[role];
  await page.getByRole('button',{name:language==='ge'?'GE':'RU',exact:true}).click();
  const view=await show(role);
  assert.ok(['completed','rated'].includes(view.deal.status));
  const link=view.card.locator('.cab-btn.pdf');
  await link.waitFor({state:'visible'});
  const responsePending=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/deals/'+dealId+'/act.pdf'&&response.request().method()==='GET');
  const pending=page.waitForEvent('download',{timeout:15000});
  await link.click();
  const response=await responsePending,requestUrl=new URL(response.url());assert.equal(response.status(),200);assert.equal(response.headers()['x-carrier-test-only'],'1');assert.equal(requestUrl.origin,new URL(page.url()).origin);assert.equal(requestUrl.searchParams.get('lang'),language);assert.equal(requestUrl.searchParams.has('token'),false);assert.ok(response.request().headers().authorization?.startsWith('Bearer '),'PDF request must use an authorization header');
  const download=await pending;
  assert.equal(await download.failure(),null);
  assert.match(download.suggestedFilename(),/^act_.+\.pdf$/);
  assert.ok(!/[\\/]/.test(download.suggestedFilename()),'PDF filename must be safe');
  const filename=label+'-'+role+'-'+language+'.pdf';
  await download.saveAs(path.join(artifacts,filename));
  const bytes=fs.readFileSync(path.join(artifacts,filename));
  assert.equal(bytes.subarray(0,5).toString(),'%PDF-');
  assert.ok(bytes.length>1000,'PDF must contain a real act, not an empty response');
  manifest.push({file:filename,language,source,deal_number:view.deal.deal_number,
   from:view.deal.load_from,to:view.deal.load_to,description:view.deal.load_desc,weight:view.deal.load_kg,
   shipper:participantNames.shipper,carrier:participantNames.carrier,registration_shipper:accounts.shipper.company_name,registration_carrier:accounts.carrier.company_name,price:Number(view.deal.price)});
  if(language!=='ru')await page.getByRole('button',{name:'RU',exact:true}).click();
 }
 async function rate(role,score,comment){
  const view=await show(role);
  assert.equal(view.deal.viewer_has_rated,false);
  assert.equal(view.deal.viewer_can_rate,true);
  await view.card.locator('button[onclick^="rateDealPrompt("]').click();
  await view.page.locator('#ratePopup').waitFor({state:'visible'});
  await view.page.locator('#starRow [data-v="'+score+'"]').click();
  await view.page.locator('#rateComment').fill(comment);
  await clickRequest(view.page,'#rateSubmit','/api/deals/'+dealId+'/rate','POST',200);
  await view.page.locator('#ratePopup').waitFor({state:'hidden'});
  const saved=await show(role);
  assert.equal(saved.deal.viewer_has_rated,true);
  assert.equal(saved.deal.viewer_can_rate,false);
  assert.equal(saved.deal.my_review.score,score);
  assert.equal(saved.deal.my_review.comment,comment);
  await saved.card.locator('.cab-deal-review[data-review="mine"]').filter({hasText:comment}).waitFor({state:'visible'});
  assert.equal(await saved.card.locator('button[onclick^="rateDealPrompt("]').count(),0);
  return{score,comment};
 }
 for(const role of['shipper','carrier']){
  const view=await state(role,'confirmed');
  assert.equal(await view.card.locator('.cab-btn.pdf').count(),0,'Final act is unavailable before delivery completion');
 }
 const firstResult=await confirm(first,'delivered');
 assert.equal(firstResult[second+'_confirmed'],false);
 assert.ok(firstResult.delivered_at);
 const waiting=await refresh(first);
 assert.equal(waiting.deal.status,'delivered');
 assert.equal(await waiting.card.locator('button[onclick="confirmDelivery('+dealId+')"]').count(),0,'A confirmed participant must wait, not confirm twice');
 assert.equal(await waiting.card.locator('.cab-btn.pdf').count(),0);
 const remaining=await state(second,'delivered');
 await remaining.card.locator('button[onclick="confirmDelivery('+dealId+')"]').waitFor({state:'visible'});
 const completed=await confirm(second,'completed');
 assert.equal(completed.shipper_confirmed,true);assert.equal(completed.carrier_confirmed,true);
 assert.ok(completed.completed_at);
 for(const role of['shipper','carrier'])await state(role,'completed');
 await confirmLegalNames();

 await downloadAct('shipper','ru');
 await downloadAct('carrier','ge');
 const firstComment='Проверка '+source+': аккуратная доставка <b>без разметки</b> & მადლობა';
 const secondComment='Обратный отзыв '+source+': всё согласовано, გმადლობთ';
 const reviews={};
 reviews[first]=await rate(first,4,firstComment);
 const unrated=await state(second,'rated');
 assert.equal(unrated.deal.viewer_has_rated,false);
 assert.equal(unrated.deal.viewer_can_rate,true,'The other participant can review after the first review');
 assert.equal(unrated.deal.counterparty_review.score,4);
 assert.equal(unrated.deal.counterparty_review.comment,firstComment);
 reviews[second]=await rate(second,5,secondComment);
 for(const role of['shipper','carrier']){
  const view=await refresh(role);
  assert.equal(view.deal.status,'rated');
  assert.equal(view.deal.my_review.score,reviews[role].score);
  assert.equal(view.deal.my_review.comment,reviews[role].comment);
  const other=role==='shipper'?'carrier':'shipper';
  assert.equal(view.deal.counterparty_review.score,reviews[other].score);
  assert.equal(view.deal.counterparty_review.comment,reviews[other].comment);
  await view.card.locator('.cab-deal-review[data-review="mine"]').filter({hasText:reviews[role].comment}).waitFor({state:'visible'});
  await view.card.locator('.cab-deal-review[data-review="counterparty"]').filter({hasText:reviews[other].comment}).waitFor({state:'visible'});
  assert.equal(await view.card.locator('button[onclick^="rateDealPrompt("]').count(),0);
  assert.equal(await view.card.locator('button[onclick="confirmDelivery('+dealId+')"]').count(),0);
  await view.page.screenshot({path:path.join(artifacts,label+'-'+role+'-completed.png'),fullPage:true});
 }
 const manifestPath=path.join(artifacts,'pdf-manifest.json');
 const previous=fs.existsSync(manifestPath)?JSON.parse(fs.readFileSync(manifestPath,'utf8')):[];
 fs.writeFileSync(manifestPath,JSON.stringify([...previous,...manifest],null,2));
 console.log(label+': both confirmations, completed status, RU/GE PDF download and both persisted reviews passed');
 return{source,dealId,first,completed:true,reviewsPersisted:true,pdfFiles:manifest.map(row=>row.file)};
};
