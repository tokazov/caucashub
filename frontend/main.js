// ═══════════════════════════════════════════════════════
// CaucasHub.ge — main.js
// Весь JS фронтенда (кроме api.js и ai-dispatcher.js)
// 
// СТРУКТУРА:
//   1. LocalStorage helpers (_lsSet, _lsGet, _lsDel)
//   2. Адресный поиск (addrSearch, selectAddr)
//   3. Города и карта (filterCity, showRouteMap)
//   4. Подписки и доступ (canSeeContact, canRespond)
//   5. Рендер грузов (renderLoads, renderTrucks)
//   6. Отклики (doRespond, addToOrders, acceptResponse)
//   7. Кабинет (showCabinet, switchCabTab, loadCabinetData)
//   8. Авторизация (openAuth, doLogin, doRegister)
//   9. Размещение груза (openPostLoad, doPostLoad)
//  10. Сделки (renderDealCard, loadDeals)
//  11. Уведомления (pushNotif, _renderOrders)
//  12. Навигация (showSection, setScope, setLang)
// ═══════════════════════════════════════════════════════

// ── SAFE LOCALSTORAGE ─────────────────────────────────
function _lsSet(k,v){try{localStorage.setItem(k,v);}catch(e){window["_ls_"+k]=v;}}
function _lsGet(k){try{return localStorage.getItem(k);}catch(e){return window["_ls_"+k]||null;}}
function _lsDel(k){try{localStorage.removeItem(k);}catch(e){delete window["_ls_"+k];}}
let _myLoads = [];
let _deals   = []; // сделки из API
// ── ADDRESS AUTOCOMPLETE (Nominatim) ─────────────────
let addrTimers={};
let addrSelected={pFrom:null, pTo:null};

function addrSearch(field, val){
  clearTimeout(addrTimers[field]);
  const dropId='dropP'+field.slice(1,2).toUpperCase()+field.slice(2);
  const drop=document.getElementById('drop'+field.slice(0,1).toUpperCase()+field.slice(1).replace('p','P'));
  const dropEl=document.getElementById('dropP'+(field==='pFrom'?'From':'To'));
  if(!dropEl) return;
  if(val.trim().length<2){dropEl.classList.remove('open');return;}
  dropEl.innerHTML='<div class="addr-loading">🔍 Ищем адрес...</div>';
  dropEl.classList.add('open');
  addrTimers[field]=setTimeout(()=>{
    ymaps.ready(()=>{
      ymaps.geocode(val+', Грузия',{results:6,lang:'ru_RU'}).then(res=>{
        const objs=res.geoObjects;
        if(!objs.getLength()){
          dropEl.innerHTML='<div class="addr-loading">Ничего не найдено</div>';
          return;
        }
        let html='';
        objs.each(obj=>{
          const fullAddr=obj.getAddressLine();
          const name=obj.properties.get('name')||fullAddr.split(',')[0];
          const sub=fullAddr.split(',').slice(1,3).join(',').trim();
          const coords=obj.geometry.getCoordinates();
          html+=`<div class="addr-item" onmousedown="selectAddr('${field}','${fullAddr.replace(/'/g,'`')}',${coords[0]},${coords[1]})"><div class="addr-main">${name}</div><div class="addr-sub">${sub}</div></div>`;
        });
        dropEl.innerHTML=html;
      }).catch(()=>{
        dropEl.innerHTML='<div class="addr-loading">Ошибка геокодера</div>';
      });
    });
  },400);
}

function selectAddr(field, addr, lat, lng){
  const inputId=field+'Addr';
  const dropId='dropP'+(field==='pFrom'?'From':'To');
  const coordId='coordsP'+(field==='pFrom'?'From':'To');
  document.getElementById(inputId).value=addr.replace(/`/g,"'");
  document.getElementById(dropId).classList.remove('open');
  const coordEl=document.getElementById(coordId);
  coordEl.textContent=`✅ Координаты: ${parseFloat(lat).toFixed(4)}, ${parseFloat(lng).toFixed(4)}`;
  coordEl.style.display='block';
  // Извлекаем название города из адреса (последний значимый компонент до запятой)
  const parts=addr.replace(/`/g,"'").split(',').map(s=>s.trim());
  // Ищем известные города Грузии в адресе
  const knownCities=['Тбилиси','Батуми','Кутаиси','Рустави','Зугдиди','Гори','Поти','Мцхета','Сенаки','Боржоми','Ахалцихе','Телави','Сигнахи','Хашури','Кобулети','Озургети','Марнеули','Самтредиа','Ткибули'];
  let cityName=parts[0];
  for(const p of parts){
    if(knownCities.some(c=>p.includes(c))){cityName=p;break;}
  }
  addrSelected[field]={addr:addr.replace(/`/g,"'"),city:cityName,lat:parseFloat(lat),lng:parseFloat(lng)};

  // Если оба адреса выбраны — показываем мини-карту
  if(addrSelected.pFrom&&addrSelected.pTo){
    selectedFrom=addrSelected.pFrom;
    selectedTo=addrSelected.pTo;
  }
}
function closeAddrDrop(field){
  const dropId='dropP'+(field==='pFrom'?'From':'To');
  const el=document.getElementById(dropId);
  if(el) el.classList.remove('open');
}

// ── CITIES ───────────────────────────────────────────
// nameGe — официальное грузинское название города
const CITIES = [
  // Грузия
  {name:'Тбилиси', nameGe:'თბილისი', lat:41.6938, lng:44.8015, region:'Грузия'},
  {name:'Батуми', nameGe:'ბათუმი', lat:41.6168, lng:41.6367, region:'Грузия'},
  {name:'Кутаиси', nameGe:'ქუთაისი', lat:42.2679, lng:42.7181, region:'Грузия'},
  {name:'Рустави', nameGe:'რუსთავი', lat:41.5500, lng:45.0000, region:'Грузия'},
  {name:'Поти', nameGe:'ფოთი', lat:42.1500, lng:41.6667, region:'Грузия'},
  {name:'Зугдиди', nameGe:'ზუგდიდი', lat:42.5082, lng:41.8709, region:'Грузия'},
  {name:'Гори', nameGe:'გორი', lat:41.9850, lng:44.1114, region:'Грузия'},
  {name:'Сенаки', nameGe:'სენაკი', lat:42.2667, lng:42.0667, region:'Грузия'},
  {name:'Самтредиа', nameGe:'სამტრედია', lat:42.1500, lng:42.3500, region:'Грузия'},
  {name:'Хашури', nameGe:'ხაშური', lat:41.9908, lng:43.5975, region:'Грузия'},
  {name:'Ткибули', nameGe:'ტყიბული', lat:42.3500, lng:42.9833, region:'Грузия'},
  {name:'Марнеули', nameGe:'მარნეული', lat:41.5000, lng:44.8000, region:'Грузия'},
  {name:'Телави', nameGe:'თელავი', lat:41.9200, lng:45.4800, region:'Грузия'},
  {name:'Сигнахи', nameGe:'სიღნაღი', lat:41.6167, lng:45.9167, region:'Грузия'},
  {name:'Мцхета', nameGe:'მცხეთა', lat:41.8450, lng:44.7200, region:'Грузия'},
  {name:'Боржоми', nameGe:'ბორჯომი', lat:41.8333, lng:43.4000, region:'Грузия'},
  {name:'Кобулети', nameGe:'ქობულეთი', lat:41.8243, lng:41.7742, region:'Грузия'},
  {name:'Озургети', nameGe:'ოზურგეთი', lat:41.9213, lng:42.0019, region:'Грузия'},
  {name:'Ахалцихе', nameGe:'ახალციხე', lat:41.6397, lng:42.9844, region:'Грузия'},
  {name:'Амбролаури', nameGe:'ამბროლაური', lat:42.5167, lng:43.1500, region:'Грузია'},
  {name:'Ланчхути', nameGe:'ლანჩხუთი', lat:41.9753, lng:42.2003, region:'Грузия'},
  {name:'Чохатаури', nameGe:'ჩოხატაური', lat:41.9833, lng:42.2833, region:'Грузия'},
  {name:'Цхалтубо', nameGe:'წყალტუბო', lat:42.3167, lng:42.6000, region:'Грузия'},
  {name:'Сачхере', nameGe:'საჩხერე', lat:42.3500, lng:43.4000, region:'Грузия'},
  {name:'Хони', nameGe:'ხონი', lat:42.2833, lng:42.8833, region:'Грузия'},
  {name:'Карели', nameGe:'კარელი', lat:41.8500, lng:44.1333, region:'Грузия'},
  {name:'Каспи', nameGe:'კასპი', lat:41.9333, lng:44.4167, region:'Грузия'},
  {name:'Дманиси', nameGe:'დმანისი', lat:41.3333, lng:44.1667, region:'Грузия'},
  {name:'Гардабани', nameGe:'გარდაბანი', lat:41.4619, lng:45.1167, region:'Грузия'},
  {name:'Лагодехи', nameGe:'ლაგოდეხი', lat:41.8244, lng:46.2733, region:'Грузия'},
  {name:'Дедоплисцкаро', nameGe:'დედოფლისწყარო', lat:41.4667, lng:46.1000, region:'Грузия'},
  {name:'Цнори', nameGe:'წნორი', lat:41.6500, lng:45.6167, region:'Грузия'},
  {name:'Кварели', nameGe:'ყვარელი', lat:41.9667, lng:45.8167, region:'Грузия'},
  {name:'Степанцминда', nameGe:'სტეფანწმინდა', lat:42.6575, lng:44.4125, region:'Грузия'},
  {name:'Местиа', nameGe:'მესტია', lat:43.0464, lng:42.7228, region:'Грузия'},
  {name:'Зестафони', nameGe:'ზესტაფონი', lat:42.1167, lng:43.0333, region:'Грузия'},
  // Международные — Турция
  {name:'Стамбул', nameGe:'სტამბული', lat:41.0082, lng:28.9784, region:'Турция 🇹🇷'},
  {name:'Анкара', nameGe:'ანკარა', lat:39.9334, lng:32.8597, region:'Турция 🇹🇷'},
  {name:'Трабзон', nameGe:'ტრაბზონი', lat:41.0015, lng:39.7178, region:'Турция 🇹🇷'},
  {name:'Измир', nameGe:'იზმირი', lat:38.4192, lng:27.1287, region:'Турция 🇹🇷'},
  // Армения
  {name:'Ереван', nameGe:'ერევანი', lat:40.1872, lng:44.5152, region:'Армения 🇦🇲'},
  {name:'Гюмри', nameGe:'გიუმრი', lat:40.7894, lng:43.8475, region:'Армения 🇦🇲'},
  // Азербайджан
  {name:'Баку', nameGe:'ბაქო', lat:40.4093, lng:49.8671, region:'Азербайджан 🇦🇿'},
  {name:'Гянджа', nameGe:'განჯა', lat:40.6828, lng:46.3606, region:'Азербайджан 🇦🇿'},
  // Россия
  {name:'Москва', nameGe:'მოსკოვი', lat:55.7558, lng:37.6176, region:'Россия 🇷🇺'},
  {name:'Санкт-Петербург', nameGe:'სანქტ-პეტერბურგი', lat:59.9343, lng:30.3351, region:'Россия 🇷🇺'},
  {name:'Сочи', nameGe:'სოჭი', lat:43.5992, lng:39.7257, region:'Россия 🇷🇺'},
  {name:'Ростов-на-Дону', nameGe:'როსტოვ-დონზე', lat:47.2357, lng:39.7015, region:'Россия 🇷🇺'},
  {name:'Краснодар', nameGe:'კრასნოდარი', lat:45.0355, lng:38.9753, region:'Россия 🇷🇺'},
  // Казахстан
  {name:'Алматы', nameGe:'ალმათი', lat:43.2220, lng:76.8512, region:'Казахстан 🇰🇿'},
  {name:'Астана', nameGe:'ასტანა', lat:51.1801, lng:71.4460, region:'Казахстан 🇰🇿'},
  {name:'Шымкент', nameGe:'შიმქენთი', lat:42.3000, lng:69.6000, region:'Казахстан 🇰🇿'},
  // Узбекистан
  {name:'Ташкент', nameGe:'ტაშქენტი', lat:41.2995, lng:69.2401, region:'Узбекистан 🇺🇿'},
  {name:'Самарканд', nameGe:'სამარყანდი', lat:39.6542, lng:66.9597, region:'Узбекистан 🇺🇿'},
  // СНГ
  {name:'Минск', nameGe:'მინსკი', lat:53.9045, lng:27.5615, region:'Беларусь 🇧🇾'},
  {name:'Киев', nameGe:'კიევი', lat:50.4501, lng:30.5234, region:'Украина 🇺🇦'},
  {name:'Одесса', nameGe:'ოდესა', lat:46.4825, lng:30.7233, region:'Украина 🇺🇦'},
  // Средний Восток
  {name:'Дубай', nameGe:'დუბაი', lat:25.2048, lng:55.2708, region:'ОАЭ 🇦🇪'},
  {name:'Абу-Даби', nameGe:'აბუ-დაბი', lat:24.4539, lng:54.3773, region:'ОАЭ 🇦🇪'},
  {name:'Тегеран', nameGe:'თეირანი', lat:35.6892, lng:51.3890, region:'Иран 🇮🇷'},
  // Европа
  {name:'Берлин', nameGe:'ბერლინი', lat:52.5200, lng:13.4050, region:'Германия 🇩🇪'},
  {name:'Варшава', nameGe:'ვარშავა', lat:52.2297, lng:21.0122, region:'Польша 🇵🇱'},
  {name:'Бухарест', nameGe:'ბუქარესტი', lat:44.4268, lng:26.1025, region:'Румыния 🇷🇴'},
  {name:'София', nameGe:'სოფია', lat:42.6977, lng:23.3219, region:'Болгария 🇧🇬'},
  {name:'Афины', nameGe:'ათენი', lat:37.9838, lng:23.7275, region:'Греция 🇬🇷'},
];

let selectedFrom=null, selectedTo=null, map=null, routeLine=null, markers=[];

// Перевод регионов Грузии
const REGION_NAMES_GE = {
  // Регионы Грузии
  'край Имеретия': 'იმერეთის მხარე',
  'край Кахетия': 'კახეთის მხარე',
  'край Самегрело': 'სამეგრელოს მხარე',
  'край Самцхе-Джавахети': 'სამცხე-ჯავახეთის მხარე',
  'край Шида Картли': 'შიდა ქართლის მხარე',
  'край Квемо Картли': 'ქვემო ქართლის მხარე',
  'Автономная Республика Аджария': 'აჭარის ავტ. რესპ.',
  'Квемо Картли': 'ქვემო ქართლი',
  // Страны
  'Грузия': 'საქართველო',
  'Турция': 'თურქეთი',
  'Армения': 'სომხეთი',
  'Азербайджан': 'აზერბაიჯანი',
  'Россия': 'რუსეთი',
  'Украина': 'უკრაინა',
  'Казахстан': 'ყაზახეთი',
  'Узбекистан': 'უზბეკეთი',
  'Беларусь': 'ბელარუსი',
  'Германия': 'გერმანია',
  'Польша': 'პოლონეთი',
  'Румыния': 'რუმინეთი',
  'Болгария': 'ბულგარეთი',
  'Греция': 'საბერძნეთი',
  'Иран': 'ირანი',
  'ОАЭ': 'არაბ. საამ.',
};

// Перевод названия города/региона на текущий язык

function translatePay(pay) {
  if (lang !== 'ge' || !pay) return pay;
  const T = TRANSLATIONS['ge'];
  const map = {
    'Наличные сразу': T.pay_cash||pay,
    'Наличные': T.pay_cash_short||'ნაღდი',
    'Нал': T.pay_cash_short||'ნაღდი',
    'Безнал 3 дня': T.pay_cashless3||pay,
    'Безнал 7 дней': T.pay_cashless7||pay,
    '50% предоплата': T.pay_prepay||pay,
    'Безнал': T.pay_cashless||'უნაღდო',
  };
  return map[pay] || pay;
}

function translateCity(name) {
  if (!name) return name;
  if (lang !== 'ge') return name;
  let result = name;
  // Регионы
  for (const [ru, ge] of Object.entries(REGION_NAMES_GE)) {
    if (result.includes(ru)) result = result.split(ru).join(ge);
  }
  // Города
  for (const city of CITIES) {
    if (city.nameGe && result.includes(city.name)) {
      result = result.split(city.name).join(city.nameGe);
    }
  }
  return result;
}

function filterCity(dir, val){
  const q=val.trim().toLowerCase();
  const id=dir==='from'?'dropFrom':'dropTo';
  const drop=document.getElementById(id);
  if(q.length<1){drop.classList.remove('open');return;}

  if(scope==='intl'){
    // Международные — показываем только страны
    const found=(typeof COUNTRIES!=='undefined'?COUNTRIES:[]).filter(c=>c.name.toLowerCase().includes(q)).slice(0,12);
    let html=found.map(c=>`<div class="city-option" style="font-size:14px;padding:10px 12px" onmousedown="selectCity('${dir}','${c.name}',null,null,true)">${c.name}</div>`).join('');
    if(!html) html=`<div class="city-option" style="color:#3498db;font-style:italic" onmousedown="selectCity('${dir}','${val.trim()}',null,null,true)">📍 Использовать: "${val.trim()}"</div>`;
    drop.innerHTML=html;
    drop.classList.add('open');
    return;
  }

  // Локальные — города Грузии
  const filtered=CITIES.filter(c=>c.name.toLowerCase().includes(q)||(c.nameGe&&c.nameGe.toLowerCase().includes(q))).slice(0,8);
  let dropHtml=filtered.map(c=>{
    const displayName = lang==='ge'&&c.nameGe ? c.nameGe : c.name;
    const displayRegion = lang==='ge' ? translateCity(c.region) : c.region;
    return `<div class="city-option" onmousedown="selectCity('${dir}','${c.name}',${c.lat||null},${c.lng||null})">${displayName} <span class="region">${displayRegion}</span></div>`;
  }).join('');
  const freeOpt=`<div class="city-option" style="color:#3498db;font-style:italic" onmousedown="selectCity('${dir}','${val.trim()}',null,null)">📍 Использовать: "${val.trim()}"</div>`;
  drop.innerHTML=dropHtml+(dropHtml?'<div style="height:1px;background:#f0f0f0;margin:2px 0"></div>':'')+freeOpt;
  drop.classList.add('open');
}
function openDrop(dir){
  const val=document.getElementById(dir==='from'?'fFrom':'fTo').value;
  if(val) filterCity(dir,val);
}
function closeDrop(dir){ document.getElementById(dir==='from'?'dropFrom':'dropTo').classList.remove('open'); }
function selectCity(dir, name, lat, lng, isCountry){
  const city=CITIES.find(c=>c.name===name)||{name,lat:lat?parseFloat(lat):null,lng:lng?parseFloat(lng):null,region:''};
  if(dir==='from'){
    selectedFrom=city;
    document.getElementById('fFrom').value=lang==='ge'&&CITIES.find(c=>c.name===name)?.nameGe||name;
    document.getElementById('dropFrom').classList.remove('open');
  } else {
    selectedTo=city;
    document.getElementById('fTo').value=lang==='ge'&&CITIES.find(c=>c.name===name)?.nameGe||name;
    document.getElementById('dropTo').classList.remove('open');
  }
  if(selectedFrom&&selectedTo&&selectedFrom.lat&&selectedTo.lat) showRouteMap();
}

// ── YANDEX MAP ────────────────────────────────────────
let ymap=null, ymapRoute=null;

function showRouteMap(){
  const wrap=document.getElementById('mapWrap');
  wrap.classList.add('open');
  const f=selectedFrom, t=selectedTo;
  document.getElementById('mapRouteLabel').textContent=`${f.name||f.addr} → ${t.name||t.addr}`;
  document.getElementById('mapDist').textContent='⏳ Строим маршрут...';

  ymaps.ready(()=>{
    if(!ymap){
      ymap=new ymaps.Map('routeMap',{
        center:[f.lat,f.lng], zoom:7,
        controls:['zoomControl','typeSelector']
      });
    } else {
      ymap.geoObjects.removeAll();
    }

    // Маркер А (откуда) — зелёный
    const pmA=new ymaps.Placemark([f.lat,f.lng],{balloonContent:`<b>${f.name||f.addr}</b>`},{
      preset:'islands#greenDotIconWithCaption',
      iconCaption:'A'
    });
    // Маркер B (куда) — красный
    const pmB=new ymaps.Placemark([t.lat,t.lng],{balloonContent:`<b>${t.name||t.addr}</b>`},{
      preset:'islands#redDotIconWithCaption',
      iconCaption:'B'
    });
    ymap.geoObjects.add(pmA).add(pmB);

    // Маршрут: сначала пробуем OSRM (реальные дороги), потом Яндекс route
    const drawLine=(coords,dist,time)=>{
      const poly=new ymaps.Polyline(coords,{},{
        strokeColor:'#f7b731', strokeWidth:5, strokeOpacity:.9
      });
      ymap.geoObjects.add(poly);
      document.getElementById('mapDist').textContent=time?`${dist} км · ~${time} ч`:`~${dist} км`;
      const bounds=ymaps.util.bounds.fromPoints(coords);
      ymap.setBounds(bounds,{checkZoomRange:true,zoomMargin:50});
    };

    // OSRM — реальные дороги
    fetch(`https://router.project-osrm.org/route/v1/driving/${f.lng},${f.lat};${t.lng},${t.lat}?overview=full&geometries=geojson`)
      .then(r=>r.json())
      .then(data=>{
        if(data.routes&&data.routes[0]){
          const route=data.routes[0];
          const dist=Math.round(route.distance/1000);
          const time=Math.round(route.duration/3600*10)/10;
          const coords=route.geometry.coordinates.map(c=>[c[1],c[0]]);
          drawLine(coords,dist,time);
        } else { throw new Error('no route'); }
      })
      .catch(()=>{
        // fallback — прямая линия
        const dist=Math.round(Math.sqrt(Math.pow((f.lat-t.lat)*111,2)+Math.pow((f.lng-t.lng)*111*Math.cos(f.lat*Math.PI/180),2)));
        const approxDist=Math.round(dist*1.3); // коэффициент дорог
        const approxTime=Math.round(approxDist/70*10)/10;
        drawLine([[f.lat,f.lng],[t.lat,t.lng]],approxDist,approxTime);
      });
  });
}

function closeMap(){
  document.getElementById('mapWrap').classList.remove('open');
  selectedFrom=null; selectedTo=null;
  document.getElementById('fFrom').value='';
  document.getElementById('fTo').value='';
  if(ymap){ ymap.geoObjects.removeAll(); }
}

// ── DATA ────────────────────────────────────────────
const LOCAL = [];
// Экспортируем shared переменные в window для api.js
Object.defineProperty(window, 'LOCAL', { get: ()=>LOCAL, set: (v)=>{ LOCAL.length=0; v.forEach(x=>LOCAL.push(x)); } });
Object.defineProperty(window, 'INTL', { get: ()=>INTL, set: (v)=>{ INTL.length=0; v.forEach(x=>INTL.push(x)); } });

