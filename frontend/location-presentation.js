/* Localized display only. Never changes coordinates, country or route identity. */
(function(){
 'use strict';
 const locale=value=>value==='ge'||value==='ka'?'ka':'ru';
 const text=value=>typeof value==='string'?value.trim():'';
 const normalize=value=>text(value).normalize('NFKC').toLocaleLowerCase().replace(/\s+/g,' ');
 const generic={
  'продукты':{ru:'Продукты',ka:'სასურსათო მაღაზია'},
  'продуктовый магазин':{ru:'Продуктовый магазин',ka:'სასურსათო მაღაზია'},
  'სასურსათო მაღაზია':{ru:'Продуктовый магазин',ka:'სასურსათო მაღაზია'},
  'магазин':{ru:'Магазин',ka:'მაღაზია'},
  'მაღაზია':{ru:'Магазин',ka:'მაღაზია'},
  'склад':{ru:'Склад',ka:'საწყობი'},
  'საწყობი':{ru:'Склад',ka:'საწყობი'},
  'точка на карте':{ru:'Точка на карте',ka:'წერტილი რუკაზე'},
  'წერტილი რუკაზე':{ru:'Точка на карте',ka:'წერტილი რუკაზე'}
 };
 function cities(){try{return typeof CITIES!=='undefined'&&Array.isArray(CITIES)?CITIES:[];}catch{return[];}}
 function regions(){try{return typeof REGION_NAMES_GE!=='undefined'?REGION_NAMES_GE:{};}catch{return{};}}
 function named(value,language){
  const raw=text(value),key=normalize(raw);if(!raw)return '';
  const matches=cities().filter(city=>[city.name,city.name_ru,city.name_ge,city.nameGe,city.name_en,city.nameEn,...(Array.isArray(city.aliases)?city.aliases:[])].some(alias=>normalize(alias)===key));
  const names=[...new Set(matches.map(city=>text(language==='ka'?city.name_ge||city.nameGe:city.name_ru||city.name)).filter(Boolean))];
  if(names.length===1)return names[0];
  for(const [ru,ka]of Object.entries(regions()))if(ka&&(normalize(ru)===key||normalize(ka)===key))return language==='ka'?ka:ru;
  return raw;
 }
 function localized(location,language,part){return text(location?.localized?.[language]?.[part]);}
 function context(location,language){
  if(!location)return null;
  const current=location.context;
  if(current&&['within','nearby','region'].includes(current.relation)&&(!current.country_iso||!location.country_iso||current.country_iso===location.country_iso)){
   const raw=text(current.names?.[language])||text(current.names?.[language==='ka'?'ru':'ka']);
   if(raw)return {name:named(raw,language),relation:current.relation};
  }
  // Canonical names may localize a known settlement, but never infer one by distance.
  const key=location.settlement_key||location.kind==='settlement'&&location.key;
  if(key){const city=cities().find(city=>[city.key,city.canonical_key].includes(key));if(city){const name=text(language==='ka'?city.name_ge||city.nameGe:city.name_ru||city.name);if(name)return{name,relation:'within'};}}
  const components=text(location.address).split(',').map(part=>part.trim().replace(/^(?:город|г\.|село|пос[её]лок)\s+/i,''));
  for(const component of components){
   const city=cities().find(city=>[city.name,city.name_ru,city.name_ge,city.nameGe,city.name_en,...(city.aliases||[])].some(alias=>alias&&normalize(alias)===normalize(component)));
   if(city)return{name:named(component,language),relation:/^край\s/i.test(city.name||city.name_ru||'')?'region':'nearby'};
  }
  // A known administrative label is a regional fallback, never a town or a POI.
  for(const component of components)for(const [ru,ka]of Object.entries(regions()))if(ka&&/(?:край|область|муниципалитет|регион|Республика Аджария)/i.test(ru)&&(normalize(component)===normalize(ru)||normalize(component)===normalize(ka)))return{name:language==='ka'?ka:ru,relation:'region'};
  return null;
 }
 function contextLabel(location,value){const language=locale(value),found=context(location,language);return found?(found.relation==='nearby'?(language==='ka'?'ახლოს: ':'рядом: '):'')+found.name:'';}
 function postal(location){
  const raw=text(location?.label);if(!raw||generic[normalize(raw)])return false;
  return /(?:^|[\s,])(?:улица|ул\.|проспект|переулок|шоссе|ქუჩა|გამზირი)(?:\s|$)|,\s*\d+[а-яa-zა-ჰ]?(?:\s|$)|^(?:край\s|Грузия,|საქართველო,)/iu.test(raw);
 }
 function label(location,value){
  const language=locale(value),raw=text(location?.label);if(!location)return '';
  if(location.label_mode==='custom')return raw;
  const translated=localized(location,language,'label')||text(language==='ka'?location.name_ge:location.name_ru);
  if(translated)return translated;
  const category=generic[normalize(raw)];if(category)return category[language];
  const canonical=named(raw,language);if(canonical!==raw)return canonical;
  // Keep the full original postal address in details; compact routes can use its known locality.
  if(language==='ka'&&postal(location)&&/[а-яё]/i.test(raw)){const found=context(location,language);if(found&&!/[а-яё]/i.test(found.name))return found.name;}
  return raw;
 }
 function address(location,value){const language=locale(value);return localized(location,language,'address')||text(location?.address);}
 function routeLabel(location,value){
  const language=locale(value),name=label(location,language),found=context(location,language);if(!found)return name;
  const prefix=contextLabel(location,language);if(!name)return prefix;
  if(location.label_mode!=='custom'&&postal(location))return prefix;
  if(normalize(name).includes(normalize(found.name)))return name;
  return prefix+' · '+name;
 }
 function isOriginal(location,part,value){
  const language=locale(value);if(!location||localized(location,language,part))return false;
  if(part==='label'&&location.label_mode==='custom')return false;
  const shown=part==='address'?address(location,language):label(location,language);
  const cyrillic=/[а-яё]/i.test(shown),georgian=/[\u10a0-\u10ff\u1c90-\u1cbf]/.test(shown),latin=/[a-z]/i.test(shown);
  return language==='ka'?cyrillic||latin&&!georgian:georgian||latin&&!cyrillic;
 }
 window.CaucasAddressPresentation=Object.freeze({label,address,routeLabel,contextLabel,isOriginal});
})();
