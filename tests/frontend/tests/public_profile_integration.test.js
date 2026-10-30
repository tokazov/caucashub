import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
const {JSDOM}=createRequire(import.meta.url)('jsdom');
const source=readFileSync(new URL('../../../frontend/main.js',import.meta.url),'utf8');
const deal=()=>({id:31,status:'completed',shipper_id:7,carrier_id:8,shipper_confirmed:true,carrier_confirmed:true,shipper:{id:7,name:'Shipper'},carrier:{id:8,name:'Carrier'},my_review:{score:5,comment:'Good delivery',public_comment:false},counterparty_review:{score:4,comment:'Peer private text',public_comment:false},viewer_has_rated:true,viewer_can_rate:false});
const reply=(data,ok=true)=>({ok,json:async()=>data});
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return{promise,resolve};};
function setup(t,record=deal()){
 const dom=new JSDOM('<div id="myDealsList"></div>',{runScripts:'outside-only',url:'http://localhost/'}),w=dom.window;t.after(()=>w.close());
 const calls=[],warnings=[];let token='local-token';
 Object.assign(w,{user:{userId:7},currentUserId:7,_deals:[structuredClone(record)],lang:'ru',API_BASE:'http://localhost',TRANSLATIONS:{ru:{},ge:{}},getToken:()=>token,showToastWarn:m=>warnings.push(m),console:{...console,log(){}}});
 w.fetch=async(url,options)=>{calls.push({url,options});return reply({ok:true,my_review:{score:5,comment:'Good delivery',public_comment:true}});};
 const escStart=source.indexOf('function esc(s) {');w.eval(source.slice(escStart,source.indexOf('// ── SAFE LOCALSTORAGE',escStart)));
 const helperStart=source.indexOf('function dealPhoneHref(');w.eval(source.slice(helperStart,source.indexOf('function showSection(',helperStart)));
 const rateStart=source.indexOf('async function rateDealPrompt(');w.eval(source.slice(rateStart,source.indexOf('async function loadDeals(){',rateStart)));
 return{w,calls,warnings,node:id=>w.document.getElementById(id),setToken:value=>{token=value;}};
}
test('only the author own review has a public-comment control and existing private text stays private',t=>{
 const h=setup(t);h.w.renderCabDeals();const root=h.node('myDealsList'),buttons=root.querySelectorAll('[data-review-visibility-deal]');assert.equal(buttons.length,1);assert.equal(buttons[0].getAttribute('aria-pressed'),'false');assert.match(buttons[0].textContent,/Показать текст/);assert.equal(root.querySelector('[data-review="counterparty"] button'),null);assert.match(root.querySelector('[data-review="counterparty"]').textContent,/только участникам/);
});
test('visibility update sends only explicit boolean and preserves score/comment',async t=>{
 const h=setup(t);h.w.renderCabDeals();const button=h.node('myDealsList').querySelector('button[data-review-visibility-deal]');await h.w.setReviewVisibility(31,true,button);assert.equal(h.calls.length,1);assert.equal(h.calls[0].url,'http://localhost/api/deals/31/review-visibility');assert.equal(h.calls[0].options.method,'PATCH');assert.deepEqual(JSON.parse(h.calls[0].options.body),{public_comment:true});assert.equal(h.w._deals[0].my_review.score,5);assert.equal(h.w._deals[0].my_review.comment,'Good delivery');assert.equal(h.w._deals[0].my_review.public_comment,true);assert.match(h.node('myDealsList').textContent,/Скрыть текст/);
});
test('duplicate clicks wait for the same author request',async t=>{
 const h=setup(t),pending=deferred();h.w.fetch=(url,options)=>{h.calls.push({url,options});return pending.promise;};h.w.renderCabDeals();const button=h.node('myDealsList').querySelector('[data-review-visibility-deal]');const first=h.w.setReviewVisibility(31,true,button);await h.w.setReviewVisibility(31,true,button);assert.equal(h.calls.length,1);assert.equal(button.disabled,true);pending.resolve(reply({my_review:{public_comment:true}}));await first;assert.equal(h.node('myDealsList').querySelector('[data-review-visibility-deal]').disabled,false);
});
test('late visibility response cannot mutate another signed-in account',async t=>{
 const h=setup(t),pending=deferred();h.w.fetch=()=>pending.promise;const request=h.w.setReviewVisibility(31,true);h.w.user={userId:8};h.setToken('another-token');pending.resolve(reply({my_review:{public_comment:true}}));await request;assert.equal(h.w._deals[0].my_review.public_comment,false);assert.equal(h.warnings.length,0);
});
test('server rejection keeps the old visibility and allows a retry',async t=>{
 const h=setup(t);h.w.fetch=async()=>reply({detail:'Not allowed'},false);h.w.renderCabDeals();const button=h.node('myDealsList').querySelector('[data-review-visibility-deal]');await h.w.setReviewVisibility(31,true,button);assert.equal(h.w._deals[0].my_review.public_comment,false);assert.equal(button.disabled,false);assert.deepEqual(h.warnings,['Not allowed']);
});
test('nonparticipants and reviews without text cannot request publication',async t=>{
 const h=setup(t);h.w.user={userId:999};await h.w.setReviewVisibility(31,true);assert.equal(h.calls.length,0);h.w.user={userId:7};h.w._deals[0].my_review.comment='';await h.w.setReviewVisibility(31,true);assert.equal(h.calls.length,0);h.w.renderCabDeals();assert.equal(h.node('myDealsList').querySelector('[data-review-visibility-deal]'),null);
});
for(const publish of [false,true])test('new review text publication requires explicit checkbox: '+publish,async t=>{
 const record=deal();Object.assign(record,{my_review:null,counterparty_review:null,viewer_has_rated:false,viewer_can_rate:true});const h=setup(t,record);
 h.w.fetch=async(url,options)=>{h.calls.push({url,options});const reviewed={...record,status:'rated',my_review:{score:4,comment:'Good delivery',public_comment:publish},viewer_has_rated:true,viewer_can_rate:false};return url.endsWith('/rate')?reply({...reviewed,ok:true}):reply({deals:[reviewed]});};
 const request=h.w.rateDealPrompt(31,'TEST');const checkbox=h.node('ratePublicComment');assert.equal(checkbox.checked,false);assert.match(checkbox.parentNode.textContent,/публичном профиле/);checkbox.checked=publish;h.node('rateComment').value=' Good delivery ';h.w._rateResolve(4);await request;assert.deepEqual(JSON.parse(h.calls[0].options.body),{score:4,comment:'Good delivery',public_comment:publish});
});
test('both counterpart names delegate public numeric IDs without exposing private contact fields',t=>{
 const h=setup(t),seen=[];h.w.CaucasPublicProfile={link:(name,id)=>{seen.push({name,id});return '<button data-test-profile="'+id+'">'+h.w.esc(name)+'</button>';}};h.w.renderCabDeals();assert.ok(seen.some(x=>x.name==='Shipper'&&x.id===7));assert.ok(seen.some(x=>x.name==='Carrier'&&x.id===8));assert.equal(h.calls.length,0);
});