const INTL = [];
const TRUCKS = [
  {id:1,from:'Тбилиси',to:'Любое направление',kg:20000,type:'Тент 120м³',date:'Сегодня',co:'Саба Транс',rat:'4.9',trips:87,plate:'GE-123-AB'},
  {id:2,from:'Батуми',to:'Тбилиси / Поти',kg:5000,type:'Газель 15м³',date:'Сегодня',co:'БатумиЭкс',rat:'4.7',trips:234,plate:'GE-456-BC'},
  {id:3,from:'Поти',to:'Тбилиси',kg:12000,type:'Рефриж. t-18°C',date:'Завтра',co:'КолдЧейн',rat:'5.0',trips:156,plate:'GE-789-CD'},
  {id:4,from:'Кутаиси',to:'Любое',kg:15000,type:'Бортовой',date:'Сегодня',co:'КутТранс',rat:'4.6',trips:43,plate:'GE-321-DE'},
];

// ══════════════════════════════════════════════════════
// ПОДПИСКИ — переключить в true когда наберём базу
const SUBSCRIPTIONS_ENABLED = false;
// ══════════════════════════════════════════════════════

// Планы подписок
const PLANS = {
  free:     { name:'Бесплатно',  price:0,   color:'#888',    contacts:0,  responds:0,  priority:false, urgent:false },
  standard: { name:'Стандарт',   price:35,  color:'#3498db', contacts:50, responds:50, priority:false, urgent:false },
  pro:      { name:'Про',        price:80,  color:'#f7b731', contacts:-1, responds:-1, priority:true,  urgent:true  },
};

// Проверка доступа (пока SUBSCRIPTIONS_ENABLED=false — всё разрешено)
function canSeeContact(){ return !SUBSCRIPTIONS_ENABLED || userHasPlan('standard'); }
function canRespond(){    return !SUBSCRIPTIONS_ENABLED || userHasPlan('standard'); }
function canSeeUrgent(){  return !SUBSCRIPTIONS_ENABLED || userHasPlan('pro'); }
function userHasPlan(min){
  if(!user) return false;
  const order=['free','standard','pro'];
  const userIdx=order.indexOf(user.plan||'free');
  const minIdx=order.indexOf(min);
  return userIdx>=minIdx;
}

let scope='local', lang='ru', user=null, cargoData=[...LOCAL];
Object.defineProperty(window, 'scope', { get: ()=>scope });
Object.defineProperty(window, 'currentUserId', { get: ()=>currentUserId, set: (v)=>{ currentUserId=v; } });
Object.defineProperty(window, 'user', { get: ()=>user, set: (v)=>{ user=v; } });
let currentUserId=null; // user_id из JWT

// ── DATE RANGE SYNC ───────────────────────────────────
function syncDateMin(){
  const d1=document.getElementById('pDate');
  const d2=document.getElementById('pDate2');
  if(d2&&d1.value){
    d2.min=d1.value;
    if(d2.value&&d2.value<d1.value) d2.value=d1.value;
  }
}

// ── DATE HELPERS ──────────────────────────────────────
function fmtD(s){
  if(!s) return null;
  // already formatted dd.mm
  if(/^\d{2}\.\d{2}/.test(s)) return s;
  const now=new Date();
  if(s==='today'){const d=new Date(now);return pad(d.getDate())+'.'+pad(d.getMonth()+1)+'.'+d.getFullYear().toString().slice(2);}
  if(s==='tomorrow'){const d=new Date(now);d.setDate(d.getDate()+1);return pad(d.getDate())+'.'+pad(d.getMonth()+1)+'.'+d.getFullYear().toString().slice(2);}
  // "28 мар" style
  const months={янв:'01',фев:'02',мар:'03',апр:'04',май:'05',июн:'06',июл:'07',авг:'08',сен:'09',окт:'10',ноя:'11',дек:'12'};
  const m=s.match(/(\d+)\s+([а-я]+)/i);
  if(m) return pad(m[1])+'.'+(months[m[2].toLowerCase()]||'??')+'.'+now.getFullYear().toString().slice(2);
  return s;
}
function pad(n){return String(n).padStart(2,'0');}
function formatDateRange(d1,d2){
  const a=fmtD(d1);
  const b=fmtD(d2);
  if(!a) return '—';
  if(!b||a===b) return a;
  return a+' – '+b;
}

// ── RENDER LOADS ─────────────────────────────────────
function renderLoads(data){
  // Фильтруем занятые грузы
  data=data.filter(d=>d.status!=='taken');
  document.getElementById('fcount').textContent=data.length+' грузов';
  const list=document.getElementById('cargoList');
  list.innerHTML='';
  if(!data.length){
    if(window._loadsLoading){
      list.innerHTML='<div id="cargoLoader" style="text-align:center;padding:40px 20px;color:#aaa;font-size:14px">⏳ Загружаем грузы...</div>';
    } else {
      list.innerHTML='<div style="text-align:center;padding:40px 20px;color:#aaa;font-size:14px">Грузов не найдено</div>';
    }
    return;
  }
  data.forEach(d=>{
    const isOwn = currentUserId && d.userId === currentUserId;
    const dateStr = formatDateRange(d.date, d.date2);

    // Класс карточки
    let cardCls = 'card-load';
    if(d.badge==='urgent') cardCls += ' card-urgent';
    else if(d.badge==='new') cardCls += ' card-fresh';
    else if(d.scope==='intl') cardCls += ' card-intl';

    // Бейдж
    let badgeHtml = '';
    if(d.badge==='urgent') badgeHtml = `<span class="badge-urgent-new">${(TRANSLATIONS[lang]||TRANSLATIONS['ru']).badge_urgent||'СРОЧНО'}</span>`;
    else if(d.badge==='new') badgeHtml = `<span class="badge-fresh-new">${(TRANSLATIONS[lang]||TRANSLATIONS['ru']).badge_new||'НОВЫЙ'}</span>`;
    else if(d.scope==='intl') badgeHtml = `<span class="badge-intl-new">${(TRANSLATIONS[lang]||TRANSLATIONS['ru']).badge_intl||'МЕЖД.'}</span>`;

    // Тип кузова — цвет тега
    const typeColors = {
      tent:{bg:'#f3e5f5',t:'#6a1b9a'},ref:{bg:'#e3f2fd',t:'#1565c0'},
      bort:{bg:'#e8f5e9',t:'#2e7d32'},termos:{bg:'#fff3e0',t:'#bf360c'},
      gazel:{bg:'#fce4ec',t:'#880e4f'},container:{bg:'#f0f2f5',t:'#555'},
      auto:{bg:'#e8eaf6',t:'#283593'},other:{bg:'#f0f2f5',t:'#555'}
    };
    const tc = typeColors[d.type] || typeColors.tent;

    // Кнопки справа
    const _alreadyResponded = typeof _orders !== 'undefined' && _orders.some(o => o.loadId === d.id);
    const rightBtns = isOwn
      ? `<div style="display:flex;gap:6px">
           <button class="card-btn-edit" onclick="event.stopPropagation();editMyLoad(${d.id})">✏️</button>
           <button class="card-btn-del" onclick="event.stopPropagation();deleteMyLoad(${d.id})">🗑</button>
         </div>`
      : _alreadyResponded
        ? `<button class="card-btn-resp" style="background:#2ecc71;color:#fff;font-size:12px;cursor:default" disabled onclick="event.stopPropagation()">${(TRANSLATIONS[lang]||TRANSLATIONS['ru']).card_sent||'✅ Отправлено'}</button>`
        : `<button class="card-btn-resp" onclick="event.stopPropagation();openCargo(window.allLoads.find(x=>x.id==${d.id})||d)">${(TRANSLATIONS[lang]||TRANSLATIONS['ru']).card_respond||'Отклик'}</button>`;

    const row = document.createElement('div');
    row.className = cardCls;
    row.onclick = () => openCargo(d);

    // Десктопная строка (таблица)
    const desktopHtml = `
      <div class="row-desktop">
        <div>
          <div class="route">${translateCity(d.from)} <span class="arrow">→</span> ${translateCity(d.to)}</div>
          <div class="sub">${d.co} ⭐${d.rat}</div>
          <div style="margin-top:3px">${badgeHtml}</div>
        </div>
        <div style="font-size:13px;color:#333">${d.kg.toLocaleString()} ${(TRANSLATIONS[lang]||TRANSLATIONS['ru']).unit_kg||'кг'}</div>
        <div><span class="tag" style="background:${tc.bg};color:${tc.t}">${d.typeLabel}</span></div>
        <div class="price">${d.cur||'₾'}${d.price.toLocaleString()}</div>
        <div style="font-size:12px;font-weight:600;color:#555">${dateStr||'—'}</div>
        <div onclick="event.stopPropagation()">${rightBtns}</div>
      </div>
    `;

    // Мобильная карточка
    const mobileHtml = `
      <div class="row-mobile">
        <div class="card-main-row">
          <div class="card-left">
            <div class="card-route-new">${translateCity(d.from)} <span class="arr">→</span> ${translateCity(d.to)}</div>
            <div class="card-meta-row">
              ${badgeHtml}
              <span class="card-co-new">${d.co} ⭐${d.rat}</span>
            </div>
          </div>
          <div class="card-right-col">
            <div class="card-price-new">${d.cur||'₾'}${d.price.toLocaleString()}</div>
            <div onclick="event.stopPropagation()">${rightBtns}</div>
          </div>
        </div>
        <div class="card-footer-row">
          <span class="card-type-tag" style="background:${tc.bg};color:${tc.t}">${d.typeLabel}</span>
          <span>${d.kg.toLocaleString()} ${(TRANSLATIONS[lang]||TRANSLATIONS['ru']).unit_kg||'кг'}</span>
          ${dateStr ? `<span>${dateStr}</span>` : ''}
        </div>
      </div>
    `;

    row.innerHTML = desktopHtml + mobileHtml;
    list.appendChild(row);
  });
  // Кнопка "Загрузить ещё"
  const _total = window._serverTotal || 0;
  if(_total > data.length){
    const lm = document.createElement('div');
    lm.className = 'load-more';
    lm.innerHTML = `<button onclick="alert('Загружаем ещё...')">Загрузить ещё ${_total - data.length} груз ↓</button>`;
    list.appendChild(lm);
  }
}

// ── RENDER TRUCKS ─────────────────────────────────────
let _myTrucks = [];
try { _myTrucks = JSON.parse(localStorage.getItem('ch_my_trucks')||'[]'); } catch(e){}

function renderTrucks(){
  const list=document.getElementById('truckList');
  list.innerHTML='';
  const allTrucks = [..._myTrucks, ...(window._serverTrucks||[]), ...((_myTrucks.length||(window._serverTrucks||[]).length)?[]:TRUCKS)];
  const countEl = document.getElementById('truckCount');
  if(countEl) countEl.textContent = allTrucks.length + ' машин свободно';
  allTrucks.forEach(t=>{
    const isOwn = t.isOwn;
    const row=document.createElement('div');
    row.className='truck-row';
    row.style.borderLeft = isOwn ? '3px solid #2ecc71' : '3px solid transparent';
    const phone = t.phone ? t.phone : '+995 555 *** ***';
    row.innerHTML=`
      <div>
        <div class="route">${t.from} <span class="arrow">→</span> ${t.to}</div>
        <div class="sub">${t.plate||'—'}</div>
      </div>
      <div>
        <div style="font-size:13px;font-weight:600">${t.co}</div>
        <div class="sub">★ ${t.rat}${t.trips ? ' · ' + t.trips + ' ' + ((TRANSLATIONS[lang]||TRANSLATIONS['ru']).unit_trips||'рейсов') : ''}</div>
      </div>
      <div style="font-size:13px">${(t.kg||0).toLocaleString()} ${(TRANSLATIONS[lang]||TRANSLATIONS['ru']).unit_kg||'кг'}</div>
      <div style="font-size:12px;color:#555">${t.type}</div>
      <div style="font-size:12px;color:#2ecc71;font-weight:600">${t.date}</div>
      <div style="display:flex;gap:4px">
        ${isOwn
          ? `<button class="btn-resp" style="background:#fce4ec;color:#c62828;border:none;padding:5px 8px;border-radius:6px;font-size:11px;cursor:pointer" onclick="deleteMyTruck('${t.id}')">🗑️</button>`
          : `<button class="btn-resp" onclick="callTruck('${t.co}','${t.plate}','${phone}')">Связаться</button>`
        }
      </div>
    `;
    list.appendChild(row);
  });
  if(allTrucks.length === 0){
    list.innerHTML='<div style="text-align:center;padding:32px;color:#aaa">Нет машин. Добавьте первую!</div>';
  }
}

function callTruck(co, plate, phone){
  if(!user){ openAuth('login'); return; }
  alert(`📞 Связаться с перевозчиком\n\n🚛 ${co}\n📋 ${plate}\n📞 ${phone}`);
}

function openPostTruck(){
  if(!user){ openAuth('register'); return; }
  document.getElementById('postTruckSuccess').style.display='none';
  document.getElementById('postTruckOverlay').classList.add('on');
}

function doPostTruck(){
  const from  = document.getElementById('tFrom').value.trim() || 'Тбилиси';
  const to    = document.getElementById('tTo').value.trim() || 'Любое направление';
  // Собираем все выбранные типы
  const selectedTypes = Array.from(document.querySelectorAll('#tTypeCheckboxes input:checked')).map(cb=>cb.value);
  if(selectedTypes.length === 0){ document.getElementById('tTypeError').style.display='block'; return; }
  document.getElementById('tTypeError').style.display='none';
  const type = selectedTypes[0]; // первый тип для основной записи
  const kg    = parseInt(document.getElementById('tKg').value) || 20000;
  const plate = document.getElementById('tPlate').value.trim() || '—';
  const date  = document.getElementById('tDate').value;
  const phone = document.getElementById('tPhone').value.trim();

  const truck = {
    id: 't_' + Date.now(),
    from, to, type, kg, plate, date, phone,
    co: user.name || user.email?.split('@')[0] || (TRANSLATIONS[lang]||TRANSLATIONS['ru']).role_carrier||'Перевозчик',
    rat: '5.0', trips: 0, isOwn: true,
  };
  const _tk = getToken ? getToken() : localStorage.getItem('ch_token');
  // Добавляем машину для каждого выбранного типа
  if(_tk){
    selectedTypes.forEach(t => {
      fetch(API_BASE+'/api/trucks/', {
        method:'POST',headers:{'Authorization':'Bearer '+_tk,'Content-Type':'application/json'},
        body:JSON.stringify({truck_type:t,capacity_kg:kg,available_from:from,available_to:to,plate:plate,phone:phone,available_date:date||null,volume_m3:null})
      }).then(r=>r.ok?r.json():null).then(d=>{if(d&&d.id) syncTrucksFromServer();}).catch(()=>{});
    });
  }
  // Добавляем в локальный список
  selectedTypes.forEach((t,i)=>{
    _myTrucks.unshift({...truck, id:'t_'+Date.now()+i, type:t});
  });
  try { localStorage.setItem('ch_my_trucks', JSON.stringify(_myTrucks)); } catch(e){}
  renderTrucks();
  document.getElementById('postTruckSuccess').style.display='block';
  setTimeout(()=>closeModal('postTruckOverlay'), 1200);
}

async function syncTrucksFromServer(){
  const tk = getToken ? getToken() : localStorage.getItem('ch_token');
  if(!tk) return;
  try{
    const r = await fetch(API_BASE+'/api/trucks/', {headers:{'Authorization':'Bearer '+tk}});
    if(r.ok){
      const d = await r.json();
      const uid = currentUserId;
      const all = (d.trucks||[]).map(t=>({
        id:'srv_'+t.id,from:t.available_from||'Тбилиси',to:t.available_to||'Любое',
        type:t.truck_type,kg:t.capacity_kg,plate:t.plate||'—',phone:t.phone||'',
        co:t.company||(TRANSLATIONS[lang]||TRANSLATIONS['ru']).role_carrier||'Перевозчик',rat:t.rating||'5.0',trips:t.trips||0,
        isOwn:(t.user_id==uid),date:t.available_date||''
      }));
      _myTrucks = all.filter(t=>t.isOwn);
      window._serverTrucks = all.filter(t=>!t.isOwn);
      renderTrucks();
    }
  }catch(e){}
}

function deleteMyTruck(id){
  if(!confirm('Удалить машину из списка?')) return;
  const _tk = getToken ? getToken() : localStorage.getItem('ch_token');
  if(id.startsWith('srv_') && _tk){
    fetch(API_BASE+'/api/trucks/'+id.replace('srv_',''),{method:'DELETE',headers:{'Authorization':'Bearer '+_tk}}).then(()=>syncTrucksFromServer());
    return;
  }
  _myTrucks = _myTrucks.filter(t=>t.id!==id);
  try{localStorage.setItem('ch_my_trucks',JSON.stringify(_myTrucks));}catch(e){}
  renderTrucks();
}

// ── OPEN CARGO MODAL ─────────────────────────────────

// Загружаем сохранённые грузы из localStorage
(function loadPersistedLoads(){
  try {
    const saved = JSON.parse(localStorage.getItem('ch_my_loads')||'[]');
    if(saved.length){
      // Только в _myLoads — LOCAL заполняется с сервера, не из localStorage
      saved.forEach(l=>{ _myLoads.unshift(l); });
    }
  } catch(e){}
  try {
    const savedOrders = JSON.parse(localStorage.getItem('ch_orders')||'[]');
    if(savedOrders.length && typeof _orders !== 'undefined') {
      savedOrders.forEach(o=>_orders.push(o));
    }
  } catch(e){}
})();

window.allLoads=[...LOCAL,...INTL];
let currentCargoId=null;
function openCargo(d){
  currentCargoId=d.id;
  window.currentCargoData=d; // сохраняем данные для addToOrders
  document.getElementById('mTitle').textContent=`${translateCity(d.from2||d.from)} → ${translateCity(d.to2||d.to)}`;
  const _loadCreated = d.created_at ? new Date(d.created_at).toLocaleDateString('ru-RU',{day:'2-digit',month:'2-digit',year:'2-digit'}) : null;
  const _addedStr = _loadCreated ? `${(TRANSLATIONS[lang]||TRANSLATIONS['ru']).added||'Добавлен'} ${_loadCreated}` : ((TRANSLATIONS[lang]||TRANSLATIONS['ru']).added_today||'Добавлен сегодня');
  document.getElementById('mSub').textContent=`#${d.scope.toUpperCase()}-${String(d.id).padStart(5,'0')} · ${d.co} · ${_addedStr}`;
  document.getElementById('mAva').textContent=d.co.slice(0,2).toUpperCase();
  document.getElementById('mComp').textContent=d.co;
  // Считаем сколько откликов на этот груз
  const respondCount = (typeof _orders!=='undefined' ? _orders.filter(o=>o.loadId===d.id).length : 0);
  const respondTxt = respondCount > 0 ? ` · 👥 ${respondCount} ${(TRANSLATIONS[lang]||TRANSLATIONS['ru']).unit_respond||'отклик'}` : '';
  document.getElementById('mStats').textContent=`★ ${d.rat}${d.trips ? " · " + d.trips + " " + ((TRANSLATIONS[lang]||TRANSLATIONS["ru"]).unit_trips||"рейсов") : ""} · Верифицирован ✅${respondTxt}`;
  document.getElementById('mGrid').innerHTML=`
    <div><div style="font-size:10px;color:#aaa;text-transform:uppercase;letter-spacing:.5px;margin-bottom:2px">${(TRANSLATIONS[lang]||TRANSLATIONS['ru']).modal_from||'Откуда'}</div><div style="font-size:14px;font-weight:700">${translateCity(d.from2)}</div></div>
    <div><div style="font-size:10px;color:#aaa;text-transform:uppercase;letter-spacing:.5px;margin-bottom:2px">${(TRANSLATIONS[lang]||TRANSLATIONS['ru']).modal_to||'Куда'}</div><div style="font-size:14px;font-weight:700">${translateCity(d.to2)}</div></div>
    <div><div style="font-size:10px;color:#aaa;text-transform:uppercase;letter-spacing:.5px;margin-bottom:2px">${(TRANSLATIONS[lang]||TRANSLATIONS['ru']).modal_date||'Дата загрузки'}</div><div style="font-size:14px;font-weight:700;color:#2ecc71">${formatDateRange(d.date,d.date2)}</div></div>
    <div><div style="font-size:10px;color:#aaa;text-transform:uppercase;letter-spacing:.5px;margin-bottom:2px">${(TRANSLATIONS[lang]||TRANSLATIONS['ru']).modal_weight||'Вес'}</div><div style="font-size:14px;font-weight:700">${d.kg.toLocaleString()} კგ</div></div>
    <div><div style="font-size:10px;color:#aaa;text-transform:uppercase;letter-spacing:.5px;margin-bottom:2px">${(TRANSLATIONS[lang]||TRANSLATIONS['ru']).modal_truck||'Кузов'}</div><div style="font-size:14px;font-weight:700">${typeof getTypeLabel==='function'?getTypeLabel(d.type):d.typeLabel}</div></div>
    <div><div style="font-size:10px;color:#aaa;text-transform:uppercase;letter-spacing:.5px;margin-bottom:2px">${(TRANSLATIONS[lang]||TRANSLATIONS['ru']).modal_pay||'Оплата'}</div><div style="font-size:14px;font-weight:700">${typeof translatePay==='function'?translatePay(d.pay):d.pay}</div></div>
  `;
  document.getElementById('mDesc').textContent=d.desc;
  document.getElementById('mPrice').textContent=`${d.cur||'\$'}${d.price.toLocaleString()}`;
  const _kmVal = d.km && d.km !== '—' ? d.km : null;
  const _kmBlock = document.getElementById('mKmBlock');
  if(_kmBlock) _kmBlock.style.display = _kmVal ? '' : 'none';
  document.getElementById('mKm').textContent = _kmVal || '';
  document.getElementById('respondSuccess').style.display='none';
  // Кнопки: Мой груз → Edit+Delete, чужой → Откликнуться+Телефон
  const _isOwn = currentUserId && d.userId === currentUserId;
  const _actRow = document.getElementById('respondActions');
  if(_actRow){
    if(_isOwn){
      _actRow.innerHTML = `<button onclick="editMyLoad(${d.id})" style="flex:1;background:#1a1a2e;color:#fff;border:none;padding:14px;border-radius:10px;font-size:15px;font-weight:800;cursor:pointer">${(TRANSLATIONS[lang]||TRANSLATIONS['ru']).btn_edit||'✏️ Редактировать'}</button><button onclick="closeModal('cargoOverlay');deleteMyLoad(${d.id})" style="background:#e74c3c;color:#fff;border:none;padding:14px;border-radius:10px;font-size:18px;cursor:pointer;min-width:54px">🗑️</button>`;
    } else {
      const _modalResponded = typeof _orders !== 'undefined' && _orders.some(o => o.loadId === d.id);
      if(_modalResponded){
        const _myOrder = typeof _orders !== 'undefined' && _orders.find(o => o.loadId === d.id);
        const _myOrderId = _myOrder ? _myOrder.id : 0;
        const _myServerId = _myOrder ? (_myOrder.serverId||0) : 0;
        _actRow.innerHTML = `<div style="display:flex;gap:8px;flex:1"><button id="btnRespond" style="flex:1;background:#2ecc71;color:#fff;border:none;padding:14px;border-radius:10px;font-size:15px;font-weight:800;cursor:default" disabled>${(TRANSLATIONS[lang]||TRANSLATIONS['ru']).respond_sent||'✅ Заявка отправлена'}</button><button onclick="cancelMyResponse(${_myOrderId},${_myServerId});closeModal('cargoOverlay')" style="background:#fee;color:#e74c3c;border:1px solid #fcc;padding:14px 16px;border-radius:10px;font-size:13px;font-weight:700;cursor:pointer;white-space:nowrap">${(TRANSLATIONS[lang]||TRANSLATIONS['ru']).btn_cancel||'✕ Отменить'}</button></div>`;
        document.getElementById('respondSuccess').style.display='block';
      } else {
        _actRow.innerHTML = `<div style="display:flex;flex-direction:column;gap:10px;flex:1"><div style="display:flex;gap:8px;align-items:center"><div style="flex:1;position:relative"><span style="position:absolute;left:12px;top:50%;transform:translateY(-50%);font-weight:700;color:#888">₾</span><input id="respondPrice" type="number" placeholder="${(TRANSLATIONS[lang]||TRANSLATIONS['ru']).ph_your_price||'Ваша цена (необязат.)'}" min="0" style="width:100%;padding:12px 12px 12px 26px;border:1.5px solid #e0e0e0;border-radius:10px;font-size:14px;box-sizing:border-box" onfocus="this.style.borderColor='#f7b731'" onblur="this.style.borderColor='#e0e0e0'"></div><button id="btnRespond" style="background:#f7b731;color:#1a1a2e;border:none;padding:14px 18px;border-radius:10px;font-size:15px;font-weight:800;cursor:pointer;white-space:nowrap" onclick="doRespond()">${(TRANSLATIONS[lang]||TRANSLATIONS['ru']).btn_respond||'Откликнуться'}</button></div><div style="font-size:12px;color:#888;text-align:center">${(TRANSLATIONS[lang]||TRANSLATIONS['ru']).respond_hint||'📞 После принятия отклика грузовладелец свяжется с вами'}</div></div>`;
      }
    }
  } else {
    const btn = document.getElementById('btnRespond');
    if(btn){ btn.disabled=false; btn.textContent=(TRANSLATIONS[lang]||TRANSLATIONS['ru']).btn_respond_load||'Откликнуться на груз'; }
  }
  document.getElementById('cargoOverlay').classList.add('on');
}

