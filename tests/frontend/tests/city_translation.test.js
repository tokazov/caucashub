import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source=path=>readFileSync(new URL('../../../'+path,import.meta.url),'utf8');
function translator(path,language='ru'){
 const code=source(path),dictionaryStart=code.indexOf('const CITIES = ['),
 dictionaryEnd=code.indexOf('function getTypeLabel',dictionaryStart),
 functionStart=code.indexOf('function _capitalize('),
 functionEnd=code.indexOf('// Получить наиболее конкретный город',functionStart);
 assert.ok(dictionaryStart>=0&&dictionaryEnd>dictionaryStart&&functionEnd>functionStart);
 const context={lang:language};vm.createContext(context);
 // Guard BEFORE evaluating/calling the actual translator. The buggy version
 // catches this exception, so retain a counter and assert it remains zero.
 // Never allow an old implementation to allocate an exponentially large string.
 vm.runInContext(String.raw`
  globalThis.emptySplits=0;
  const originalSplit=String.prototype.split;
  String.prototype.split=function(separator,...rest){
   if(separator===''){globalThis.emptySplits++;throw new Error('Blocked empty translation separator');}
   if(this.length>50000)throw new Error('Blocked oversized translation');
   return originalSplit.call(this,separator,...rest);
  };
 `,context);
 vm.runInContext(code.slice(dictionaryStart,dictionaryEnd)+
  code.slice(functionStart,functionEnd)+
  '\nglobalThis.cities=CITIES;globalThis.regions=REGION_NAMES_GE;',context);
 return{context,translate(name){
  const result=context.translateCity(name);
  assert.equal(context.emptySplits,0,'Reverse translation tried split(\"\")');
  assert.ok(!result||result.length<50000,'Translation output must stay bounded');
  return result;
 }};
}

for(const path of['main.js','frontend/main.js']){
 test(path+': uses the production dictionaries including empty prefix mappings',()=>{
  const{context}=translator(path);
  assert.ok(context.cities.length>100);
  assert.equal(context.regions['город '],'');
  assert.equal(context.regions['край Имеретия'],'იმერეთის მხარე');
 });
 test(path+': Georgian cities translate to Russian without empty splits',()=>{
  const{translate}=translator(path);
  for(const[ge,ru]of[['თბილისი','Тбилиси'],['ბათუმი','Батуми'],['ქუთაისი','Кутаиси'],['მარნეული','Марнеули']])
   assert.equal(translate(ge),ru);
 });
 test(path+': unknown Georgian text is preserved and bounded',()=>{
  const{translate}=translator(path);
  for(const value of['ჭყპტესტი','უცნობი მისამართი 123','თბილისურეთი'])
   assert.equal(translate(value),value);
 });
 test(path+': Georgian region and compound route translate safely',()=>{
  const{translate}=translator(path);
  assert.equal(translate('კახეთის მხარე'),'край Кахетия');
  assert.equal(translate('იმერეთის მხარე, ქუთაისი'),'край Имеретия, Кутаиси');
  assert.equal(translate('თბილისი → ბათუმი'),'Тбилиси → Батуми');
 });
 test(path+': reverse unknown Georgian never performs an empty split',()=>{
  const{translate}=translator(path);
  // Even unknown text enters the reverse-region loop; this catches the OOM
  // independently of successful city lookup.
  assert.equal(translate('ჭყპ'), 'ჭყპ');
 });
 test(path+': lowercase Russian and Latin capitalization remains supported',()=>{
  const{translate}=translator(path);
  assert.equal(translate('тбилиси'),'Тбилиси');
  assert.equal(translate('tbilisi'),'Tbilisi');
  assert.equal(translate('batumi'),'Batumi');
 });
 test(path+': forward Georgian translation still removes every administrative prefix',()=>{
  const{translate,context}=translator(path,'ge');
  const prefixes=Object.entries(context.regions).filter(([,ge])=>ge==='').map(([ru])=>ru);
  assert.equal(prefixes.length,9);
  for(const prefix of prefixes)assert.equal(translate(prefix+'Марнеули'),'მარნეული',prefix);
 });
 test(path+': forward regions, unknown Cyrillic fallback and empty inputs remain supported',()=>{
  const{translate}=translator(path,'ge');
  assert.equal(translate('край Имеретия, Кутаиси'),'იმერეთის მხარე, ქუთაისი');
  assert.equal(translate('Тестоград'),'ტესტოგრად');
  assert.equal(translate(''), '');
  assert.equal(translate(null),null);
 });
}
