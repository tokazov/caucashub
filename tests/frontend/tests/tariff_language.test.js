import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const read=path=>readFileSync(new URL('../../../'+path,import.meta.url),'utf8');
const section=(source,start,end)=>{
 const a=source.indexOf(start),b=source.indexOf(end,a);
 assert.ok(a>=0&&b>a,`Missing ${start}`);return source.slice(a,b);
};
const element=()=>({textContent:'',innerHTML:''});
function modal(){
 const title=element(),subtitle=element(),freeNow=element(),soon=element();
 const months=Array.from({length:3},element),plans={};
 for(const name of ['free','pro','business']){
  const features=element(),buy=name==='free'?null:element(),current=name==='free'?element():null,popular=name==='pro'?element():null;
  plans[name]={features,buy,current,popular,querySelector:selector=>({
   '[data-pw-features]':features,'[data-pw-btn]':buy,'#paywallBtnFree':current,'[data-i18n="pw_best"]':popular
  })[selector]||null};
 }
 const selectors={'#paywallTitle':title,'#paywallSub':subtitle,'[data-i18n="pw_free_now"]':freeNow,'[data-i18n="pw_coming_soon"]':soon};
 const pw={dataset:{},classList:{add(name){assert.equal(name,'on');pw.open=true;}},
  querySelector:selector=>plans[selector.match(/^\[data-pw-plan="(.*?)"\]$/)?.[1]]||selectors[selector]||null,
  querySelectorAll:selector=>selector==='[data-i18n="pw_per_month"]'?months:[]};
 return {pw,title,subtitle,freeNow,soon,months,plans};
}
function harness(source){
 const dom=modal(),closed=[];
 const context={...dom,lang:'ru',user:null,closed,
  document:{getElementById:id=>id==='paywallOverlay'?dom.pw:null,
   querySelector:()=>null,querySelectorAll:()=>[]},
  closeModal:id=>closed.push(id),setTimeout:callback=>callback(),
  TRANSLATIONS:{ru:{},ge:{}},window:{}};
 vm.createContext(context);
 vm.runInContext(section(source,'function openPaywall(reason){','function choosePlan('),context);
 vm.runInContext(section(source,'function openPlansModal(e){','// ═══ DEALS'),context);
 vm.runInContext(section(source,'function applyLang(l) {','function setLang('),context);
 return context;
}

for(const prefix of ['', 'frontend/']){
 const source=read(prefix+'main.js'),html=read(prefix+'index.html');
 test(prefix+'tariff HTML uses RU fallback and the localized opener',()=>{
  const block=section(html,'id="paywallOverlay"','id="cargoOverlay"');
  assert.doesNotMatch(block,/[ა-ჰ]/u);
  if(prefix)assert.match(html,/onclick="openPlansModal\(event\)"/);
 });
 test(prefix+'registration tariff opener localizes on every opening and RU/GE switch',()=>{
  const ctx=harness(source);
  ctx.openPlansModal({stopPropagation(){}});
  assert.equal(ctx.pw.open,true);assert.deepEqual(ctx.closed,['authOverlay']);
  assert.equal(ctx.title.textContent,'Тарифные планы');
  assert.match(ctx.plans.free.features.innerHTML,/5 активных грузов/);
  assert.equal(ctx.plans.pro.buy.textContent,'💳 Купить за ₾49');
  assert.equal(ctx.plans.business.buy.textContent,'💳 Купить за ₾149');
  assert.ok(ctx.months.every(el=>el.textContent==='/мес'));
  ctx.lang='ge';ctx.applyLang('ge');
  assert.match(ctx.plans.free.features.innerHTML,/[ა-ჰ]/u);
  assert.match(ctx.plans.pro.buy.textContent,/[ა-ჰ]/u);
  ctx.lang='ru';ctx.applyLang('ru');
  for(const text of [ctx.title,ctx.subtitle,ctx.freeNow,ctx.soon,...ctx.months,
    ...Object.values(ctx.plans).flatMap(p=>[p.features,p.buy,p.current,p.popular]).filter(Boolean)]){
   assert.doesNotMatch(text.textContent+text.innerHTML,/[ა-ჰ]/u);
  }
 });
 test(prefix+'paywall reason survives translation and is cleared for general tariffs',()=>{
  const ctx=harness(source);ctx.openPaywall('respond');
  assert.match(ctx.title.textContent,/откликаться/);
  ctx.lang='ge';ctx.applyLang('ge');assert.match(ctx.title.textContent,/[ა-ჰ]/u);
  ctx.lang='ru';ctx.applyLang('ru');assert.match(ctx.subtitle.textContent,/грузовладельцам/);
  ctx.openPlansModal();assert.equal(ctx.title.textContent,'Тарифные планы');assert.equal(ctx.subtitle.textContent,'');
 });
 for(const [saved,device,expected] of [['ru','ka-GE','ru'],[null,'ru-RU','ru'],[null,'en-US','ru'],
   ['en','en-US','ru'],['invalid','ru-RU','ru'],['ge','ru-RU','ge'],[null,'ka-GE','ge']]){
  test(prefix+`restores language before rendering (${saved}/${device})`,()=>{
   const calls=[],context={localStorage:{getItem:()=>saved},navigator:{language:device},
    document:{querySelector:selector=>({selector})},setLang:(...args)=>calls.push(args)};
   vm.createContext(context);
   vm.runInContext(section(source,'// Always restore a supported language','if(document.readyState'),context);
   assert.equal(calls.length,1);assert.equal(calls[0][0],expected);
   assert.ok(calls[0][1].selector.includes(expected));
  });
 }
}

for(const path of ['main.js','frontend/main.js','frontend/translations.js'])test(path+': every GE translation has a Russian counterpart',()=>{
 const source=read(path),context={window:{}};vm.createContext(context);
 vm.runInContext(section(source,'const TRANSLATIONS =','window.TRANSLATIONS')+'window.T=TRANSLATIONS;',context);
 const {ru,ge}=context.window.T;
 assert.deepEqual(Object.keys(ge).filter(key=>!ru[key]),[]);
 for(const text of Object.values(ru))assert.doesNotMatch(text,/[ა-ჰ]/u);
});