// ── RESPOND ───────────────────────────────────────────
function doRespond(){
  const _tk = getToken ? getToken() : localStorage.getItem('ch_token');
  if(!user || !user.email || !_tk){ closeModal('cargoOverlay'); openAuth('login'); return; }

  // Проверка профиля перевозчика
  if(!user.role || user.role==='carrier'){
    // Нужны данные об автомобиле и компании/ИП
    const missingFields=[];
    if(!user.truckType) missingFields.push('тип кузова');
    if(!user.tonnage)   missingFields.push('грузоподъёмность');
    if(!user.inn)       missingFields.push('ИНН / ID код компании');
    if(!user.orgType||user.orgType==='')  missingFields.push('форма (ООО/ИП)');
    if(missingFields.length){
      alert('❌ Для отклика заполните профиль перевозчика:\n\n• '+missingFields.join('\n• ')+'\n\nПрофиль → Настройки аккаунта');
      closeModal('cargoOverlay');
      if(typeof openSettings==='function') openSettings();
      return;
    }
  }

  if(!canRespond()){ openPaywall('respond'); return; }
  const btn=document.getElementById('btnRespond');
  btn.textContent='Отправляем...'; btn.disabled=true;

  // Реальный запрос к API
  const _d = window.currentCargoData || window.allLoads?.find(l=>l.id==currentCargoId);
  const _loadServerId = _d?.serverId || _d?.id;
  if(getToken() && _loadServerId){
    const _priceInput = document.getElementById('respondPrice');
    const _priceVal = _priceInput && _priceInput.value ? parseFloat(_priceInput.value) : null;
    fetch('https://api-production-f3ea.up.railway.app/api/responses/load/'+_loadServerId, {
      method:'POST',
      headers:{'Authorization':'Bearer '+getToken(),'Content-Type':'application/json'},
      body:JSON.stringify({price: _priceVal})
    }).then(r=>r.json()).then(r=>{
      const serverResponseId = r?.response_id || null;
      document.getElementById('respondSuccess').style.display='block';
      btn.textContent='✅ Заявка отправлена';
      addToOrders(serverResponseId);
      // Перерисовываем список грузов чтобы кнопка стала зелёной сразу
      if(typeof renderLoads === 'function') renderLoads();
    }).catch(()=>{
      document.getElementById('respondSuccess').style.display='block';
      btn.textContent='✅ Заявка отправлена';
      addToOrders(null);
    });
  } else {
    setTimeout(()=>{
      document.getElementById('respondSuccess').style.display='block';
      btn.textContent='✅ Заявка отправлена';
      addToOrders(null);
    },1000);
  }
}
function addToOrders(serverResponseId){
  // Берём данные текущего груза
  const d = window.currentCargoData || 
            window.allLoads?.find(l=>l.id===currentCargoId) ||
            window.allLoads?.find(l=>l.id==currentCargoId); // нестрогое сравнение на случай строка/число
  if(!d){ console.warn('[addToOrders] cargo not found, id:', currentCargoId); return; }

  // Добавляем в _orders массив
  const order = {
    id: Date.now(),
    serverId: serverResponseId || null,
    loadId: d.id,
    title: `${d.from} → ${d.to}`,
    price: d.price,
    cur: d.cur||'₾',
    co: d.co,
    status: 'pending',
    created: Date.now()
  };
  if(typeof _orders !== 'undefined') { _orders.push(order); persistOrders(); }

  // Добавляем отклик к грузу (виден грузовладельцу)
  if(d && typeof _loadResponses !== 'undefined'){
    if(!_loadResponses[d.id]) _loadResponses[d.id]=[];
    _loadResponses[d.id].push({
      id: Date.now(),
      name: user?.name || (TRANSLATIONS[lang]||TRANSLATIONS['ru']).role_carrier||'Перевозчик',
      truck: user?.truckType || 'Тент',
      tonnage: user?.tonnage || '?',
      rating: user?.rat || '5.0',
      status: 'pending',
      userId: user?.email
    });
  }

  // Обновляем счётчик откликов в профиле
  updateRespondCount();

  // Перерисовываем
  if(typeof _renderOrders === 'function') _renderOrders();
}

async function acceptResponse(loadId, respId){
  var tk = getToken ? getToken() : localStorage.getItem('ch_token');
  if(!tk){ alert('Войдите в аккаунт'); return; }
  try {
    const _accR = await fetch('https://api-production-f3ea.up.railway.app/api/responses/accept/' + respId, {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + tk }
    });
    // Считаем успехом и 200 и 422 (уже принят) — данные сохранены
    let _ad = null; try { _ad = await _accR.json(); } catch(e){}
    const _cPhone = _ad?.carrier_phone || ''; const _cName = _ad?.carrier_name || ''; const _dNum = _ad?.deal_number || '';
    if(_cPhone){ alert('✅ Отклик принят! Сделка ' + _dNum + ' создана.\n\n📞 Перевозчик: ' + _cName + '\nТелефон: ' + _cPhone); }
    pushNotif('✅ Сделка ' + _dNum + ' создана', _cPhone ? '📞 ' + _cName + ': ' + _cPhone : 'Перевозчик уведомлён.', []);
    if(typeof loadCabinetData === 'function') loadCabinetData();
  } catch(e) {
    alert('Нет соединения с сервером');
  }
}

async function cancelMyResponse(orderId, serverId){
  if(!confirm('Отменить заявку?')) return;
  // Убираем из локального массива
  const order = _orders.find(o=>o.id===orderId);
  const idx = _orders.findIndex(o=>o.id===orderId);
  if(idx>-1){ _orders.splice(idx,1); persistOrders(); }
  _renderOrders();
  // Отзываем с сервера
  const _tk = getToken ? getToken() : localStorage.getItem('ch_token');
  if(_tk){
    try{
      if(serverId){
        // Прямая отмена по ID отклика
        await fetch('https://api-production-f3ea.up.railway.app/api/responses/cancel/'+serverId, {
          method:'DELETE', headers:{'Authorization':'Bearer '+_tk}
        });
      } else if(order && order.loadId){
        // Нет serverId — ищем отклик через /my и отменяем по loadId
        const r = await fetch('https://api-production-f3ea.up.railway.app/api/responses/my', {
          headers:{'Authorization':'Bearer '+_tk}
        });
        if(r.ok){
          const d = await r.json();
          const found = (d.responses||[]).find(x=>x.load_id===order.loadId && x.status==='pending');
          if(found){
            await fetch('https://api-production-f3ea.up.railway.app/api/responses/cancel/'+found.id, {
              method:'DELETE', headers:{'Authorization':'Bearer '+_tk}
            });
          }
        }
      }
    }catch(e){}
  }
  pushNotif('✅ Заявка отменена', 'Вы можете откликнуться на другой груз', []);
}

function rejectResponse(loadId, respId){
  const resps = _loadResponses[loadId]||[];
  const r = resps.find(x=>x.id===respId);
  if(r) r.status='rejected';
  _renderOrders();
}

function updateRespondCount(){
  const count = typeof _orders !== 'undefined' ? _orders.length : 0;
  // Показываем в шапке профиля
  const pr = document.getElementById('profileRole');
  if(pr && user){
    const role = user.role==='shipper' ? (TRANSLATIONS[lang]||TRANSLATIONS['ru']).role_shipper||'Грузовладелец' : (TRANSLATIONS[lang]||TRANSLATIONS['ru']).role_carrier||'Перевозчик';
    pr.innerHTML = `${role} · ⭐ ${user.rat||'5.0'} · ${user.trips||0} ${(TRANSLATIONS[lang]||TRANSLATIONS['ru']).unit_trips||'рейсов'}${count>0?` · <span style="color:#f7b731;font-weight:700">${count} отклик${count===1?'':count<5?'а':'ов'}</span>`:''}`;
  }
  // Бейдж на кнопке "Мои заказы"
  const navTabs = document.querySelectorAll('.nav-tab');
  navTabs.forEach(tab=>{
    if(tab.textContent.includes('Заказы')){
      if(count>0) tab.innerHTML=`📋 Мои заказы <span style="background:#e74c3c;color:#fff;border-radius:10px;font-size:10px;padding:1px 5px;margin-left:2px">${count}</span>`;
    }
  });
}
// ── PAYWALL ───────────────────────────────────────────
function openPaywall(reason){
  const titles={
    contact:'Чтобы видеть контакты — нужна подписка',
    respond:'Чтобы откликаться на грузы — нужна подписка',
    urgent:'Срочные грузы доступны на тарифе Про',
  };
  const subs={
    contact:'Откройте телефон и email грузовладельца',
    respond:'Отправляйте заявки перевозчикам напрямую',
    urgent:'Получайте срочные грузы первым',
  };
  document.getElementById('paywallTitle').textContent=titles[reason]||'Откройте доступ';
  document.getElementById('paywallSub').textContent=subs[reason]||'';
  document.getElementById('paywallOverlay').classList.add('on');
}
function choosePlan(plan){
  // Подписки пока не активированы — просто закрываем модал
  closeModal('paywallOverlay');
}

// ── SUBSCRIPTION BADGE ────────────────────────────────
function getPlanBadge(){
  if(!SUBSCRIPTIONS_ENABLED) return '<span style="background:#2ecc71;color:#fff;font-size:10px;padding:2px 8px;border-radius:8px;font-weight:700">Бесплатный период</span>';
  const plan=user?.plan||'free';
  const colors={free:'#888',standard:'#3498db',pro:'#f7b731'};
  const names={free:'Бесплатно',standard:'Стандарт',pro:'Про'};
  return `<span style="background:${colors[plan]};color:#fff;font-size:10px;padding:2px 8px;border-radius:8px;font-weight:700">${names[plan]}</span>`;
}

function showPhone(){
  if(!user){ closeModal('cargoOverlay'); openAuth('login'); return; }
  if(!canSeeContact()){ openPaywall('contact'); return; }
  // реальный контакт — берётся из данных груза
  const d=window.allLoads.find(x=>x.id===currentCargoId);
  const phone=d?.phone||'+995 555 123 456';
  const email=d?.email||'cargo@company.ge';
  window.location.href = 'tel:' + phone;
}

// ── AUTH ──────────────────────────────────────────────
function openAuth(tab){
  document.getElementById('authOverlay').classList.add('on');
  switchAuth(tab);
}
function switchAuth(tab){
  document.getElementById('formLogin').style.display=tab==='login'?'block':'none';
  document.getElementById('formRegister').style.display=tab==='register'?'block':'none';
  document.getElementById('formForgot').style.display=tab==='forgot'?'block':'none';
  document.getElementById('tabLogin').classList.toggle('active',tab==='login');
  document.getElementById('tabRegister').classList.toggle('active',tab==='register');
  if(tab==='register') backToStep1();
}

function showForgotForm(){
  document.getElementById('formLogin').style.display='none';
  document.getElementById('formRegister').style.display='none';
  document.getElementById('formForgot').style.display='block';
  document.getElementById('forgotStep1').style.display='block';
  document.getElementById('forgotStep2').style.display='none';
  document.getElementById('forgotSuccess').style.display='none';
  document.getElementById('forgotError').style.display='none';
  // Подставляем email если уже введён
  const email=document.getElementById('loginEmail').value;
  if(email) document.getElementById('forgotEmail').value=email;
}

let _forgotEmail='';
async function doForgotStep1(){
  const email=document.getElementById('forgotEmail').value.trim();
  const errEl=document.getElementById('forgotError');
  if(!email){errEl.textContent='Введите email';errEl.style.display='block';return;}
  errEl.style.display='none';
  const btn=event.target||document.querySelector('#forgotStep1 .btn-primary');
  if(btn){btn.textContent='Отправляем...';btn.disabled=true;}
  try{
    const r=await fetch('https://api-production-f3ea.up.railway.app/api/auth/forgot-password',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({email})
    });
    const d=await r.json();
    if(btn){btn.textContent='Получить код';btn.disabled=false;}
    _forgotEmail=email;
    document.getElementById('forgotEmailShow').textContent=email;
    document.getElementById('forgotStep1').style.display='none';
    document.getElementById('forgotStep2').style.display='block';
    // DEV: показываем код прямо на экране пока нет email
    if(d.dev_code){
      // Код пришёл в ответе - вставляем автоматически
      const codeInput=document.getElementById('forgotCode');
      codeInput.value=d.dev_code;
      codeInput.style.background='#f0fdf4';
    }
  }catch(e){
    if(btn){btn.textContent='Получить код';btn.disabled=false;}
    errEl.textContent='Ошибка соединения';errEl.style.display='block';
  }
}

async function doForgotStep2(){
  const code=document.getElementById('forgotCode').value.trim();
  const pass1=document.getElementById('forgotNewPass').value;
  const pass2=document.getElementById('forgotNewPass2').value;
  const errEl=document.getElementById('forgotError2');
  if(!code||code.length!==6){errEl.textContent='Введите 6-значный код';errEl.style.display='block';return;}
  if(!pass1||pass1.length<6){errEl.textContent='Пароль минимум 6 символов';errEl.style.display='block';return;}
  if(pass1!==pass2){errEl.textContent='Пароли не совпадают';errEl.style.display='block';return;}
  errEl.style.display='none';
  const btn=event.target;
  if(btn){btn.textContent='Меняем...';btn.disabled=true;}
  try{
    const r=await fetch('https://api-production-f3ea.up.railway.app/api/auth/reset-password',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({email:_forgotEmail,code,new_password:pass1})
    });
    const d=await r.json();
    if(btn){btn.textContent='Сменить пароль';btn.disabled=false;}
    if(r.ok&&(d.ok||d.message)){
      document.getElementById('forgotStep2').style.display='none';
      document.getElementById('forgotSuccess').style.display='block';
      document.getElementById('loginEmail').value=_forgotEmail;
      document.getElementById('loginPass').value='';
    } else {
      // Если пароль уже изменён — код инвалидируется сервером, показываем успех
      const errMsg = d.detail||'';
      if(errMsg.toLowerCase().includes('expired')||errMsg.toLowerCase().includes('invalid')||errMsg.toLowerCase().includes('not found')){
        // Пробуем войти с новым паролем чтобы проверить изменился ли пароль
        const testLogin = await fetch('https://api-production-f3ea.up.railway.app/api/auth/login',{
          method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({email:_forgotEmail,password:pass1})
        }).catch(()=>null);
        if(testLogin&&testLogin.ok){
          // Пароль изменён успешно!
          document.getElementById('forgotStep2').style.display='none';
          document.getElementById('forgotSuccess').style.display='block';
          document.getElementById('loginEmail').value=_forgotEmail;
          document.getElementById('loginPass').value='';
          return;
        }
      }
      errEl.textContent=errMsg||'Неверный код';errEl.style.display='block';
    }
  }catch(e){
    if(btn){btn.textContent='Сменить пароль';btn.disabled=false;}
    errEl.textContent='Ошибка соединения';errEl.style.display='block';
  }
}

function selectRegType(type){
  // подсветка выбранной кнопки
  ['rtCarrier','rtShipperCo','rtShipperPerson'].forEach(id=>{
    document.getElementById(id).classList.remove('selected');
  });
  const map={carrier:'rtCarrier',shipper_company:'rtShipperCo',shipper_person:'rtShipperPerson'};
  document.getElementById(map[type]).classList.add('selected');

  document.getElementById('regRole').value=type;
  document.getElementById('regStep1').style.display='none';
  document.getElementById('regStep2').style.display='block';

  // настраиваем поля по типу
  const isCarrier=type==='carrier';
  const isCompany=type==='carrier'||type==='shipper_company';
  const isPerson=type==='shipper_person';

  document.getElementById('regCompanyFields').style.display=isCompany?'block':'none';
  document.getElementById('regCarrierFields').style.display=isCarrier?'block':'none';

  const nameLabel=document.getElementById('regNameLabel');
  const nameInput=document.getElementById('regName');
  if(isCarrier){
    nameLabel.textContent='Название компании / ФИО ИП';
    nameInput.placeholder='ООО ГрузТранс или Иванов И.И.';
  } else if(type==='shipper_company'){
    nameLabel.textContent='Название компании / ФИО ИП';
    nameInput.placeholder='ООО СтройКарго или Петров А.В.';
  } else {
    nameLabel.textContent='Ваше имя';
    nameInput.placeholder='Имя Фамилия';
  }
}

function backToStep1(){
  document.getElementById('regStep1').style.display='block';
  document.getElementById('regStep2').style.display='none';
  ['rtCarrier','rtShipperCo','rtShipperPerson'].forEach(id=>{
    document.getElementById(id).classList.remove('selected');
  });
}
async function doLogin(){
  const email=document.getElementById('loginEmail').value;
  const pass=document.getElementById('loginPass').value;
  if(!email||!pass){alert('Заполните email и пароль');return;}

  const btn=document.querySelector('#formLogin .btn-primary');
  if(btn){btn.textContent='Входим...';btn.disabled=true;}

  // Пробуем API
  let userData={name:email.split('@')[0],email};
  if(typeof CaucasAPI!=='undefined'){
    const r=await CaucasAPI.login({email,password:pass});
    if(r.ok){
      userData={...userData,userId:r.user_id,role:r.role,token:r.token};
      currentUserId=r.user_id; // обновляем сразу
    } else {
      if(btn){btn.textContent='Войти в аккаунт';btn.disabled=false;}
      const loginErr=document.getElementById('loginErrorMsg');
      if(r.status===0){
        if(loginErr){loginErr.textContent='⚠️ Нет связи с сервером. Проверьте интернет.';loginErr.style.display='block';}
        else{alert('Нет связи с сервером.');}
        return;
      } else {
        const msg=typeof r.error==='string'?r.error:'Неверный email или пароль';
        if(loginErr){loginErr.textContent='❌ '+msg;loginErr.style.display='block';}
        else{alert(msg);}
        return;
      }
    }
  }

  user=userData;
  _lsSet('ch_user',JSON.stringify(user));
  document.getElementById('loginSuccess').style.display='block';
  setTimeout(()=>{
    closeModal('authOverlay');
    showUserState();
    if(typeof syncLoadsFromServer==='function') syncLoadsFromServer();
    if(typeof loadDeals==='function') loadDeals();
    // Подгружаем полный профиль с сервера
    if(getToken()) fetch('https://api-production-f3ea.up.railway.app/api/users/me',{
      headers:{'Authorization':'Bearer '+getToken()}
    }).then(r=>r.json()).then(d=>{
      if(d.id && user){
        user.inn=d.inn||user.inn; user.orgType=d.org_type||user.orgType;
        user.city=d.city||user.city; user.phone=d.phone||user.phone;
        user.name=d.company_name||user.name;
        _lsSet('ch_user',JSON.stringify(user));
      }
    }).catch(()=>{});
  },400);
  if(btn){btn.textContent='Войти в аккаунт';btn.disabled=false;}
}

async function doRegister(){
  const role=document.getElementById('regRole').value;
  if(!role){alert('Выберите тип аккаунта');return;}
  const name=document.getElementById('regName').value;
  const email=document.getElementById('regEmail').value;
  const pass=document.getElementById('regPass').value;
  const phone=document.getElementById('regPhone').value;
  if(!name||!email||!pass){alert('Заполните все обязательные поля');return;}
  const inn=document.getElementById('regInn')?.value||'';
  const orgType=document.getElementById('regOrgType')?.value||'';
  const city=document.getElementById('regCity')?.value||'';
  const truckType=document.getElementById('regTruckType')?.value||'';
  const tonnage=document.getElementById('regTonnage')?.value||'';

  const btn=document.querySelector('#formRegister .btn-primary');
  if(btn){btn.textContent='Создаём...';btn.disabled=true;}

  let userData={name,email,phone,role,inn,orgType,city,truckType,tonnage};

  if(typeof CaucasAPI!=='undefined'){
    const r=await CaucasAPI.register({email,password:pass,name,phone,role,inn,orgType,city});
    if(r.ok){
      userData={...userData,userId:r.user_id,token:r.token};
      currentUserId=r.user_id; // обновляем сразу
    } else {
      if(btn){btn.textContent='Создать аккаунт';btn.disabled=false;}
      if(r.status===0){
        // Нет связи с сервером — показываем понятную ошибку
        const errEl=document.getElementById('regErrorMsg');
        if(errEl){ errEl.textContent='⚠️ Нет связи с сервером. Проверьте интернет и попробуйте снова.'; errEl.style.display='block'; }
        else { alert('Нет связи с сервером. Проверьте интернет.'); }
        return;
      } else {
        const errMsg=Array.isArray(r.error)?r.error.map(e=>e.msg).join(', '):(r.error||'Ошибка регистрации');
        const errEl=document.getElementById('regErrorMsg');
        if(errEl){ errEl.textContent='❌ '+errMsg; errEl.style.display='block'; }
        else { alert(errMsg); }
        return;
      }
    }
  }

  user=userData;
  _lsSet('ch_user',JSON.stringify(user));
  document.getElementById('regSuccess').style.display='block';
  setTimeout(()=>{
    closeModal('authOverlay');
    showUserState();
    if(typeof syncLoadsFromServer==='function') syncLoadsFromServer();
  },400);
  if(btn){btn.textContent='Создать аккаунт';btn.disabled=false;}
}
function showUserState(){
  document.getElementById('btnLogin').style.display='none';
  document.getElementById('btnReg').style.display='none';
  const ab=document.getElementById('authBtns');
  if(ab) ab.style.display='none';
  document.getElementById('userAvatar').style.display='flex';
  document.getElementById('userAvatar').textContent=user.name.slice(0,2).toUpperCase();
  document.getElementById('profileName').textContent=user.name;
  const pb=document.getElementById('profilePlanBadge');
  if(pb) pb.innerHTML=getPlanBadge();
  // показываем заказы
  document.getElementById('ordersEmpty').innerHTML='<div class="icon">📋</div><div style="font-size:18px;font-weight:700;color:#555;margin-bottom:8px">Нет активных заказов</div><div style="font-size:14px">Откликайтесь на грузы — они появятся здесь</div>';
  const nb=document.getElementById('notifBtn');if(nb)nb.style.display='';
  const od=document.getElementById('onlineDot');if(od)od.style.display='inline-block';
}
function doLogout(){
  user=null;
  _lsDel('ch_user');
  const od2=document.getElementById('onlineDot');
  if(od2)od2.style.display='none';
  document.getElementById('btnLogin').style.display='';
  document.getElementById('btnReg').style.display='';
  const ab2=document.getElementById('authBtns');
  if(ab2) ab2.style.display='flex';
  document.getElementById('userAvatar').style.display='none';
  document.getElementById('ordersList').innerHTML='';
  document.getElementById('ordersEmpty').style.display='block';
  document.getElementById('ordersEmpty').innerHTML='<div class="icon">📋</div><div style="font-size:18px;font-weight:700;color:#555;margin-bottom:8px">Нет активных заказов</div><div style="font-size:14px;margin-bottom:20px">Войдите в аккаунт чтобы видеть свои заказы</div><button class="btn-primary" style="max-width:200px;margin:0 auto" onclick="openAuth(\'login\')">Войти</button>';
  document.getElementById('ordersList').style.display='none';
  closeModal('profileOverlay');
}
function openProfile(){
  if(!user){openAuth('login');return;}
  document.getElementById('profileOverlay').classList.add('on');
}

