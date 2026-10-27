import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source=path=>readFileSync(new URL('../../../'+path,import.meta.url),'utf8');
const saved={ok:true,load:{id:31,serverId:31,from:'Tbilisi',to:'Batumi',price:375.5,
  date:'27.10.30',load_date:'2030-10-27',load_date_end:'2030-10-30'}};

function form(path,{scope='local',reply=saved,token='test-token',missingClient=false}={}) {
  const code=source(path),calls={requests:[],warnings:[],auth:[],closed:[],timers:[],limits:[]};
  const button={disabled:false,textContent:'Submit'};
  const fields={pFromAddr:{value:'Tbilisi'},pToAddr:{value:'Batumi'},pWeight:{value:'1250.5'},
    pPrice:{value:'375.5'},pTruck:{value:'tent',selectedIndex:0,options:[{text:'Тент'}]},
    pDesc:{value:'Test cargo'},pPay:{value:'cash'},pUrgent:{checked:false},
    pDate:{value:'2030-10-27'},pDate2:{value:'2030-10-30'},postSuccess:{style:{display:'none'}},fcount:{}};
  const context={document:{getElementById:id=>fields[id],querySelector:()=>button},window:{},
    TRANSLATIONS:{ru:{warn_network:'Network error',warn_login:'Please sign in'}},lang:'ru',scope,
    user:{email:'shipper@example.test',name:'Test shipper'},currentUserId:7,addrSelected:{},
    LOCAL:[],INTL:[],_myLoads:[],_postLoadIdempotencyKey:'form-key',_postLoadSubmitting:false,
    _editingLoadId:null,_genUUID:()=> 'retry-key',getToken:()=>token,setToken:()=>{},
    showToastWarn:message=>calls.warnings.push(message),openAuth:mode=>calls.auth.push(mode),
    closeModal:id=>calls.closed.push(id),renderLoads:()=>{},persistMyLoads:()=>{},
    setTimeout:callback=>calls.timers.push(callback),showLimitModal:data=>calls.limits.push(data)};
  context.addMyLoad=load=>context._myLoads.unshift(load);
  if(!missingClient) context.CaucasAPI={createLoad:async(load,key)=>{
    calls.requests.push({load,key});return typeof reply==='function'?await reply():reply;
  }};
  vm.createContext(context);
  const api=source('frontend/api.js');
  vm.runInContext(api.slice(api.indexOf('// Calendar days in Georgia'),api.indexOf('// ── AUTH ─')),context);
  const dates=code.indexOf('function readPostLoadingDates(');
  vm.runInContext(code.slice(dates,code.indexOf('function openPostLoad(',dates)),context);
  const start=code.indexOf('async function doPostLoad()');
  vm.runInContext(code.slice(start,code.indexOf('// Массив своих грузов',start)),context);
  return {context,calls,fields,button};
}

