// ── CaucasHub API Client ──────────────────────────────
// Все запросы к Railway бэкенду

const API_BASE = 'https://api-production-f3ea.up.railway.app';

// Токен из localStorage
function getToken(){ return localStorage.getItem('ch_token') || null; }
function setToken(t){ if(t) localStorage.setItem('ch_token',t); else localStorage.removeItem('ch_token'); }


async function apiRequest(method, path, body=null, extraHeaders={}){
  const headers = { 'Content-Type': 'application/json', ...extraHeaders };
  const token = getToken();
  if(token) headers['Authorization'] = 'Bearer ' + token;

  const opts = { method, headers, signal: AbortSignal.timeout(10000) };
  if(body) opts.body = JSON.stringify(body);

  try {
    const resp = await fetch(API_BASE + path, opts);
    const data = await resp.json().catch(()=>null);
    return { ok: resp.ok, status: resp.status, data };
  } catch(e) {
    console.warn('[API]', method, path, e.message);
    return { ok: false, status: 0, data: null, error: e.message };
  }
}

// Calendar days in Georgia must not depend on the browser's timezone.
function loadingDayToday(now = new Date()) {
  const p = Object.fromEntries(new Intl.DateTimeFormat('en-CA', {
    timeZone:'Asia/Tbilisi', year:'numeric', month:'2-digit', day:'2-digit'
  }).formatToParts(now).map(x => [x.type,x.value]));
  return p.year + '-' + p.month + '-' + p.day;
}
function shiftLoadingDay(day, offset) {
  const d = new Date(day + 'T00:00:00Z');
  d.setUTCDate(d.getUTCDate() + offset);
  return d.toISOString().slice(0,10);
}
function loadDateISO(value) {
  if(value === null || value === undefined || value === '') return null;
  let s = String(value).trim();
  if(s === 'today') return loadingDayToday();
  if(s === 'tomorrow') return shiftLoadingDay(loadingDayToday(),1);
  const old = s.match(/^(\d{2})\.(\d{2})\.(\d{2}|\d{4})$/);
  if(old) s = (old[3].length===2?'20'+old[3]:old[3])+'-'+old[2]+'-'+old[1];
  if(!/^\d{4}-\d{2}-\d{2}$/.test(s)) throw new Error('Укажите корректную дату загрузки');
  const d = new Date(s+'T00:00:00Z');
  if(!Number.isFinite(d.getTime()) || d.toISOString().slice(0,10)!==s || s.slice(0,4)==='0000')
    throw new Error('Укажите корректную дату загрузки');
  return s;
}
function displayLoadingDay(value) {
  const d=loadDateISO(value);
  return d ? d.slice(8,10)+'.'+d.slice(5,7)+'.'+d.slice(2,4) : null;
}
function loadingDatesPayload(load, partial=false) {
  const own=name=>Object.prototype.hasOwnProperty.call(load,name), dates={};
  if(!partial || own('load_date') || own('date')) {
    dates.load_date=loadDateISO(own('load_date')?load.load_date:load.date);
    if(!dates.load_date) throw new Error('Укажите дату загрузки');
  }
  if(!partial || own('load_date_end') || own('date2'))
    dates.load_date_end=loadDateISO(own('load_date_end')?load.load_date_end:load.date2);
  if(dates.load_date && dates.load_date_end && dates.load_date_end<dates.load_date)
    throw new Error('Дата окончания не может быть раньше даты начала');
  return dates;
}
function loadingRequestError(detail) {
  return typeof detail==='string' ? detail : Array.isArray(detail)
    ? detail.map(x=>x.msg||'').join('; ') : 'Не удалось сохранить груз';
}

// Profile capacities are tonnes. Reject invalid values before JSON can turn
// NaN/Infinity into null (which would otherwise clear a saved default).
function carrierTonnageValue(value){
  if(value===null||value===undefined||(typeof value==='string'&&!value.trim())) return null;
  if((typeof value!=='number'&&typeof value!=='string')||
     !Number.isFinite(Number(value))||Number(value)<=0||Number(value)>100)
    throw new Error('Грузоподъёмность должна быть больше 0 и не больше 100 тонн');
  return Number(value);
}
function carrierCapacityError(error){
  return {ok:false,status:422,error:[{loc:['body','tonnage'],msg:error.message}]};
}

