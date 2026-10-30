/* Notification UI and provider assertions, restricted to the localhost fixture. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const PORT=process.env.CARRIER_BROWSER_PORT||'8765';
if(!/^\d+$/.test(PORT)||Number(PORT)<1024||Number(PORT)>65535)throw Error('Local fixture port must be between1024 and65535');
const ORIGIN='http://127.0.0.1:'+Number(PORT);

async function fixture(page,endpoint,method='GET'){
 assert.equal(new URL(page.url()).origin,ORIGIN);
 const result=await page.evaluate(async({origin,endpoint,method})=>{
  const response=await fetch(origin+endpoint,{method,headers:{Authorization:'Bearer '+localStorage.getItem('ch_token')}});
  return{status:response.status,marker:response.headers.get('x-carrier-test-only'),body:await response.json()};
 },{origin:ORIGIN,endpoint,method});
 assert.equal(result.status,200,endpoint+': '+JSON.stringify(result.body));
 assert.equal(result.marker,'1');assert.equal(result.body.test_only,true);
 return result.body;
}
const state=page=>fixture(page,'/__test__/notification-state');
const drain=page=>fixture(page,'/__test__/notification-drain','POST');
function keyForRequest(source,id){return(source==='cargo'?'response:':'transport_request:')+id+':created';}
function expectedType(source){return source==='cargo'?'new_response':'new_transport_request';}
function assertNoPrivateContact(value,account){
 const text=JSON.stringify(value);
 for(const secret of[account.phone,account.email].filter(Boolean))assert.equal(text.includes(secret),false,'Pre-acceptance event must not contain a private contact');
}
async function linkChannels(page,account){
 const linked=await fixture(page,'/__test__/notification-link','POST');
 assert.equal(linked.user_id,account.id);assert.equal(linked.email,account.email);
 assert.match(linked.telegram_id,/^[1-9]\d+$/);
 account.telegram_id=linked.telegram_id;
 const initial=await state(page);
 assert.equal(initial.notifications.length,0);assert.equal(initial.provider_attempts.length,0);
 assert.equal(initial.unexpected_provider_requests,0);
}
async function afterRequest({owner,actor,source,requestId,accounts,ownerRole,actorRole}){
 const recipient=await state(owner),sender=await state(actor),key=keyForRequest(source,requestId);
 const rows=recipient.notifications.filter(row=>row.event_key===key);
 assert.equal(rows.length,1);assert.equal(rows[0].type,expectedType(source));
 assert.equal(rows[0].recipient_id,accounts[ownerRole].id);assert.equal(rows[0].actor_id,accounts[actorRole].id);
 assert.equal(rows[0].data.source,source);
 assertNoPrivateContact(rows[0].data,accounts[actorRole]);
 assert.equal(sender.notifications.filter(row=>row.event_key===key).length,0);
 assert.equal(recipient.unexpected_provider_requests,0);
}
async function afterAccept({shipper,carrier,source,dealId,accounts}){
 for(const[role,page]of Object.entries({shipper,carrier})){
  const result=await state(page);
  const rows=result.notifications.filter(row=>row.event_key==='deal:'+dealId+':created');
  assert.equal(rows.length,1);assert.equal(rows[0].type,'deal_created');
  assert.equal(rows[0].recipient_id,accounts[role].id);assert.equal(rows[0].data.deal_id,dealId);
  assert.equal(rows[0].data.source,source);
 }
}
async function inbox(page){
 const result=await page.evaluate(async origin=>{
  const response=await fetch(origin+'/api/notifications?limit=50&offset=0',{headers:{Authorization:'Bearer '+localStorage.getItem('ch_token')}});
  return{status:response.status,body:await response.json()};
 },ORIGIN);
 assert.equal(result.status,200);
 return result.body;
}
async function openPanel(page,expected,unread){
 const panel=page.locator('#notifPanel');
 if((await panel.getAttribute('class')||'').split(/\s+/).includes('open'))await page.locator('#notifBtn').click();
 await page.locator('#notifBtn').click();
 await panel.waitFor({state:'visible'});
 await page.waitForFunction(ids=>{
  const actual=[...document.querySelectorAll('#notifPanel .notif-item[data-notification-key^="server:"]')]
   .map(node=>Number(node.dataset.notificationKey.slice(7))).sort((a,b)=>a-b);
  return JSON.stringify(actual)===JSON.stringify([...ids].sort((a,b)=>a-b));
 },expected.map(row=>row.id));
 const badge=(await page.locator('#notifBadge').textContent()||'').trim();
 assert.equal(badge,unread?(unread>9?'9+':String(unread)):'');
 for(const row of expected){
  const item=page.locator('.notif-item[data-notification-key="server:'+row.id+'"]');
  assert.equal(await item.getAttribute('data-notification-type'),row.type);
  const isUnread=(await item.getAttribute('class')||'').split(/\s+/).includes('unread');
  assert.equal(isUnread,!row.read_at);
 }
 assert.equal(await page.locator('#notifPanel .notif-item[data-notification-key^="local:"]').count(),0,'Covered events must not also create local duplicates');
}
async function logout(page){
 const panel=page.locator('#notifPanel');
 if((await panel.getAttribute('class')||'').split(/\s+/).includes('open'))await page.locator('#notifBtn').click();
 await page.locator('#userAvatar').click();
 await page.locator('#profileOverlay button[onclick="doLogout()"]').click();
 await page.locator('#btnLogin').waitFor({state:'visible'});
 await page.waitForFunction(()=>document.querySelectorAll('.notif-item[data-notification-key^="server:"]').length===0);
}
async function login(page,account,password){
 await page.locator('#btnLogin').click();
 await page.locator('#loginEmail').fill(account.email);
 await page.locator('#loginPass').fill(password);
 const pending=page.waitForResponse(r=>r.url().split('?')[0]===ORIGIN+'/api/auth/login'&&r.request().method()==='POST');
 await page.locator('#formLogin button[onclick="doLogin()"]').click();
 const response=await pending;assert.equal(response.status(),200);
 await page.locator('#authOverlay').waitFor({state:'hidden'});
 await page.locator('#userAvatar').waitFor({state:'visible'});
 await page.waitForFunction(id=>Number(JSON.parse(localStorage.getItem('ch_user')||'{}').userId)===id,account.id);
}
function checkKinds(result,role,accounts,journeys){
 assert.equal(result.recipient_id,accounts[role].id);
 assert.equal(result.notifications.length,7);
 const expectations=role==='shipper'?{
  cargo:['new_response','deal_created','delivery_confirmation_required','deal_completed'],
  transport:['deal_created','delivery_waiting','deal_completed'],
 }:{
  cargo:['deal_created','delivery_waiting','deal_completed'],
  transport:['new_transport_request','deal_created','delivery_confirmation_required','deal_completed'],
 };
 for(const source of['cargo','transport']){
  const rows=result.notifications.filter(row=>row.data.source===source);
  assert.deepEqual(rows.map(row=>row.type).sort(),expectations[source].sort());
  const dealId=journeys[source].contacts[0].dealId;
  for(const row of rows){
   assert.equal(row.recipient_id,accounts[role].id);
   if(row.type.startsWith('deal_')||row.type.startsWith('delivery_'))assert.equal(row.data.deal_id,dealId);
   if(['delivery_waiting','delivery_confirmation_required'].includes(row.type)){
    const first=source==='cargo'?'carrier':'shipper';
    assert.equal(row.actor_id,accounts[first].id);
    assert.equal(row.type,role===first?'delivery_waiting':'delivery_confirmation_required');
   }
   assert.equal(row.read_at,null);
  }
 }
 assert.equal(new Set(result.notifications.map(row=>row.event_key)).size,7);
 assert.equal(new Set(result.notifications.map(row=>row.id)).size,7);
 assert.equal(result.deliveries.length,12);
 assert.equal(result.provider_attempts.length,12);
 assert.equal(result.unexpected_provider_requests,0);
 const attempts=new Map(result.provider_attempts.map(row=>[row.provider_id,row]));
 assert.equal(attempts.size,12);
 for(const notification of result.notifications){
  const deliveries=result.deliveries.filter(row=>row.notification_id===notification.id);
  if(notification.type==='delivery_waiting'){
   assert.equal(deliveries.length,0);continue;
  }
  assert.deepEqual(deliveries.map(row=>row.channel).sort(),['email','telegram']);
  for(const delivery of deliveries){
   assert.equal(delivery.status,'sent');assert.equal(delivery.attempts,1);
   const provider=attempts.get(delivery.provider_id);assert.ok(provider,'Every sent row must map to an actual captured HTTP request');
   assert.equal(provider.channel,delivery.channel);assert.equal(provider.status,200);
   assert.equal(String(provider.recipient),delivery.channel==='email'?accounts[role].email:accounts[role].telegram_id);
   if(['new_response','new_transport_request'].includes(notification.type)){
    const other=role==='shipper'?'carrier':'shipper';
    assertNoPrivateContact({html:provider.html,text:provider.text,subject:provider.subject},accounts[other]);
   }
  }
 }
}
async function finish(options){
 const{shipper,carrier,configuration,accounts,cargo,transport,password,artifacts,tab}=options;
 const pages={shipper,carrier},journeys={cargo,transport};
 const sent=await drain(shipper);
 assert.equal(sent.unexpected_provider_requests,0);
 assert.equal(sent.stats.sent,24);assert.equal(sent.new_provider_attempts,24);
 const again=await drain(shipper);
 assert.equal(again.stats.claimed,0);assert.equal(again.new_provider_attempts,0);
 const before={shipper:await state(shipper),carrier:await state(carrier)};
 for(const role of['shipper','carrier']){
  checkKinds(before[role],role,accounts,journeys);
  const feed=await inbox(pages[role]);assert.equal(feed.total,7);assert.equal(feed.unread_count,7);
  await openPanel(pages[role],before[role].notifications,7);
  await pages[role].screenshot({path:path.join(artifacts,configuration.name+'-'+role+'-notifications-unread.png'),fullPage:true});
 }
 const selected=before.shipper.notifications.find(row=>row.type==='deal_completed'&&row.data.source==='transport');
 assert.ok(selected&&selected.data.deal_number);
 if((await shipper.locator('#notifPanel').getAttribute('class')||'').split(/\s+/).includes('open'))await shipper.locator('#notifBtn').click();
 await tab(shipper,configuration,'trucks');
 await openPanel(shipper,before.shipper.notifications,7);
 const mark=shipper.waitForResponse(r=>r.url().split('?')[0]===ORIGIN+'/api/notifications/'+selected.id+'/read'&&r.request().method()==='POST');
 await shipper.locator('.notif-item[data-notification-key="server:'+selected.id+'"]').click();
 const marked=await mark;assert.equal(marked.status(),200);
 await shipper.locator('#sec-orders.active').waitFor({state:'visible'});
 await shipper.locator('#cabTab-deals').waitFor({state:'visible'});
 await shipper.locator('#myDealsList .cab-deal-card').filter({hasText:selected.data.deal_number}).first().waitFor({state:'visible'});
 const target=await inbox(shipper);assert.equal(target.unread_count,6);assert.equal(target.total,7);
 assert.ok(target.notifications.find(row=>row.id===selected.id).read_at);
 const peer=await inbox(carrier);assert.equal(peer.unread_count,7);
 await openPanel(shipper,target.notifications,6);
 const all=shipper.waitForResponse(r=>r.url().split('?')[0]===ORIGIN+'/api/notifications/read-all'&&r.request().method()==='POST');
 await shipper.locator('#notifPanel .notif-mark').click();
 const read=await all;assert.equal(read.status(),200);
 let own=await inbox(shipper);assert.equal(own.unread_count,0);assert.equal(own.notifications.length,7);
 assert.ok(own.notifications.every(row=>row.read_at));
 assert.equal((await inbox(carrier)).unread_count,7);
 await shipper.reload({waitUntil:'domcontentloaded'});
 await shipper.locator('#userAvatar').waitFor({state:'visible'});
 await openPanel(shipper,own.notifications,0);
 // The same browser context must discard one account's inbox before another login.
 await logout(shipper);await login(shipper,accounts.carrier,password);
 const switched=await inbox(shipper);assert.equal(switched.unread_count,7);
 assert.deepEqual(switched.notifications.map(row=>row.id).sort((a,b)=>a-b),before.carrier.notifications.map(row=>row.id).sort((a,b)=>a-b));
 await openPanel(shipper,switched.notifications,7);
 assert.equal(await shipper.locator('.notif-item[data-notification-key="server:'+selected.id+'"]').count(),0);
 await logout(shipper);await login(shipper,accounts.shipper,password);
 own=await inbox(shipper);assert.equal(own.unread_count,0);assert.equal(own.total,7);
 await openPanel(shipper,own.notifications,0);
 assert.equal((await inbox(carrier)).unread_count,7);
 await shipper.screenshot({path:path.join(artifacts,configuration.name+'-shipper-notifications-read-persisted.png'),fullPage:true});
 const final=await drain(shipper);assert.equal(final.new_provider_attempts,0);assert.equal(final.stats.claimed,0);
 const summary={viewport:configuration.name,notificationsPerRole:7,notificationsTotal:14,
  externalRequests:24,externalDeliveriesOnce:true,firstConfirmationRecipientsCorrect:true,
  readStatePersistent:true,accountSwitchIsolated:true,peerUnreadUnchanged:true,
  sources:['cargo','transport'],sent:sent.stats,repeatedDrain:again.stats};
 fs.writeFileSync(path.join(artifacts,configuration.name+'-notification-summary.json'),JSON.stringify(summary,null,2));
 console.log(configuration.name+': 14 persistent inbox rows, 24 correct HTTP deliveries, no duplicate drain, read persistence and account isolation passed');
 return summary;
}
module.exports={linkChannels,afterRequest,afterAccept,finish};