for(const path of ['main.js','frontend/main.js']) {
  test(path+': waits for server confirmation and ignores a second click',async()=>{
    let resolve;
    const {context,calls,fields,button}=form(path,{reply:()=>new Promise(r=>{resolve=r;})});
    const pending=context.doPostLoad();
    await context.doPostLoad();
    assert.equal(calls.requests.length,1);
    assert.equal(button.disabled,true);
    assert.equal(context.LOCAL.length,0);
    assert.equal(context._myLoads.length,0);
    assert.equal(fields.postSuccess.style.display,'none');
    assert.equal(calls.timers.length,0);
    resolve(saved);await pending;
    assert.equal(context.LOCAL.length,1);
    assert.equal(context._myLoads.length,1);
    assert.equal(context.LOCAL[0].id,31);
    assert.equal(context.LOCAL[0].price,375.5);
    assert.equal(calls.requests[0].load.kg,1250.5);
    assert.equal(fields.postSuccess.style.display,'block');
    assert.equal(calls.closed.length,0);
    calls.timers[0]();
    assert.deepEqual(calls.closed,['postOverlay']);
  });

  test(path+': international load keeps its original scope during a slow request',async()=>{
    let resolve;
    const {context,calls}=form(path,{scope:'intl',reply:()=>new Promise(r=>{resolve=r;})});
    const pending=context.doPostLoad();context.scope='local';resolve(saved);await pending;
    assert.equal(calls.requests[0].load.scope,'intl');
    assert.equal(calls.requests[0].load.cur,'$');
    assert.equal(context.LOCAL.length,0);
    assert.equal(context.INTL[0].serverId,31);
  });

  for(const reply of [
    {ok:false,status:0,error:'offline'}, {ok:false,status:422,error:'Invalid weight'},
    {ok:false,status:500,error:'Server error'}, {ok:true,load:{id:31}},
  ]) test(path+': failed publication keeps the draft and has no ghost listing ('+(reply.status||'malformed')+')',async()=>{
    const {context,calls,fields,button}=form(path,{reply});
    await context.doPostLoad();
    assert.equal(context.LOCAL.length+context.INTL.length+context._myLoads.length,0);
    assert.equal(fields.postSuccess.style.display,'none');
    assert.equal(fields.pFromAddr.value,'Tbilisi');
    assert.equal(fields.pDate2.value,'2030-10-30');
    assert.equal(calls.timers.length+calls.closed.length,0);
    assert.equal(button.disabled,false);
    assert.equal(context._postLoadIdempotencyKey,'form-key');
    assert.equal(calls.warnings.length,1);
  });

  test(path+': lost response can be retried with the same idempotency key',async()=>{
    const {context,calls}=form(path,{reply:()=>{throw Error('connection lost');}});
    await context.doPostLoad();
    context.CaucasAPI.createLoad=async(load,key)=>{calls.requests.push({load,key});return saved;};
    await context.doPostLoad();
    assert.deepEqual(calls.requests.map(r=>r.key),['form-key','form-key']);
    assert.equal(context._myLoads.length,1);
    assert.equal(context.LOCAL.length,1);
  });

  test(path+': expired login and tariff limits preserve the entered form',async()=>{
    for(const error of ['session_expired','limit_exceeded']) {
      const {context,calls,fields}=form(path,{reply:{ok:false,error,limitData:{limit:5}}});
      await context.doPostLoad();
      assert.equal(context._myLoads.length,0);
      assert.equal(fields.postSuccess.style.display,'none');
      assert.equal(fields.pWeight.value,'1250.5');
      assert.equal(calls.closed.length,0);
      assert.equal(error==='session_expired'?calls.auth[0]:calls.limits[0].limit,error==='session_expired'?'login':5);
    }
  });

  test(path+': validation never invents missing cities or weight',async()=>{
    for(const [field,value] of [['pFromAddr',''],['pToAddr',','],['pWeight',''],['pWeight','0'],['pWeight','50001'],['pPrice','0']]) {
      const {context,calls,fields,button}=form(path);fields[field].value=value;
      await context.doPostLoad();
      assert.equal(calls.requests.length,0);
      assert.equal(context._myLoads.length,0);
      assert.equal(button.disabled,false);
      assert.equal(calls.warnings.length,1);
    }
  });

  test(path+': missing login or API client cannot create local success',async()=>{
    for(const opts of [{token:null},{missingClient:true}]) {
      const {context,calls,fields}=form(path,opts);await context.doPostLoad();
      assert.equal(context._myLoads.length,0);
      assert.equal(fields.postSuccess.style.display,'none');
      assert.equal(calls.requests.length,0);
      assert.equal(calls.warnings.length,1);
    }
  });

  test(path+': replay updates a record already refreshed from the server',async()=>{
    const {context}=form(path);
    context.LOCAL.push({id:31,serverId:31});context._myLoads.push({id:31,serverId:31});
    await context.doPostLoad();
    assert.equal(context.LOCAL.length,1);assert.equal(context._myLoads.length,1);
    assert.equal(context.LOCAL[0].from,'Tbilisi');
  });

  test(path+': previous success timer cannot close a new publication form',async()=>{
    const {context,calls}=form(path);await context.doPostLoad();
    context._postLoadIdempotencyKey='new-form-key';calls.timers[0]();
    assert.equal(calls.closed.length,0);
  });

  test(path+': unavailable API cannot fake login or registration',async()=>{
    const code=source(path);
    for(const [name,end] of [['doLogin','async function doRegister'],['doRegister','function showUserState']]) {
      const warnings=[],context={TRANSLATIONS:{ru:{}},lang:'ru',showToastWarn:s=>warnings.push(s)};
      vm.createContext(context);
      const start=code.indexOf('async function '+name+'(');
      vm.runInContext(code.slice(start,code.indexOf(end,start+1)),context);
      await context[name]();assert.equal(warnings.length,1);assert.equal(context.user,undefined);
    }
  });
}