// ── AUTH ──────────────────────────────────────────────
const CaucasAPI = {

  async register({ email, password, name, phone, role, inn, orgType, city, truckType, tonnage }){
    let capacity;
    try{capacity=carrierTonnageValue(tonnage);}catch(error){return carrierCapacityError(error);}
    const r = await apiRequest('POST', '/api/auth/register', {
      email, password,
      company_name: name,
      phone: phone || '',
      role: role || 'carrier',
      inn:      inn      || null,
      org_type: orgType  || null,
      city:     city     || null,
      truck_type: truckType || null,
      tonnage: capacity,
    });
    if(r.ok && r.data?.token){
      setToken(r.data.token);
      return { ok: true, token: r.data.token, user_id: r.data.user_id,
        ...(Object.prototype.hasOwnProperty.call(r.data,'truck_type')?{truck_type:r.data.truck_type}:{}),
        ...(Object.prototype.hasOwnProperty.call(r.data,'tonnage')?{tonnage:r.data.tonnage}:{}) };
    }
    return { ok: false, status:r.status, error: r.data?.detail || 'Ошибка регистрации' };
  },

  async login({ email, password }){
    const r = await apiRequest('POST', '/api/auth/login', { email, password });
    if(r.ok && r.data?.token){
      setToken(r.data.token);
      return { ok: true, token: r.data.token, user_id: r.data.user_id, role: r.data.role };
    }
    return { ok: false, status:r.status, error: r.data?.detail || 'Неверный email или пароль' };
  },

  logout(){
    setToken(null);
  },

  // ── LOADS ───────────────────────────────────────────
  async getLoads({ scope, from_city, to_city, from_city_id, to_city_id, from_city_key, to_city_key, truck_type } = {}){
    const params = new URLSearchParams();
    if(scope) params.set('scope', scope);
    if(from_city) params.set('from_city', from_city);
    if(to_city) params.set('to_city', to_city);
    if(from_city_id) params.set('from_city_id', from_city_id);
    if(to_city_id) params.set('to_city_id', to_city_id);
    if(from_city_key) params.set('from_city_key', from_city_key);
    if(to_city_key) params.set('to_city_key', to_city_key);
    if(truck_type) params.set('truck_type', truck_type);
    params.set('limit', '100');
    const loads=[],seen=new Set();
    // Keep local filtering complete beyond the first page without a request on each keystroke.
    // A broken/changing pagination response must never become a false empty/partial result.
    for(let page=0,offset=0;page<50;page++){
      if(offset) params.set('offset',String(offset));
      const r = await apiRequest('GET', '/api/loads/?' + params.toString());
      if(!r.ok||!Array.isArray(r.data?.loads)) throw new Error('Loads are temporarily unavailable');
      const rows=r.data.loads;
      const total=Number.isSafeInteger(r.data.total)&&r.data.total>=0?r.data.total:null;
      const before=loads.length;
      for(const row of rows){
        if(row?.id==null) throw new Error('Invalid loads response');
        const id=String(row.id);
        if(!seen.has(id)){seen.add(id);loads.push(row);}
      }
      if(total!==null&&loads.length>=total) return loads;
      if(total===null&&rows.length<100) return loads;
      if(!rows.length||loads.length===before) throw new Error('Incomplete loads response; please retry');
      offset+=rows.length;
    }
    throw new Error('Too many loads to synchronize; please retry later');
  },

  async getMyLoads(){
    const r = await apiRequest('GET', '/api/loads/my/loads');
    return r.ok ? r.data?.loads || [] : [];
  },

  async createLoad(load, idempotencyKey){
    let dates;
    try { dates=loadingDatesPayload(load); }
    catch(e) { return {ok:false,error:e.message}; }
    const body = {
      from_city: load.from,
      from_address: load.from2 || load.from,
      to_city: load.to,
      to_address: load.to2 || load.to,
      scope: load.scope || 'local',
      weight_kg: load.kg,
      truck_type: load.type || 'tent',
      cargo_desc: load.desc,
      price_gel: load.cur === '₾' ? load.price : null,
      price_usd: load.cur === '$' ? load.price : null,
      payment_type: load.pay,
      is_urgent: load.urgent || false,
      company_name: load.co,
      ...dates,
    };
    for(const field of ['from_city_id','to_city_id','from_city_key','to_city_key','from_location','to_location']){
      if(load[field]!=null)body[field]=load[field];
    }
    const extraH=idempotencyKey?{'Idempotency-Key':idempotencyKey}:{};
    const r=await apiRequest('POST','/api/loads/',body,extraH);
    if(r.ok && r.data?.id){
      return {ok:true,load:{...load,...mapServerLoad(r.data)}};
    }
    if(r.status===401) return {ok:false,status:401,error:'session_expired'};
    if(r.data?.detail?.code==='idempotency_payload_mismatch')
      return {ok:false,status:r.status,error:'idempotency_payload_mismatch'};
    if(r.status===403 && r.data?.detail?.error==='limit_exceeded'){
      return {ok:false,status:r.status,error:'limit_exceeded',limitData:r.data.detail};
    }
    return {ok:false,status:r.status,error:loadingRequestError(r.data?.detail)};
  },

  async updateLoad(serverId, updates){
    let dates;
    try { dates=loadingDatesPayload(updates,true); }
    catch(e) { return {ok:false,error:e.message}; }
    const body={...dates};
    const fields={from:'from_city',to:'to_city',from2:'from_address',to2:'to_address',
      from_city_id:'from_city_id',to_city_id:'to_city_id',from_city_key:'from_city_key',to_city_key:'to_city_key',
      from_location:'from_location',to_location:'to_location',
      kg:'weight_kg',desc:'cargo_desc',type:'truck_type',pay:'payment_type',urgent:'is_urgent'};
    for(const [key,apiKey] of Object.entries(fields))
      if(Object.prototype.hasOwnProperty.call(updates,key)) body[apiKey]=updates[key];
    if(updates.price!==undefined && updates.cur==='₾') body.price_gel=updates.price;
    if(updates.price!==undefined && updates.cur==='$') body.price_usd=updates.price;
    const r=await apiRequest('PUT',`/api/loads/${serverId}`,body);
    return r.ok ? {ok:true,load:mapServerLoad(r.data)}
      : {ok:false,status:r.status,error:loadingRequestError(r.data?.detail)};
  },

  async deleteLoad(serverId){
    const r = await apiRequest('DELETE', `/api/loads/${serverId}`);
    return { ok: r.ok, status: r.status }; // SILENT-1: expose status for error handling
  },

  async getProfile(){
    const r = await apiRequest('GET', '/api/users/me');
    return r.ok ? r.data : null;
  },

  async updateProfile({ company_name, phone, inn, org_type, city, lang, truck_type, tonnage }){
    const body={
      company_name:company_name||null,phone:phone||null,inn:inn||null,
      org_type:org_type||null,city:city||null,lang:lang||null
    };
    // Omitted defaults preserve prior values; explicit null clears them.
    if(truck_type!==undefined) body.truck_type=truck_type||null;
    if(tonnage!==undefined){
      try{body.tonnage=carrierTonnageValue(tonnage);}catch(error){return carrierCapacityError(error);}
    }
    const r=await apiRequest('PUT','/api/users/me',body);
    return r.ok?r.data:{ok:false,status:r.status,error:r.data?.detail};
  },

  async forgotPassword(email){
    const r = await apiRequest('POST', '/api/auth/forgot-password', { email });
    return r.data || { ok: false };
  },

  async resetPassword(email, code, new_password){
    const r = await apiRequest('POST', '/api/auth/reset-password', { email, code, new_password });
    return { ok: r.ok, data: r.data };
  },

};

