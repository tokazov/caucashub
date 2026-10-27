/* Runs only in the existing disposable localhost carrier fixture. */
const assert=require('node:assert/strict');
const path=require('node:path');

module.exports=async function mariSteps(page, options){
 const {name,artifacts,logout,login,email,password}=options;
 assert.equal(new URL(page.url()).hostname,'127.0.0.1');
 const requests=[],publications=[];
 let releaseSlow,reply='MARI SEARCH OK';
 const date=new Date(Date.now()+86400000).toISOString().slice(0,10);
 const draft={intent:'post_load',scope:'local',from:'Тбилиси',to:'Батуми',weight_cap:5000,truck:'tent',date,price:800,currency:'GEL',cargo_desc:'Паллеты'};
 const fulfill=(route,body,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
 await page.route('**/api/ai/dispatcher',async route=>{
  const body=route.request().postDataJSON();requests.push(body);
  if(body.message==='slow'){
   await new Promise(resolve=>{releaseSlow=resolve;});
   return fulfill(route,{reply:'STALE MARI RESULT',state:{},loads:[]}).catch(()=>{});
  }
  if(body.message==='error')return fulfill(route,{detail:'Provider unavailable'},503);
  if(body.message==='draft'||body.message==='guest draft')return fulfill(route,{reply:'MARI DRAFT READY',state:draft,draft});
  if(body.message==='transport draft'){
   const offer={...draft,intent:'post_transport',capacity_kg:7000,truck:'bort'};
   return fulfill(route,{reply:'MARI TRANSPORT READY',state:offer,draft:offer});
  }
  return fulfill(route,{reply,state:{intent:'search_load'},loads:[{id:901,from:'<img src=x onerror=alert(1)>',to:'Батуми',kg:1000,price:500,cur:'₾'}]});
 });
 const track=request=>{
  if(request.method()==='POST'&&/\/api\/(loads\/|transport\/$)/.test(new URL(request.url()).pathname))publications.push(request.url());
 };
 page.on('request',track);
 const open=async()=>{
  if(!await page.locator('#aiChat').isVisible())await page.locator('.ai-fab').click();
  await page.locator('#aiInput').waitFor({state:'visible'});
 };
 const send=async(text,expected)=>{
  await page.locator('#aiInput').fill(text);await page.locator('.ai-send').click();
  if(expected)await page.locator('#aiMessages').getByText(expected,{exact:true}).last().waitFor();
  await page.waitForFunction(()=>!document.getElementById('aiInput').disabled);
 };
 try{
  await open();
  await send('search',reply);
  assert.equal(requests.at(-1).user_role,'carrier');
  assert.equal(requests.at(-1).lang,'ru');
  assert.ok(requests.at(-1).history.every(item=>item.text!=='search'));
  assert.equal(await page.locator('#aiMessages img[src=x]').count(),0);
  assert.ok((await page.locator('#aiMessages').innerText()).includes('<img src=x onerror=alert(1)>'));

  await page.locator('.ai-chat-header button[onclick="aiReset()"]').click();
  await page.locator('#aiInput').fill('slow');await page.locator('.ai-send').click();
  await page.waitForFunction(()=>document.getElementById('aiInput').disabled);
  await page.locator('.ai-chat-header button[onclick="aiReset()"]').click();
  await page.waitForFunction(()=>!document.getElementById('aiInput').disabled);
  if(releaseSlow)releaseSlow();
  await send('error');
  assert.equal(await page.locator('#aiInput').inputValue(),'error');
  assert.ok(!(await page.locator('#aiMessages').innerText()).includes('STALE MARI RESULT'));

  await page.locator('.ai-close').click();
  await page.getByRole('button',{name:'GE',exact:true}).click();
  await open();reply='მარი მზად არის';await send('ქართული ძებნა',reply);
  assert.equal(requests.at(-1).lang,'ge');
  await page.screenshot({path:path.join(artifacts,name+'-mari-ge.png')});
  await page.locator('.ai-close').click();
  await page.getByRole('button',{name:'RU',exact:true}).click();

  await open();await send('draft','MARI DRAFT READY');
  await page.locator('#aiPostBtn').click();
  await page.locator('#postOverlay').waitFor({state:'visible'});
  assert.equal(await page.locator('#pFromAddr').inputValue(),'Тбилиси');
  assert.equal(await page.locator('#pWeight').inputValue(),'5000');
  assert.equal(await page.locator('#pTruck').inputValue(),'tent');
  assert.equal(await page.locator('#pDate').inputValue(),date);
  assert.equal(await page.locator('#pPrice').inputValue(),'800');
  await page.screenshot({path:path.join(artifacts,name+'-mari-load-draft.png')});
  await page.locator('#postOverlay .close-btn').click();

  await open();await send('transport draft','MARI TRANSPORT READY');
  await page.locator('#aiPostBtn').click();
  await page.locator('#postTransportOverlay').waitFor({state:'visible'});
  assert.equal(await page.locator('#ptCapacity').inputValue(),'7000');
  assert.equal(await page.locator('#ptTruckType').inputValue(),'bort');
  assert.equal(await page.locator('#ptDateFrom').inputValue(),date);
  await page.screenshot({path:path.join(artifacts,name+'-mari-transport-draft.png')});
  await page.locator('#postTransportOverlay .close-btn').click();
  await logout(page);

  await open();await send('guest draft','MARI DRAFT READY');
  assert.equal(requests.at(-1).user_role,null);
  await page.locator('#aiPostBtn').click();
  await page.locator('#authOverlay').waitFor({state:'visible'});
  await page.locator('#authOverlay .close-btn').click();
  await login(page,email,password);
  await page.locator('#postOverlay').waitFor({state:'visible'});
  assert.equal(await page.locator('#pWeight').inputValue(),'5000');
  assert.equal(await page.locator('#pDate').inputValue(),date);
  await page.locator('#postOverlay .close-btn').click();
  assert.deepEqual(publications,[],'Preparing/reviewing drafts must never publish automatically');
  console.log(name+': Mari language, role, history, safe cards, recovery, reset and both draft forms passed');
 }finally{
  if(releaseSlow)releaseSlow();
  page.off('request',track);await page.unroute('**/api/ai/dispatcher');
 }
};
