import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

function source(path) { return readFileSync(new URL('../../../'+path,import.meta.url),'utf8'); }
function helpers(code) { return code.slice(code.indexOf('// Calendar days in Georgia'),code.indexOf('// ── AUTH ─')); }
function client(path, fail=false) {
  const code=source(path), calls=[];
  const context={apiRequest:async(method,url,body)=>{
    calls.push({method,url,body});
    if(fail) return {ok:false,status:422,data:{detail:'Invalid period'}};
    return {ok:true,data:{id:7,from:'Tbilisi',to:'Batumi',
      load_date:body.load_date || '2030-10-27',
      load_date_end:body.load_date_end ?? null}};
  }};
  vm.createContext(context);
  const a=code.indexOf('const CaucasAPI ='),b=code.indexOf('\n};',a)+3;
  const m=code.indexOf('function mapServerLoad(l){'),n=code.indexOf('// FIX: openPlansModal',m);
  vm.runInContext(helpers(code)+code.slice(a,b)+code.slice(m,n),context);
  return {api:vm.runInContext('CaucasAPI',context),context,calls};
}

for(const path of ['api.js','frontend/api.js']) {
  test(path+': create sends selected days instead of the current time',async()=>{
    const {api,calls}=client(path);
    const r=await api.createLoad({from:'Tbilisi',to:'Batumi',kg:1000,price:500,cur:'₾',
      date:'27.10.30',date2:'30.10.2030'});
    assert.equal(r.ok,true);
    assert.equal(calls[0].body.load_date,'2030-10-27');
    assert.equal(calls[0].body.load_date_end,'2030-10-30');
    assert.equal(r.load.date2,'30.10.30');
    assert.equal(r.load.load_date,'2030-10-27');
  });
  test(path+': invalid dates fail before making a request',async()=>{
    const {api,calls}=client(path);
    for(const period of [
      {date:'31.02.30'},{date:''},{date:'27.10.30',date2:'26.10.30'}
    ]) assert.equal((await api.createLoad(period)).ok,false);
    assert.equal(calls.length,0);
  });
  test(path+': partial edit preserves omitted end and explicitly clears null',async()=>{
    const {api,calls}=client(path);
    await api.updateLoad(7,{date:'28.10.30',date2:null});
    assert.equal(calls[0].body.load_date,'2030-10-28');
    assert.equal(calls[0].body.load_date_end,null);
    await api.updateLoad(7,{desc:'Changed notes'});
    assert.equal(Object.hasOwn(calls[1].body,'load_date_end'),false);
    assert.equal(Object.hasOwn(calls[1].body,'load_date'),false);
  });
  test(path+': error from server is returned to the editor',async()=>{
    const {api}=client(path,true);
    const result=await api.updateLoad(7,{date:'28.10.30'});
    assert.equal(result.ok,false);
    assert.equal(result.error,'Invalid period');
  });
  test(path+': Georgian day changes at 20:00 UTC in any browser timezone',()=>{
    const {context}=client(path);
    assert.equal(vm.runInContext("loadingDayToday(new Date('2026-10-26T19:59:59Z'))",context),'2026-10-26');
    assert.equal(vm.runInContext("loadingDayToday(new Date('2026-10-26T20:00:00Z'))",context),'2026-10-27');
    assert.equal(vm.runInContext("loadDateISO('29.02.2028')",context),'2028-02-29');
  });
}

for(const path of ['main.js','frontend/main.js']) {
  test(path+': period search uses overlapping days',()=>{
    const code=source(path),apiCode=source('frontend/api.js');
    const a=code.indexOf('function filterLoadingDates('),b=code.indexOf('function filterByDate(',a);
    const context={};vm.createContext(context);
    vm.runInContext(helpers(apiCode)+code.slice(a,b),context);
    const result=vm.runInContext("filterLoadingDates([{date:'25.10.30',date2:'28.10.30'},{date:'29.10.30'}],['2030-10-27','2030-10-27'])",context);
    assert.equal(result.length,1);
    assert.equal(result[0].date,'25.10.30');
  });

  for(const ok of [false,true]) test(path+': editor '+(ok?'persists server response':'keeps previous data on failure'),async()=>{
    const code=source(path),apiCode=source('frontend/api.js');
    const fields={
      pFromAddr:{value:'Tbilisi'},pToAddr:{value:'Batumi'},pWeight:{value:'1000'},
      pPrice:{value:'500'},pTruck:{value:'tent'},pDesc:{value:'Updated'},pPay:{value:'cash'},
      pUrgent:{checked:false},pDate:{value:'2030-10-28'},pDate2:{value:'2030-10-30'}
    };
    const original={id:7,serverId:7,fromServer:true,from:'Tbilisi',to:'Batumi',cur:'₾',load_date:'2030-10-27'};
    const button={disabled:false},calls={closed:0,warnings:[],saved:0,updates:null};
    const context={document:{getElementById:id=>fields[id],querySelector:()=>button},
      _editingLoadId:7,_myLoads:[{...original}],LOCAL:[{...original}],INTL:[],
      addrSelected:{},window:{},scope:'local',getToken:()=> 'test',
      showToastWarn:text=>calls.warnings.push(text),closeModal:()=>calls.closed++,
      renderLoads:()=>{},persistMyLoads:()=>calls.saved++,
      CaucasAPI:{updateLoad:async(id,updates)=>{calls.updates=updates;return ok
        ? {ok:true,load:{...original,load_date:'2030-10-28',load_date_end:'2030-10-30'}}
        : {ok:false,error:'Not saved'};}}};
    vm.createContext(context);
    const datesStart=code.indexOf('function readPostLoadingDates('),datesEnd=code.indexOf('function openPostLoad(',datesStart);
    const a=code.indexOf('async function saveEditedLoad('),b=code.indexOf('// ── FILTER',a);
    vm.runInContext(helpers(apiCode)+code.slice(datesStart,datesEnd)+code.slice(a,b),context);
    await vm.runInContext('saveEditedLoad()',context);
    assert.equal(calls.updates.load_date,'2030-10-28');
    assert.equal(calls.updates.load_date_end,'2030-10-30');
    assert.equal(context._myLoads[0].load_date,ok?'2030-10-28':'2030-10-27');
    assert.equal(calls.closed,ok?1:0);
    assert.equal(calls.saved,ok?1:0);
    assert.equal(button.disabled,false);
    if(!ok) assert.equal(calls.warnings[0],'Not saved');
  });
}