// ── Расшифровка JWT → user_id ─────────────────────────
function decodeJwtUserId(token){
  try {
    const p = token.split('.')[1];
    const d = JSON.parse(atob(p.replace(/-/g,'+').replace(/_/g,'/')));
    const sub = d.sub !== undefined ? d.sub : (d.user_id || d.id);
    return sub !== undefined ? Number(sub) : null;
  } catch(e){ return null; }
}

// ── SYNC: загружаем грузы с сервера при старте ────────
async function syncLoadsFromServer(){
  const requestedScope=scope;
  const syncSequence=(window._loadsSyncSequence||0)+1;
  window._loadsSyncSequence=syncSequence;
  const current=()=>syncSequence===window._loadsSyncSequence&&scope===requestedScope;
  var syncFailed=false;
  window._loadsLoading = true;
  try {
    // Определяем currentUserId из токена
    const tok = getToken();
    if(tok){
      currentUserId = decodeJwtUserId(tok);
    } else {
      currentUserId = null;
    }

    // Загружаем публичные грузы с сервера (для всех, не только залогиненных)
    const serverLoads = await CaucasAPI.getLoads({ scope: requestedScope });
    if(!current()) return;
    if(!Array.isArray(serverLoads)) throw new Error('Invalid loads response');
    // Public results are authoritative, including an empty response. Drafts stay private.
    const mapped=serverLoads.map(l=>mapServerLoad(l));
    const target=requestedScope==='local'?LOCAL:INTL;
    target.splice(0,target.length,...mapped);
    window.allLoads=[...LOCAL,...INTL];
    window._serverTotal=serverLoads.length;
    if(typeof renderLoads==='function') renderLoads(target);

    // Загружаем свои грузы если залогинен
    if(tok && currentUserId){
      const myLoads = await CaucasAPI.getMyLoads();
      if(!current()) return;
      if(myLoads && myLoads.length){
        // Очищаем серверные грузы из _myLoads (оставляем только локальные)
        _myLoads = _myLoads.filter(l => !l.fromServer);
        myLoads.forEach(l => {
          const mapped = mapServerLoad(l);
          _myLoads.unshift(mapped);
          // Обновляем userId в LOCAL/INTL массиве
          const inLocal = LOCAL.find(x => x.id === l.id);
          if(inLocal) inLocal.userId = l.user_id;
          const inIntl = INTL.find(x => x.id === l.id);
          if(inIntl) inIntl.userId = l.user_id;
        });
        window.allLoads = [...LOCAL, ...INTL];
        // Перерисовываем список грузов чтобы обновить кнопки
        if(typeof renderLoads === 'function') renderLoads(scope === 'local' ? LOCAL : INTL);
        if(typeof _renderOrders === 'function') _renderOrders();
      }
    }
  } catch(e) {
    if(!current()) return;
    syncFailed=true;
    console.warn('[syncLoads]', e);
    // БАГ-7: показываем сообщение вместо вечного спиннера
    var _errList = document.getElementById('cargoList');
    if(_errList) _errList.innerHTML = '<div style="text-align:center;padding:40px 20px;color:#aaa;font-size:14px">Нет данных. Попробуйте позже.</div>';
  } finally {
    if(!current()) return;
    window._loadsLoading = false;
    // A successful empty search must finish with an empty state, not a spinner.
    var currentLoads=scope==='local'?LOCAL:INTL;
    if(!syncFailed&&typeof renderLoads==='function'&&
      (!currentLoads.length||(typeof filterLoadData==='function'&&!filterLoadData(currentLoads).length))){
      renderLoads(currentLoads);
    }
    // После загрузки грузов — восстанавливаем сохранённую вкладку
    // fix P1: не вызываем если пользователь уже кликнул вкладку вручную (_userClickedTab)
    //         это предотвращает abort активного loadTransportOffers fetch
    if(!window._tabRestored && !window._userClickedTab){
      window._tabRestored = true;
      var savedTab = localStorage.getItem('ch_tab');
      if(savedTab && savedTab !== 'loads'){
        var showTab = (savedTab === 'cabinet') ? 'orders' : savedTab;
        var secEl = document.getElementById('sec-'+showTab);
        if(secEl && typeof showSection === 'function'){
          var btn = document.querySelector('[onclick*="showSection(\''+showTab+'\'"]');
          showSection(showTab, btn);
        }
      }
      // Если кабинет открыт — обновляем данные
      if(typeof showCabinet === 'function' && document.getElementById('cabinetPanel') && document.getElementById('cabinetPanel').style.display !== 'none'){
        if(typeof loadCabinetData === 'function') loadCabinetData();
      }
    }
  }
}