// ── POST LOAD ─────────────────────────────────────────
function openPostLoad(){
  if(!user){openAuth('register');return;}
  document.getElementById('postSuccess').style.display='none';
  const d=new Date(); const dd=String(d.getDate()).padStart(2,'0'); const mm=String(d.getMonth()+1).padStart(2,'0');
  document.getElementById('pDate').value=`${d.getFullYear()}-${mm}-${dd}`;
  document.getElementById('pDate2').value='';
  // Правильная валюта при открытии
  const cl=document.getElementById('priceCurLabel');
  if(cl) cl.textContent=scope==='intl'?'Ставка ($)':'Ставка (₾)';
  if(typeof updateFormForIntl==='function') updateFormForIntl();
  document.getElementById('postOverlay').classList.add('on');
}
function doPostLoad(){
  const fromAddr=document.getElementById('pFromAddr').value||'Адрес не указан';
  const toAddr=document.getElementById('pToAddr').value||'Адрес не указан';
  // Город — первое слово из адреса
  const from=addrSelected.pFrom?.city||fromAddr.split(',')[0]||'Тбилиси';
  const to=addrSelected.pTo?.city||toAddr.split(',')[0]||'Батуми';
  const kg=parseInt(document.getElementById('pWeight').value)||5000;
  const price=parseInt(document.getElementById('pPrice').value)||300;
  const truck=document.getElementById('pTruck').value;
  const desc=document.getElementById('pDesc').value||((TRANSLATIONS[lang]||TRANSLATIONS['ru']).default_desc||'Груз без описания');
  const pay=document.getElementById('pPay').value;
  const urgent=document.getElementById('pUrgent').checked;
  const typeMap={'Тент':{typeClr:'#f3e5f5',typeClrT:'#6a1b9a'},'Рефрижератор':{typeClr:'#e3f2fd',typeClrT:'#1565c0'},'Бортовой':{typeClr:'#e8f5e9',typeClrT:'#2e7d32'},'Термос':{typeClr:'#fff3e0',typeClrT:'#bf360c'},'Газель':{typeClr:'#fce4ec',typeClrT:'#880e4f'},'Контейнер':{typeClr:'#f0f2f5',typeClrT:'#555'}};
  // Маппинг русских названий → API enum (tent/ref/bort/termos/gazel/container/auto/other)
  const truckTypeMap={'тент':'tent','рефрижератор':'ref','рефтент':'ref','мегатент':'tent','бортовой':'bort','термос':'termos','фургон (до 3.5т)':'gazel','газель':'gazel','контейнер':'container','автовоз':'auto','эвакуатор':'auto','цистерна':'other','зерновоз':'other','самосвал':'other'};
  const truckTypeApi = truckTypeMap[truck.toLowerCase()] || 'other';
  const tc=typeMap[truck]||typeMap['Тент'];
  const rawDate=document.getElementById('pDate').value;
  const rawDate2=document.getElementById('pDate2').value;
  function toDisplay(s){if(!s)return null;const[y,m,d]=s.split('-');return `${d}.${m}.${y.slice(2)}`;}
  const loadDate=toDisplay(rawDate)||'28.03.26';
  const loadDate2=rawDate2?toDisplay(rawDate2):null;
  const cur = scope==='intl' ? '$' : '₾';
  const newLoad={id:Date.now(),from,to,kg,type:truckTypeApi,typeLabel:truck,...tc,price,cur,date:loadDate,date2:loadDate2,urgent,scope:scope==='intl'?'intl':'local',desc,co:user.name,rat:'5.0',trips:0,pay,from2:fromAddr,to2:toAddr,km:'~уточните',badge:urgent?'urgent':'new',ownerId:user.email,userId:currentUserId};

  LOCAL.unshift(newLoad);
  window.allLoads=[...LOCAL,...INTL];
  addMyLoad(newLoad);
  document.getElementById('postSuccess').style.display='block';

  // Сохраняем на сервере — ОБЯЗАТЕЛЬНО, груз без serverId не переживёт рефреш
  if(typeof CaucasAPI!=='undefined' && getToken()){
    CaucasAPI.createLoad(newLoad).then(r=>{
      if(r.ok && r.load?.serverId){
        // Успешно сохранено — обновляем serverId
        newLoad.serverId = r.load.serverId;
        newLoad.userId   = currentUserId;
        newLoad.fromServer = true;
        const mi=_myLoads.findIndex(l=>l.id===newLoad.id);
        if(mi>-1){ _myLoads[mi].serverId=r.load.serverId; _myLoads[mi].userId=currentUserId; _myLoads[mi].fromServer=true; }
        const li=LOCAL.findIndex(l=>l.id===newLoad.id);
        if(li>-1){ LOCAL[li].serverId=r.load.serverId; LOCAL[li].userId=currentUserId; LOCAL[li].fromServer=true; }
        window.allLoads=[...LOCAL,...INTL];
        persistMyLoads();
        renderLoads(scope==='local'?LOCAL:INTL);
        // Сбрасываем кэш кабинета чтобы новый груз появился сразу
        window._cabinetFetching = false;
        window._tabRestored = false;
        if(typeof _renderOrders==='function') _renderOrders();
        console.log('[createLoad] Saved to server, id='+r.load.serverId);
      } else {
        // Сервер не принял — удаляем из LOCAL чтобы не было дублей после sync
        console.warn('[createLoad] Server rejected, removing from LOCAL');
        const li=LOCAL.findIndex(l=>l.id===newLoad.id);
        if(li>-1) LOCAL.splice(li,1);
        renderLoads(scope==='local'?LOCAL:INTL);
        alert('⚠️ Груз не удалось сохранить на сервере. Попробуйте ещё раз.');
      }
    }).catch((err)=>{
      console.warn('[createLoad] Network error:', err);
      alert('⚠️ Нет соединения. Груз не сохранён. Проверьте интернет и попробуйте снова.');
      const li=LOCAL.findIndex(l=>l.id===newLoad.id);
      if(li>-1) LOCAL.splice(li,1);
      renderLoads(scope==='local'?LOCAL:INTL);
    });
  } else {
    // Нет токена — не залогинен
    alert('⚠️ Войдите в аккаунт чтобы добавить груз.');
    const li=LOCAL.findIndex(l=>l.id===newLoad.id);
    if(li>-1) LOCAL.splice(li,1);
    renderLoads(scope==='local'?LOCAL:INTL);
  }

  setTimeout(()=>{
    closeModal('postOverlay');
    renderLoads(scope==='local'?LOCAL:INTL);
    document.getElementById('fcount').textContent=LOCAL.length+' грузов';
  },1200);
}

// Массив своих грузов (отдельно от откликов)

// ── Статусы сделок ─────────────────────────────────────────────────
const DEAL_STATUS = {
  rated:      { label:(TRANSLATIONS[lang]||TRANSLATIONS['ru']).btn_rated||'⭐ Оценено',       color:'#f7b731', border:'#f7b731' },
  confirmed:  { label:'✅ Подтверждена',  color:'#2ecc71', border:'#2ecc71' },
  loading:    { label:'📦 Загрузка',      color:'#3498db', border:'#3498db' },
  in_transit: { label:'🚛 В пути',        color:'#9b59b6', border:'#9b59b6' },
  delivered:  { label:'🏁 Доставлен',     color:'#f7b731', border:'#f7b731' },
  completed:  { label:'🎉 Завершена',     color:'#27ae60', border:'#27ae60' },
  disputed:   { label:'⚠️ Спор',          color:'#e74c3c', border:'#e74c3c' },
  canceled:   { label:'✕ Отменена',      color:'#aaa',    border:'#ddd'    },
};

function renderDealCard(d){
  const st = DEAL_STATUS[d.status] || DEAL_STATUS.confirmed;
  const isShipper = user && d.shipper_id === user.userId;
  const isCarrier = user && d.carrier_id === user.userId;
  const price = d.agreed_price ? `${d.currency==='GEL'?'₾':'$'}${Number(d.agreed_price).toLocaleString()}` : '—';

  // Кнопки действий в зависимости от статуса и роли
  let actions = '';
  if(d.status === 'confirmed' && isCarrier){
    actions = `<div><button onclick="dealAction(${d.id},'loading')" style="background:#3498db;color:#fff;border:none;padding:7px 14px;border-radius:8px;font-size:13px;cursor:pointer;font-weight:600">📦 Приступил к загрузке</button><div style="font-size:11px;color:#888;margin-top:4px">Нажмите когда начали грузить товар</div></div>`;
  } else if(d.status === 'confirmed' && isShipper){
    actions = `<div style="font-size:12px;color:#e67e22;background:#fff3e0;padding:8px 12px;border-radius:8px;margin-top:4px">⏳ Ожидаем перевозчика — он должен нажать "Приступил к загрузке"</div>`;
  } else if(d.status === 'loading' && isCarrier){
    actions = `<div><button onclick="dealAction(${d.id},'in_transit')" style="background:#9b59b6;color:#fff;border:none;padding:7px 14px;border-radius:8px;font-size:13px;cursor:pointer;font-weight:600">🚛 Груз отправлен</button><div style="font-size:11px;color:#888;margin-top:4px">Нажмите когда машина выехала с грузом</div></div>`;
  } else if(d.status === 'loading' && isShipper){
    actions = `<div style="font-size:12px;color:#2980b9;background:#e3f2fd;padding:8px 12px;border-radius:8px;margin-top:4px">📦 Перевозчик грузит — ожидайте отправки</div>`;
  } else if(d.status === 'in_transit'){
    const _isCarrierDeal = user && d.carrier_id === user.userId;
    const _isShipperDeal = user && d.shipper_id === user.userId;
    actions = _isCarrierDeal
      ? `<button onclick="dealAction(${d.id},'delivered')" style="background:#f7b731;color:#1a1a2e;border:none;padding:7px 14px;border-radius:8px;font-size:13px;cursor:pointer;font-weight:700">🏁 Груз доставлен</button>`
      : `<span style="font-size:13px;color:#888">⏳ Ожидаем подтверждения доставки от перевозчика</span>`;
  } else if(d.status === 'delivered'){
    const myConfirmed = (isShipper && d.shipper_confirmed) || (isCarrier && d.carrier_confirmed);
    actions = myConfirmed
      ? `<span style="font-size:12px;color:#2ecc71">✅ Вы подтвердили — ждём вторую сторону</span>`
      : `<button onclick="confirmDelivery(${d.id})" style="background:#2ecc71;color:#fff;border:none;padding:7px 14px;border-radius:8px;font-size:13px;cursor:pointer;font-weight:700">✅ Подтвердить получение</button>`;
  } else if(d.status === 'completed' || d.status === 'rated'){
    const _showRate = d.status === 'completed';
    actions = `<div style="display:flex;gap:8px;flex-wrap:wrap">
      ${_showRate ? `<button onclick="rateDealPrompt(${d.id},'${d.act_number||d.id}')" style="background:#f7b731;color:#1a1a2e;border:none;padding:7px 14px;border-radius:8px;font-size:13px;cursor:pointer;font-weight:700">⭐ Оценить</button>` : '<span style="font-size:12px;color:#2ecc71;font-weight:700">⭐ Оценено</span>'}
      <a href="${'https://api-production-f3ea.up.railway.app'}/api/deals/${d.id}/act.pdf?token=${getToken()}" target="_blank" style="display:inline-block;background:#1a1a2e;color:#fff;padding:7px 14px;border-radius:8px;font-size:13px;font-weight:700;text-decoration:none">📄 Скачать акт</a>
    </div>`;
  }

  return `
  <div style="padding:14px 16px;background:#fff;border-bottom:1px solid #f2f2f2;border-left:3px solid ${st.border}">
    <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px">
      <div>
        <div style="font-weight:700;font-size:14px">${d.from_city||'—'} → ${d.to_city||'—'}</div>
        <div style="font-size:12px;color:#888;margin-top:2px">Акт № ${d.act_number||'—'} · ${price}</div>
      </div>
      <span style="background:${st.border}22;color:${st.color};padding:4px 9px;border-radius:10px;font-size:11px;font-weight:700;white-space:nowrap">${st.label}</span>
    </div>
    ${actions ? `<div style="margin-top:8px">${actions}</div>` : ''}
  </div>`;
}

async function rateDealPrompt(dealId, num){
  const stars = prompt('Оцените сделку ' + num + ' от 1 до 5 звёзд:', '5');
  if(!stars || isNaN(stars) || stars < 1 || stars > 5) return;
  const tk = getToken ? getToken() : localStorage.getItem('ch_token');
  try{
    const r = await fetch('https://api-production-f3ea.up.railway.app/api/deals/' + dealId + '/rate', {
      method: 'POST',
      headers: {'Authorization': 'Bearer ' + tk, 'Content-Type': 'application/json'},
      body: JSON.stringify({score: parseInt(stars)})
    });
    if(r.ok){
      pushNotif('⭐ Спасибо!', 'Оценка ' + stars + '/5 сохранена.', []);
      loadDeals();
    } else {
      const e = await r.json();
      alert('Ошибка: ' + (e.detail || 'не удалось сохранить оценку'));
    }
  }catch(e){ alert('Ошибка соединения'); }
}
async function loadDeals(){
  if(!user || !getToken()) return;
  try{
    const r = await fetch('https://api-production-f3ea.up.railway.app/api/deals/my', {
      headers: {'Authorization': 'Bearer ' + getToken()}
    });
    if(r.ok){
      const data = await r.json();
      // Обогащаем сделки данными о грузе
      _deals = await Promise.all((data.deals||[]).map(async d => {
        try{
          const lr = await fetch(`https://api-production-f3ea.up.railway.app/api/loads/${d.load_id}`);
          if(lr.ok){ const ld = await lr.json(); d.from_city=ld.from; d.to_city=ld.to; }
        }catch(e){}
        return d;
      }));
      _renderOrders();
      // Показываем панель экспорта если есть завершённые сделки
      const _ep = document.getElementById('exportPanel');
      const _hasFinishedDeals = _deals.some(d => d.status==='completed'||d.status==='rated');
      if(_ep) _ep.style.display = _hasFinishedDeals ? 'flex' : 'none';
    }
  }catch(e){ console.warn('[Deals]', e); }
}

async function dealAction(dealId, status){
  if(!getToken()) return;
  try{
    const r = await fetch(`https://api-production-f3ea.up.railway.app/api/deals/${dealId}/status`, {
      method:'POST',
      headers:{'Authorization':'Bearer '+getToken(),'Content-Type':'application/json'},
      body: JSON.stringify({status})
    });
    if(r.ok){
      const d = await r.json();
      const idx = _deals.findIndex(x=>x.id===dealId);
      if(idx>-1) Object.assign(_deals[idx], d);
      _renderOrders();
      pushNotif('✅ Статус обновлён', DEAL_STATUS[status]?.label || status, []);
    }
  }catch(e){ alert('Ошибка: '+e.message); }
}

async function confirmDelivery(dealId){
  if(!dealId) return;
  if(!getToken()) return;
  try{
    const r = await fetch(`https://api-production-f3ea.up.railway.app/api/deals/${dealId}/confirm`, {
      method:'POST',
      headers:{'Authorization':'Bearer '+getToken()}
    });
    if(r.ok){
      const d = await r.json();
      const idx = _deals.findIndex(x=>x.id===dealId);
      if(idx>-1) Object.assign(_deals[idx], d);
      _renderOrders();
      if(d.status==='completed'){
        pushNotif('🎉 Сделка завершена!', 'Акт выполненных работ доступен для скачивания', []);
      } else {
        pushNotif('✅ Подтверждено', 'Ожидаем подтверждения второй стороны', []);
      }
    }
  }catch(e){ alert('Ошибка: '+e.message); }
}
// Отклики на мои грузы: {loadId: [{id, name, truck, tonnage, rating, status}]}
let _loadResponses = {};

// Сохранение данных
function persistMyLoads(){ try{localStorage.setItem('ch_my_loads',JSON.stringify(_myLoads));}catch(e){} }

function renderMyDeals(){
  const sec = document.getElementById('sDeals');
  if(!sec) return;
  if(!user){ sec.innerHTML='<div style="text-align:center;padding:40px;color:#999">Войдите чтобы увидеть сделки</div>'; return; }
  if(!_deals||!_deals.length){ sec.innerHTML='<div style="text-align:center;padding:40px;color:#999"><div style="font-size:32px">🤝</div><div style="margin-top:8px">Сделок пока нет</div><div style="font-size:13px;margin-top:4px;color:#bbb">Примите отклик на груз чтобы создать сделку</div></div>'; return; }
  sec.innerHTML = _deals.map(d=>`<div style="background:#fff;border-radius:12px;padding:16px;margin-bottom:12px;box-shadow:0 2px 8px rgba(0,0,0,.06)">
    <div style="font-weight:800;font-size:15px">${d.load_from||d.from||''} → ${d.load_to||d.to||''}</div>
    <div style="font-size:12px;color:#aaa;margin-top:2px">${d.deal_number||'#'+d.id} · ${new Date(d.created_at).toLocaleDateString('ru')}</div>
    <div style="margin-top:8px;font-size:13px"><span style="color:#aaa">Сумма: </span><strong>${d.currency||'₾'}${(d.price||0).toLocaleString()}</strong></div>
    <div style="font-size:12px;margin-top:4px;background:#e8f5e9;color:#2e7d32;display:inline-block;padding:2px 10px;border-radius:10px;font-weight:700">${d.status||'active'}</div>
  </div>`).join('');
}

function persistOrders(){ try{localStorage.setItem('ch_orders',JSON.stringify(_orders||[]));}catch(e){} }

function addMyLoad(load){
  _myLoads.unshift(load);
  persistMyLoads();
  _renderOrders();
}

function deleteMyLoad(id){
  if(!confirm('Удалить груз из биржи?')) return;
  const load=_myLoads.find(l=>l.id===id);
  // Удаляем с сервера если есть serverId
  if(load?.serverId && typeof CaucasAPI!=='undefined' && user?.token){
    CaucasAPI.deleteLoad(load.serverId).catch(()=>{});
  }
  const idx=LOCAL.findIndex(l=>l.id===id);
  if(idx>-1) LOCAL.splice(idx,1);
  window.allLoads=[...LOCAL,...INTL];
  _myLoads=_myLoads.filter(l=>l.id!==id);
  persistMyLoads();
  renderLoads(scope==='local'?LOCAL:INTL);
  document.getElementById('fcount').textContent=LOCAL.length+' грузов';
  _renderOrders();
}

// Редактирование своего груза
let _editingLoadId = null;
function editMyLoad(id){
  const load = _myLoads.find(l=>l.id===id) || LOCAL.find(l=>l.id===id);
  if(!load) return;
  _editingLoadId = id;

  // Открываем форму размещения с данными груза
  if(typeof openPostLoad === 'function') openPostLoad();

  setTimeout(()=>{
    const fill = (elId, val) => { const el=document.getElementById(elId); if(el&&val!=null) el.value=val; };
    fill('pFromAddr', load.from2||load.from);
    fill('pToAddr',   load.to2||load.to);
    fill('pWeight',   load.kg);
    fill('pPrice',    load.price);
    fill('pDesc',     load.desc);
    fill('pPay',      load.pay);
    if(load.urgent) document.getElementById('pUrgent').checked=true;

    // Меняем заголовок и кнопку
    const title = document.querySelector('#postOverlay .modal-title');
    if(title) title.textContent = '✏️ Редактировать груз';
    const btn = document.querySelector('#postOverlay .btn-primary');
    if(btn) btn.textContent = '💾 Сохранить изменения';
    btn.onclick = saveEditedLoad;
  }, 300);
}

function saveEditedLoad(){
  if(!_editingLoadId) return doPostLoad();

  const fromAddr=document.getElementById('pFromAddr').value||'Адрес не указан';
  const toAddr=document.getElementById('pToAddr').value||'Адрес не указан';
  const from=addrSelected.pFrom?.city||fromAddr.split(',')[0]||'Тбилиси';
  const to=addrSelected.pTo?.city||toAddr.split(',')[0]||'Батуми';
  const kg=parseInt(document.getElementById('pWeight').value)||5000;
  const price=parseInt(document.getElementById('pPrice').value)||300;
  const truck=document.getElementById('pTruck').value;
  const desc=document.getElementById('pDesc').value||'';
  const pay=document.getElementById('pPay').value;
  const urgent=document.getElementById('pUrgent').checked;
  const rawDate=document.getElementById('pDate').value;
  const rawDate2=document.getElementById('pDate2').value;
  function toDisplay(s){if(!s)return null;const[y,m,d]=s.split('-');return`${d}.${m}.${y.slice(2)}`;}

  // Обновляем в LOCAL
  const lidx=LOCAL.findIndex(l=>l.id===_editingLoadId);
  if(lidx>-1){
    LOCAL[lidx]={...LOCAL[lidx],from,to,kg,price,desc,pay,urgent,
      date:toDisplay(rawDate)||LOCAL[lidx].date,
      date2:rawDate2?toDisplay(rawDate2):null,
      from2:fromAddr,to2:toAddr};
  }
  // Обновляем в _myLoads
  const midx=_myLoads.findIndex(l=>l.id===_editingLoadId);
  if(midx>-1){
    _myLoads[midx]={..._myLoads[midx],from,to,kg,price,desc,pay,
      date:toDisplay(rawDate)||_myLoads[midx].date,
      date2:rawDate2?toDisplay(rawDate2):null};
  }

  window.allLoads=[...LOCAL,...INTL];
  persistMyLoads();
  _editingLoadId=null;

  // Восстанавливаем форму
  const title=document.querySelector('#postOverlay .modal-title');
  if(title) title.textContent='📦 Разместить груз';
  const btn=document.querySelector('#postOverlay .btn-primary');
  if(btn){btn.textContent='📦 Разместить груз';btn.onclick=doPostLoad;}

  document.getElementById('postSuccess').style.display='block';
  setTimeout(()=>{
    closeModal('postOverlay');
    renderLoads(scope==='local'?LOCAL:INTL);
    _renderOrders();
  },1000);
}



