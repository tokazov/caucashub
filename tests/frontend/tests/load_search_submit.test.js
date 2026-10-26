import {test} from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';

const source=path=>readFileSync(new URL('../../../'+path,import.meta.url),'utf8');
function form(prefix,{realPeriod=false}={}){
 const html=source(prefix+'index.html'),code=source(prefix+'main.js');
 const markup=html.match(/<form\b[^>]*class="[^"]*\bload-filters\b[^"]*"[^>]*>/)?.[0];
 assert.ok(markup,'load search form exists');
 const handler=markup.match(/onsubmit="([^"]+)"/)?.[1];
 assert.ok(handler,'native form submit handler exists');
 assert.match(html,/<button\b[^>]*type="submit"[^>]*id="loadSearchBtn"/);
 const calls={prevented:0,applied:0,filtered:[],warnings:[]},options=[];
 const fields={fDate:{value:'',querySelector:()=>options.find(o=>o.value==='pick_range')||null,
  appendChild:option=>options.push(option)},fDateFrom:{value:''},fDateTo:{value:''},
  datePeriodPop:{style:{display:'block'}}};
 const context={document:{getElementById:id=>fields[id],createElement:()=>({})},
  applyDatePeriod:()=>calls.applied++,filterLoads:()=>calls.filtered.push(fields.fDate.value),
  showToastWarn:message=>calls.warnings.push(message),displayLoadingDay:value=>value};
 vm.createContext(context);
 const start=code.indexOf('function submitLoadSearch()');
 assert.ok(start>=0,'actual submission helper exists');
 vm.runInContext(code.slice(start,code.indexOf('function filterLoads(',start)),context);
 if(realPeriod){
  const period=code.indexOf('function applyDatePeriod()');
  vm.runInContext(code.slice(period,code.indexOf('function clearDatePeriod()',period)),context);
 }
 return {fields,calls,options,submit:via=>{
  context.event={type:'submit',submitter:via==='find'?{id:'loadSearchBtn'}:null,
   preventDefault:()=>calls.prevented++};
  vm.runInContext('(function(event){'+handler+'})(event);',context);
 }};
}
for(const prefix of ['','frontend/']){
 for(const via of ['enter','find']){
  test(prefix+via+': pending period applies instead of filtering immediately',()=>{
   const h=form(prefix);h.fields.fDate.value='pick';h.submit(via);
   assert.equal(h.calls.prevented,1);assert.equal(h.calls.applied,1);assert.equal(h.calls.filtered.length,0);
  });
  for(const value of ['','today','pick_range'])test(prefix+via+': '+(value||'all dates')+' filters normally',()=>{
   const h=form(prefix);h.fields.fDate.value=value;h.submit(via);
   assert.equal(h.calls.prevented,1);assert.equal(h.calls.applied,0);assert.deepEqual(h.calls.filtered,[value]);
  });
 }
 test(prefix+'submit rejects a reversed pending period and keeps its editor open',()=>{
  const h=form(prefix,{realPeriod:true});h.fields.fDate.value='pick';
  h.fields.fDateFrom.value='2030-01-05';h.fields.fDateTo.value='2030-01-04';h.submit('enter');
  assert.equal(h.calls.prevented,1);assert.equal(h.calls.warnings.length,1);
  assert.equal(h.calls.filtered.length,0);assert.equal(h.fields.fDate.value,'pick');
  assert.equal(h.fields.datePeriodPop.style.display,'block');assert.equal(h.options.length,0);
 });
 test(prefix+'submit commits a valid pending period before filtering',()=>{
  const h=form(prefix,{realPeriod:true});h.fields.fDate.value='pick';
  h.fields.fDateFrom.value='2030-01-04';h.fields.fDateTo.value='2030-01-05';h.submit('find');
  assert.equal(h.calls.warnings.length,0);assert.deepEqual(h.calls.filtered,['pick_range']);
  assert.equal(h.fields.fDate.value,'pick_range');assert.equal(h.fields.datePeriodPop.style.display,'none');
  assert.equal(h.options[0].value,'pick_range');
 });
}
