import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const read=path=>readFileSync(new URL('../../../'+path,import.meta.url),'utf8');
const sample={
 id:31,status:'confirmed',act_number:'QA-0031',deal_number:'QA-0031',
 shipper_id:7,carrier_id:8,shipper_confirmed:false,carrier_confirmed:false,
 load_from:'Тбилиси',load_to:'Батуми',price:500,
 shipper:{id:7,name:'Shipper',phone:'+995599102030',email:'shipper@example.test'},
 carrier:{id:8,name:'Carrier',phone:'+995599405060',email:'carrier@example.test'}
};
const completed={...sample,status:'completed',shipper_confirmed:true,carrier_confirmed:true,
 viewer_has_rated:false,viewer_can_rate:true,my_review:null,counterparty_review:null};
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return{promise,resolve};};
const response=(data,ok=true)=>({ok,json:async()=>data});
const drain=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
function environment(path,{viewer={userId:7},record=sample,language='ru'}={}){
 const elements={myDealsList:{innerHTML:''}};
 const button={disabled:false,style:{}};
 const calls={fetch:[],warnings:[],notifications:[],timers:[],appended:[]};
 const document={
  getElementById:id=>elements[id]||null,
  querySelector:selector=>selector.includes('confirmDelivery(')?button:null,
  querySelectorAll:()=>[],
  createElement:()=>({id:'',style:{},innerHTML:'',textContent:'',remove(){
   if(this.id&&elements[this.id]===this){delete elements[this.id];delete elements.rateComment;delete elements.rateVal;}
  }}),
  body:{appendChild(element){calls.appended.push(element);
   if(element.id){elements[element.id]=element;if(element.id==='ratePopup'){
    elements.rateComment={value:''};elements.rateVal={value:'5'};
   }}
  }}
 };
 const context={document,user:viewer,currentUserId:viewer?.userId??viewer?.id??7,_token:'session-one',
  _deals:[structuredClone(record)],window:{},lang:language,
  TRANSLATIONS:{ru:{},ge:{}},getToken:()=>context._token,localStorage:{getItem:()=>context._token},
  translateCity:value=>value,showToastWarn:value=>calls.warnings.push(value),
  pushNotif:(...args)=>calls.notifications.push(args),
  setTimeout:(fn,delay)=>{calls.timers.push({fn,delay});return calls.timers.length;},
  fetch:(url,options)=>{calls.fetch.push({url,options});return context.respond(url,options);},
  respond:async()=>{throw Error('Unexpected request');}
 };
 vm.createContext(context);
 const source=read(path);
 const escStart=source.indexOf('function esc(s) {'),escEnd=source.indexOf('// ── SAFE LOCALSTORAGE',escStart);
 vm.runInContext(source.slice(escStart,escEnd),context);
 const start=source.indexOf('function dealPhoneHref('),end=source.indexOf('function showSection(',start);
 vm.runInContext(source.slice(start,end),context);
 const rateStart=source.indexOf('async function rateDealPrompt('),rateEnd=source.indexOf('async function loadDeals(){',rateStart);
 vm.runInContext(source.slice(rateStart,rateEnd),context);
 const confirmStart=source.indexOf('async function confirmDelivery('),confirmEnd=source.indexOf('// Отклики на мои грузы:',confirmStart);
 vm.runInContext(source.slice(confirmStart,confirmEnd),context);
 return{context,calls,elements,button,
  render(){context.renderCabDeals();return elements.myDealsList.innerHTML;},
  click(id){const html=elements.ratePopup?.innerHTML||'';
   const match=html.match(new RegExp('<button id="'+id+'" onclick="([^"]+)"'));
   assert.ok(match,'Real popup button handler exists: '+id);vm.runInContext(match[1],context);
  },
  flush(delay){const selected=calls.timers.filter(t=>t.delay===delay);calls.timers=calls.timers.filter(t=>t.delay!==delay);selected.forEach(t=>t.fn());}
 };
}
for(const path of ['main.js','frontend/main.js']){
 test(path+': current userId and both legacy identity fallbacks hide only own confirmed button',()=>{
  for(const[viewer,currentId,role]of[[{userId:7,id:8},8,'shipper'],[{id:8},7,'carrier'],[{},8,'carrier']]){
   const h=environment(path,{viewer,record:{...sample,status:'delivered',shipper_confirmed:role==='shipper',carrier_confirmed:role==='carrier'}});
   h.context.currentUserId=currentId;const html=h.render();
   assert.ok(html.includes('Ожидаем подтверждения второй стороны'));
   assert.ok(!html.includes('onclick="confirmDelivery('));
  }
 });
 test(path+': either participant can confirm a delivered deal while the other waits',()=>{
  for(const[id,record]of[[7,{...sample,status:'delivered',carrier_confirmed:true}],[8,{...sample,status:'delivered',shipper_confirmed:true}]]){
   const h=environment(path,{viewer:{userId:id},record});const html=h.render();
   assert.ok(html.includes('onclick="confirmDelivery(31)"'));assert.ok(!html.includes('class="cab-btn pdf"'));
  }
 });
 test(path+': PDF is offered only after completion and no confirm action leaks to nonparticipants',()=>{
  for(const status of ['confirmed','loading','in_transit','delivered','canceled','cancelled','disputed','completed','rated']){
   const h=environment(path,{record:{...sample,status}}),html=h.render();
   assert.equal(html.includes('class="cab-btn pdf"'),['completed','rated'].includes(status),status);
  }
  for(const viewer of [null,{userId:99}]){
   const html=environment(path,{viewer}).render();assert.ok(!html.includes('onclick="confirmDelivery('));
   for(const status of ['completed','rated']){
    const stale=environment(path,{viewer,record:{...completed,status}}).render();
    assert.ok(!stale.includes('class="cab-btn pdf"'),'Stale nonparticipant deal has no act');
    assert.ok(!stale.includes('Акт доступен после подтверждения'),'Act placeholder is for participants');
   }
  }
 });
 test(path+': loading deals retain a confirmation action for either participant',()=>{
  for(const id of [7,8]){
   const html=environment(path,{viewer:{userId:id},record:{...sample,status:'loading'}}).render();
   assert.ok(html.includes('onclick="confirmDelivery(31)"'));
   assert.ok(html.includes('Акт доступен после подтверждения обеих сторон'));
  }
 });
 test(path+': canonical canceled and disputed states use localized labels without actions',()=>{
  for(const[language,status,label]of[['ru','canceled','Отменена'],['ge','canceled','გაუქმებულია'],['ru','disputed','Спор'],['ge','disputed','დავა']]){
   const html=environment(path,{record:{...sample,status},language}).render();
   assert.ok(html.includes(label));assert.ok(!html.includes('onclick="confirmDelivery('));
   assert.ok(!html.includes('onclick="rateDealPrompt('));assert.ok(!html.includes('class="cab-btn pdf"'));
  }
 });
 test(path+': first confirmation renders waiting using canonical flags and preserves contact enrichment',async()=>{
  const h=environment(path);h.context.respond=async()=>response({id:31,status:'delivered',shipper_confirmed:true,carrier_confirmed:false});
  await h.context.confirmDelivery(31);
  const html=h.elements.myDealsList.innerHTML;
  assert.match(h.calls.fetch[0].url,/\/api\/deals\/31\/confirm$/);
  assert.equal(h.calls.fetch[0].options.method,'POST');assert.equal(h.calls.fetch[0].options.headers.Authorization,'Bearer session-one');
  assert.ok(html.includes('Ожидаем подтверждения второй стороны'));assert.ok(!html.includes('onclick="confirmDelivery('));
  assert.ok(html.includes('tel:+995599405060'));assert.equal(h.context._deals[0].status,'delivered');
  assert.ok(!html.includes('class="cab-btn pdf"'));assert.equal(h.button.disabled,false);
 });
 test(path+': second confirmation reveals completed PDF and own available rating',async()=>{
  const h=environment(path,{viewer:{userId:8},record:{...sample,status:'delivered',shipper_confirmed:true}});
  h.context.respond=async()=>response({...completed,viewer_can_rate:true});
  await h.context.confirmDelivery(31);
  const html=h.elements.myDealsList.innerHTML;
  assert.ok(html.includes('/api/deals/31/act.pdf?token=session-one'));assert.ok(html.includes('onclick="rateDealPrompt(31'));
  assert.ok(!html.includes('onclick="confirmDelivery('));assert.equal(h.context._deals[0].status,'completed');
 });
 test(path+': failed confirmation restores the action without changing the deal',async()=>{
  const h=environment(path);h.context.respond=async()=>response({detail:'Подтверждение запрещено'},false);
  await h.context.confirmDelivery(31);
  assert.equal(h.button.disabled,false);assert.equal(h.button.style.opacity,'');
  assert.equal(h.context._deals[0].status,'confirmed');assert.ok(h.calls.warnings[0].includes('Подтверждение запрещено'));
 });
 test(path+': pending confirmation has one request and cannot update a later login',async()=>{
  const h=environment(path),held=deferred();h.context.respond=()=>held.promise;
  const pending=h.context.confirmDelivery(31);await h.context.confirmDelivery(31);
  assert.equal(h.calls.fetch.length,1);assert.equal(h.button.disabled,true);
  h.context.user={userId:7};h.context._token='second-login';h.context._deals=[{id:900,status:'confirmed'}];
  held.resolve(response(completed));await pending;
  assert.equal(h.context._deals[0].id,900);assert.equal(h.calls.notifications.length,0);
  assert.equal(h.calls.timers.length,0);assert.equal(h.elements.myDealsList.innerHTML,'');
 });
 test(path+': delayed canonical deal refresh cannot repopulate a signed-out or new session',async()=>{
  const h=environment(path),held=deferred();
  h.context.respond=(url)=>url.endsWith('/confirm')?Promise.resolve(response({...sample,status:'delivered',shipper_confirmed:true})):held.promise;
  await h.context.confirmDelivery(31);h.flush(300);
  h.context.user=null;h.context._token=null;h.context._deals=[];h.elements.myDealsList.innerHTML='signed-out';
  held.resolve(response({deals:[completed]}));await drain();
  assert.equal(h.context._deals.length,0);assert.equal(h.elements.myDealsList.innerHTML,'signed-out');
 });
 test(path+': rating availability is participant-specific even after global rated status',()=>{
  for(const[record,canRate]of[
   [{...completed},true],
   [{...completed,viewer_can_rate:false,viewer_has_rated:true},false],
   [{...completed,status:'rated',viewer_can_rate:true,counterparty_review:{score:5,comment:'On time'}},true],
   [{...completed,status:'rated',viewer_can_rate:false,legacy_rating:true},false],
   [{...sample,status:'confirmed',viewer_can_rate:true},false]
  ]){
   const h=environment(path,{record}),html=h.render();assert.equal(html.includes('onclick="rateDealPrompt('),canRate);
  }
  const legacy={...completed};delete legacy.viewer_can_rate;
  assert.ok(environment(path,{record:legacy}).render().includes('onclick="rateDealPrompt('));
  legacy.status='rated';assert.ok(!environment(path,{record:legacy}).render().includes('onclick="rateDealPrompt('));
 });
 test(path+': saved own and counterparty reviews are rendered as escaped API text',()=>{
  const h=environment(path,{record:{...completed,status:'rated',viewer_has_rated:true,viewer_can_rate:false,
   my_review:{score:4,comment:'<img src=x onerror=alert(1)>'},counterparty_review:{score:5,comment:'Excellent'}}});
  const html=h.render();
  assert.ok(html.includes('data-review="mine">Ваша оценка: 4/5 · &lt;img'));
  assert.ok(html.includes('data-review="counterparty">Оценка второй стороны: 5/5 · Excellent'));
  assert.ok(!html.includes('<img'));assert.ok(!html.includes('onclick="rateDealPrompt('));
 });
 test(path+': rating popup preserves stars and has role-aware RU and GE titles',async()=>{
  for(const[language,id,title]of[['ru',7,'Оцените перевозчика'],['ru',8,'Оцените отправителя'],['ge',7,'შეაფასეთ გადამზიდველი'],['ge',8,'შეაფასეთ გამგზავნი']]){
   const h=environment(path,{viewer:{userId:id},record:completed,language}),pending=h.context.rateDealPrompt(31,'<QA>');
   const html=h.elements.ratePopup.innerHTML;
   assert.ok(html.includes(title));assert.ok(html.includes('&lt;QA&gt;'));
   assert.equal((html.match(/data-v="/g)||[]).length,5);assert.match(html,/<textarea id="rateComment" maxlength="2000"/);
   h.click('rateCancel');await pending;assert.equal(h.calls.fetch.length,0);
  }
 });
 test(path+': actual rating submit sends score and trimmed review then renders canonical response and refresh',async()=>{
  const h=environment(path,{record:completed}),review={score:4,comment:'Good delivery',created_at:'2026-10-27T12:00:00Z'};
  const rated={...completed,status:'rated',viewer_has_rated:true,viewer_can_rate:false,my_review:review};
  h.context.respond=async url=>url.endsWith('/rate')?response({ok:true,deal_id:31,id:31,status:'rated',
   viewer_has_rated:true,viewer_can_rate:false,my_review:review}):response({deals:[rated]});
  const pending=h.context.rateDealPrompt(31,'QA');h.elements.rateVal.value='4';h.elements.rateComment.value='  Good delivery  ';
  h.click('rateSubmit');await pending;
  assert.deepEqual(JSON.parse(h.calls.fetch[0].options.body),{score:4,comment:'Good delivery'});
  assert.equal(h.calls.fetch[0].options.headers.Authorization,'Bearer session-one');assert.equal(h.calls.fetch[0].options.method,'POST');
  assert.match(h.calls.fetch[0].url,/\/api\/deals\/31\/rate$/);assert.match(h.calls.fetch[1].url,/\/api\/deals\/my$/);
  assert.ok(h.elements.myDealsList.innerHTML.includes('Ваша оценка: 4/5 · Good delivery'));
  assert.ok(h.elements.myDealsList.innerHTML.includes('tel:+995599405060'));
  assert.equal(h.elements.ratePopup,undefined);assert.ok(!h.elements.myDealsList.innerHTML.includes('onclick="rateDealPrompt('));
 });
 test(path+': invalid rating or oversized review is rejected before JSON and request',async()=>{
  for(const[value,comment]of[['0','bad'],['6','bad'],['NaN','bad'],['4','x'.repeat(2001)]]){
   const h=environment(path,{record:completed}),pending=h.context.rateDealPrompt(31,'QA');
   h.elements.rateVal.value=value;h.elements.rateComment.value=comment;h.click('rateSubmit');await pending;
   assert.equal(h.calls.fetch.length,0);assert.equal(h.calls.warnings.length,1);
  }
 });
 test(path+': popup from a previous login cannot submit with the new token',async()=>{
  const h=environment(path,{record:completed}),pending=h.context.rateDealPrompt(31,'QA');
  h.context.user={userId:8};h.context._token='new-login';h.elements.rateComment.value='old-session';h.click('rateSubmit');await pending;
  assert.equal(h.calls.fetch.length,0);assert.equal(h.calls.warnings.length,0);
 });
 test(path+': late rating POST response cannot mutate the next logged-in user cabinet',async()=>{
  const h=environment(path,{record:completed}),held=deferred();h.context.respond=()=>held.promise;
  const pending=h.context.rateDealPrompt(31,'QA');h.click('rateSubmit');await drain();
  h.context.user={userId:8};h.context._token='new-login';h.context._deals=[{id:900,status:'confirmed'}];h.elements.myDealsList.innerHTML='new-user';
  held.resolve(response({...completed,status:'rated',viewer_has_rated:true,viewer_can_rate:false}));await pending;
  assert.equal(h.context._deals[0].id,900);assert.equal(h.elements.myDealsList.innerHTML,'new-user');
  assert.equal(h.calls.fetch.length,1);assert.equal(h.calls.appended.length,1);
 });
 test(path+': late rating canonical refresh is ignored after logout',async()=>{
  const h=environment(path,{record:completed}),held=deferred();
  h.context.respond=url=>url.endsWith('/rate')?Promise.resolve(response({...completed,status:'rated',viewer_can_rate:false,viewer_has_rated:true})):held.promise;
  const pending=h.context.rateDealPrompt(31,'QA');h.click('rateSubmit');await drain();assert.equal(h.calls.fetch.length,2);
  h.context.user=null;h.context._token=null;h.context._deals=[];h.elements.myDealsList.innerHTML='signed-out';
  held.resolve(response({deals:[completed]}));await pending;
  assert.equal(h.context._deals.length,0);assert.equal(h.elements.myDealsList.innerHTML,'signed-out');
 });
 test(path+': rejected review does not claim success or overwrite canonical fields',async()=>{
  const h=environment(path,{record:completed});h.context.respond=async()=>response({detail:'Оценка уже сохранена'},false);
  const pending=h.context.rateDealPrompt(31,'QA');h.click('rateSubmit');await pending;
  assert.equal(h.context._deals[0].status,'completed');assert.ok(h.calls.warnings[0].includes('Оценка уже сохранена'));
  assert.equal(h.calls.fetch.length,1);assert.equal(h.calls.appended.length,1);
 });
}