// ── FILTER ─────────────────────────────────────────────
function filterLoads(){
  const fromVal=document.getElementById('fFrom').value.toLowerCase();
  const toVal=document.getElementById('fTo').value.toLowerCase();
  const type=document.getElementById('fType').value;
  const weightRange=document.getElementById('fWeight')?.value||'';
  const priceRange=document.getElementById('fPrice')?.value||'';
  let data=scope==='local'?[...LOCAL]:[...INTL];

  // Откуда (страна для intl, город для local)
  if(fromVal){
    const fromQ=fromVal.split(',')[0].trim().toLowerCase();
    if(scope==='intl'){
      const fromCode=findCountryCode(fromQ);
      if(fromCode) data=filterByCountryCode(data,fromCode,'from');
      else data=data.filter(d=>d.from.toLowerCase().includes(fromQ)||d.to.toLowerCase().includes(fromQ));
    } else {
      data=data.filter(d=>d.from.toLowerCase().includes(fromQ));
    }
  }
  // Куда (страна для intl, город для local)
  if(toVal){
    const toQ=toVal.split(',')[0].trim().toLowerCase();
    if(scope==='intl'){
      const toCode=findCountryCode(toQ);
      if(toCode) data=filterByCountryCode(data,toCode,'to');
      else data=data.filter(d=>d.to.toLowerCase().includes(toQ)||d.from.toLowerCase().includes(toQ));
    } else {
      data=data.filter(d=>d.to.toLowerCase().includes(toQ));
    }
  }
  // Тип кузова
  if(type&&type!=='🚛 Кузов') data=data.filter(d=>d.typeLabel.includes(type.slice(0,4)));
  // Тоннаж
  if(weightRange){
    const [wMin,wMax]=weightRange.split('-').map(Number);
    data=data.filter(d=>d.kg>=wMin&&d.kg<=wMax);
  }
  // Стоимость
  if(priceRange){
    const [pMin,pMax]=priceRange.split('-').map(Number);
    data=data.filter(d=>d.price>=pMin&&d.price<=pMax);
  }

  renderLoads(data);
  document.getElementById('fcount').textContent=data.length+' грузов';

  // Карта если оба города выбраны
  if(fromVal&&toVal){
    const fromCity=fromVal.split(',')[0].trim();
    const toCity=toVal.split(',')[0].trim();
    const cf=CITIES.find(c=>c.name.toLowerCase().includes(fromCity))||selectedFrom;
    const ct=CITIES.find(c=>c.name.toLowerCase().includes(toCity))||selectedTo;
    if(cf&&ct){ selectedFrom=cf; selectedTo=ct; showRouteMap(); }
  }
}

// ═══ КАБИНЕТ — внутренние вкладки ═══
var _currentCabTab = 'loads';

function switchCabTab(tab, el){
 _currentCabTab = tab;
 document.querySelectorAll('.cab-tab').forEach(function(b){
 b.classList.remove('active');
 if(!b.classList.contains('cab-tab-btn')){
 b.style.color = '#aaa';
 b.style.borderBottomColor = 'transparent';
 }
 });
 if(el){
 el.classList.add('active');
 if(!el.classList.contains('cab-tab-btn')){
 el.style.color = '#f7b731';
 el.style.borderBottomColor = '#f7b731';
 }
 }
 document.querySelectorAll('.cab-tab-content').forEach(function(d){ d.style.display = 'none'; });
 var content = document.getElementById('cabTab-' + tab);
 if(content) content.style.display = 'block';
 localStorage.setItem('ch_cab_tab', tab);
 if(tab === 'deals') renderCabDeals();
 if(tab === 'loads') renderCabLoads();
 if(tab === 'responses') renderCabResponses();
}
function showCabinet(){
  var empty = document.getElementById('ordersEmpty');
  var panel = document.getElementById('cabinetPanel');
  var tk = getToken ? getToken() : localStorage.getItem('ch_token');
  if(!tk){ if(empty) empty.style.display='block'; if(panel) panel.style.display='none'; return; }
  if(empty) empty.style.display='none';
  if(panel) panel.style.display='block';
 // Заполняем шапку кабинета
 var u = user || (localStorage.getItem('ch_user') ? JSON.parse(localStorage.getItem('ch_user')) : null);
 if(u){
 var nameEl = document.getElementById('cabUserName');
 var subEl = document.getElementById('cabUserSub');
 var avatarEl = document.getElementById('cabAvatar');
 if(nameEl) nameEl.textContent = u.name || u.company_name || u.email || '';
 if(subEl) subEl.textContent = (u.email || '') + (u.role ? ' · ' + (u.role === 'carrier' ? (TRANSLATIONS[lang]||TRANSLATIONS['ru']).role_carrier||'Перевозчик' : (TRANSLATIONS[lang]||TRANSLATIONS['ru']).role_shipper||'Грузовладелец') : '');
 if(avatarEl){
 var nm = u.name || u.company_name || u.email || '?';
 avatarEl.textContent = nm.charAt(0).toUpperCase();
 }
 }
  // Восстанавливаем последнюю вкладку
  var savedCabTab = localStorage.getItem('ch_cab_tab') || 'loads';
  var tabBtn = document.querySelector('.cab-tab[onclick*="switchCabTab(\''+savedCabTab+'\'"]');
  switchCabTab(savedCabTab, tabBtn);
  // Грузим данные
  loadCabinetData();
}

function loadCabinetData(){
  var tk = getToken ? getToken() : localStorage.getItem('ch_token');
  if(!tk) return;
  // Мои грузы
  fetch('https://api-production-f3ea.up.railway.app/api/loads/my/loads',{headers:{'Authorization':'Bearer '+tk}})
    .then(r=>r.ok?r.json():null).then(data=>{
      if(!data) return;
      var loads = data.loads || [];
      _myLoads = loads.map(l=>typeof mapServerLoad==='function'?mapServerLoad(l):l);
      // Отклики на каждый груз
      loads.forEach(l=>{
        fetch('https://api-production-f3ea.up.railway.app/api/responses/load/'+l.id,{headers:{'Authorization':'Bearer '+tk}})
          .then(r=>r.ok?r.json():null).then(d=>{
            if(!d) return;
            _loadResponses[l.id]=(d.responses||[]).map(r=>({id:r.id,name:r.carrier_name||(TRANSLATIONS[lang]||TRANSLATIONS['ru']).role_carrier||'Перевозчик',phone:r.carrier_phone||null,message:r.message||null,price:r.price||null,status:r.status||'pending'}));
            if(_currentCabTab==='loads') renderCabLoads();
          }).catch(()=>{});
      });
      if(_currentCabTab==='loads') renderCabLoads();
    }).catch(()=>{});
  // Мои отклики как перевозчик
  fetch('https://api-production-f3ea.up.railway.app/api/responses/my',{headers:{'Authorization':'Bearer '+tk}})
    .then(r=>r.ok?r.json():null).then(d=>{
      if(!d) return;
      _orders = (d.responses||[]).map(r=>({id:r.id,serverId:r.id,loadId:r.load_id,title:(r.from||'?')+' → '+(r.to||'?'),from:r.from,to:r.to,price:r.price,cur:'₾',co:r.company_name||'—',status:r.status,created:r.created_at}));
      persistOrders();
      if(_currentCabTab==='responses') renderCabResponses();
    }).catch(()=>{});
  // Сделки
  fetch('https://api-production-f3ea.up.railway.app/api/deals/my',{headers:{'Authorization':'Bearer '+tk}})
    .then(r=>r.ok?r.json():null).then(d=>{
      if(!d) return;
      _deals = d.deals||[];
      if(_currentCabTab==='deals') renderCabDeals();
    }).catch(()=>{});
}