function mapServerLoad(l){
  const typeClrs = {
    tent:      { typeClr:'#f3e5f5', typeClrT:'#6a1b9a', typeLabel:'Тент'      },
    ref:       { typeClr:'#e3f2fd', typeClrT:'#1565c0', typeLabel:'Рефриж.'   },
    bort:      { typeClr:'#e8f5e9', typeClrT:'#2e7d32', typeLabel:'Борт'       },
    termos:    { typeClr:'#fff3e0', typeClrT:'#bf360c', typeLabel:'Термос'     },
    gazel:     { typeClr:'#fce4ec', typeClrT:'#880e4f', typeLabel:'Фургон'     },
    container: { typeClr:'#f0f2f5', typeClrT:'#555',    typeLabel:'Контейнер'  },
    auto:      { typeClr:'#e8eaf6', typeClrT:'#283593', typeLabel:'Автовоз'   },
    other:     { typeClr:'#f0f2f5', typeClrT:'#555',    typeLabel:'Другой'    },
  };
  const tc = typeClrs[l.type] || typeClrs.tent;
  return {
    id:        l.id,
    serverId:  l.id,
    userId:    l.user_id || null,   // ← владелец груза
    from:      l.from  || '',
    from2:     l.from2 || l.from || '',
    to:        l.to    || '',
    to2:       l.to2   || l.to || '',
    from_location:l.from_location||null,
    to_location:l.to_location||null,
    scope:     l.route_scope || l.scope || 'unverified',
    route_scope:l.route_scope || l.scope || 'unverified',
    from_city_id:l.from_city_id ?? null,
    to_city_id:l.to_city_id ?? null,
    from_city_key:l.from_city_key || null,
    to_city_key:l.to_city_key || null,
    from_city_aliases:Array.isArray(l.from_city_aliases)?l.from_city_aliases:[],
    to_city_aliases:Array.isArray(l.to_city_aliases)?l.to_city_aliases:[],
    from_country_iso:l.from_country_iso || null,
    to_country_iso:l.to_country_iso || null,
    kg:        l.kg    || 0,
    type:      l.type  || 'tent',
    ...tc,
    price:     l.price || 0,
    cur:       l.cur   || '₾',
    desc:      l.desc  || '',
    pay:       l.pay   || 'Нал',
    urgent:    l.urgent || false,
    date:      l.date  || '',
    date2:     l.date2 || displayLoadingDay(l.load_date_end),
    load_date: l.load_date || loadDateISO(l.date),
    load_date_end: l.load_date_end || loadDateISO(l.date2),
    km:        '—',
    co:        l.co    || 'CaucasHub',
    rat:       l.rating ?? l.rat ?? null,
    review_count: l.review_count ?? l.ratings_received ?? 0,
    rating_verified: l.rating_verified === true,
    trips:     l.trips || 0,
    badge:     l.urgent ? 'urgent' : (l.badge || null),
    created_at: l.created_at || null,
    fromServer: true,
  };
}


