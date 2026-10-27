// ── CaucasHub AI Dispatcher — Мари ───────────────────
// Подключается к POST /api/ai/dispatcher на Railway

(function(){
  const API = 'https://api-production-f3ea.up.railway.app';
  var _sessionId = 'sess_' + Math.random().toString(36).slice(2);
  var _aiOpen = false;
  var _aiLoading = false;
  var _chatHistory = []; // {role, text}
  var _aiState = {}; // state от бэкенда (роль, маршрут, etc)
  var _request = null, _generation = 0, _draft = null, _pendingDraft = null;
  var _welcomeShown = false; // флаг чтобы приветствие показывалось только 1 раз

  // ── текущий язык ──────────────────────────────────
  function _getLang(){ return typeof lang !== 'undefined' && lang === 'ge' ? 'ge' : 'ru'; }
  function _account(){ return typeof getToken === 'function' ? getToken() : null; }
  function _user(){ return typeof user !== 'undefined' ? user : null; }

  // ── тексты по языкам ──────────────────────────────
  var _i18n = {
    ru: {
      welcome: 'Привет! Я Мари — ваш AI диспетчер 🚛\n\nМогу помочь найти груз, подобрать машину или ответить на вопросы по перевозкам. Напишите что нужно!',
      placeholder: 'Напишите о грузе...',
      loading: '⏳ Думаю...',
      error: 'Ошибка связи. Попробуйте позже.',
      name: 'Мари — AI Диспетчер',
      status: 'Помощь с перевозками', view: 'Посмотреть →', draft: 'Проверить черновик →', kg: 'кг', tooLong: 'Сократите сообщение до 2000 символов.'
    },
    ge: {
      welcome: 'გამარჯობა! მე ვარ მარი — თქვენი AI დისპეჩერი 🚛\n\nდაგეხმარებით ტვირთის პოვნაში, მანქანის შერჩევაში ან გადაზიდვასთან დაკავშირებულ ნებისმიერ კითხვაზე. დაწერეთ რა გჭირდებათ!',
      placeholder: 'დაწერეთ ტვირთის შესახებ...',
      loading: '⏳ ვფიქრობ...',
      error: 'კავშირის შეცდომა. სცადეთ მოგვიანებით.',
      name: 'მარი — AI დისპეჩერი',
      status: 'გადაზიდვაში დახმარება', view: 'ნახვა →', draft: 'მონახაზის შემოწმება →', kg: 'კგ', tooLong: 'შეამცირეთ შეტყობინება 2000 სიმბოლომდე.'
    },
    en: {
      welcome: 'Hi! I\'m Mari — your AI dispatcher 🚛\n\nI can help you find cargo, match a truck, or answer any shipping questions. What do you need?',
      placeholder: 'Describe your cargo...',
      loading: '⏳ Thinking...',
      error: 'Connection error. Please try again later.',
      name: 'Mari — AI Dispatcher',
      status: '● Online 24/7'
    }
  };

  function _t(key){ var l=_getLang(); return (_i18n[l]||_i18n['ru'])[key]; }

  // Обновляем шапку чата и placeholder при смене языка
  function _updateChatLang(){
    var labels = _getLang()==='ge' ? {from:'საიდან',to:'სად',desc:'ტვირთი',weight:'წონა / ტევადობა',date:'თარიღი',truck:'ძარა',price:'ფასი',pay:'გადახდა'}
      : {from:'Откуда',to:'Куда',desc:'Груз',weight:'Вес / вместимость',date:'Дата',truck:'Кузов',price:'Ставка',pay:'Оплата'};
    var keys=['from','to','desc','weight','date','truck','price','pay'];
    document.querySelectorAll('#aiTemplate .ai-field-label').forEach(function(el,index){el.textContent=labels[keys[index]]||'';});
    var title=document.querySelector('.ai-template-title');
    if(title) title.textContent=_getLang()==='ge'?'📋 განცხადების მონახაზი':'📋 Черновик объявления';
    var nameEl = document.querySelector('.ai-name');
    var statusEl = document.querySelector('.ai-status');
    var inp = document.getElementById('aiInput');
    if(nameEl) nameEl.textContent = _t('name');
    if(statusEl) statusEl.textContent = _t('status');
    if(inp) inp.placeholder = _t('placeholder');
  }

  // ── toggle чата ───────────────────────────────────
  window.toggleAI = function(){
    var chat = document.getElementById('aiChat');
    if(!chat) return;
    _aiOpen = !_aiOpen;
    if(_aiOpen){
      chat.classList.add('open');
      chat.style.display = 'flex';
      // Позиционируем чат над FAB кнопкой
      // На мобиле чат статичный снизу — не позиционируем
      if(window.innerWidth > 480){
        var fab = document.querySelector('.ai-fab');
        if(fab){
          var fabBottom = parseInt(fab.style.bottom) || 140;
          var fabRight = parseInt(fab.style.right) || 16;
          chat.style.bottom = (fabBottom + 70) + 'px';
          chat.style.right = fabRight + 'px';
        }
      } else {
        // Мобиль — сбрасываем позицию чтобы CSS сработал
        chat.style.bottom = '';
        chat.style.right = '';
        chat.style.left = '';
      }
    } else {
      chat.classList.remove('open');
      chat.style.display = 'none';
    }
    if(_aiOpen){
      // Показываем приветствие только один раз
      _updateChatLang();
      if(_chatHistory.length === 0 && !_welcomeShown){
        _welcomeShown = true;
        var welcome = _t('welcome');
        _appendMsg('ai', welcome);
        _chatHistory.push({role:'ai', text: welcome});
      }
      setTimeout(function(){
        var inp = document.getElementById('aiInput');
        if(inp) inp.focus();
      }, 100);
    }
  };

  // ── отправка сообщения ────────────────────────────
  window.aiSend = async function(){
    if(_aiLoading) return;
    var inp = document.getElementById('aiInput');
    var text = inp && (inp.value || '').trim();
    if(!text) return;
    if(text.length > 2000){ _appendMsg('ai', _t('tooLong')); return; }
    var history = _chatHistory.slice(-8).map(function(m){
      return {role:m.role === 'user' ? 'user' : 'assistant', text:m.text};
    });
    var account = _account(), language = _getLang(), generation = _generation;
    var requestScope = typeof scope !== 'undefined' && scope === 'intl' ? 'intl' : 'local';
    var owner = _user(), controller = new AbortController();
    _request = controller;
    var current = function(){ return generation === _generation && account === _account() && language === _getLang(); };
    inp.value = ''; inp.style.height = 'auto';
    _appendMsg('user', text);
    _chatHistory.push({role:'user', text:text});
    _setLoading(true);
    var timeout = setTimeout(function(){ controller.abort(); }, 25000);
    try {
      var response = await fetch(API + '/api/ai/dispatcher', {
        method:'POST', headers:{'Content-Type':'application/json'}, signal:controller.signal,
        body:JSON.stringify({message:text, history:history, state:_aiState,
          user_role:owner && owner.role || null, lang:language, scope:requestScope})
      });
      var data = await response.json();
      if(!current()) return;
      if(!response.ok || !data || typeof data.reply !== 'string' || !data.reply.trim()) throw new Error('Mari unavailable');
      _appendMsg('ai', data.reply);
      _chatHistory.push({role:'ai', text:data.reply});
      _chatHistory = _chatHistory.slice(-12);
      _aiState = data.state && typeof data.state === 'object' ? data.state : {};
      _showDraft(data.draft);
      _showLoadsInChat(Array.isArray(data.loads) ? data.loads : []);
      _showLoadsInChat(Array.isArray(data.offers) ? data.offers : [], true);
    } catch(error) {
      if(current()){
        _appendMsg('ai', _t('error'));
        if(!inp.value) inp.value = text;
        // A retry must not send the unsuccessful message twice in the history.
        if(_chatHistory[_chatHistory.length-1]?.role === 'user') _chatHistory.pop();
      }
    } finally {
      clearTimeout(timeout);
      if(current()){ _request = null; _setLoading(false); }
    }
  };

  // ── вспомогательные функции ───────────────────────
  function _appendMsg(role, text){
    var msgs = document.getElementById('aiMessages');
    if(!msgs) return;

    var div = document.createElement('div');
    div.style.cssText = 'margin-bottom:12px;display:flex;gap:8px;align-items:flex-start;' +
      (role === 'user' ? 'flex-direction:row-reverse;' : '');

    var avatar = document.createElement('div');
    avatar.style.cssText = 'width:28px;height:28px;border-radius:50%;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:14px;' +
      (role === 'user'
        ? 'background:#f7b731;color:#1a1a2e;font-weight:700;'
        : 'background:transparent;overflow:hidden;');
    if(role === 'user'){
      var u = _user();
      avatar.textContent = (u && u.name) ? u.name[0].toUpperCase() : 'Я';
    } else {
      var img = document.createElement('img');
      img.src = 'dispatcher.jpg';
      img.width = 28; img.height = 28;
      img.style.cssText = 'border-radius:50%;object-fit:cover;object-position:center top;';
      img.onerror = function(){ avatar.textContent = '🤖'; img.remove(); };
      avatar.appendChild(img);
    }

    var bubble = document.createElement('div');
    bubble.style.cssText = 'max-width:75%;padding:10px 14px;border-radius:' +
      (role === 'user' ? '16px 4px 16px 16px' : '4px 16px 16px 16px') +
      ';font-size:14px;line-height:1.5;white-space:pre-wrap;word-break:break-word;' +
      (role === 'user'
        ? 'background:#f7b731;color:#1a1a2e;'
        : 'background:#f0f2f5;color:#1a1a2e;');
    bubble.textContent = text;

    div.appendChild(avatar);
    div.appendChild(bubble);
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
  }

  function _showDraft(draft){
    _draft = draft && ['post_load','post_transport'].includes(draft.intent) ? draft : null;
    var template = document.getElementById('aiTemplate'), button = document.getElementById('aiPostBtn');
    if(template) template.style.display = _draft ? 'block' : 'none';
    if(button){ button.style.display = _draft ? 'block' : 'none'; button.textContent = _t('draft'); }
    if(!_draft) return;
    var fields = {aiTFrom:draft.from, aiTTo:draft.to, tDesc:draft.cargo_desc,
      tWeight:(draft.capacity_kg || draft.weight_cap) ? (draft.capacity_kg || draft.weight_cap)+' '+_t('kg') : null,
      aiTDate:draft.date, tTruck:draft.truck, tPrice:draft.price ? draft.price+' '+draft.currency : null, tPay:null};
    Object.keys(fields).forEach(function(id){ var el=document.getElementById(id); if(el) el.textContent=fields[id] || '—'; });
  }

  function _showLoadsInChat(loads, transport){
    var msgs = document.getElementById('aiMessages');
    if(!msgs) return;
    loads.slice(0,5).forEach(function(record){
      if(!record || !Number.isSafeInteger(record.id) || record.id <= 0) return;
      var card=document.createElement('div'), route=document.createElement('div'), detail=document.createElement('div'), button=document.createElement('button');
      card.className='ai-result-card';
      card.style.cssText='background:#fff;border:1.5px solid #e0e0e0;border-radius:10px;padding:12px;margin-bottom:8px';
      route.style.cssText='font-weight:700;font-size:14px;color:#1a1a2e';
      // Listing text is untrusted. Never interpolate it into HTML or handlers.
      route.textContent=(record.from || '—')+' → '+(record.to || '—');
      detail.textContent=(Number(record.kg)||0).toLocaleString()+' '+_t('kg')+' · '+(record.price == null ? '—' : (record.cur || '')+Number(record.price).toLocaleString());
      button.textContent=_t('view');
      button.style.cssText='margin-top:8px;width:100%;background:#f7b731;color:#1a1a2e;border:none;padding:7px;border-radius:7px;font-size:13px;font-weight:700;cursor:pointer';
      button.onclick=async function(){
        if(button.disabled) return;
        var account=_account(), generation=_generation;
        button.disabled=true;
        try {
          var response=await fetch(API+'/api/ai/listing/'+(transport?'transport/':'load/')+record.id, {signal:AbortSignal.timeout(10000)});
          var data=await response.json();
          if(account!==_account() || generation!==_generation) return;
          if(!response.ok || !data || data.id!==record.id || data.error) throw new Error('Listing unavailable');
          if(transport){
            if(data.status!=='active' || data.dates_expired) throw new Error('Listing unavailable');
            if(typeof _transportOffers!=='undefined'){
              _transportOffers=_transportOffers.filter(function(o){return o.id!==data.id;});_transportOffers.push(data);
            }
            window.closeAI();
            if(typeof openTransportRequest==='function') openTransportRequest(data.id);
          }else{
            window.closeAI();
            if(typeof openCargo==='function' && typeof mapServerLoad==='function') openCargo(mapServerLoad(data));
          }
        }catch(error){ if(account===_account() && generation===_generation) _appendMsg('ai',_t('error')); }
        finally{button.disabled=false;}
      };
      card.appendChild(route);card.appendChild(detail);card.appendChild(button);msgs.appendChild(card);
    });
    msgs.scrollTop=msgs.scrollHeight;
  }

  function _setLoading(on){
    _aiLoading = on;
    var status=document.querySelector('.ai-status'); if(status) status.textContent=on?_t('loading'):_t('status');
    var btn = document.querySelector('.ai-send');
    var inp = document.getElementById('aiInput');
    var loader = document.getElementById('aiLoader');

    if(btn) btn.disabled = on;
    if(inp) inp.disabled = on;

    if(on){
      if(!loader){
        var l = document.createElement('div');
        l.id = 'aiLoader';
        l.style.cssText = 'display:flex;gap:4px;padding:10px 14px;align-items:center;';
        l.innerHTML = '<div style="background:#e0e0e0;border-radius:50%;width:8px;height:8px;animation:aipulse 1s infinite 0s"></div>' +
          '<div style="background:#e0e0e0;border-radius:50%;width:8px;height:8px;animation:aipulse 1s infinite .2s"></div>' +
          '<div style="background:#e0e0e0;border-radius:50%;width:8px;height:8px;animation:aipulse 1s infinite .4s"></div>';
        var msgs = document.getElementById('aiMessages');
        if(msgs){ msgs.appendChild(l); msgs.scrollTop = msgs.scrollHeight; }
      }
    } else {
      if(loader) loader.remove();
    }
  }

  // ── closeAI ──────────────────────────────────────
  window.closeAI = function(){
    var chat = document.getElementById('aiChat');
    if(!chat) return;
    _aiOpen = false;
    chat.classList.remove('open');
    chat.style.display = 'none';
  };

  // ── aiReset ───────────────────────────────────────
  window.aiReset = function(){
    _generation++;
    if(_request) _request.abort();
    _request=null; _draft=null; _pendingDraft=null;
    _setLoading(false);
    _chatHistory = [];
    _aiState = {};
    _welcomeShown = false;
    _sessionId = 'sess_' + Math.random().toString(36).slice(2);
    _updateChatLang();
    var msgs = document.getElementById('aiMessages');
    if(msgs) msgs.innerHTML = '';
    var tpl = document.getElementById('aiTemplate');
    if(tpl) tpl.style.display = 'none';
    var btn = document.getElementById('aiPostBtn');
    if(btn) btn.style.display = 'none';
    var _w = _t('welcome');
    _appendMsg('ai', _w);
    _chatHistory.push({role:'ai', text: _w});
    _welcomeShown = true;
  };

  // A guest draft stays in memory only after an explicit request to open its form.
  window.resetAISession = function(clearGuestDraft){
    var pending = !clearGuestDraft && !_user() ? _pendingDraft : null;
    window.aiReset(); _pendingDraft=pending;
  };
  function _fill(id, value){ var el=document.getElementById(id); if(el) el.value=value == null ? '' : String(value); }
  function _openDraft(draft){
    if(draft.intent==='post_transport'){
      if(typeof openPostTransportOffer!=='function') return;
      openPostTransportOffer();
      _fill('ptFrom',draft.from);_fill('ptTo',draft.to);
      var types={bort:'open',auto:'autovoz',evacuator:'lowboy'};
      _fill('ptTruckType',types[draft.truck]||draft.truck);
      _fill('ptCapacity',draft.capacity_kg||draft.weight_cap);_fill('ptDateFrom',draft.date);
      _fill('ptDateTo',draft.date_end);_fill('ptPrice',draft.currency==='USD'?null:draft.price);_fill('ptNotes',draft.cargo_desc);
    }else{
      if(typeof openPostLoad!=='function') return;
      if(typeof setScope==='function' && typeof scope!=='undefined' && draft.scope!==scope){
        setScope(draft.scope,document.getElementById(draft.scope==='intl'?'sIntl':'sLocal'));
      }
      openPostLoad();
      _fill('pFromAddr',draft.from);_fill('pToAddr',draft.to);_fill('pDesc',draft.cargo_desc);
      _fill('pWeight',draft.weight_cap);_fill('pPrice',draft.currency===(draft.scope==='intl'?'USD':'GEL')?draft.price:null);_fill('pDate',draft.date);_fill('pDate2',draft.date_end);
      if(draft.truck) _fill('pTruck',draft.truck);
      if(draft.from_country) _fill('pFromCountry',draft.from_country);
      if(draft.to_country) _fill('pToCountry',draft.to_country);
      if(typeof addrSelected!=='undefined'){addrSelected.pFrom=null;addrSelected.pTo=null;}
    }
    var formCurrency=draft.intent==='post_transport'?'GEL':(draft.scope==='intl'?'USD':'GEL');
    if(draft.price && draft.currency!==formCurrency && typeof showToastWarn==='function'){
      showToastWarn(_getLang()==='ge'?'ფასი სხვა ვალუტაშია. გამოქვეყნებამდე მიუთითეთ ფასი '+formCurrency+'-ში.':'Цена указана в другой валюте. Перед публикацией укажите ставку в '+formCurrency+'.');
    }
    window.closeAI();
  }
  window.resumeAIDraft = function(){
    if(!_pendingDraft || !_account() || !_user()) return;
    var draft=_pendingDraft;_pendingDraft=null;_openDraft(draft);
  };
  window.aiPostLoad = function(){
    if(!_draft) return;
    if(!_account() || !_user()){
      _pendingDraft=JSON.parse(JSON.stringify(_draft));
      window.closeAI();
      if(typeof openAuth==='function') openAuth('register');
      return;
    }
    _openDraft(_draft);
  };

  // Integrate with the existing page lifecycle without rewriting the shared app.
  var pageReset=window.resetCabinetState;
  if(typeof pageReset==='function') window.resetCabinetState=function(clearDraft){
    window.resetAISession(clearDraft);return pageReset.apply(this,arguments);
  };
  var pageUserState=window.showUserState;
  if(typeof pageUserState==='function') window.showUserState=function(){
    var result=pageUserState.apply(this,arguments);window.resumeAIDraft();return result;
  };
  var pageScope=window.setScope;
  if(typeof pageScope==='function') window.setScope=function(next){
    if(typeof scope!=='undefined' && next!==scope) window.resetAISession(true);
    return pageScope.apply(this,arguments);
  };

  // ── aiStartVoice ──────────────────────────────────
  window.aiStartVoice = function(){
    if(!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)){
      alert('Голосовой ввод не поддерживается в вашем браузере');
      return;
    }
    var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    var rec = new SR();
    var _cur = _getLang();
    rec.lang = _cur === 'ge' ? 'ka-GE' : (_cur === 'en' ? 'en-US' : 'ru-RU');
    rec.interimResults = false;
    var micBtn = document.querySelector('.ai-mic');
    if(micBtn){ micBtn.textContent = '🔴'; micBtn.disabled = true; }
    rec.start();
    rec.onresult = function(e){
      var text = e.results[0][0].transcript;
      var inp = document.getElementById('aiInput');
      if(inp){ inp.value = text; }
      if(micBtn){ micBtn.textContent = '🎤'; micBtn.disabled = false; }
    };
    rec.onerror = function(){
      if(micBtn){ micBtn.textContent = '🎤'; micBtn.disabled = false; }
    };
    rec.onend = function(){
      if(micBtn){ micBtn.textContent = '🎤'; micBtn.disabled = false; }
    };
  };

  // ── Draggable FAB кнопка + drag за хедер чата ──────
  (function(){
    var fab = document.querySelector('.ai-fab');
    if(!fab) return;

    // Восстанавливаем позицию
    function clampFab(){
      var w = window.innerWidth;
      var h = window.innerHeight;
      if(w <= 600){
        // Мобиль — всегда дефолт, убираем localStorage
        localStorage.removeItem('ch_fab_pos');
        fab.style.bottom = '80px';
        fab.style.right = '16px';
      } else {
        try {
          var saved = JSON.parse(localStorage.getItem('ch_fab_pos'));
          if(saved && saved.bottom && saved.right){
            var rightVal = parseInt(saved.right);
            var bottomVal = parseInt(saved.bottom);
            // Проверяем что кнопка в пределах экрана
            if(rightVal >= 8 && rightVal <= w - 60 && bottomVal >= 60 && bottomVal <= h - 60){
              fab.style.bottom = saved.bottom; fab.style.right = saved.right;
            } else {
              localStorage.removeItem('ch_fab_pos');
              fab.style.bottom = '80px'; fab.style.right = '16px';
            }
          }
        } catch(e){}
      }
    }
    clampFab();
    // При изменении ориентации/размера — пересчитываем позицию
    window.addEventListener('resize', clampFab);
    window.addEventListener('orientationchange', function(){ setTimeout(clampFab, 300); });

    var dragging = false, moved = false, startX, startY, startBottom, startRight, dragTarget = null;

    function startDrag(target, e){
      var touch = e.touches ? e.touches[0] : e;
      dragging = true; moved = false; dragTarget = target;
      startX = touch.clientX; startY = touch.clientY;
      var rect = fab.getBoundingClientRect();
      startBottom = window.innerHeight - rect.bottom;
      startRight = window.innerWidth - rect.right;
      e.preventDefault();
    }

    function onMove(e){
      if(!dragging) return;
      var touch = e.touches ? e.touches[0] : e;
      var dx = touch.clientX - startX;
      var dy = touch.clientY - startY;
      if(Math.abs(dx) > 5 || Math.abs(dy) > 5) moved = true;
      if(!moved) return;
      var newBottom = Math.max(60, Math.min(window.innerHeight - 60, startBottom - dy));
      var newRight = Math.max(4, Math.min(window.innerWidth - 60, startRight - dx));
      fab.style.bottom = newBottom + 'px';
      fab.style.right = newRight + 'px';
      var chat = document.getElementById('aiChat');
      if(chat && _aiOpen){
        chat.style.bottom = (newBottom + 70) + 'px';
        chat.style.right = newRight + 'px';
      }
      e.preventDefault();
    }

    function onEnd(){
      if(!dragging) return;
      if(!moved) { window.toggleAI && window.toggleAI(); }
      dragging = false; moved = false; dragTarget = null;
      try { localStorage.setItem('ch_fab_pos', JSON.stringify({bottom: fab.style.bottom, right: fab.style.right})); } catch(e){}
    }

    // FAB — drag и тап через touch (убираем onclick конфликт)
    fab.removeAttribute('onclick');
    fab.addEventListener('mousedown', function(e){ startDrag(fab, e); });
    fab.addEventListener('touchstart', function(e){ startDrag(fab, e); }, {passive:false});
    document.addEventListener('mousemove', onMove);
    document.addEventListener('touchmove', onMove, {passive:false});
    document.addEventListener('mouseup', onEnd);
    document.addEventListener('touchend', onEnd);

    // Drag за хедер чата
    document.addEventListener('DOMContentLoaded', function(){
      var header = document.querySelector('.ai-chat-header');
      if(header){
        header.style.cursor = 'grab';
        header.addEventListener('mousedown', function(e){ if(e.target.closest('button')) return; startDrag(header, e); });
        header.addEventListener('touchstart', function(e){ if(e.target.closest('button')) return; startDrag(header, e); }, {passive:false});
      }
    });
  })();

  // ── CSS анимация для лоадера ──────────────────────
  var style = document.createElement('style');
  style.textContent = '@keyframes aipulse{0%,100%{opacity:.3;transform:scale(.8)}50%{opacity:1;transform:scale(1)}}';
  document.head.appendChild(style);

  // ── автоматический resize textarea ───────────────
  // Resize textarea при вводе
  document.addEventListener('DOMContentLoaded', function(){
    var inp = document.getElementById('aiInput');
    if(inp){
      inp.addEventListener('input', function(){
        this.style.height = 'auto';
        this.style.height = Math.min(this.scrollHeight, 120) + 'px';
      });
    }
  });

})();