function renderCabLoads(){
 var el = document.getElementById('myLoadsList');
 if(!el) return;
 var cabStat = document.getElementById('cabStatLoads');
 if(cabStat) cabStat.textContent = _myLoads.length;
 if(!_myLoads.length){
 el.innerHTML = '<div class="cab-empty"><div class="cab-empty-icon">📦</div><div class="cab-empty-title">Нет размещённых грузов</div><div class="cab-empty-sub">Разместите груз и перевозчики сразу увидят его</div><div style="margin-top:14px"><button onclick="openPostLoad()" class="cab-btn primary" style="padding:10px 24px;font-size:14px">+ Разместить груз</button></div></div>';
 return;
 }
 el.innerHTML = _myLoads.map(function(l){
 var responses = _loadResponses[l.id] || [];
 var isIntl = l.scope === 'intl';
 var borderCls = l.urgent ? 'urgent' : (isIntl ? 'intl' : '');
 var respBadge = responses.length
 ? '<span class="cab-resp-badge has">' + responses.length + ' откл.</span>'
 : '<span class="cab-resp-badge none">Нет откликов</span>';
 var respBlock = '';
 if(responses.length){
 respBlock = '<div class="cab-inline-resps"><div class="cab-inline-resp-label">Отклики (' + responses.length + ')</div>'
 + responses.map(function(r){
 var actions = '';
 if(r.status === 'pending'){
 actions = '<div class="cab-inline-resp-actions"><button onclick="acceptResponse(' + l.id + ',' + r.id + ')" class="cab-accept-btn">✓ Принять</button><button onclick="rejectResponse(' + l.id + ',' + r.id + ')" class="cab-reject-btn">✕</button></div>';
 } else if(r.status === 'accepted'){
 actions = '<span class="cab-status-badge accepted">Принят</span>';
 } else {
 actions = '<span class="cab-status-badge rejected">Отклонён</span>';
 }
 return '<div class="cab-inline-resp-row"><div><div class="cab-inline-resp-name">' + r.name + '</div>' + (r.price ? '<div class="cab-inline-resp-price">₾' + r.price + '</div>' : '') + (r.phone ? '<a href="tel:' + r.phone + '" style="font-size:11px;color:#1a6ec0;text-decoration:none;display:block">📞 ' + r.phone + '</a>' : '') + '</div>' + actions + '</div>';
 }).join('') + '</div>';
 } else {
 respBlock = '<div style="font-size:12px;color:#ccc;padding:6px 0;text-align:center">Откликов пока нет</div>';
 }
 return '<div class="cab-load-card ' + borderCls + '">'
 + '<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px">'
 + '<div style="flex:1"><div class="cab-load-route">' + l.from + ' → ' + l.to + '</div>'
 + '<div class="cab-load-meta"><span>' + (l.kg||0).toLocaleString() + ' кг</span><span>' + (l.typeLabel||'') + '</span><span>' + (l.cur||'₾') + (l.price||0) + '</span>' + (l.date ? '<span>' + l.date + '</span>' : '') + '</div></div>'
 + '<div style="display:flex;flex-direction:column;gap:4px;flex-shrink:0">'
 + '<button onclick="editMyLoad(' + l.id + ')" class="cab-btn edit">✏️ Изменить</button>'
 + '<button onclick="deleteMyLoad(' + l.id + ')" class="cab-btn del">✕ Удалить</button>'
 + '</div></div>'
 + '<div class="cab-load-footer" style="margin-top:10px">' + respBadge + '</div>'
 + respBlock
 + '</div>';
 }).join('')
 + '<div class="cab-add-btn"><button onclick="openPostLoad()" class="cab-btn primary" style="padding:9px 20px;font-size:13px">+ Разместить новый груз</button></div>';
}
function renderCabResponses(){
 var el = document.getElementById('myResponsesList');
 if(!el) return;
 if(!_orders || !_orders.length){
 el.innerHTML = '<div class="cab-empty"><div class="cab-empty-icon">🚛</div><div class="cab-empty-title">Нет активных откликов</div><div class="cab-empty-sub">Откликнитесь на грузы — они появятся здесь</div></div>';
 var badge = document.getElementById('cabRespBadge');
 if(badge) badge.style.display = 'none';
 return;
 }
 var pendingCount = _orders.filter(function(o){ return o.status === 'pending'; }).length;
 var badge = document.getElementById('cabRespBadge');
 if(badge){
 if(pendingCount > 0){ badge.style.display = 'inline'; badge.textContent = pendingCount; }
 else badge.style.display = 'none';
 }
 el.innerHTML = _orders.map(function(o){
 var statusCls = o.status === 'accepted' ? 'accepted' : o.status === 'rejected' ? 'rejected' : 'pending';
 var statusLabel = o.status === 'accepted' ? '✅ Принят' : o.status === 'rejected' ? '❌ Отклонён' : '⏳ Ожидание';
 var ts = '';
 try { ts = new Date(o.created).toLocaleString('ru', {day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit'}); } catch(e){}
 var cancelBtn = o.status === 'pending'
 ? '<div style="margin-top:8px"><button onclick="cancelMyResponse(' + o.id + ',' + (o.serverId||0) + ')" class="cab-btn del" style="width:100%;padding:7px;font-size:13px">✕ Отменить заявку</button></div>'
 : '';
 return '<div class="cab-resp-item">'
 + '<div><div class="cab-resp-route">🚛 ' + o.title + '</div>'
 + '<div class="cab-resp-meta">' + (o.price && o.price !== 'null' && o.price !== null ? '₾' + o.price + ' · ' : '') + o.co + (ts ? ' · ' + ts : '') + '</div>'
 + cancelBtn + '</div>'
 + '<span class="cab-status-badge ' + statusCls + '">' + statusLabel + '</span>'
 + '</div>';
 }).join('');
}
function renderCabDeals(){
 var el = document.getElementById('myDealsList');
 if(!el) return;
 if(!_deals || !_deals.length){
 el.innerHTML = '<div class="cab-empty"><div class="cab-empty-icon">🤝</div><div class="cab-empty-title">Нет сделок</div><div class="cab-empty-sub">Примите отклик на груз чтобы создать сделку</div></div>';
 return;
 }
 var cabDeals = document.getElementById('cabStatDeals');
 if(cabDeals) cabDeals.textContent = _deals.length;
 var total = _deals.reduce(function(s,d){ return s + (d.price||d.agreed_price||0); }, 0);
 var cabRev = document.getElementById('cabStatRevenue');
 if(cabRev) cabRev.textContent = '₾' + total.toLocaleString();
 var ST = {
 confirmed:{l:'✅ Подтверждена',cls:'accepted'},
 loading:{l:'🔄 Загрузка',cls:'pending'},
 in_transit:{l:'🚛 В пути',cls:'pending'},
 delivered:{l:'📍 Доставлено',cls:'accepted'},
 completed:{l:'🏆 Завершена',cls:'accepted'},
 cancelled:{l:'❌ Отменена',cls:'rejected'}
 };
 var tk = getToken ? getToken() : localStorage.getItem('ch_token');
 el.innerHTML = _deals.map(function(d){
 var st = ST[d.status] || {l:d.status,cls:'pending'};
 var carrier = d.carrier_name || (d.carrier && d.carrier.name) || '';
 return '<div class="cab-deal-card">'
 + '<div class="cab-deal-header">'
 + '<div><div class="cab-deal-num">' + (d.deal_number||'#'+d.id) + '</div>'
 + '<div class="cab-deal-route">' + (d.load_from||'?') + ' → ' + (d.load_to||'?') + '</div></div>'
 + '<div style="text-align:right"><div class="cab-deal-price">₾' + (d.price||d.agreed_price||0).toLocaleString() + '</div>'
 + '<span class="cab-status-badge ' + st.cls + '">' + st.l + '</span></div>'
 + '</div>'
 + '<div class="cab-deal-meta">'
 + (d.load_kg ? '<span>⚖️ ' + d.load_kg.toLocaleString() + ' кг</span>' : '')
 + (carrier ? '<span>🚛 ' + carrier + '</span>' : '')
 + '</div>'
 + '<div class="cab-deal-actions">'
 + '<a href="https://api-production-f3ea.up.railway.app/api/deals/' + d.id + '/act.pdf?token=' + tk + '" target="_blank" class="cab-btn pdf" style="text-decoration:none;display:inline-block;padding:7px 14px;font-size:12px">📄 Скачать акт PDF</a>'
 + (d.status === 'confirmed' || d.status === 'in_transit'
 ? (d.id ? '<button onclick="confirmDelivery(' + d.id + ')" class="cab-btn primary" style="font-size:12px;padding:7px 14px">✅ Подтвердить доставку</button>' : '')
 : '')
 + '</div>'
 + '</div>';
 }).join('');
}
function showSection(name, el){
  _userClickedTab = true;
  document.querySelectorAll('.section').forEach(s=>s.classList.remove('active'));
  const _secEl = document.getElementById('sec-'+name);
  if(_secEl) _secEl.classList.add('active');
  if(name==='deals') setTimeout(loadDeals, 50);
  if(name==='trucks') setTimeout(syncTrucksFromServer, 50);
  document.querySelectorAll('.nav-tab').forEach(t=>t.classList.remove('active'));
  if(el) el.classList.add('active');
  localStorage.setItem('ch_tab', name);
  document.querySelectorAll('.bitem').forEach(b=>b.classList.remove('active'));
  const map={loads:0,trucks:1,rates:3,orders:4,cabinet:4};
  const bnav=document.querySelectorAll('.bitem');
  if(map[name]!==undefined) bnav[map[name]].classList.add('active');
  if(name==='trucks') renderTrucks();
  if(name==='cabinet' || name==='orders'){
    if(typeof showCabinet === 'function') showCabinet();
    else setTimeout(function(){ if(typeof showCabinet==='function') showCabinet(); }, 100);
  }
}

// ── SCOPE ─────────────────────────────────────────────
function setScope(s, el){
  scope=s;
  document.querySelectorAll('.scope-tab').forEach(t=>t.classList.remove('active'));
  el.classList.add('active');
  const data=s==='local'?LOCAL:INTL;
  renderLoads(data);
  syncLoadsFromServer(); // перезагружаем грузы при смене вкладки
  // statLoads updated by syncLoadsFromServer
  // statTrucks updated by syncLoadsFromServer
  document.getElementById('fcount').textContent=data.length+' грузов';
  // Показываем фильтр стран для международных
  const cf=document.getElementById('fCountry');
  if(cf) cf.style.display=s==='intl'?'block':'none';
  if(typeof updateFormForIntl==='function') updateFormForIntl();
  // Меняем placeholder полей откуда/куда
  const pfrom=document.getElementById('fFrom');
  const pto=document.getElementById('fTo');
  if(pfrom) pfrom.placeholder=s==='intl'?'🌍 Страна отправки':'📍 Откуда (город)';
  if(pto) pto.placeholder=s==='intl'?'🌍 Страна назначения':'🏁 Куда (город)';
  // Очищаем поля при смене scope
  if(pfrom) pfrom.value='';
  if(pto) pto.value='';
  selectedFrom=null; selectedTo=null;
  document.getElementById('mapWrap').classList.remove('open');
}

// ── LANG / i18n ───────────────────────────────────────
const TRANSLATIONS = {
  ru: {
    nav_exchange: 'Биржа',
    nav_orders: 'Мои заказы',
    nav_transport: 'Транспорт',
    nav_rates: 'Ставки',
    nav_deals: 'Мои сделки',
    hero_title: 'Биржа грузов',
    hero_sub: 'Кавказа',
    hero_desc: 'Грузы по Грузии и СНГ — быстро и надёжно',
    btn_post: 'Разместить груз',
    btn_find: 'Найти машину',
    tab_local: 'Локальные',
    tab_intl: 'Международные',
    btn_respond: 'Откликнуться',
    btn_login: 'Войти',
    btn_register: 'Регистрация',
    btn_place: 'Разместить',
    btn_filters: 'Фильтры',
    btn_search: 'Найти',
    lbl_from: 'Откуда',
    lbl_to: 'Куда',
    lbl_weight: 'Вес (кг)',
    lbl_trucktype: 'Тип кузова',
    lbl_price: 'Стоимость',
    lbl_desc: 'Описание груза',
    lbl_urgent: 'Срочно',
    status_confirmed: 'Подтверждено',
    status_loading: 'Загрузка',
    status_in_transit: 'В пути',
    status_delivered: 'Доставлено',
    status_completed: 'Завершено',
    opt_date: '📅 Дата',
    opt_today: 'Сегодня',
    opt_tomorrow: 'Завтра',
    opt_week: 'На неделе',
    opt_trucktype: '🚛 Кузов',
    opt_tonnage: '⚖️ Тоннаж',
    opt_price: '💰 Стоимость',
    ph_from: '📍 Откуда',
    ph_to: '🏁 Куда',
    badge_urgent: 'СРОЧНО',
    badge_new: 'НОВЫЙ',
    badge_intl: 'МЕЖД.',
    unit_kg: 'кг',
    card_respond: 'Отклик',
    card_sent: '✅ Отправлено',
    bnav_loads: 'Грузы',
    bnav_trucks: 'Машины',
    bnav_rates: 'Ставки',
    bnav_cabinet: 'Кабинет',
    bnav_post: 'Груз',
    nav_loads: '📦 Грузы',
    nav_rates2: '📊 Ставки',
    nav_cabinet: '📋 Кабинет',
    stat_loads: 'грузов',
    stat_trucks: 'машин онлайн',
    stat_companies: 'компаний',
    type_tent: 'Тент',
    type_ref: 'Рефриж.',
    type_bort: 'Борт',
    type_termos: 'Термос',
    type_gazel: 'Фургон',
    type_container: 'Контейнер',
    type_auto: 'Автовоз',
    type_other: 'Другой',
    modal_from: 'Откуда',
    modal_to: 'Куда',
    modal_date: 'Дата загрузки',
    modal_weight: 'Вес',
    modal_truck: 'Кузов',
    modal_pay: 'Оплата',
    fcount_suffix: 'грузов',
    th_route: 'ОТКУДА → КУДА',
    th_weight: 'ВЕС',
    th_truck: 'КУЗОВ',
    th_price: 'ЦЕНА',
    th_date: 'ДАТА ЗАГРУЗКИ',
    th_truck_route: 'МАШИНА / МАРШРУТ',
    th_company: 'КОМПАНИЯ',
    th_tonnage: 'ТОННАЖ',
    th_date2: 'ДАТА',
    th_route2: 'МАРШРУТ',
    th_tent_rate: 'ТЕНТ $/км',
    th_ref_rate: 'РЕФРИЖ $/км',
    th_trend: 'ТРЕНД',
    th_volume: 'ОБЪЁМ/НЕД',
    pay_cash: 'Наличные сразу',
    pay_cashless3: 'Безнал 3 дня',
    pay_cashless7: 'Безнал 7 дней',
    pay_prepay: '50% предоплата',
    unit_trips: 'рейсов',
    verified: 'Верифицирован',
    empty_loads: 'Грузов не найдено',
    empty_responses: 'Нет активных откликов',
    empty_trucks: 'Нет машин. Добавьте первую!',
    empty_myloads: 'Нет размещённых грузов',
    empty_deals: 'Нет сделок',
    login_for_deals: 'Войдите чтобы увидеть сделки',
    rates_subtitle: 'Средние ставки на маршрутах · обновлено сегодня',
    map_choose_route: 'Выберите маршрут',
    pop_routes: '🗺️ Популярные маршруты',
    loading_loads: '⏳ Загружаем грузы...',
    btn_add_truck: '+ Добавить машину',
    btn_add_truck2: '🚛 Добавить машину',
    btn_post_truck: '📤 Разместить машину',
    online_indicator: '● Онлайн 24/7',
    trips_suffix: 'рейсов',
    empty_orders: 'Нет активных заказов',
    empty_orders_sub: 'Откликайтесь на грузы — они появятся здесь',
    empty_myloads_sub: 'Разместите груз и перевозчики сразу увидят его',
    btn_post_load: '+ Разместить груз',
    btn_post_new: '+ Разместить новый груз',
    btn_respond_load: 'Откликнуться на груз',
    role_carrier: 'Перевозчик',
    role_shipper: 'Грузовладелец',
    role_both: 'Оба',
    btn_rate: '⭐ Оценить',
    btn_rated: '⭐ Оценено',
    btn_pdf: '📄 Акт PDF',
    status_confirmed: 'Подтверждено',
    status_loading: 'Загрузка',
    status_in_transit: 'В пути',
    status_delivered: 'Доставлено',
    status_completed: 'Завершено',
    status_rated: 'Оценено',
    reg_who: 'Кто вы?',
    reg_shipper_company: 'Грузовладелец — компания / ИП',
    reg_shipper_private: 'Грузовладелец — частное лицо',
    login_title: 'Войти в аккаунт',
    btn_register2: 'Зарегистрироваться',
    already_account: 'Уже есть аккаунт?',
    forgot_pwd: 'Забыли пароль?',
    btn_back: '← Назад',
    btn_back_login: '← Назад ко входу',
    login_new_pwd: 'Войдите с новым паролем',
    forgot_hint: 'Введите ваш email — пришлём код',
    code_label: 'Код подтверждения (6 цифр)',
    pwd_reset_title: '🔑 Сброс пароля',
    reg_company_label: 'Название компании / ФИО ИП',
    reg_name_label: 'Имя / Название компании',
    reg_city_label: 'Город / регион работы',
    reg_truck_type: 'Тип транспорта',
    reg_capacity_t: 'Грузоподъёмность (т)',
    reg_capacity_kg: 'Грузоподъёмность (кг)',
    reg_inn_ge: 'ИНН / ID код Грузия',
    reg_inn: 'ИНН / ID код',
    reg_org_form2: 'Форма организации',
    lbl_pay_type: 'Тип оплаты',
    btn_create_account: 'Создать аккаунт',
    reg_sub_carrier: 'Компания или ИП — ищу грузы',
    reg_sub_carrier2: 'Частный перевозчик',
    reg_private: 'Частное лицо',
    reg_choose_type: 'Выберите хотя бы один тип',
    reg_choose_all: '(выбери все свои)',
    post_hint: 'Заполните данные — перевозчики увидят ваш груз сразу',
    post_date_hint: 'Если груз гибкий — укажите диапазон',
    post_when: 'Когда готова',
    post_weight_label: 'Вес (кг)',
    post_date_label: 'Дата загрузки',
    date_from_label: 'Дата с',
    date_to_label: 'Дата по',
    pick_period: 'Выберите период',
    post_data_title: '📋 Данные груза:',
    post_addr_from: '📍 Точный адрес отправки',
    post_addr_to: '🏁 Точный адрес доставки',
    post_country_from: '🌍 Страна отправки',
    post_country_to: '🌍 Страна доставки',
    cab_my_orders: '📋 Мои заказы',
    cab_responses: '🚛 Отклики',
    cab_deals: '🤝 Сделки',
    cab_analytics: '📊 Моя аналитика',
    cab_settings: '⚙️ Настройки аккаунта',
    cab_notifications: '🔔 Уведомления',
    cab_logout: '🚪 Выйти',
    cab_settings_sub: 'Управление профилем и уведомлениями',
    cab_rs_hint: 'Данные о сделках для налоговой Грузии',
    cab_export: 'Экспорт для rs.ge',
    cab_report: '📊 Отчёт',
    cab_see_rates: '📊 Посмотреть тарифы →',
    this_month: 'В этом месяце',
    earned_march: 'Заработано (март)',
    truck_carrier_data: '🚛 Данные перевозчика',
    company_requisites: '📋 Реквизиты компании',
    tg_label: 'Telegram (для уведомлений)',
    btn_save: '💾 Сохранить',
    msg_registered: '✅ Аккаунт создан! Добро пожаловать!',
    msg_logged_in: '✅ Вход выполнен успешно!',
    msg_load_posted: '✅ Груз размещён! Перевозчики уже видят ваше объявление.',
    msg_respond_sent: '✅ Заявка отправлена! Заказчик получит уведомление.',
    msg_truck_added: '✅ Машина добавлена в список!',
    login_for_orders: (TRANSLATIONS[lang]||TRANSLATIONS['ru']).login_for_orders||'Войдите в аккаунт чтобы видеть свои заказы',
    login_for_cab: 'Войдите чтобы видеть свои грузы, отклики и сделки',
    no_notifs: 'Уведомлений нет',
    sub_all_standard: '✅ Всё из Стандарта',
    sub_50resp: '✅ 50 откликов в месяц',
    sub_unlimited: '✅ Безлимитные отклики',
    sub_verify: '✅ Верификация компании',
    sub_contacts: '✅ Видите контакты грузовладельца',
    sub_priority: '✅ Приоритет в выдаче',
    sub_urgent_first: '✅ Срочные грузы первым',
    sub_ai: '✅ AI диспетчер без лимитов',
    sub_loads_find: 'Грузы находят тебя сами',
    notif_my_routes: 'Грузы по моим маршрутам',
    notif_rate_changes: 'Изменение ставок на маршрутах',
    per_month: '/мес',
    loading_text: 'Загрузка...',
    added: 'Добавлен',
    added_today: 'Добавлен сегодня',
    unit_respond: 'отклик',
    default_desc: 'Груз без описания',
    ph_your_price: 'Ваша цена (необязат.)',
    respond_hint: '📞 После принятия отклика грузовладелец свяжется с вами',
    btn_show_route: '🗺️ Показать маршрут на карте',
    respond_sent: '✅ Заявка отправлена',
    btn_cancel: '✕ Отменить',
    btn_edit: '✏️ Редактировать',
    lbl_rate_modal: 'Ставка',
    lbl_distance: 'Расстояние',
    pay_cash_short: 'Наличные',
    pay_cashless: 'Безнал',
    modal_post_title: 'Разместить груз',
    lbl_weight_form: 'Вес (кг)',
    lbl_trucktype_form: 'Тип кузова',
    lbl_load_date: 'Дата загрузки',
    lbl_rate_form: 'Ставка (₾)', lbl_rate_intl: 'Ставка ($)',
    lbl_cargo_desc: 'Описание груза',
    lbl_pay_type: 'Тип оплаты',
    lbl_urgent_check: 'Срочный груз',
    btn_cancel_form: 'Отмена',
    btn_post_submit: '📦 Разместить груз',
    hint_flexible_date: 'Если груз гибкий — укажите диапазон',
    truck_tent: 'Тент', truck_ref_full: 'Рефрижератор',
    truck_reftent: 'Рефтент', truck_megatent: 'Мегатент',
    truck_bort_full: 'Бортовой', truck_termos_full: 'Термос',
    truck_gazel_full: 'Фургон (до 3.5т)', truck_container_full: 'Контейнер',
    truck_auto_full: 'Автовоз', truck_evac: 'Эвакуатор',
    truck_cistern: 'Цистерна', truck_grain: 'Зерновоз',
    truck_dump: 'Самосвал', truck_other_full: 'Другой',
    role_carrier: 'Перевозчик', role_shipper_co: 'Грузовладелец — компания / ИП',
    role_shipper_person: 'Грузовладелец — частное лицо',
    role_carrier_sub: 'Компания или ИП — ищу грузы',
    role_person_sub: 'Разовые отправки, без ИП',
    role_shipper_co_sub: 'Регулярные отправки, договор',
    lbl_company_name: 'Имя / Название компании', lbl_name: 'Имя',
    lbl_city: 'Город / регион работы',
    lbl_capacity: 'Грузоподъёмность (т)', lbl_capacity_kg: 'Грузоподъёмность (кг)',
    lbl_inn: 'ИНН / ID код', lbl_inn_ge: 'ИНН / ID код Грузия',
    btn_register_submit: 'Зарегистрироваться', btn_login_submit: 'Войти в аккаунт',
    link_forgot: 'Забыли пароль?',
    hint_forgot_email: 'Введите ваш email — пришлём код',
    lbl_code: 'Код подтверждения (6 цифр)', hint_new_pass: 'Войдите с новым паролем',
    btn_login_short: 'Войти', carrier_promo: 'Грузы находят тебя сами',
  },
  ge: {
    nav_exchange: 'ბირჟა',
    nav_orders: 'ჩემი შეკვეთები',
    nav_transport: 'ტრანსპორტი',
    nav_rates: 'ტარიფები',
    nav_deals: 'ჩემი გარიგებები',
    hero_title: 'სატვირთო ბირჟა',
    hero_sub: 'კავკასიის',
    hero_desc: 'ტვირთები საქართველოს მასშტაბით — სწრაფად და საიმედოდ',
    btn_post: 'ტვირთის განთავსება',
    btn_find: 'მანქანის პოვნა',
    tab_local: 'ადგილობრივი',
    tab_intl: 'საერთაშორისო',
    btn_respond: 'გამოხმაურება',
    btn_login: 'შესვლა',
    btn_register: 'რეგისტრაცია',
    btn_place: 'განთავსება',
    btn_filters: 'ფილტრები',
    btn_search: 'ძებნა',
    lbl_from: 'საიდან',
    lbl_to: 'სად',
    lbl_weight: 'წონა (კგ)',
    lbl_trucktype: 'კუზოვის ტიპი',
    lbl_price: 'ღირებულება',
    lbl_desc: 'ტვირთის აღწერა',
    lbl_urgent: 'სასწრაფო',
    status_confirmed: 'დადასტურებული',
    status_loading: 'დატვირთვა',
    status_in_transit: 'გზაში',
    status_delivered: 'მიტანილია',
    status_completed: 'დასრულებული',
    opt_date: '📅 თარიღი',
    opt_today: 'დღეს',
    opt_tomorrow: 'ხვალ',
    opt_week: 'კვირაში',
    opt_trucktype: '🚛 კუზოვი',
    opt_tonnage: '⚖️ ტონაჟი',
    opt_price: '💰 ღირებულება',
    ph_from: '📍 საიდან',
    ph_to: '🏁 სად',
    badge_urgent: 'სასწრაფო',
    badge_new: 'ახალი',
    badge_intl: 'საერთ.',
    unit_kg: 'კგ',
    card_respond: 'გამოხმაურება',
    card_sent: '✅ გაგზავნილია',
    bnav_loads: 'ტვირთები',
    bnav_trucks: 'მანქანები',
    bnav_rates: 'ტარიფები',
    bnav_cabinet: 'კაბინეტი',
    bnav_post: 'ტვირთი',
    nav_loads: '📦 ტვირთები',
    nav_rates2: '📊 ტარიფები',
    nav_cabinet: '📋 კაბინეტი',
    stat_loads: 'ტვირთი',
    stat_trucks: 'მანქანა ონლაინ',
    stat_companies: 'კომპანია',
    type_tent: 'ტენტი',
    type_ref: 'რეფრიჟ.',
    type_bort: 'ბორტი',
    type_termos: 'თერმოსი',
    type_gazel: 'ფურგონი',
    type_container: 'კონტეინერი',
    type_auto: 'ავტოვოზი',
    type_other: 'სხვა',
    modal_from: 'საიდან',
    modal_to: 'სად',
    modal_date: 'ჩატვირთვის თარიღი',
    modal_weight: 'წონა',
    modal_truck: 'კუზოვი',
    modal_pay: 'გადახდა',
    fcount_suffix: 'ტვირთი',
    th_route: 'საიდან → სად',
    th_weight: 'წონა',
    th_truck: 'კუზოვი',
    th_price: 'ფასი',
    th_date: 'ჩატვირთვის თარიღი',
    th_truck_route: 'მანქანა / მარშრუტი',
    th_company: 'კომპანია',
    th_tonnage: 'ტონაჟი',
    th_date2: 'თარიღი',
    th_route2: 'მარშრუტი',
    th_tent_rate: 'ტენტი $/კმ',
    th_ref_rate: 'რეფრიჟ. $/კმ',
    th_trend: 'ტენდენცია',
    th_volume: 'მოცულობა/კვ',
    pay_cash: 'ნაღდი ანგარიშსწორება',
    pay_cashless3: 'უნაღდო 3 დღე',
    pay_cashless7: 'უნაღდო 7 დღე',
    pay_prepay: '50% წინასწარი გადახდა',
    unit_trips: 'გზა',
    verified: 'ვერიფიცირებული',
    empty_loads: 'ტვირთი ვერ მოიძებნა',
    empty_responses: 'გამოხმაურებები არ არის',
    empty_trucks: 'მანქანები არ არის. დაამატეთ პირველი!',
    empty_myloads: 'განთავსებული ტვირთი არ არის',
    empty_deals: 'გარიგებები არ არის',
    login_for_deals: 'შედით გარიგებების სანახავად',
    rates_subtitle: 'საშუალო ტარიფები მარშრუტებზე · განახლდა დღეს',
    map_choose_route: 'აირჩიეთ მარშრუტი',
    pop_routes: '🗺️ პოპულარული მარშრუტები',
    loading_loads: '⏳ იტვირთება...',
    btn_add_truck: '+ მანქანის დამატება',
    btn_add_truck2: '🚛 მანქანის დამატება',
    btn_post_truck: '📤 მანქანის განთავსება',
    online_indicator: '● ონლაინ 24/7',
    trips_suffix: 'გზა',
    empty_orders: 'შეკვეთები არ არის',
    empty_orders_sub: 'გამოხმაურება — ტვირთები აქ გამოჩნდება',
    empty_myloads_sub: 'განათავსეთ ტვირთი და გადამზიდველები დაუყოვნებლივ დაინახავენ',
    btn_post_load: '+ ტვირთის განთავსება',
    btn_post_new: '+ ახალი ტვირთის განთავსება',
    btn_respond_load: 'ტვირთზე გამოხმაურება',
    role_carrier: 'გადამზიდველი',
    role_shipper: 'ტვირთის მფლობელი',
    role_both: 'ორივე',
    btn_rate: '⭐ შეფასება',
    btn_rated: '⭐ შეფასებულია',
    btn_pdf: '📄 აქტი PDF',
    status_confirmed: 'დადასტურებული',
    status_loading: 'დატვირთვა',
    status_in_transit: 'გზაში',
    status_delivered: 'მიტანილია',
    status_completed: 'დასრულებული',
    status_rated: 'შეფასებულია',
    reg_who: 'ვინ ხართ?',
    reg_shipper_company: 'ტვირთის მფლობელი — კომპ./ინდ.მ.',
    reg_shipper_private: 'ტვირთის მფლობელი — კერძო პირი',
    login_title: 'ანგარიშში შესვლა',
    btn_register2: 'რეგისტრაცია',
    already_account: 'უკვე გაქვთ ანგარიში?',
    forgot_pwd: 'დაგავიწყდათ პაროლი?',
    btn_back: '← უკან',
    btn_back_login: '← შესვლასთან დაბრუნება',
    login_new_pwd: 'შედით ახალი პაროლით',
    forgot_hint: 'შეიყვანეთ ელ.ფოსტა — გამოვგზავნით კოდს',
    code_label: 'დამადასტურებელი კოდი (6 ციფრი)',
    pwd_reset_title: '🔑 პაროლის აღდგენა',
    reg_company_label: 'კომპანიის სახელი / სახელი',
    reg_name_label: 'სახელი / კომპანიის სახელი',
    reg_city_label: 'ქალაქი / სამუშაო რეგიონი',
    reg_truck_type: 'სატრანსპორტო სახეობა',
    reg_capacity_t: 'ტვირთამწეობა (ტ)',
    reg_capacity_kg: 'ტვირთამწეობა (კგ)',
    reg_inn_ge: 'სხ / ID კოდი',
    reg_inn: 'სხ / ID კოდი',
    reg_org_form2: 'ორგანიზაციის ფორმა',
    lbl_pay_type: 'გადახდის ტიპი',
    btn_create_account: 'ანგარიშის შექმნა',
    reg_sub_carrier: 'კომპანია ან ინდ.მ. — ვეძებ ტვირთებს',
    reg_sub_carrier2: 'კერძო გადამზიდველი',
    reg_private: 'კერძო პირი',
    reg_choose_type: 'აირჩიეთ მინიმუმ ერთი ტიპი',
    reg_choose_all: '(ყველა თქვენი)',
    post_hint: 'შეავსეთ მონაცემები — გადამზიდველები დაუყოვნებლივ დაინახავენ',
    post_date_hint: 'თუ თარიღი მოქნილია — მიუთითეთ დიაპაზონი',
    post_when: 'როდის არის მზად',
    post_weight_label: 'წონა (კგ)',
    post_date_label: 'ჩატვირთვის თარიღი',
    date_from_label: 'თარიღი-დან',
    date_to_label: 'თარიღი-მდე',
    pick_period: 'აირჩიეთ პერიოდი',
    post_data_title: '📋 ტვირთის მონაცემები:',
    post_addr_from: '📍 ზუსტი მისამართი (გაგზავნა)',
    post_addr_to: '🏁 ზუსტი მისამართი (მიტანა)',
    post_country_from: '🌍 გაგზავნის ქვეყანა',
    post_country_to: '🌍 მიტანის ქვეყანა',
    cab_my_orders: '📋 ჩემი შეკვეთები',
    cab_responses: '🚛 გამოხმაურებები',
    cab_deals: '🤝 გარიგებები',
    cab_analytics: '📊 ჩემი ანალიტიკა',
    cab_settings: '⚙️ ანგარიშის პარამეტრები',
    cab_notifications: '🔔 შეტყობინებები',
    cab_logout: '🚪 გასვლა',
    cab_settings_sub: 'პროფილის მართვა',
    cab_rs_hint: 'გარიგებების მონაცემები rs.ge-სთვის',
    cab_export: 'ექსპორტი rs.ge-სთვის',
    cab_report: '📊 ანგარიში',
    cab_see_rates: '📊 ტარიფების ნახვა →',
    this_month: 'ამ თვეში',
    earned_march: 'გამომუშავებული (მარ)',
    truck_carrier_data: '🚛 გადამზიდველის მონაცემები',
    company_requisites: '📋 კომპანიის რეკვიზიტები',
    tg_label: 'Telegram (შეტყობინებებისთვის)',
    btn_save: '💾 შენახვა',
    msg_registered: '✅ ანგარიში შეიქმნა! მოგესალმებით!',
    msg_logged_in: '✅ წარმატებით შეხვედით!',
    msg_load_posted: '✅ ტვირთი განთავსდა!',
    msg_respond_sent: '✅ განაცხადი გაგზავნილია!',
    msg_truck_added: '✅ მანქანა სიაში დაემატა!',
    login_for_orders: 'შედით ანგარიშში შეკვეთების სანახავად',
    login_for_cab: 'შედით ტვირთების სანახავად',
    no_notifs: 'შეტყობინება არ არის',
    sub_all_standard: '✅ სტანდარტის ყველაფერი',
    sub_50resp: '✅ 50 გამოხმაურება თვეში',
    sub_unlimited: '✅ ულიმიტო გამოხმაურებები',
    sub_verify: '✅ კომპანიის ვერიფიკაცია',
    sub_contacts: '✅ ტვირთის მფლობელის კონტაქტები',
    sub_priority: '✅ პრიორიტეტი',
    sub_urgent_first: '✅ სასწრაფო ტვირთები პირველი',
    sub_ai: '✅ AI დისპეტჩერი',
    sub_loads_find: 'ტვირთები თავად გიპოვიან',
    notif_my_routes: 'ტვირთები ჩემს მარშრუტებზე',
    notif_rate_changes: 'ტარიფების ცვლილება',
    per_month: '/თვე',
    loading_text: 'იტვირთება...',
    added: 'დამატებულია',
    added_today: 'დამატებულია დღეს',
    unit_respond: 'გამოხმაურება',
    default_desc: 'აღწერა არ არის',
    ph_your_price: 'თქვენი ფასი (სურვილისამებრ)',
    respond_hint: '📞 გამოხმაურების მიღების შემდეგ ტვირთის მფლობელი დაგიკავშირდებათ',
    btn_show_route: '🗺️ მარშრუტის ჩვენება რუკაზე',
    respond_sent: '✅ განაცხადი გაგზავნილია',
    btn_cancel: '✕ გაუქმება',
    btn_edit: '✏️ რედაქტირება',
    lbl_rate_modal: 'ტარიფი',
    lbl_distance: 'მანძილი',
    pay_cash_short: 'ნაღდი',
    pay_cashless: 'უნაღდო',
    modal_post_title: 'ტვირთის განთავსება',
    lbl_weight_form: 'წონა (კგ)',
    lbl_trucktype_form: 'კუზოვის ტიპი',
    lbl_load_date: 'ჩატვირთვის თარიღი',
    lbl_rate_form: 'ტარიფი (₾)', lbl_rate_intl: 'ტარიფი ($)',
    lbl_cargo_desc: 'ტვირთის აღწერა',
    lbl_pay_type: 'გადახდის ტიპი',
    lbl_urgent_check: 'სასწრაფო ტვირთი',
    btn_cancel_form: 'გაუქმება',
    btn_post_submit: '📦 ტვირთის განთავსება',
    hint_flexible_date: 'თუ თარიღი მოქნილია — მიუთითეთ დიაპაზონი',
    truck_tent: 'ტენტი', truck_ref_full: 'რეფრიჟერატორი',
    truck_reftent: 'რეფ-ტენტი', truck_megatent: 'მეგა-ტენტი',
    truck_bort_full: 'ბორტიანი', truck_termos_full: 'თერმოსი',
    truck_gazel_full: 'ფურგონი (3.5ტ-მდე)', truck_container_full: 'კონტეინერი',
    truck_auto_full: 'ავტოვოზი', truck_evac: 'ევაკუატორი',
    truck_cistern: 'ცისტერნა', truck_grain: 'მარცვლეულის',
    truck_dump: 'თვითმცლელი', truck_other_full: 'სხვა',
    role_carrier: 'გადამზიდველი', role_shipper_co: 'ტვირთის მფლობელი — კომპანია / ი/მ',
    role_shipper_person: 'ტვირთის მფლობელი — ფიზიკური პირი',
    role_carrier_sub: 'კომპანია ან ი/მ — ვეძებ ტვირთებს',
    role_person_sub: 'ერთჯერადი გაგზავნები, ი/მ-ის გარეშე',
    role_shipper_co_sub: 'რეგულარული გაგზავნები, ხელშეკრულება',
    lbl_company_name: 'სახელი / კომპანიის დასახელება', lbl_name: 'სახელი',
    lbl_city: 'ქალაქი / სამუშაო რეგიონი',
    lbl_capacity: 'ტვირთამწეობა (ტ)', lbl_capacity_kg: 'ტვირთამწეობა (კგ)',
    lbl_inn: 'საიდენტიფიკაციო კოდი', lbl_inn_ge: 'საიდენტ. კოდი (საქართველო)',
    btn_register_submit: 'ანგარიშის შექმნა', btn_login_submit: 'ანგარიშში შესვლა',
    link_forgot: 'დაგავიწყდათ პაროლი?',
    hint_forgot_email: 'შეიყვანეთ email — გამოგიგზავნით კოდს',
    lbl_code: 'დადასტურების კოდი (6 ციფრი)', hint_new_pass: 'შედით ახალი პაროლით',
    btn_login_short: 'შესვლა', carrier_promo: 'ტვირთები თავად გპოვებენ',
  }
};

function applyLang(l) {
  const T = TRANSLATIONS[l] || TRANSLATIONS['ru'];
  // textContent по data-i18n
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.dataset.i18n;
    if (T[key]) el.textContent = T[key];
  });
  // placeholder по data-i18n-ph
  document.querySelectorAll('[data-i18n-ph]').forEach(el => {
    const key = el.dataset.i18nPh;
    if (T[key]) el.placeholder = T[key];
  });
  // Города в таблице ставок (data-i18n-city)
  document.querySelectorAll('[data-i18n-city]').forEach(el => {
    const route = el.getAttribute('data-i18n-city');
    if (l === 'ge') {
      el.textContent = route.split(' → ').map(c => translateCity(c)).join(' → ');
    } else {
      el.textContent = route;
    }
  });
  // option с data-i18n (типы оплаты)
  document.querySelectorAll('option[data-i18n]').forEach(el => {
    const key = el.dataset.i18n;
    if (T[key]) el.textContent = T[key];
  });
  // рейсы/гзаt (data-i18n-trips="N")
  document.querySelectorAll('[data-i18n-trips]').forEach(el => {
    const n = el.getAttribute('data-i18n-trips');
    el.textContent = n + ' ' + (T.trips_suffix || 'рейсов');
  });
  // Заголовок страницы
  const titleEl = document.querySelector('title');
  if (titleEl) {
    const key = l === 'ge' ? 'data-i18n-title-ge' : 'data-i18n-title-ru';
    const val = titleEl.getAttribute(key);
    if (val) document.title = val;
  }
  // fcount — счётчик грузов
  const fcount = document.getElementById('fcount');
  if (fcount) {
    const m = fcount.textContent.match(/^(\d+)/);
    if (m) fcount.textContent = m[1] + ' ' + (T.fcount_suffix || 'грузов');
  }
  document.documentElement.lang = l === 'ge' ? 'ka' : l;
  // Перерисовываем карточки грузов если они уже загружены
  if (typeof renderLoads === 'function' && window.allLoads && window.allLoads.length) renderLoads();
}

function setLang(l, btn) {
  lang = l;
  document.querySelectorAll('.lang-btn').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  applyLang(l);
  localStorage.setItem('ch_lang', l);
}

// ── MODALS ────────────────────────────────────────────
function closeModal(id){ document.getElementById(id).classList.remove('on'); }
function closeOverlay(id,e){ if(e.target===document.getElementById(id)) closeModal(id); }

// ── COUNTRY FILTER ────────────────────────────────────
const COUNTRY_FLAGS={'GE':'🇬🇪','TR':'🇹🇷','AM':'🇦🇲','AZ':'🇦🇿','RU':'🇷🇺','UA':'🇺🇦','CN':'🇨🇳','DE':'🇩🇪','PL':'🇵🇱','IT':'🇮🇹','BG':'🇧🇬','KZ':'🇰🇿','UZ':'🇺🇿','TM':'🇹🇲','KG':'🇰🇬','TJ':'🇹🇯','MD':'🇲🇩','BY':'🇧🇾','IL':'🇮🇱','IR':'🇮🇷','AE':'🇦🇪','GR':'🇬🇷','RO':'🇷🇴'};
const COUNTRY_NAMES={'GE':'Грузия','TR':'Турция','AM':'Армения','AZ':'Азербайджан','RU':'Россия','UA':'Украина','CN':'Китай','DE':'Германия','PL':'Польша','IT':'Италия','BG':'Болгария'};
const COUNTRY_NAMES_GE={'GE':'საქართველო','TR':'თურქეთი','AM':'სომხეთი','AZ':'აზერბაიჯანი','RU':'რუსეთი','UA':'უკრაინა','CN':'ჩინეთი','DE':'გერმანია','PL':'პოლონეთი','IT':'იტალია','BG':'ბულგარეთი','KZ':'ყაზახეთი','UZ':'უზბეკეთი','BY':'ბელარუსი','IL':'ისრაელი','IR':'ირანი','AE':'არაბეთის გაერთიანებული საამიროები','GR':'საბერძნეთი','RO':'რუმინეთი'};

// Показываем/скрываем фильтр стран при переключении Local/Intl
// setScope расширен в оригинале

function filterByCountry(code){
  let data=[...INTL];
  if(code){
    const flag=COUNTRY_FLAGS[code]||'';
    const name=(COUNTRY_NAMES[code]||'').toLowerCase();
    data=data.filter(d=>{
      const toL=d.to.toLowerCase();
      const fromL=d.from.toLowerCase();
      return d.to.includes(flag)||d.from.includes(flag)||
             toL.includes(name)||fromL.includes(name);
    });
  }
  renderLoads(data);
  document.getElementById('fcount').textContent=data.length+' грузов';
}

function updateFormForIntl(){
  const isIntl=scope==='intl';
  const wFrom=document.getElementById('countryFromWrap');
  const wTo=document.getElementById('countryToWrap');
  if(wFrom) wFrom.style.display=isIntl?'block':'none';
  if(wTo) wTo.style.display=isIntl?'block':'none';
  const cl=document.getElementById('priceCurLabel');
  if(cl) cl.textContent=isIntl?'Ставка ($)':'Ставка (₾)';
}

// ── DATE FILTER ────────────────────────────────────────
function filterByDate(val){
  var pop = document.getElementById('datePeriodPop');
  if(val === 'pick'){
    // Показываем попап периода
    if(pop){ pop.style.display = pop.style.display==='none' ? 'block' : 'none'; }
    return;
  }
  // Закрываем попап если открыт
  if(pop) pop.style.display='none';
  if(!val){ filterLoads(); return; }
  var data = scope==='local' ? [...LOCAL] : [...INTL];
  if(val==='today') data = data.filter(function(d){ return d.date==='today'; });
  else if(val==='tomorrow') data = data.filter(function(d){ return d.date==='tomorrow'; });
  else if(val==='week') data = data.filter(function(d){ return d.date; });
  renderLoads(data);
  document.getElementById('fcount').textContent = data.length+' грузов';
}

function applyDatePeriod(){
  var fromStr = document.getElementById('fDateFrom').value;
  var toStr   = document.getElementById('fDateTo').value;
  document.getElementById('datePeriodPop').style.display = 'none';

  if(!fromStr && !toStr){ filterLoads(); return; }

  var fromDate = fromStr ? new Date(fromStr) : null;
  var toDate   = toStr   ? new Date(toStr)   : null;
  if(toDate) toDate.setHours(23,59,59);

  // Форматируем метку в select
  var label = '📅 ';
  if(fromStr && toStr) label += fromStr.split('-').reverse().join('.') + ' – ' + toStr.split('-').reverse().join('.');
  else if(fromStr) label += 'с ' + fromStr.split('-').reverse().join('.');
  else label += 'по ' + toStr.split('-').reverse().join('.');
  var sel = document.getElementById('fDate');
  var opt = sel.querySelector('option[value="pick_range"]');
  if(!opt){ opt = document.createElement('option'); opt.value='pick_range'; sel.appendChild(opt); }
  opt.textContent = label;
  sel.value = 'pick_range';

  var data = scope==='local' ? [...LOCAL] : [...INTL];
  data = data.filter(function(d){
    if(!d.date) return false;
    // Конвертируем d.date в Date
    var today = new Date(); today.setHours(0,0,0,0);
    var tomorrow = new Date(today); tomorrow.setDate(today.getDate()+1);
    var loadDate;
    if(d.date==='today') loadDate = today;
    else if(d.date==='tomorrow') loadDate = tomorrow;
    else {
      // dd.mm.yy или dd.mm.yyyy
      var parts = d.date.split('.');
      if(parts.length===3){
        var y = parts[2].length===2 ? '20'+parts[2] : parts[2];
        loadDate = new Date(y+'-'+parts[1]+'-'+parts[0]);
      }
    }
    if(!loadDate) return false;
    if(fromDate && loadDate < fromDate) return false;
    if(toDate   && loadDate > toDate)   return false;
    return true;
  });
  renderLoads(data);
  document.getElementById('fcount').textContent = data.length+' грузов';
}

function clearDatePeriod(){
  document.getElementById('fDateFrom').value = '';
  document.getElementById('fDateTo').value   = '';
  document.getElementById('datePeriodPop').style.display = 'none';
  var sel = document.getElementById('fDate');
  sel.value = '';
  filterLoads();
}

// Закрываем попап при клике вне
document.addEventListener('click', function(e){
  var pop = document.getElementById('datePeriodPop');
  var sel = document.getElementById('fDate');
  if(pop && !pop.contains(e.target) && e.target !== sel){
    pop.style.display = 'none';
  }
});


// ── SETTINGS & ANALYTICS ──────────────────────────────
function openSettings(){
  closeModal('profileOverlay');
  if(user){
    document.getElementById('sName').value=user.name||'';
    document.getElementById('sEmail').value=user.email||'';
    document.getElementById('sPhone').value=user.phone||'';
    document.getElementById('sTelegram').value=user.telegram||'';
    const sr=document.getElementById('sRole'); if(sr&&user.role) sr.value=user.role;
    document.getElementById('sInn').value=user.inn||'';
    document.getElementById('sInnAll').value=user.inn||'';
    document.getElementById('sInnAll').value=user.inn||'';
    const sotAll=document.getElementById('sOrgTypeAll'); if(sotAll) sotAll.value=user.orgType||'';
    document.getElementById('sCityAll').value=user.city||'';
    const sot=document.getElementById('sOrgType'); if(sot&&user.orgType) sot.value=user.orgType;
    const stt=document.getElementById('sTruckType'); if(stt&&user.truckType) stt.value=user.truckType;
    document.getElementById('sTonnage').value=user.tonnage||'';
  }
  // Показываем поля перевозчика только для carrier/both
  const cf=document.getElementById('sCarrierFields');
  const role=document.getElementById('sRole');
  if(cf&&role) cf.style.display=(role.value==='shipper')?'none':'block';
  if(role) role.onchange=()=>{ if(cf) cf.style.display=(role.value==='shipper')?'none':'block'; };
  document.getElementById('settingsOverlay').classList.add('on');
}
function saveSettings(){
  const name=document.getElementById('sName').value;
  const phone=document.getElementById('sPhone').value;
  const tg=document.getElementById('sTelegram').value;
  const role=document.getElementById('sRole').value;
  const inn=document.getElementById('sInn').value || document.getElementById('sInnAll').value;
  const orgType=document.getElementById('sOrgType').value || document.getElementById('sOrgTypeAll').value;
  const city=document.getElementById('sCityAll').value;
  const truckType=document.getElementById('sTruckType').value;
  const tonnage=document.getElementById('sTonnage').value;

  if(!user){ user = {}; }
  user.name=name||user.name||'Пользователь';
  user.phone=phone; user.telegram=tg; user.role=role;
  user.inn=inn; user.orgType=orgType; user.truckType=truckType; user.tonnage=tonnage; user.city=city;
  _lsSet('ch_user',JSON.stringify(user));

  // Обновляем UI
  const av=document.getElementById('userAvatar');
  if(av&&user.name) av.textContent=user.name.slice(0,2).toUpperCase();
  const pn=document.getElementById('profileName');
  if(pn&&user.name) pn.textContent=user.name;

  // Сохраняем на сервер
  if(getToken()){
    fetch('https://api-production-f3ea.up.railway.app/api/users/me', {
      method:'PUT',
      headers:{'Authorization':'Bearer '+getToken(),'Content-Type':'application/json'},
      body: JSON.stringify({
        company_name: name||null,
        phone: phone||null,
        inn: inn||null,
        org_type: orgType||null,
        city: city||null,
        telegram: tg||null,
        truck_type: truckType||null,
        tonnage: tonnage||null,
      })
    }).then(r=>r.ok?r.json():null).then(d=>{
      if(d) pushNotif('✅ Данные обновлены', 'Профиль сохранён на сервере', []);
    }).catch(()=>{});
  }

  closeModal('settingsOverlay');
  // Показываем подтверждение прямо на экране
  const toast = document.createElement('div');
  toast.textContent = '✅ Настройки сохранены';
  toast.style.cssText = 'position:fixed;bottom:80px;left:50%;transform:translateX(-50%);background:#2ecc71;color:#fff;padding:12px 24px;border-radius:30px;font-weight:700;font-size:15px;z-index:9999;box-shadow:0 4px 20px rgba(0,0,0,.2)';
  document.body.appendChild(toast);
  setTimeout(()=>toast.remove(), 2500);
  pushNotif('✅ Настройки сохранены', 'Профиль обновлён', []);
}

function openAnalytics(){
  closeModal('profileOverlay');
  if(user){
    document.getElementById('analyticsUser').textContent=`Статистика: ${user.name}`;
    // Реальные данные из сделок
    const _allDeals = (typeof _deals!=='undefined'&&_deals)||[];
    const _completedDeals = _allDeals.filter(d=>d.status==='completed');
    const _now = new Date();
    const _thisMonth = _allDeals.filter(d=>{
      const dt=new Date(d.created_at||d.updatedAt||0);
      return dt.getMonth()===_now.getMonth()&&dt.getFullYear()===_now.getFullYear();
    });
    const _revenue = _completedDeals.reduce(function(s,d){return s+(d.price||d.agreed_price||0);},0);
    document.getElementById('aStat1').textContent = user.trips || _allDeals.length || 0;
    document.getElementById('aStat2').textContent = _thisMonth.length;
    const _s3=document.getElementById('aStat3');
    if(_s3) _s3.textContent='₾'+_revenue.toLocaleString();
    const _s4=document.getElementById('aStat4');
    if(_s4) _s4.textContent=(user.rat?Math.round(parseFloat(user.rat)):5)+' ⭐';
    // Популярные маршруты
    const _routes={};
    _allDeals.forEach(function(d){
      if(d.load_from&&d.load_to){
        const k=d.load_from+' → '+d.load_to;
        _routes[k]=(_routes[k]||0)+1;
      }
    });
    const _topRoutes=Object.entries(_routes).sort((a,b)=>b[1]-a[1]).slice(0,3);
    const _rEl=document.getElementById('aRoutes');
    if(_rEl&&_topRoutes.length){
      _rEl.innerHTML=_topRoutes.map(function(r){
        return '<div style="display:flex;justify-content:space-between;padding:8px 12px;background:#f8f9fa;border-radius:8px">'
          +'<span style="font-size:13px">'+r[0]+'</span>'
          +'<span style="font-size:13px;font-weight:700;color:#f7b731">'+r[1]+' '+((TRANSLATIONS[typeof lang!=='undefined'?lang:'ru']||TRANSLATIONS['ru']).unit_trips||'рейсов')+'</span>'
          +'</div>';
      }).join('');
    }
  }
  document.getElementById('analyticsOverlay').classList.add('on');
}

// ── NOTIFICATIONS ─────────────────────────────────────
let _notifs=[], _orders=[];
// Восстанавливаем заявки из localStorage
try {
  const _savedOrd = JSON.parse(localStorage.getItem('ch_orders')||'[]');
  if(_savedOrd.length) _savedOrd.forEach(o=>_orders.push(o));
} catch(e){}
const _STATUS={pending:{l:'⏳ Ожидание',c:'s-pending'},accepted:{l:'✅ Принят',c:'s-accepted'},transit:{l:'🚛 В пути',c:'s-transit'},done:{l:'✔️ Завершён',c:'s-done'},rated:{l:'⭐ Оценён',c:'s-rated'}};

function pushNotif(title,body,actions){
  const n={id:Date.now()+(Math.random()*99|0),title,body,actions:actions||[],unread:true,time:new Date()};
  _notifs.unshift(n);
  _renderNotifs();
  _updateBadge();
}
function _renderNotifs(){
  const el=document.getElementById('notifList');
  if(!el)return;
  if(!_notifs.length){el.innerHTML='<div class="notif-empty">Нет уведомлений</div>';return;}
  el.innerHTML=_notifs.map(n=>{
    const t=n.time.toLocaleTimeString('ru',{hour:'2-digit',minute:'2-digit'});
    const a=n.actions.map(x=>`<button class="${x.c}" onclick="${x.fn}">${x.l}</button>`).join('');
    return `<div class="notif-item${n.unread?' unread':''}" onclick="_markRead(${n.id})">
      <div class="ni-title">${n.title}</div>
      <div class="ni-body">${n.body}</div>
      ${a?`<div class="ni-actions">${a}</div>`:''}
      <div class="ni-time">${t}</div>
    </div>`;
  }).join('');
}
function _markRead(id){const n=_notifs.find(x=>x.id===id);if(n)n.unread=false;_renderNotifs();_updateBadge();}
function clearNotifs(){_notifs.forEach(n=>n.unread=false);_renderNotifs();_updateBadge();}
function _updateBadge(){
  const c=_notifs.filter(n=>n.unread).length;
  const b=document.getElementById('notifBadge');
  if(b){b.textContent=c||'';b.classList.toggle('has',c>0);}
}
function toggleNotifs(){
  const p=document.getElementById('notifPanel');
  if(p){p.classList.toggle('open');if(p.classList.contains('open'))clearNotifs();}
}
document.addEventListener('click',function(e){
  const p=document.getElementById('notifPanel'),b=document.getElementById('notifBtn');
  if(p&&b&&!p.contains(e.target)&&!b.contains(e.target))p.classList.remove('open');
});

// Статусы заявок
function _renderOrders(){
  // Новый кабинет с вкладками активен — очищаем старый рендер
  var cab = document.getElementById('cabinetPanel');
  if(cab && cab.style.display !== 'none') {
    // Скрываем все старые элементы кабинета
    var oldList = document.getElementById('ordersList');
    if(oldList) { oldList.style.display='none'; oldList.innerHTML=''; }
    var oldEmpty = document.getElementById('ordersEmpty');
    if(oldEmpty) oldEmpty.style.display='none';
    var oldEp = document.getElementById('exportPanel');
    if(oldEp) oldEp.style.display='none';
    // Обновляем новый кабинет
    var tab = window._currentCabTab || 'loads';
    if(tab==='loads' && typeof renderCabLoads==='function'){
      renderCabLoads();
      // Обновляем бейдж новых откликов
      const _allNewResps = Object.values(_loadResponses||{}).flat().filter(r=>r.status==='pending').length;
      const _loadsBadge = document.getElementById('cabLoadsBadge');
      if(_loadsBadge){ if(_allNewResps>0){_loadsBadge.textContent=_allNewResps;_loadsBadge.style.display='inline';}else _loadsBadge.style.display='none'; }
    }
    if(tab==='responses' && typeof renderCabResponses==='function') renderCabResponses();
    if(tab==='deals' && typeof renderCabDeals==='function') renderCabDeals();
    return;
  }
  const empty=document.getElementById('ordersEmpty'),list=document.getElementById('ordersList');
  const hasContent=_orders.length||_myLoads.length||_deals.length;
  // Показываем exportPanel только если есть завершённые сделки
  const _ep=document.getElementById('exportPanel');
  const _tok = getToken ? getToken() : localStorage.getItem('ch_token');
  const _hasFinished = (_deals||[]).some(d => d.status==='completed'||d.status==='rated');
  if(_ep) _ep.style.display = (_tok && _hasFinished) ? 'flex' : 'none';
  if(!hasContent){
    if(empty){
      empty.style.display='block';
      if(_tok){
        empty.innerHTML='<div class="icon">📋</div><div style="font-size:18px;font-weight:700;color:#555;margin-bottom:8px">Нет активных заказов</div><div style="font-size:14px">Откликайтесь на грузы — они появятся здесь</div>';
      } else {
        empty.innerHTML='<div class="icon">📋</div><div style="font-size:18px;font-weight:700;color:#555;margin-bottom:8px">Нет активных заказов</div><div style="font-size:14px;margin-bottom:20px">Войдите в аккаунт чтобы видеть свои заказы</div><button class="btn-primary" style="max-width:200px;margin:0 auto" onclick="openAuth(\'login\')">Войти</button>';
      }
    }
    if(list)list.style.display='none';
    return;
  }
  if(empty)empty.style.display='none';
  if(!list)return;
  list.style.display='block';
  const ds=document.getElementById('dealsSection');
  if(ds){ds.style.display=getToken()?'block':'none';if(getToken())loadDeals();}

  // Мои размещённые грузы
  const myLoadsHtml=_myLoads.map(l=>{
    // Отклики на этот груз
    const responses = (_loadResponses[l.id]||[]);
    const respHtml = responses.length ? `
      <div style="margin-top:10px;border-top:1px solid #f0f0f0;padding-top:10px">
        <div style="font-size:12px;font-weight:700;color:#555;margin-bottom:8px">👥 Отклики (${responses.length}):</div>
        ${responses.map(r=>`
          <div style="display:flex;justify-content:space-between;align-items:center;padding:8px 10px;background:#f8f9fa;border-radius:8px;margin-bottom:6px">
            <div>
              <div style="font-weight:600;font-size:13px">${r.name}</div>
              <div style="font-size:11px;color:#888">${r.truck} · ${r.tonnage}т · ⭐${r.rating}</div>
            </div>
            <div style="display:flex;gap:6px">
              ${r.status==='pending'?`
                <button onclick="acceptResponse(${l.id},${r.id})" style="background:#2ecc71;color:#fff;border:none;padding:5px 10px;border-radius:6px;font-size:12px;cursor:pointer">✓ Принять</button>
                <button onclick="rejectResponse(${l.id},${r.id})" style="background:#fee;color:#e74c3c;border:1px solid #fcc;padding:5px 8px;border-radius:6px;font-size:12px;cursor:pointer">✕</button>
              `:r.status==='accepted'?`<span style="color:#2ecc71;font-size:12px;font-weight:700">✅ Принят</span>`:
               `<span style="color:#aaa;font-size:12px">Отклонён</span>`}
            </div>
          </div>
        `).join('')}
      </div>` : `<div style="font-size:12px;color:#aaa;margin-top:8px;text-align:center">Откликов пока нет</div>`;

    return `
    <div id="myload-${l.id}" style="padding:14px 16px;background:#fff;border-bottom:1px solid #f2f2f2;border-left:3px solid #2ecc71">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px">
        <div style="flex:1">
          <div style="font-weight:700">${l.from} → ${l.to}</div>
          <div style="font-size:12px;color:#888;margin-top:2px">${l.kg.toLocaleString()} кг · ${l.cur||'₾'}${l.price} · ${l.date}</div>
          <div style="font-size:12px;color:#888;margin-top:1px">${l.desc||''}</div>
        </div>
        <div style="display:flex;flex-direction:column;align-items:flex-end;gap:6px;flex-shrink:0">
          <span style="background:#e8f5e9;color:#2e7d32;padding:4px 8px;border-radius:10px;font-size:11px;white-space:nowrap">📦 Мой груз</span>
          <div style="display:flex;flex-direction:column;gap:4px">
            <button onclick="editMyLoad(${l.id})" style="background:#f0f7ff;color:#1a6ec0;border:1px solid #bee3f8;border-radius:8px;padding:5px 10px;cursor:pointer;font-size:11px;font-weight:600;white-space:nowrap">${(TRANSLATIONS[lang]||TRANSLATIONS['ru']).btn_edit||'✏️ Редактировать'}</button>
            <button onclick="deleteMyLoad(${l.id})" style="background:#fee;border:1px solid #fcc;color:#e74c3c;border-radius:8px;padding:5px 10px;cursor:pointer;font-size:11px;font-weight:600;white-space:nowrap">✕ Удалить</button>
          </div>
        </div>
      </div>
      ${respHtml}
    </div>`;
  }).join('');

  const ordersHtml = _orders.map(o=>{
    const s=_STATUS[o.status]||_STATUS.pending;
    let act='';
    if(o.status==='pending') act=`<button onclick="cancelMyResponse(${o.id},${o.serverId||0})" style="margin-top:8px;background:#fee;color:#e74c3c;border:1px solid #fcc;padding:6px 14px;border-radius:6px;font-size:13px;cursor:pointer;font-weight:600">✕ Отменить заявку</button>`;
    if(o.status==='accepted') act=`<div style="margin-top:8px;font-size:12px;color:#2980b9;background:#e3f2fd;padding:6px 12px;border-radius:6px">✅ Принят — следите за статусом в разделе <strong>Сделки</strong></div>`;
    if(o.status==='done') act=`<button onclick="_rate(${o.id})" style="margin-top:8px;background:#f0f2f5;border:none;padding:5px 14px;border-radius:6px;font-size:13px;cursor:pointer">⭐ Оставить отзыв</button>`;
    const ts=new Date(o.created).toLocaleString('ru',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});
    const bc=o.status==='accepted'?'#3498db':o.status==='done'?'#2ecc71':o.status==='transit'?'#9b59b6':'#f7b731';
    return `<div style="padding:14px 16px;background:#fff;border-bottom:1px solid #f2f2f2;border-left:3px solid ${bc}">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:4px">
        <div style="font-weight:700;font-size:14px">🚛 ${o.title}</div>
        <span class="sbadge ${s.c}">${s.l}</span>
      </div>
      <div style="font-size:12px;color:#888">${o.cur||'₾'}${o.price} · ${o.co||''} · ${ts}</div>
      ${act}
    </div>`;
  }).join('');

  // Рендерим сделки из API
  const dealsSection = _deals.length ? `
    <div style="padding:10px 16px 6px;background:#f8f9fa;border-bottom:1px solid #eee">
      <div style="font-size:11px;font-weight:700;color:#555;text-transform:uppercase;letter-spacing:.5px">🤝 Активные сделки</div>
    </div>
    ${_deals.map(d => renderDealCard(d)).join('')}
    <div style="height:8px;background:#f8f9fa"></div>
  ` : '';

  const myLoadsHeader = _myLoads.length ? `
    <div style="padding:10px 16px 6px;background:#f8f9fa;border-bottom:1px solid #eee">
      <div style="font-size:11px;font-weight:700;color:#555;text-transform:uppercase;letter-spacing:.5px">📦 Мои грузы</div>
    </div>
  ` : '';

  const ordersHeader = _orders.length ? `
    <div style="padding:10px 16px 6px;background:#f8f9fa;border-bottom:1px solid #eee">
      <div style="font-size:11px;font-weight:700;color:#555;text-transform:uppercase;letter-spacing:.5px">🚛 Мои отклики</div>
    </div>
  ` : '';

  list.innerHTML = dealsSection + myLoadsHeader + myLoadsHtml + ordersHeader + ordersHtml;
}
function _acceptOrder(id){const o=_orders.find(x=>x.id===id);if(!o)return;o.status='accepted';_renderOrders();pushNotif('✅ Принято!',`Груз "${o.title}" принят.`,[{l:'🚛 Доставлен',c:'ni-done',fn:`_delivered(${id})`}]);}
function _delivered(id){const o=_orders.find(x=>x.id===id);if(!o)return;o.status='done';_renderOrders();pushNotif('🎉 Доставлен!',`"${o.title}" доставлен. Оставьте отзыв.`,[{l:(TRANSLATIONS[lang]||TRANSLATIONS['ru']).btn_rate||'⭐ Оценить',c:'ni-done',fn:`_rate(${id})`}]);}
function _rate(id){const o=_orders.find(x=>x.id===id);if(!o)return;const r=prompt(`Оцените "${o.title}" (1-5):`,'5');if(r&&+r>=1&&+r<=5){o.status='rated';_renderOrders();pushNotif('⭐ Спасибо!',`Оценка ${r}/5 сохранена.`,[]);}}