for(const path of ['api.js','frontend/api.js']) {
  function client(result) {
    const code=source(path),calls=[],context={setToken:()=>{},apiRequest:async(...args)=>{calls.push(args);return result;}};
    vm.createContext(context);
    const helpers=code.slice(code.indexOf('// Calendar days in Georgia'),code.indexOf('// ── AUTH ─'));
    const start=code.indexOf('const CaucasAPI ='),end=code.indexOf('\n};',start)+3;
    const mapping=code.indexOf('function mapServerLoad(l){'),mappingEnd=code.indexOf('// FIX: openPlansModal',mapping);
    vm.runInContext(helpers+code.slice(start,end)+code.slice(mapping,mappingEnd),context);
    return {api:vm.runInContext('CaucasAPI',context),calls};
  }
  test(path+': publication includes a reusable request key',async()=>{
    const {api,calls}=client({ok:false,status:500});
    await api.createLoad({from:'Tbilisi',to:'Batumi',date:'27.10.30'},'same-key');
    assert.equal(calls[0][3]['Idempotency-Key'],'same-key');
  });
  test(path+': client preserves auth errors and classifies publication failures',async()=>{
    for(const status of [0,401,422]) {
      const {api}=client({ok:false,status,data:{detail:'Test error'}});
      assert.equal((await api.register({})).status,status);
      assert.equal((await api.login({})).status,status);
      const published=await api.createLoad({date:'27.10.30'});
      assert.equal(published.status,status);
      if(status===401) assert.equal(published.error,'session_expired');
    }
  });
}

for(const path of ['main.js','frontend/main.js']) {
  for(const [status,body,changedCargo=false] of [
    [500,{error:'server failure'}],[200,{}],[200,null],[200,{ok:true,response_id:77}],
    [200,{ok:true,response_id:77},true],[401,{detail:'Invalid token'}],
    [403,{detail:'Account blocked'}],[403,{detail:{error:'limit_exceeded'}}],
  ]) {
    test(path+': response requires a confirmed ID ('+status+','+JSON.stringify(body)+','+changedCargo+')',async()=>{
      let resolve;const requests=[],orders=[],warnings=[],paywalls=[],auth=[];
      const button={disabled:false},success={style:{display:'none'}};
      const context={user:{email:'carrier@example.test',role:'both'},getToken:()=> 'test',
        canRespond:()=>true,document:{getElementById:id=>id==='btnRespond'?button:id==='respondSuccess'?success:{value:''}},
        TRANSLATIONS:{ru:{}},lang:'ru',window:{currentCargoData:{id:31,serverId:31}},
        fetch:(...args)=>{requests.push(args);return new Promise(r=>{resolve=r;});},
        addToOrders:(id,cargo)=>orders.push({id,cargo}),showToastWarn:message=>warnings.push(message),
        closeModal:()=>{},openPaywall:kind=>paywalls.push(kind),openAuth:mode=>auth.push(mode),
        setToken:()=>{},localStorage:{removeItem:()=>{}}};
      vm.createContext(context);const code=source(path),start=code.indexOf('function doRespond(){');
      vm.runInContext(code.slice(start,code.indexOf('function addToOrders(',start)),context);
      context.doRespond();context.doRespond();assert.equal(requests.length,1);
      if(changedCargo) context.window.currentCargoData={id:52,serverId:52};
      resolve({status,ok:status<400,json:async()=>body});
      await new Promise(setImmediate);
      const confirmed=body?.response_id===77;
      assert.equal(orders.length,confirmed?1:0);
      assert.equal(success.style.display,confirmed&&!changedCargo?'block':'none');
      if(confirmed) assert.equal(orders[0].cargo.id,31);
      if(!confirmed){
        assert.equal(button.disabled,false);
        if(status===401) assert.deepEqual(auth,['login']);
        else if(body?.detail?.error==='limit_exceeded') assert.deepEqual(paywalls,['respond']);
        else {assert.equal(warnings.length,1);assert.equal(paywalls.length,0);}
      }
    });
  }
}

