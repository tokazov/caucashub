// ── CaucasHub API Client ──────────────────────────────
// Все запросы к Railway бэкенду

const API_BASE = 'https://api-production-f3ea.up.railway.app';

// Токен из localStorage
function getToken(){ return localStorage.getItem('ch_token') || null; }
function setToken(t){ if(t) localStorage.setItem('ch_token',t); else localStorage.removeItem('ch_token'); }

async function apiRequest(method, path, body=null){
  const headers = { 'Content-Type': 'application/json' };
  const token = getToken();
  if(token) headers['Authorization'] = 'Bearer ' + token;

  const opts = { method, headers };
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

// ── AUTH ──────────────────────────────────────────────
const CaucasAPI = {

  async register({ email, password, name, phone, role, inn, orgType, city, truckType, tonnage }){
    const r = await apiRequest('POST', '/api/auth/register', {
      email, password,
      company_name: name,
      phone: phone || '',
      role: role || 'carrier',
      inn:      inn      || null,
      org_type: orgType  || null,
      city:     city     || null,
    });
    if(r.ok && r.data?.token){
      setToken(r.data.token);
      return { ok: true, token: r.data.token, user_id: r.data.user_id };
    }
    return { ok: false, error: r.data?.detail || 'Ошибка регистрации' };
  },

  async login({ email, password }){
    const r = await apiRequest('POST', '/api/auth/login', { email, password });
    if(r.ok && r.data?.token){
      setToken(r.data.token);
      return { ok: true, token: r.data.token, user_id: r.data.user_id, role: r.data.role };
    }
    return { ok: false, error: r.data?.detail || 'Неверный email или пароль' };
  },

  logout(){
    setToken(null);
  },

  // ── LOADS ───────────────────────────────────────────
  async getLoads({ scope, from_city, to_city, truck_type } = {}){
    const params = new URLSearchParams();
    if(scope) params.set('scope', scope);
    if(from_city) params.set('from_city', from_city);
    if(to_city) params.set('to_city', to_city);
    if(truck_type) params.set('truck_type', truck_type);
    params.set('limit', '100');
    const r = await apiRequest('GET', '/api/loads/?' + params.toString());
    return r.ok ? r.data?.loads || [] : [];
  },

  async getMyLoads(){
    const r = await apiRequest('GET', '/api/loads/my/loads');
    return r.ok ? r.data?.loads || [] : [];
  },

  async createLoad(load){
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
      load_date: new Date().toISOString(),
    };
    const r = await apiRequest('POST', '/api/loads/', body);
    if(r.ok && r.data?.id){
      return { ok: true, load: { ...load, id: r.data.id, serverId: r.data.id } };
    }
    return { ok: false, error: 'Ошибка сохранения' };
  },

  async updateLoad(serverId, updates){
    const body = {};
    if(updates.from)  body.from_city    = updates.from;
    if(updates.to)    body.to_city      = updates.to;
    if(updates.kg)    body.weight_kg    = updates.kg;
    if(updates.desc)  body.cargo_desc   = updates.desc;
    if(updates.type)  body.truck_type   = updates.type;
    if(updates.pay)   body.payment_type = updates.pay;
    if(updates.urgent !== undefined) body.is_urgent = updates.urgent;
    if(updates.price && updates.cur === '₾') body.price_gel = updates.price;
    if(updates.price && updates.cur === '$') body.price_usd = updates.price;
    const r = await apiRequest('PUT', `/api/loads/${serverId}`, body);
    return { ok: r.ok };
  },

  async deleteLoad(serverId){
    const r = await apiRequest('DELETE', `/api/loads/${serverId}`);
    return { ok: r.ok };
  },

  async getProfile(){
    const r = await apiRequest('GET', '/api/users/me');
    return r.ok ? r.data : null;
  },

  async updateProfile({ company_name, phone, inn, org_type, city, lang }){
    const r = await apiRequest('PUT', '/api/users/me', {
      company_name: company_name || null,
      phone:        phone        || null,
      inn:          inn          || null,
      org_type:     org_type     || null,
      city:         city         || null,
      lang:         lang         || null,
    });
    return r.ok ? r.data : { ok: false, error: r.data?.detail };
  },

  async forgotPassword(email){
    const r = await apiRequest('POST', '/api/auth/forgot-password/', { email });
    return r.data || { ok: false };
  },

  async resetPassword(email, code, new_password){
    const r = await apiRequest('POST', '/api/auth/reset-password/', { email, code, new_password });
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
    const serverLoads = await CaucasAPI.getLoads({ scope: scope });
    if(serverLoads && serverLoads.length > 0){
      const mapped = serverLoads.map(l => mapServerLoad(l));
      if(scope === 'local'){
        // Сохраняем локальные грузы (без serverId) которые ещё не попали на сервер
        const localOnly = LOCAL.filter(l => !l.fromServer && !l.serverId);
        LOCAL.length = 0;
        mapped.forEach(l => LOCAL.push(l));
        // Восстанавливаем локальные грузы (дедуп по id)
        localOnly.forEach(l => { if(!LOCAL.find(x => x.id === l.id)) LOCAL.unshift(l); });
      } else {
        const localOnly = INTL.filter(l => !l.fromServer && !l.serverId);
        INTL.length = 0;
        mapped.forEach(l => INTL.push(l));
        localOnly.forEach(l => { if(!INTL.find(x => x.id === l.id)) INTL.unshift(l); });
      }
      window.allLoads = [...LOCAL, ...INTL];
      window._serverTotal = serverLoads.length;
      if(typeof renderLoads === 'function') renderLoads(scope === 'local' ? LOCAL : INTL);
      // Обновляем счётчик реальными данными
      const _statEl = document.getElementById('statLoads');
      if(_statEl) _statEl.textContent = serverLoads.length;
      // Обновляем fcount тоже
      const _fcEl = document.getElementById('fcount');
      if(_fcEl) _fcEl.textContent = serverLoads.length + ' грузов';
      console.log('[API] Loaded', serverLoads.length, 'loads from server');
    }

    // Загружаем свои грузы если залогинен
    if(tok && currentUserId){
      const myLoads = await CaucasAPI.getMyLoads();
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
    console.warn('[syncLoads]', e);
  } finally {
    window._loadsLoading = false;
    // После загрузки грузов — восстанавливаем сохранённую вкладку
    if(!window._tabRestored){
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
    scope:     l.scope || 'local',
    kg:        l.kg    || 0,
    type:      l.type  || 'tent',
    ...tc,
    price:     l.price || 0,
    cur:       l.cur   || '₾',
    desc:      l.desc  || '',
    pay:       l.pay   || 'Нал',
    urgent:    l.urgent || false,
    date:      l.date  || '',
    date2:     null,
    km:        '—',
    co:        l.co    || 'CaucasHub',
    rat:       l.rat   || '5.0',
    trips:     l.trips || 0,
    badge:     l.urgent ? 'urgent' : (l.badge || null),
    fromServer: true,
  };
}


// FIX: openPlansModal — open paywall instead of /plans page
window.openPlansModal = function(e){
  if(e) e.stopPropagation();
  if(typeof closeModal==='function') closeModal('authOverlay');
  setTimeout(function(){
    var pw = document.getElementById('paywallOverlay');
    if(pw) pw.classList.add('on');
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
