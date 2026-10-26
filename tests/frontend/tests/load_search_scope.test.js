import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

function scopeSwitch(path,target){
 const fields={
  fFrom:{value:'Тбилиси'},fTo:{value:'Батуми'},fType:{value:'tent'},
  fWeight:{value:'1000-2000'},fPrice:{value:''},fDate:{value:'week'},
  fDateFrom:{value:'2030-01-01'},fDateTo:{value:'2030-01-07'},
  fCountry:{value:'',style:{}},fcount:{textContent:'before'},
  mapWrap:{classList:{remove(){}}}
 };
 const rows=[
  {id:1,from:'Москва',to:'Тбилиси',type:'tent',kg:1500},
  {id:2,from:'Батуми',to:'Тбилиси',type:'ref',kg:1500},
  {id:3,from:'Кутаиси',to:'Тбилиси',type:'tent',kg:5000}
 ];
 const calls={renders:[],sync:0};
 const ctx={scope:target==='local'?'intl':'local',LOCAL:rows,INTL:rows,
  selectedFrom:{name:'Тбилиси'},selectedTo:{name:'Батуми'},lang:'ru',
  TRANSLATIONS:{ru:{fcount_suffix:'loads',ph_from:'From',ph_to:'To',
   ph_country_from:'Country from',ph_country_to:'Country to'}},
  document:{getElementById:id=>fields[id],querySelectorAll:()=>[]},
  updateFormForIntl(){},
  // Leave refresh unresolved so it cannot repair a bad immediate scope render.
  syncLoadsFromServer(){calls.sync++;return new Promise(()=>{});},
  renderLoads(data){
   calls.renders.push({
    from:fields.fFrom.value,to:fields.fTo.value,type:fields.fType.value,
    weight:fields.fWeight.value,date:fields.fDate.value,
    selectedFrom:ctx.selectedFrom,selectedTo:ctx.selectedTo
   });
   const [min,max]=fields.fWeight.value.split('-').map(Number);
   const visible=data.filter(row=>
    (!fields.fFrom.value||row.from.includes(fields.fFrom.value))&&
    (!fields.fTo.value||row.to.includes(fields.fTo.value))&&
    row.type===fields.fType.value&&row.kg>=min&&row.kg<=max);
   fields.fcount.textContent=visible.length+' visible';
  }
 };
 vm.createContext(ctx);
 const source=readFileSync(new URL('../../../'+path,import.meta.url),'utf8');
 const start=source.indexOf('function setScope(s, el){');
 const end=source.indexOf('// ── LANG / i18n',start);
 assert.ok(start>=0&&end>start,'Extract the real setScope function');
 vm.runInContext(source.slice(start,end),ctx);
 ctx.setScope(target,{classList:{add(){}}});
 return{ctx,fields,calls};
}

for(const path of ['main.js','frontend/main.js']){
 test(path+': scope clears the previous route before the immediate render',()=>{
  for(const target of ['local','intl']){
   const h=scopeSwitch(path,target);
   assert.equal(h.ctx.scope,target);
   assert.equal(h.calls.renders.length,1);
   const rendered=h.calls.renders[0];
   assert.equal(rendered.from,'');assert.equal(rendered.to,'');
   assert.equal(rendered.selectedFrom,null);assert.equal(rendered.selectedTo,null);
   assert.equal(h.calls.sync,1);
  }
 });
 test(path+': changing scope retains the chosen type, weight and date filters',()=>{
  for(const target of ['local','intl']){
   const h=scopeSwitch(path,target),rendered=h.calls.renders[0];
   assert.equal(rendered.type,'tent');assert.equal(rendered.weight,'1000-2000');
   assert.equal(rendered.date,'week');
   assert.equal(h.fields.fType.value,'tent');assert.equal(h.fields.fWeight.value,'1000-2000');
   assert.equal(h.fields.fDate.value,'week');assert.equal(h.fields.fDateFrom.value,'2030-01-01');
   assert.equal(h.fields.fDateTo.value,'2030-01-07');
  }
 });
 test(path+': scope leaves the filtered render count instead of writing the source total',()=>{
  for(const target of ['local','intl']){
   const h=scopeSwitch(path,target);
   assert.equal(h.fields.fcount.textContent,'1 visible');
   assert.equal(h.calls.sync,1);
  }
 });
}