for(const path of ['main.js','frontend/main.js']) {
  for(const method of ['submitTransportRequest','submitTransportOffer']) {
    for(const valid of [false,true]) test(path+': '+method+' confirms an ID and prevents repeated sends ('+valid+')',async()=>{
      const code=source(path),button={disabled:false},requests=[],closed=[],notifications=[],timers=[];
      const fields={
        trDesc:{value:'Cargo'},trWeight:{value:'3000'},trMsg:{value:''},trError:{style:{}},
        ptFrom:{value:'Tbilisi'},ptTo:{value:'Batumi'},ptTruckType:{value:'tent'},
        ptCapacity:{value:'10000'},ptDateFrom:{value:'2030-10-27'},ptDateTo:{value:''},
        ptPrice:{value:'500'},ptNotes:{value:''},ptUrgent:{checked:false},ptError:{style:{}},
        postTransportSuccess:{style:{display:'none'}}};
      let resolve;
      const context={window:{},document:{getElementById:id=>fields[id],querySelector:()=>button},
        getToken:()=> 'test',TRANSLATIONS:{ru:{}},lang:'ru',API_BASE:'https://api.example.test',
        _currentTransportOfferId:17,_currentTransportMaxKg:10000,
        _transportRequestSubmitting:false,_transportOfferSubmitting:false,
        fetch:(...args)=>{requests.push(args);return new Promise(r=>{resolve=r;});},
        closeModal:id=>closed.push(id),pushNotif:message=>notifications.push(message),showToastWarn:message=>notifications.push(message),
        setTimeout:callback=>timers.push(callback),loadTransportOffers:()=>{}};
      vm.createContext(context);
      const start=code.indexOf('window.'+method+' = async function()');
      const end=code.indexOf('\n};',start)+4;
      vm.runInContext(code.slice(start,end),context);
      const pending=context.window[method]();await context.window[method]();
      assert.equal(requests.length,1);assert.equal(button.disabled,true);
      const body=valid?{ok:true,request:{id:71},offer:{id:72}}:{};
      resolve({status:201,ok:true,json:async()=>body});await pending;
      if(method==='submitTransportRequest') {
        assert.equal(closed.length,valid?1:0);assert.equal(notifications.length,valid?1:0);
        assert.equal(context._transportRequestSubmitting,false);
      } else {
        assert.equal(fields.postTransportSuccess.style.display,valid?'block':'none');
        assert.equal(button.disabled,valid);
        assert.equal(context._transportOfferSubmitting,false);
        if(valid) {await context.window[method]();assert.equal(requests.length,1);}
      }
      if(!valid){assert.equal(timers.length,0);assert.equal(button.disabled,false);}
    });
  }
}