// Переопределяем showUserState чтобы показывать колокольчик


// Переопределяем doRespond чтобы добавлять в _orders
// doRespond расширена выше

// showSection расширен через оригинал выше

// ── INIT ──────────────────────────────────────────────
// Восстанавливаем сессию безопасно
try{
  const _saved=_lsGet('ch_user');
  if(_saved&&_saved!=='null'){
    user=JSON.parse(_saved);
    if(user&&user.name){
      showUserState();
      // Восстанавливаем JWT токен
      if(user.token && typeof setToken!=='undefined') setToken(user.token);
      // Восстанавливаем currentUserId из сохранённого userId
      if(user.userId) currentUserId = Number(user.userId);
      // Синхронизируем грузы с сервером
      setTimeout(()=>{
        if(typeof syncLoadsFromServer==='function') syncLoadsFromServer();
      }, 300);
    }
  }
}catch(e){try{_lsDel('ch_user');}catch(e2){}}
// Устанавливаем min дату для календаря
const _dateInput=document.getElementById('fDate');
if(_dateInput){
  const _today=new Date();
  _dateInput.min=_today.toISOString().split('T')[0];
}
// Гарантируем рендер после загрузки DOM
if(document.readyState==='loading'){
  document.addEventListener('DOMContentLoaded',()=>{
    // Сначала рендерим из localStorage (мгновенно), потом sync с сервером
    if(LOCAL.length) renderLoads(LOCAL);
    syncLoadsFromServer();
  });
} else {
  // Сначала рендерим из localStorage (мгновенно), потом sync с сервером
  if(LOCAL.length) renderLoads(LOCAL);
  syncLoadsFromServer();
}