// FIX: openPlansModal — open paywall instead of /plans page
window.openPlansModal = function(e){
  if(e) e.stopPropagation();
  if(typeof closeModal==='function') closeModal('authOverlay');
  setTimeout(function(){
    var pw = document.getElementById('paywallOverlay');
    if(typeof openPaywall === 'function') openPaywall();
    else if(pw) pw.classList.add('on');
  }, 150);
};


// ═══ ЯНДЕКС КАРТА В МОДАЛЕ ═══
var _routeMap = null;
window.openRouteMap = function(){
  var title = document.getElementById('mTitle') ? document.getElementById('mTitle').textContent.trim() : '';
  var parts = title.split(' → ');
  var from = parts[0] ? parts[0].trim() : '';
  var to = parts[1] ? parts[1].trim() : '';
  if(!from || !to){ alert('Не указан маршрут'); return; }
  
  var block = document.getElementById('routeMapBlock');
  var btn = document.querySelector('[onclick="openRouteMap()"]');
  if(!block) return;
  
  if(block.style.display !== 'none'){
    block.style.display = 'none';
    if(_routeMap){ _routeMap.destroy(); _routeMap=null; }
    if(btn) btn.textContent = '🗺️ Показать маршрут на карте';
    return;
  }
  
  block.style.display = 'block';
  if(btn) btn.textContent = '🗺️ Скрыть карту';
  
  if(typeof ymaps === 'undefined'){ 
    document.getElementById('routeMap').innerHTML='<div style="padding:20px;text-align:center;color:#999">Карты загружаются...</div>';
    return;
  }
  
  if(_routeMap){ _routeMap.destroy(); _routeMap=null; }
  
  ymaps.ready(function(){
    _routeMap = new ymaps.Map('routeMap', {center:[41.7151,44.8271], zoom:7});
    ymaps.geocode(from+', Грузия', {results:1}).then(function(res){
      var fromCoords = res.geoObjects.get(0) ? res.geoObjects.get(0).geometry.getCoordinates() : null;
      ymaps.geocode(to+', Грузия', {results:1}).then(function(res2){
        var toCoords = res2.geoObjects.get(0) ? res2.geoObjects.get(0).geometry.getCoordinates() : null;
        if(!fromCoords || !toCoords) return;
        var route = new ymaps.multiRouter.MultiRoute(
          {referencePoints:[fromCoords, toCoords], params:{routingMode:'auto'}},
          {routeActiveStrokeWidth:5, routeActiveStrokeColor:'#f7b731'}
        );
        _routeMap.geoObjects.add(route);
        route.model.events.add('requestsuccess', function(){
          _routeMap.setBounds(route.getBounds(), {checkZoomRange:true, zoomMargin:40});
        });
      });
    });
  });
};

