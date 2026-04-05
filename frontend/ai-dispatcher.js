// ── CaucasHub AI Dispatcher — Мари ───────────────────
// Подключается к POST /api/ai/dispatcher на Railway

(function(){
  const API = 'https://api-production-f3ea.up.railway.app';
  var _sessionId = 'sess_' + Math.random().toString(36).slice(2);
  var _aiOpen = false;
  var _aiLoading = false;
  var _chatHistory = []; // {role, text}
  var _aiState = {}; // state от бэкенда (роль, маршрут, etc)
  var _welcomeShown = false; // флаг чтобы приветствие показывалось только 1 раз

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
      if(_chatHistory.length === 0 && !_welcomeShown){
        _welcomeShown = true;
        var welcome = 'Привет! Я Мари — ваш AI диспетчер 🚛\n\nМогу помочь найти груз, подобрать машину или ответить на вопросы по перевозкам. Напишите что нужно!';
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
  window.aiSend = function(){
    if(_aiLoading) return;
    var inp = document.getElementById('aiInput');
    if(!inp) return;
    var text = (inp.value || '').trim();
    if(!text) return;
    inp.value = '';
    inp.style.height = 'auto';

    _appendMsg('user', text);
    _chatHistory.push({role:'user', text:text});
    _setLoading(true);

    // Контекст: текущие грузы на экране
    var loadsCtx = '';
    try {
      var visible = (window.LOCAL || []).slice(0,5).map(function(l){
        return (l.from||'?') + ' → ' + (l.to||'?') + ', ' + (l.kg||0) + 'кг, ' + (l.cur||'₾') + (l.price||0);
      });
      if(visible.length) loadsCtx = 'Грузы на экране: ' + visible.join('; ');
    } catch(e){}

    var payload = {
      message: text,
      session_id: _sessionId,
      context: loadsCtx || undefined,
      history: _chatHistory.slice(-8).map(function(m){ return {role: m.role==='user'?'user':'assistant', text: m.text}; }),
      state: _aiState || {}
    };

    fetch(API + '/api/ai/dispatcher', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    })
    .then(function(r){ return r.json(); })
    .then(function(d){
      _setLoading(false);
      var reply = d.reply || 'Не смог обработать запрос, попробуйте ещё раз.';
      _appendMsg('ai', reply);
      _chatHistory.push({role:'ai', text:reply});
      // Сохраняем state для следующего запроса
      if(d.state) _aiState = d.state;

      // Если диспетчер нашёл фильтры — применяем поиск
      if(d.search_filters && typeof window.applyAIFilters === 'function'){
        window.applyAIFilters(d.search_filters);
      }

      // Если диспетчер нашёл грузы — показываем их
      if(d.loads && d.loads.length > 0){
        _showLoadsInChat(d.loads);
      }
    })
    .catch(function(){
      _setLoading(false);
      // Офлайн fallback — простой локальный ответ
      var fallback = 'Нет связи с сервером. ';
      var lower = text.toLowerCase();
      if(lower.includes('батуми') || lower.includes('тбилис') || lower.includes('кутаис') || lower.includes('боржом')){
        fallback += 'Попробуйте поискать груз через фильтры выше 👆';
      } else {
        fallback += 'Попробуйте позже или используйте поиск выше.';
      }
      _appendMsg('ai', fallback);
    });
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
      var u = window.user;
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

  function _showLoadsInChat(loads){
    var msgs = document.getElementById('aiMessages');
    if(!msgs) return;

    var div = document.createElement('div');
    div.style.cssText = 'margin-bottom:12px;';
    var inner = loads.map(function(l){
      var price = l.price ? (l.cur||'₾') + l.price.toLocaleString() : '—';
      return '<div style="background:#fff;border:1.5px solid #e0e0e0;border-radius:10px;padding:12px;margin-bottom:8px;">' +
        '<div style="font-weight:700;font-size:14px;color:#1a1a2e;">' + (l.from||'?') + ' → ' + (l.to||'?') + '</div>' +
        '<div style="font-size:12px;color:#888;margin-top:3px;">' + (l.kg||0).toLocaleString() + ' кг · ' + price + (l.company && l.company!=='—' ? ' · '+l.company : '') + '</div>' +
        '<button onclick="closeAI()" style="margin-top:8px;width:100%;background:#f7b731;color:#1a1a2e;border:none;padding:7px;border-radius:7px;font-size:13px;font-weight:700;cursor:pointer;">Посмотреть и откликнуться →</button>' +
        '</div>';
    }).join('');
    div.innerHTML = inner;
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
  }

  function _setLoading(on){
    _aiLoading = on;
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
    _chatHistory = [];
    _aiState = {};
    _welcomeShown = false;
    _sessionId = 'sess_' + Math.random().toString(36).slice(2);
    var msgs = document.getElementById('aiMessages');
    if(msgs) msgs.innerHTML = '';
    var tpl = document.getElementById('aiTemplate');
    if(tpl) tpl.style.display = 'none';
    var btn = document.getElementById('aiPostBtn');
    if(btn) btn.style.display = 'none';
    _appendMsg('ai', 'Привет! Я Мари — ваш AI диспетчер 🚛\n\nМогу помочь найти груз, подобрать машину или ответить на вопросы по перевозкам. Напишите что нужно!');
  };

  // ── aiPostLoad ────────────────────────────────────
  window.aiPostLoad = function(){
    if(typeof openPostLoad === 'function'){
      openPostLoad();
    } else {
      var btn = document.querySelector('[onclick*="showPost"]') || document.querySelector('.btn-post');
      if(btn) btn.click();
    }
    window.closeAI();
  };

  // ── aiStartVoice ──────────────────────────────────
  window.aiStartVoice = function(){
    if(!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)){
      alert('Голосовой ввод не поддерживается в вашем браузере');
      return;
    }
    var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    var rec = new SR();
    rec.lang = 'ru-RU';
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
    try {
      var saved = JSON.parse(localStorage.getItem('ch_fab_pos'));
      if(saved && saved.bottom && saved.right){ fab.style.bottom = saved.bottom; fab.style.right = saved.right; }
    } catch(e){}

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