function openPlansModal(e){ 
  if(e) e.stopPropagation(); 
  closeModal('authOverlay'); 
  setTimeout(function(){ document.getElementById('paywallOverlay').classList.add('on'); }, 150); 
}

// ═══ DEALS (Мои сделки) ═══
const DEAL_STATUS_MAP = {
  pending:   {label:'⏳ Ожидание',    color:'#e67e22', bg:'#fff3e0'},
  confirmed: {label:'✅ Подтверждена',color:'#27ae60', bg:'#e8f5e9'},
  loading:   {label:'📦 Погрузка',    color:'#2980b9', bg:'#e3f2fd'},
  in_transit:{label:'🚛 В пути',      color:'#8e44ad', bg:'#f3e5f5'},
  delivered: {label:'📍 Доставлено',  color:'#16a085', bg:'#e0f2f1'},
  completed: {label:'🏆 Завершена',   color:'#27ae60', bg:'#e8f5e9'},
  cancelled: {label:'❌ Отменена',    color:'#e74c3c', bg:'#fce4ec'},
};
const DEAL_NEXT_MAP = {confirmed:'loading',loading:'in_transit',in_transit:'delivered'};
let dealsData = [], exportDateFrom='', exportDateTo='';

async function loadDeals(){
  const tk = getToken ? getToken() : localStorage.getItem('ch_token');
  if(!tk){document.getElementById('dealsLoading').style.display='none'; return;}
  document.getElementById('dealsLoading').style.display='block';
  document.getElementById('dealsList').innerHTML='';
  try{
    const r = await fetch(API_BASE+'/api/deals/my',{headers:{'Authorization':'Bearer '+tk}});
    if(r.ok){const d=await r.json();dealsData=d.deals||d||[];renderDeals();}
  }catch(e){}
  document.getElementById('dealsLoading').style.display='none';
}

function renderDeals(){
  const el=document.getElementById('dealsList');
  if(!el) return;
  if(!dealsData.length){
    el.innerHTML='<div style="text-align:center;padding:40px;background:#fff;border-radius:12px;color:#999"><div style="font-size:32px;margin-bottom:8px">📂</div><div>Сделок пока нет</div><div style="font-size:13px;margin-top:4px">Примите отклик на груз чтобы создать сделку</div></div>';
    return;
  }
  el.innerHTML='';
  dealsData.forEach(function(deal){
    const st=DEAL_STATUS_MAP[deal.status]||{label:deal.status,color:'#555',bg:'#f0f2f5'};
    const next=DEAL_NEXT_MAP[deal.status];
    const uid=currentUserId;
    const iS=uid&&deal.shipper&&deal.shipper.id==uid;
    const iC=uid&&deal.carrier&&deal.carrier.id==uid;
    const myConf=iS?deal.shipper_confirmed:iC?deal.carrier_confirmed:false;
    const card=document.createElement('div');
    card.style.cssText='background:#fff;border-radius:12px;padding:16px;margin-bottom:12px;box-shadow:0 2px 8px rgba(0,0,0,.06)';
    card.innerHTML='<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px">'
      +'<div><div style="font-size:16px;font-weight:900">'+(deal.load_from||'?')+' → '+(deal.load_to||'?')+'</div>'
      +'<div style="font-size:12px;color:#999;margin-top:2px">'+(deal.deal_number||'')+' · '+new Date(deal.created_at).toLocaleDateString('ru')+'</div></div>'
      +'<span style="background:'+st.bg+';color:'+st.color+';padding:4px 10px;border-radius:20px;font-size:12px;font-weight:700">'+st.label+'</span></div>'
      +'<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px;font-size:13px">'
      +'<div><span style="color:#aaa">Груз: </span>'+((deal.load_kg||0)).toLocaleString()+' кг</div>'
      +'<div><span style="color:#aaa">Сумма: </span><strong>'+(deal.currency||"₾")+((deal.price||0)).toLocaleString()+'</strong></div>'
      +'<div><span style="color:#aaa">Отправитель: </span>'+(deal.shipper&&deal.shipper.name||'—')+'</div>'
      +'<div><span style="color:#aaa">Перевозчик: </span>'+(deal.carrier&&deal.carrier.name||'—')+'</div></div>'
      +'<div id="deal-btns-'+deal.id+'" style="display:flex;gap:8px;flex-wrap:wrap"></div>';
    el.appendChild(card);
    const btns=document.getElementById('deal-btns-'+deal.id);
    if(next && deal.status !== 'in_transit'){const b=document.createElement('button');b.textContent='→ '+(DEAL_STATUS_MAP[next]&&DEAL_STATUS_MAP[next].label||next);b.style.cssText='background:#1a1a2e;color:#fff;border:none;padding:8px 14px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer';b.onclick=function(){updateDealStatus(deal.id,next);};btns.appendChild(b);} if(deal.status==='in_transit'){const isCa=currentUserId&&deal.carrier&&deal.carrier.id==currentUserId;if(isCa){const b=document.createElement('button');b.textContent='🏁 Груз доставлен';b.style.cssText='background:#f7b731;color:#1a1a2e;border:none;padding:8px 14px;border-radius:8px;font-size:13px;font-weight:700;cursor:pointer';b.onclick=function(){updateDealStatus(deal.id,'delivered');};btns.appendChild(b);}}
    if(deal.status==='delivered'&&!myConf){const b=document.createElement('button');b.textContent='✅ Подтвердить получение';b.style.cssText='background:#2ecc71;color:#fff;border:none;padding:8px 14px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer';b.onclick=function(){confirmDeal(deal.id);};btns.appendChild(b);}
    if(deal.status==='completed'){const b=document.createElement('button');b.textContent=(TRANSLATIONS[lang]||TRANSLATIONS['ru']).btn_rate||'⭐ Оценить';b.style.cssText='background:#f7b731;color:#1a1a2e;border:none;padding:8px 14px;border-radius:8px;font-size:13px;cursor:pointer';b.onclick=function(){rateDealDialog(deal.id,deal.deal_number||'');};btns.appendChild(b);}
    const bp=document.createElement('button');bp.textContent=(TRANSLATIONS[lang]||TRANSLATIONS['ru']).btn_pdf||'📄 Акт PDF';bp.style.cssText='background:#f0f2f5;color:#333;border:none;padding:8px 14px;border-radius:8px;font-size:13px;cursor:pointer';bp.onclick=function(){downloadPDF(deal.id,deal.deal_number||'deal');};btns.appendChild(bp);
  });
}

async function updateDealStatus(id,status){
  const tk=getToken?getToken():localStorage.getItem('ch_token');
  if(!tk)return;
  await fetch(API_BASE+'/api/deals/'+id+'/status',{method:'POST',headers:{'Authorization':'Bearer '+tk,'Content-Type':'application/json'},body:JSON.stringify({status})});
  loadDeals();
}
async function confirmDeal(id){
  const tk=getToken?getToken():localStorage.getItem('ch_token');
  await fetch(API_BASE+'/api/deals/'+id+'/confirm',{method:'POST',headers:{'Authorization':'Bearer '+tk}});
  loadDeals();
}
async function downloadPDF(id,num){
  const tk=getToken?getToken():localStorage.getItem('ch_token');
  const r=await fetch(API_BASE+'/api/deals/'+id+'/act.pdf',{headers:{'Authorization':'Bearer '+tk}});
  if(r.ok){const b=await r.blob();const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download=(num||'deal')+'.pdf';a.click();}
}
async function rateDealDialog(id,num){
  const s=prompt('Оцените сделку '+num+'\nВведите оценку от 1 до 5:');
  if(s&&!isNaN(s)&&s>=1&&s<=5){
    const tk=getToken?getToken():localStorage.getItem('ch_token');
    await fetch(API_BASE+'/api/deals/'+id+'/rate',{method:'POST',headers:{'Authorization':'Bearer '+tk,'Content-Type':'application/json'},body:JSON.stringify({score:parseInt(s)})});
    alert('Спасибо за оценку!');loadDeals();
  }
}
async function exportDealsData(fmt){
  const tk=getToken?getToken():localStorage.getItem('ch_token');
  let url=API_BASE+'/api/deals/export?format='+fmt;
  if(exportDateFrom)url+='&from='+exportDateFrom;
  if(exportDateTo)url+='&to='+exportDateTo;
  const r=await fetch(url,{headers:{'Authorization':'Bearer '+tk}});
  if(r.ok){const b=await r.blob();const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='deals.'+fmt;a.click();}
}

// Восстановление вкладки теперь в api.js → syncLoadsFromServer finally блок

// ═══ УВЕДОМЛЕНИЯ ═══
// _notifs already declared above
try { _notifs = JSON.parse(localStorage.getItem('ch_notifs')||'[]'); } catch(e){}

function pushNotif(title, body, actions){
  const n = {id:Date.now(), title, body, actions:actions||[], time:new Date().toLocaleTimeString('ru',{hour:'2-digit',minute:'2-digit'}), read:false};
  _notifs.unshift(n);
  if(_notifs.length > 20) _notifs = _notifs.slice(0,20);
  try{localStorage.setItem('ch_notifs',JSON.stringify(_notifs));}catch(e){}
  renderNotifs();
  // Flash bell
  const bell = document.getElementById('bellBtn');
  if(bell){ bell.style.animation='none'; setTimeout(()=>{bell.style.animation='bell-ring 0.5s';},10); }
}

function renderNotifs(){
  const list = document.getElementById('notifList');
  const count = document.getElementById('bellCount');
  if(!list) return;
  const unread = _notifs.filter(n=>!n.read).length;
  if(count){ count.style.display = unread ? 'block' : 'none'; count.textContent = unread > 9 ? '9+' : unread; }
  if(!_notifs.length){ list.innerHTML='<div style="text-align:center;padding:20px;color:#aaa;font-size:13px">Уведомлений нет</div>'; return; }
  list.innerHTML = _notifs.slice(0,10).map(n=>
    '<div style="padding:12px 16px;border-bottom:1px solid #f9f9f9;cursor:pointer" onclick="markRead('+n.id+')">'
    +'<div style="font-weight:600;font-size:13px">'+n.title+'</div>'
    +'<div style="font-size:12px;color:#888;margin-top:2px">'+n.body+'</div>'
    +'<div style="font-size:11px;color:#bbb;margin-top:4px">'+n.time+'</div>'
    +(n.actions&&n.actions.length?'<div style="display:flex;gap:6px;margin-top:6px">'+n.actions.map(a=>'<button onclick="('+(typeof a.action==="function"?a.action.toString()+"()":a.fn||"")+'; event.stopPropagation()" style="background:#f7b731;color:#1a1a2e;border:none;padding:4px 10px;border-radius:6px;font-size:11px;cursor:pointer">'+a.label+'</button>').join('')+'</div>':'')
    +'</div>'
  ).join('');
}

function markRead(id){ _notifs.forEach(n=>{ if(n.id===id) n.read=true; }); try{localStorage.setItem('ch_notifs',JSON.stringify(_notifs));}catch(e){} renderNotifs(); }
function clearNotifs(){ _notifs=[]; try{localStorage.removeItem('ch_notifs');}catch(e){} renderNotifs(); document.getElementById('notifPanel').style.display='none'; }
function toggleNotifPanel(){ 
  const p=document.getElementById('notifPanel'); 
  p.style.display=p.style.display==='none'?'block':'none';
  if(p.style.display==='block'){ _notifs.forEach(n=>n.read=true); try{localStorage.setItem('ch_notifs',JSON.stringify(_notifs));}catch(e){} renderNotifs(); }
}
// Закрытие при клике вне панели
document.addEventListener('click', function(e){ const p=document.getElementById('notifPanel'); const b=document.getElementById('bellBtn'); if(p&&b&&!p.contains(e.target)&&!b.contains(e.target)) p.style.display='none'; });
// Инициализация
setTimeout(renderNotifs, 100);

// ═══ ЯНДЕКС КАРТА В МОДАЛЕ ═══
window.openRouteMap = function(){
  // Берём from/to из текущего открытого груза
  let from = '', to = '';
  if(window.currentCargoId && window.allLoads){
    const d = window.allLoads.find(l=>l.id===window.currentCargoId);
    if(d){ from = d.from2||d.from||''; to = d.to2||d.to||''; }
  }
  // fallback: читаем из mGrid
  if(!from || !to){
    const cells = document.querySelectorAll('#mGrid > div > div:last-child');
    if(cells.length >= 2){ from = cells[0].textContent.trim(); to = cells[1].textContent.trim(); }
  }
  if(!from || !to){ alert('Не указан маршрут'); return; }
  
  const block = document.getElementById('routeMapBlock');
  if(!block) return;
  
  if(block.style.display !== 'none'){
    block.style.display = 'none';
    if(_routeMap){ _routeMap.destroy(); _routeMap=null; }
    const _mapBtn2 = document.querySelector('[onclick="openRouteMap()"]'); if(_mapBtn2) _mapBtn2.textContent = (TRANSLATIONS[lang]||TRANSLATIONS['ru']).btn_show_route||'🗺️ Показать маршрут на карте';
    return;
  }
  
  block.style.display = 'block';
  document.querySelector('[onclick="openRouteMap()"]').textContent = '🗺️ Скрыть карту';
  
  if(_routeMap){ _routeMap.destroy(); _routeMap=null; }
  
  var mapEl = document.getElementById('routeMapModal');
  mapEl.innerHTML='<div style="padding:30px;text-align:center;color:#aaa;font-size:14px">⏳ Загружаем карту...</div>';
  
  function _initMap(){
    if(typeof ymaps === 'undefined'){
      // ymaps ещё не загрузился — ждём
      setTimeout(_initMap, 300);
      return;
    }
    mapEl.innerHTML='';
  ymaps.ready(function(){
    _routeMap = new ymaps.Map('routeMapModal', {center:[41.7151,44.8271],zoom:7});
    ymaps.geocode(from+', Грузия',{results:1}).then(function(res){
      const fromCoords = res.geoObjects.get(0)?.geometry?.getCoordinates();
      ymaps.geocode(to+', Грузия',{results:1}).then(function(res2){
        const toCoords = res2.geoObjects.get(0)?.geometry?.getCoordinates();
        if(!fromCoords||!toCoords) return;
        
        const route = new ymaps.multiRouter.MultiRoute({
          referencePoints: [fromCoords, toCoords],
          params: {routingMode:'auto'}
        },{wayPointFinishIconColor:'#e74c3c',routeActiveStrokeWidth:5,routeActiveStrokeColor:'#f7b731'});
        
        _routeMap.geoObjects.add(route);
        route.model.events.add('requestsuccess', function(){
          _routeMap.setBounds(route.getBounds(), {checkZoomRange:true, zoomMargin:40});
        });
      });
    });
  }); // ymaps.ready
  } // _initMap
  _initMap();
}


// Явно регистрируем все функции как глобальные
window.showSection = showSection;
window.setScope = setScope;
window.setLang = setLang;
window.openAuth = openAuth;
window.switchAuth = switchAuth;
window.doLogout = doLogout;
window.openPostLoad = openPostLoad;
window.doPostLoad = doPostLoad;
window.openCargo = openCargo;
window.doRespond = doRespond;
window.showCabinet = showCabinet;
window.switchCabTab = switchCabTab;
window.filterLoads = filterLoads;
window.openPostTruck = openPostTruck;
window.doPostTruck = doPostTruck;
window.deleteMyLoad = deleteMyLoad;
window.editMyLoad = editMyLoad;
window.saveEditedLoad = saveEditedLoad;
window.acceptResponse = acceptResponse;
window.rejectResponse = rejectResponse;
window.openProfile = openProfile;
window.showForgotForm = showForgotForm;
window.closeModal = closeModal;
window.closeOverlay = closeOverlay;
window.openPaywall = openPaywall;
window.choosePlan = choosePlan;
window.showPhone = showPhone;
window.callTruck = callTruck;
window.deleteMyTruck = deleteMyTruck;
window.filterByCountry = filterByCountry;
window.selectRegType = selectRegType;
window.backToStep1 = backToStep1;
window.openDrop = openDrop;
window.closeDrop = closeDrop;
window.selectCity = selectCity;
window.addrSearch = addrSearch;
window.selectAddr = selectAddr;
window.closeAddrDrop = closeAddrDrop;
window.showRouteMap = showRouteMap;
window.closeMap = closeMap;
window.updateFormForIntl = updateFormForIntl;
window.syncDateMin = syncDateMin;
window.renderLoads = renderLoads;
window.clearNotifs = clearNotifs;
window.toggleNotifPanel = toggleNotifPanel;

// Дополнительные регистрации (правильные имена)
window.doLogin = doLogin;
window.doRegister = doRegister;
window.cancelMyResponse = cancelMyResponse;
window.doForgotStep1 = doForgotStep1;
window.doForgotStep2 = doForgotStep2;
window.dealAction = dealAction;
window.confirmDelivery = confirmDelivery;
window.exportDealsData = typeof exportDealsData !== 'undefined' ? exportDealsData : function(){};

// ── ЯЗЫК — восстановление при загрузке ───────────────
(function() {
  const saved = localStorage.getItem('ch_lang');
  if (saved && saved !== 'ru') {
    const btn = document.querySelector(`.lang-btn[onclick*="'${saved}'"]`);
    setLang(saved, btn);
  }
})();