// Явная регистрация в window
window.CaucasAPI = CaucasAPI;
window.syncLoadsFromServer = syncLoadsFromServer;
window.mapServerLoad = mapServerLoad;
window.getToken = getToken;
window.setToken = setToken;
window.decodeJwtUserId = decodeJwtUserId;
window.openRouteMap = function(){ if(typeof openRouteMap_==='function') openRouteMap_(); };

// ── Public counters: unknown is not zero; never fabricate a successful snapshot. ──
(function loadStatsCounters(){
  var ids=['statTrucks','statCompanies','statLoads','statUsers','statOnlineUsers'];
  function unavailable(){
    ids.forEach(function(id){var el=document.getElementById(id);if(el)el.textContent='—';});
    var status=document.getElementById('statsDataStatus');
    if(status)status.textContent=typeof lang!=='undefined'&&lang==='ge'?'მონაცემები დროებით მიუწვდომელია':'Данные временно недоступны';
  }
  function counter(value){
    return typeof value==='number'&&Number.isSafeInteger(value)&&value>=0?value.toLocaleString():'—';
  }
  function applyCounters(d){
    if(!d||typeof d!=='object'||Array.isArray(d))throw new Error('Invalid counters response');
    [['statTrucks','online_trucks'],['statCompanies','registered_profiles'],['statLoads','active_loads'],['statUsers','total_users'],['statOnlineUsers','online_users']].forEach(function(pair){
      var el=document.getElementById(pair[0]);if(el)el.textContent=counter(d[pair[1]]);
    });
    var status=document.getElementById('statsDataStatus');
    if(status){
      var ge=typeof lang!=='undefined'&&lang==='ge';
      var snapshot=d.as_of?new Date(d.as_of):null;
      var hasSnapshot=snapshot&&Number.isFinite(snapshot.getTime());
      var received=new Intl.DateTimeFormat(ge?'ka-GE':'ru-RU',{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit',timeZone:'Asia/Tbilisi'}).format(hasSnapshot?snapshot:new Date());
      status.textContent=(hasSnapshot?(ge?'API · მონაცემები ':'API · данные на '):(ge?'API · მიღებულია ':'API · получено '))+received;
      status.title=ge?'რეგისტრირებული პროფილები და განცხადებები — არა გადამოწმებული იურიდიული პირების რაოდენობა':'Зарегистрированные профили и объявления; это не число проверенных юридических лиц';
    }
  }
  function refresh(){
    return fetch(API_BASE+'/api/stats/counters',{signal:AbortSignal.timeout(10000)})
      .then(function(r){if(!r.ok)throw new Error('Counters unavailable');return r.json();})
      .then(applyCounters).catch(unavailable);
  }
  unavailable();
  refresh();
  setInterval(refresh,30000);
})();
