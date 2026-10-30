/* Shared publication address search and exact-point picker. Existing Yandex JS API only. */
(function(){
 'use strict';
 const fields={pFrom:{input:'pFromAddr',drop:'dropPFrom',note:'coordsPFrom',side:'from'},pTo:{input:'pToAddr',drop:'dropPTo',note:'coordsPTo',side:'to'},ptFrom:{input:'ptFrom',drop:'dropPtFrom',note:'coordsPtFrom',side:'from'},ptTo:{input:'ptTo',drop:'dropPtTo',note:'coordsPtTo',side:'to'}};
 const state={},selections={},inflight=new Map(),recentRemote=new Map();
 let catalog=[],catalogPromise=null,mapsPromise=null,active=null,map=null,marker=null,reverseTimer=null,pickerSequence=0,returnFocus=null;
 const node=id=>document.getElementById(id);
 const ge=()=>typeof lang!=='undefined'&&['ge','ka'].includes(lang);
 const locale=()=>ge()?'ka':'ru';
 const tr=(ru,ka)=>ge()?ka:ru;
 const base=()=>typeof API_BASE!=='undefined'?API_BASE:'';
 const currentScope=()=>typeof scope!=='undefined'?scope:'local';
 const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const normalize=value=>String(value||'').normalize('NFKC').toLocaleLowerCase().trim().replace(/[.,'’_-]+/g,' ').replace(/\s+/g,' ');
 const copy=value=>value?JSON.parse(JSON.stringify(value)):null;
 const finitePoint=point=>point&&Number.isFinite(Number(point.lat))&&Number.isFinite(Number(point.lon))&&Math.abs(Number(point.lat))<=90&&Math.abs(Number(point.lon))<=180;
 function timeout(promise,ms,message){let timer;return Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error(message)),ms);})]).finally(()=>clearTimeout(timer));}
 async function request(path,options){
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),6500);
  try{const response=await fetch(base()+path,{...options,signal:controller.signal});const data=await response.json();if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:tr('Не удалось определить место. Уточните точку.','ადგილი ვერ განისაზღვრა. დააზუსტეთ წერტილი.'));return data;}
  finally{clearTimeout(timer);}
 }
 function labelOf(location){return window.CaucasAddressPresentation?.label(location,locale())||(location.label_mode==='custom'?location.label:location.localized?.[locale()]?.label||(ge()?location.name_ge:location.name_ru)||location.label||location.name_en)||'';}
 function addressOf(location){return window.CaucasAddressPresentation?.address(location,locale())||location.localized?.[locale()]?.address||location.address||'';}
 function contextOf(location){return window.CaucasAddressPresentation?.contextLabel(location,locale())||location.context?.names?.[locale()]||location.context?.names?.ru||location.context?.names?.ka||'';}
 function rawLabel(location){return location.label||location.name_ru||location.name_ge||location.name_en||'';}
 function localizedText(label,address){const out={};for(const [field,value]of Object.entries({label,address})){if(!value)continue;const language=/[\u10a0-\u10ff]/.test(value)?'ka':'ru';(out[language]??={})[field]=value;}return out;}
 function mergePresentation(target,extra){
  if(extra.localized){target.localized=copy(target.localized)||{};for(const language of ['ru','ka'])if(extra.localized[language])target.localized[language]={...target.localized[language],...copy(extra.localized[language])};}
  if(extra.context&&(!extra.context.country_iso||!target.country_iso||extra.context.country_iso===target.country_iso))target.context={...copy(target.context),...copy(extra.context),names:{...target.context?.names,...extra.context.names}};
  return target;
 }
 function paintPicker(){
  if(!active)return;
  node('locationPickerLabel').value=labelOf(active.location);
  node('locationPickerAddress').textContent=addressOf(active.location)||'';
  let context=node('locationPickerContext');if(!context){context=document.createElement('div');context.id='locationPickerContext';context.className='location-picker-context';node('locationPickerAddress').after(context);}
  context.textContent=contextOf(active.location);context.hidden=!context.textContent;
  const original=window.CaucasAddressPresentation?.isOriginal(active.location,'address',locale())||false;
  node('locationPickerAddress').dataset.addressOriginal=String(original);
  let notice=node('locationPickerOriginal');if(!notice){notice=document.createElement('small');notice.id='locationPickerOriginal';notice.className='address-original';context.after(notice);}
  notice.hidden=!original;notice.textContent=original?tr('Адрес показан на языке источника','მისამართი ნაჩვენებია წყაროს ენაზე'):'';
 }
 function fallbackCatalog(){return (typeof CITIES!=='undefined'?CITIES:[]).filter(c=>!String(c.name).startsWith('край ')).map(c=>({kind:'settlement',label:c.name,name_ru:c.name,name_ge:c.nameGe,lat:c.lat,lon:c.lng,city:c.name,aliases:[c.name,c.nameGe].filter(Boolean),legacy:true}));}
 function preload(){
  if(catalogPromise)return catalogPromise;
  catalogPromise=request('/api/locations/suggest?q=&limit=250&lang=ru').then(data=>{
   if(!Array.isArray(data.results))throw Error('Invalid location catalogue');
   catalog=data.results;return catalog;
  }).catch(()=>{catalogPromise=null;return fallbackCatalog();});
  return catalogPromise;
 }
 function mapsReady(){
  if(mapsPromise)return mapsPromise;
  mapsPromise=timeout(new Promise((resolve,reject)=>{
   if(typeof loadYmapsLazy!=='function'){reject(Error('Maps unavailable'));return;}
   loadYmapsLazy(()=>{if(typeof ymaps==='undefined'){reject(Error('Maps unavailable'));return;}ymaps.ready(()=>resolve(ymaps));},reject);
  }),7000,'Maps unavailable').catch(error=>{mapsPromise=null;throw error;});
  return mapsPromise;
 }
 function warm(){preload();mapsReady().catch(()=>{});}
 function localMatches(query){
  const q=normalize(query),rows=catalog.length?catalog:fallbackCatalog();
  return rows.filter(row=>currentScope()!=='local'||!row.country_iso||row.country_iso==='GE').map(row=>{
   const names=[row.key,row.label,row.name_ru,row.name_ge,row.name_en,...(row.aliases||[])].filter(Boolean).map(normalize);
   const exact=names.some(name=>name===q),prefix=names.some(name=>name.startsWith(q));
   return{row,score:exact?0:prefix?1:names.some(name=>name.includes(q))?2:10};
  }).filter(item=>item.score<10).sort((a,b)=>a.score-b.score||(a.row.kind==='border_checkpoint'?-1:1)).slice(0,7).map(item=>({...item.row,label:rawLabel(item.row),label_mode:'auto'}));
 }
 function exactLocal(query){const q=normalize(query);return localMatches(query).some(row=>[row.label,row.name_ru,row.name_ge,row.name_en,...(row.aliases||[])].filter(Boolean).some(name=>normalize(name)===q));}
 function countryFromObject(object){
  const meta=object.properties?.get?.('metaDataProperty.GeocoderMetaData')||{};
  return String(meta.Address?.country_code||meta.AddressDetails?.Country?.CountryNameCode||object.address?.country_code||'').toUpperCase();
 }
 function localityFromObject(object){
  const metadata=object.properties?.get?.('metaDataProperty.GeocoderMetaData')||{},components=Array.isArray(metadata.Address?.Components)?metadata.Address.Components:[];
  const address=object.address||{},country=countryFromObject(object),localities=object.getLocalities?.()||[];
  const locality=String(address.city||address.town||address.village||components.find(part=>['locality','village'].includes(part.kind))?.name||localities[0]||'').trim();
  const region=String(components.find(part=>part.kind==='area')?.name||components.find(part=>part.kind==='province')?.name||address.state||address.region||'').trim();
  const name=locality||region;if(!name)return null;
  const known=country&&catalog.find(row=>row.kind==='settlement'&&row.country_iso===country&&[row.label,row.name_ru,row.name_ge,row.name_en,...(row.aliases||[])].some(alias=>alias&&normalize(alias)===normalize(name)));
  const names=known?{ru:known.name_ru||known.label,...(known.name_ge?{ka:known.name_ge}:{})}:{[/[\u10a0-\u10ff]/.test(name)?'ka':'ru']:name};
  const within=locality&&['house','street','district'].includes(metadata.kind)&&metadata.precision!=='other';
  return{relation:locality?(within?'within':'nearby'):'region',names,source:'yandex',...(country?{country_iso:country}:{}),...(known?.key?{key:known.key}:{})};
 }
 function objectLocation(object){
  const coords=object.geometry?.getCoordinates?.();if(!coords)return null;
  const metadata=typeof geocodedPublicationAddress==='function'?geocodedPublicationAddress(object):{};
  const address=object.getAddressLine?.()||metadata.addr||'';
  const name=object.properties?.get?.('name')||address;
  const country=countryFromObject(object),context=localityFromObject(object),city=metadata.city||object.getLocalities?.()?.[0]||'';
  const settlement=country&&city&&catalog.find(row=>row.kind==='settlement'&&row.country_iso===country&&[row.label,row.name_ru,row.name_ge,row.name_en,...(row.aliases||[])].some(alias=>alias&&normalize(alias)===normalize(city)));
  const label=String(city?address:name||address||tr('Точка на карте','წერტილი რუკაზე')).slice(0,100).trim();
  return{kind:'point',key:null,label,label_mode:'auto',address,localized:localizedText(label,address),...(context?{context}:{}),city:settlement?.name_ru||city,settlement_key:settlement?.settlement_key||settlement?.key||null,settlement_id:settlement?.settlement_id||null,lat:Number(coords[0]),lon:Number(coords[1]),country_iso:country||undefined,source:'yandex'};
 }
 function searchRemote(query,whichScope){
  const key='ru|'+whichScope+'|'+normalize(query);
  const cached=recentRemote.get(key);if(cached&&Date.now()-cached.at<300000)return Promise.resolve(copy(cached.rows));
  if(inflight.has(key))return inflight.get(key);
  const operation=timeout(mapsReady().then(api=>api.geocode(whichScope==='intl'?query:query+', Грузия',{results:6,lang:'ru_RU'})),3500,'Address search timed out').then(result=>{
   const rows=[];result.geoObjects.each(object=>{const row=objectLocation(object);if(row)rows.push(row);});recentRemote.set(key,{at:Date.now(),rows});if(recentRemote.size>30)recentRemote.delete(recentRemote.keys().next().value);return rows;
  }).finally(()=>inflight.delete(key));inflight.set(key,operation);return operation;
 }
 function render(field,rows,pending){
  const config=fields[field],drop=node(config.drop);if(!drop)return;
  const entry=state[field];entry.rows=rows;entry.pending=pending;
  drop.innerHTML=rows.map((row,index)=>'<button type="button" class="addr-item location-option" data-location-index="'+index+'" data-location-key="'+escape(row.key||'')+'"><span class="addr-main">'+escape(labelOf(row))+'</span><span class="addr-sub">'+escape(addressOf(row)||[row.city,row.country_iso].filter(Boolean).join(', '))+'</span></button>').join('')+
   (pending?'<div class="addr-loading">'+tr('Ищем другие адреса…','სხვა მისამართების ძიება…')+'</div>':'')+
   (!rows.length&&!pending?'<div class="addr-loading">'+tr('Адрес не найден. Укажите точку на карте.','მისამართი ვერ მოიძებნა. მონიშნეთ წერტილი რუკაზე.')+'</div>':'')+
   '<button type="button" class="addr-item location-map-option" data-open-location-map="'+field+'">🗺️ '+tr('Выбрать на карте','არჩევა რუკაზე')+'</button>';
  drop.classList.add('open');
  drop.querySelectorAll('[data-location-index]').forEach(button=>{button.addEventListener('mousedown',event=>event.preventDefault());button.addEventListener('click',()=>choose(field,rows[Number(button.dataset.locationIndex)]));});
  const mapOption=drop.querySelector('[data-open-location-map]');mapOption?.addEventListener('mousedown',event=>event.preventDefault());mapOption?.addEventListener('click',()=>open(field));
 }
 function search(field,value){
  const config=fields[field];if(!config)return;
  const prior=state[field]||{},sequence=(prior.sequence||0)+1;
  clearTimeout(prior.timer);state[field]={sequence,rows:[]};delete selections[field];
  const input=node(config.input);if(input){delete input.dataset.locationKey;input.removeAttribute('aria-busy');}
  const note=node(config.note);if(note)note.style.display='none';
  const query=String(value||'').trim(),whichScope=currentScope();
  const valid=()=>state[field]?.sequence===sequence&&currentScope()===whichScope&&node(config.input)?.value.trim()===query;
  if(query.length<2){node(config.drop)?.classList.remove('open');return;}
  const own=localMatches(query);render(field,own,query.length>=3&&!exactLocal(query));
  preload().then(()=>{if(valid())render(field,localMatches(query),query.length>=3&&!exactLocal(query));});
  if(query.length<3)return;
  state[field].timer=setTimeout(async()=>{
   if(valid()&&exactLocal(query)){render(field,localMatches(query),false);return;}
   try{const remote=await searchRemote(query,whichScope);if(!valid())return;
    const local=localMatches(query),seen=new Set(local.map(row=>normalize(row.label)+'|'+row.lat+'|'+row.lon));
    const merged=local.concat(remote.filter(row=>{const key=normalize(row.label)+'|'+row.lat+'|'+row.lon;if(seen.has(key))return false;seen.add(key);return true;})).slice(0,9);render(field,merged,false);
   }catch{if(valid())render(field,localMatches(query),false);}
  },250);
 }
 function apply(field,location){
  const config=fields[field],input=node(config.input);if(!input)return;
  if(state[field]){clearTimeout(state[field].timer);state[field].sequence++;}
  const selected=copy(location);selected.label=selected.label||rawLabel(selected);input.value=labelOf(selected);
  selections[field]={input:input.value,location:selected};
  if(selected.key)input.dataset.locationKey=selected.key;else delete input.dataset.locationKey;
  node(config.drop)?.classList.remove('open');
  const note=node(config.note);if(note){note.textContent=[addressOf(selected),contextOf(selected)].filter(Boolean).filter((text,index,array)=>!index||!normalize(array[0]).includes(normalize(text))).join(' · ')||tr('Точная точка выбрана на карте','ზუსტი წერტილი მონიშნულია რუკაზე');if(window.CaucasAddressPresentation?.isOriginal(selected,'address',locale()))note.textContent+=' · '+tr('Адрес на языке источника','მისამართი წყაროს ენაზე');note.style.display='block';}
  input.setAttribute('aria-busy','false');
 }
 async function resolve(location){
  if(location.key||location.legacy)return copy(location);
  const {lat,lon,label,label_mode,address,settlement_id,settlement_key,localized,context}=location;
  const result=await request('/api/locations/resolve',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind:'point',lat,lon,label,label_mode,address:address||label,settlement_id,settlement_key,localized,context,include_presentation:true})});
  if(!finitePoint(result.location)||!result.location.resolution_token)throw Error(tr('Не удалось подтвердить точку. Повторите выбор.','წერტილი ვერ დადასტურდა. სცადეთ ხელახლა.'));
  return {...location,...result.location,city:location.city||'',label,address:result.location.address||address};
 }
 async function choose(field,location){
  if(!location)return;
  const config=fields[field],input=node(config.input),original=input?.value,sequence=state[field]?.sequence;
  if(input)input.setAttribute('aria-busy','true');
  try{const selected=await resolve({...location,label_mode:location.label_mode||'auto'});if(input?.value!==original||state[field]?.sequence!==sequence)return;apply(field,selected);}
  catch(error){if(input?.value!==original)return;input?.setAttribute('aria-busy','false');const note=node(config.note);if(note){note.textContent=error.message;note.style.display='block';}}
 }
 function read(field,text){
  if(node(fields[field]?.input)?.getAttribute('aria-busy')==='true')throw Error(tr('Дождитесь подтверждения выбранного адреса','დაელოდეთ არჩეული მისამართის დადასტურებას'));
  const selected=selections[field];if(!selected||selected.input!==String(text).trim())return null;
  const location=copy(selected.location);
  const city=location.city||String(location.kind==='settlement'?location.name_ru||location.label:location.label).slice(0,100);
  const endpoint={city,lat:location.lat,lng:location.lon,address:location.address||location.label};
  if(location.kind==='settlement'){if(location.settlement_id)endpoint.city_id=location.settlement_id;if(location.settlement_key||location.key)endpoint.canonical_key=location.settlement_key||location.key;}
  if(!location.legacy){endpoint.location={};for(const key of ['kind','key','label','label_mode','lat','lon','address','country_iso','settlement_id','settlement_key','resolution_token','localized','context'])if(location[key]!=null)endpoint.location[key]=location[key];}
  return endpoint;
 }
 function restore(field,location){if(location&&finitePoint(location))apply(field,location);else delete selections[field];}
 function errorText(message){const error=node('locationPickerError');if(error){error.textContent=message||'';error.hidden=!message;}}
 function automaticPointLabel(location){
  const label=normalize(location?.label);
  const cataloguePlace=['settlement','border_checkpoint'].includes(location?.kind);
  const entry=cataloguePlace?(catalog.find(row=>row.key===location.key)||{}):{};
  const catalogueNames=cataloguePlace?[location.name_ru,location.name_ge,location.name_en,entry.label,entry.name_ru,entry.name_ge,entry.name_en]:[];
  return !label||['Точка на карте','წერტილი რუკაზე',String(location?.address||'').slice(0,100),...catalogueNames].some(value=>normalize(value)===label);
 }

 function distanceMeters(first,second){
  const rad=value=>Number(value)*Math.PI/180;
  const a=rad(Number(second.lat)-Number(first.lat)),b=rad(Number(second.lon)-Number(first.lon));
  const h=Math.sin(a/2)**2+Math.cos(rad(first.lat))*Math.cos(rad(second.lat))*Math.sin(b/2)**2;
  return 6371000*2*Math.atan2(Math.sqrt(h),Math.sqrt(Math.max(0,1-h)));
 }
 function nearbyCheckpoints(){
  if(!active||!finitePoint(active.location))return[];
  return catalog.filter(row=>row.kind==='border_checkpoint'&&row.key&&finitePoint(row)&&row.key!==active.location.key)
   .map(row=>({row,distance:distanceMeters(active.location,row)})).filter(item=>item.distance<=500)
   .sort((a,b)=>a.distance-b.distance).map(item=>item.row);
 }
 function renderNearby(){
  let panel=node('locationPickerNearby');
  if(!panel){
   const coordinates=node('locationPickerCoordinates');if(!coordinates)return;
   panel=document.createElement('div');panel.id='locationPickerNearby';panel.className='location-picker-nearby';
   panel.setAttribute('aria-label',tr('Погранпереходы рядом','სასაზღვრო პუნქტები ახლოს'));coordinates.after(panel);
  }
  const options=nearbyCheckpoints();panel.hidden=!options.length;panel.replaceChildren();
  for(const location of options){
   const country={GE:tr('Грузия','საქართველო'),RU:tr('Россия','რუსეთი')}[location.country_iso]||location.country_iso;
   const button=document.createElement('button');button.type='button';button.dataset.nearbyLocationKey=location.key;
   const label=labelOf(location),caption=normalize(label).includes(normalize(country))?label:label+' — '+country;
   button.textContent=tr('Рядом: ','ახლოს: ')+caption+'. '+tr('Выбрать КПП','პუნქტის არჩევა');
   button.addEventListener('click',()=>selectNearby(location.key));panel.append(button);
  }
 }
 function selectNearby(key){
  if(!active)return;
  const location=nearbyCheckpoints().find(row=>row.key===key);if(!location){renderNearby();return;}
  const input=node('locationPickerLabel'),custom=active.location.label_mode==='custom'?input.value.trim():'';
  active.labelEdited=!!custom;
  active.location={...copy(location),label:custom||rawLabel(location),label_mode:custom?'custom':'auto'};input.value=labelOf(active.location);
  errorText('');
  const coordinates=[Number(location.lat),Number(location.lon)];setCoordinates(coordinates);map?.setCenter(coordinates);
 }

 function setCoordinates(coords,place){
  if(!active)return;
  const lat=Number(coords[0]),lon=Number(coords[1]);if(!finitePoint({lat,lon}))return;
  if(active.selectionError){active.selectionError=false;node('locationPickerConfirm').disabled=false;errorText('');}
  const moved=Math.abs(lat-active.location.lat)>0.000001||Math.abs(lon-active.location.lon)>0.000001;
  if(!moved&&!place&&active.place)return;
  if(moved){
   active.place=null;
   // Only explicit manual provenance survives moving. Legacy POI names may
   // differ from postal addresses, so that difference cannot prove a custom name.
   active.labelEdited=active.location.label_mode==='custom';
   const label=active.labelEdited?node('locationPickerLabel').value.trim():tr('Точка на карте','წერტილი რუკაზე');
   active.location={kind:'point',key:null,lat,lon,label:label||tr('Точка на карте','წერტილი რუკაზე'),label_mode:active.labelEdited?'custom':'auto',address:''};
   if(!active.labelEdited)node('locationPickerLabel').value=active.location.label;
  }
  if(place){
   active.labelEdited=active.location.label_mode==='custom';
   const label=active.labelEdited?node('locationPickerLabel').value.trim():place.label;
   active.place=place;active.location={kind:'point',key:null,lat,lon,label:label||place.label,label_mode:active.labelEdited?'custom':'auto',address:place.address||place.label,localized:localizedText(place.label,place.address||place.label)};
   node('locationPickerLabel').value=labelOf(active.location);
  }
  marker?.geometry.setCoordinates([lat,lon]);
  node('locationPickerCoordinates').textContent=lat.toFixed(6)+', '+lon.toFixed(6);
  clearTimeout(reverseTimer);const ticket=++pickerSequence;
  renderNearby();
  if(active.location.kind==='border_checkpoint'&&active.location.key){
   paintPicker();return;
  }
  if(active.place||!moved&&addressOf(active.location))paintPicker();else{node('locationPickerAddress').textContent=tr('Уточняем адрес…','მისამართის დაზუსტება…');const context=node('locationPickerContext');if(context){context.textContent=contextOf(active.location);context.hidden=!context.textContent;}}
  const owner=active;
  const reverse=async()=>{
   try{const result=await timeout(mapsReady().then(api=>api.geocode([lat,lon],{results:1,lang:'ru_RU'})),3500,'Reverse search timed out');
    if(!active||pickerSequence!==ticket)return;
    const object=result.geoObjects.get(0),found=object&&objectLocation(object);
    if(found){
     if(found.context)mergePresentation(active.location,{context:found.context});
     // Reverse results only enrich a native POI's locality. Its object name,
     // address and exact geometry belong to the selected native map feature.
     if(!active.place){
      active.location.address=found.address;
      mergePresentation(active.location,{localized:localizedText('',found.address)});
      if(!active.labelEdited&&found.address.trim()){
       active.location.label=found.address.trim().slice(0,100).trim();active.location.label_mode='auto';mergePresentation(active.location,{localized:localizedText(active.location.label,'')});
      }
     }
     paintPicker();if(!addressOf(active.location))node('locationPickerAddress').textContent=tr('Точка без почтового адреса','წერტილი საფოსტო მისამართის გარეშე');
    }
    else node('locationPickerAddress').textContent=tr('Точка без почтового адреса','წერტილი საფოსტო მისამართის გარეშე');
   }catch{if(active&&pickerSequence===ticket&&!active.place)node('locationPickerAddress').textContent=tr('Название можно указать вручную. Точка сохранится по координатам.','სახელი მიუთითეთ ხელით. წერტილი კოორდინატებით შეინახება.');}
  };
  owner.contextReady=owner.place?reverse():null;
  if(!owner.place)reverseTimer=setTimeout(reverse,300);
 }
 function selectNativePlace(selectionMap){
  if(!active||map!==selectionMap)return;
  const balloon=selectionMap.balloon,data=balloon?.getData?.(),properties=data?.properties;
  // Native base-layer POIs expose an IDataManager through the public balloon.
  // Their balloon position is in global pixels, not latitude/longitude.
  if(data?.map!==selectionMap||!data.layer||typeof properties?.get!=='function')return;
  try{
   const name=properties.get('name'),label=typeof name==='string'?name.trim():'',position=balloon.getPosition();
   const projection=selectionMap.options?.get?.('projection');
   const coords=Array.isArray(position)&&position.length===2&&position.every(Number.isFinite)?projection?.fromGlobalPixels(position,selectionMap.getZoom()):null;
   if(!label||!Array.isArray(coords)||coords.length!==2||!coords.every(Number.isFinite)||!finitePoint({lat:coords[0],lon:coords[1]}))throw Error('Invalid map object');
   const addressValue=properties.get('address')||properties.get('description'),address=typeof addressValue==='string'?addressValue.trim():label;
   balloon.close(true);setCoordinates(coords,{label:label.slice(0,100),address});selectionMap.setCenter(coords);
   node('locationPickerConfirm').disabled=false;errorText('');
  }catch{
   active.selectionError=true;
   node('locationPickerConfirm').disabled=true;errorText(tr('Не удалось выбрать объект. Укажите точку рядом на карте.','ობიექტი ვერ აირჩა. მონიშნეთ ახლოს მდებარე წერტილი რუკაზე.'));
  }
 }
 async function open(field){
  const config=fields[field];if(!config)return;
  close(false);returnFocus=node(config.input);
  const raw=node(config.input)?.value.trim()||'',selected=selections[field]?.input===raw?selections[field].location:null;
  const seed=selected||(raw?localMatches(raw)[0]:null);
  const location=finitePoint(seed)?copy(seed):{kind:'point',key:null,label:raw||tr('Точка на карте','წერტილი რუკაზე'),label_mode:'auto',lat:42.1,lon:43.9,address:''};
  // Keep a restored POI/legacy name at the same point. Its mode, rather than
  // its difference from a postal address, decides what to keep after moving.
  active={field,location,labelEdited:location.label_mode==='custom'||!!selected&&!automaticPointLabel(selected)};
  const owner=active;preload().then(()=>{if(active===owner)renderNearby();});
  const overlay=node('locationPickerOverlay');overlay.hidden=false;
  node('locationPickerTitle').textContent=config.side==='from'?tr('Место отправления','გაგზავნის ადგილი'):tr('Место доставки','მიწოდების ადგილი');
  node('locationPickerLabelCaption').textContent=tr('Название места','ადგილის სახელი');
  node('locationPickerInstruction').textContent=tr('Передвиньте карту или метку и подтвердите точку.','გადაადგილეთ რუკა ან ნიშნული და დაადასტურეთ წერტილი.');
  node('locationPickerConfirm').textContent=tr('Выбрать эту точку','ამ წერტილის არჩევა');node('locationPickerConfirm').disabled=true;
  node('locationPickerCancel').textContent=tr('Отмена','გაუქმება');
  paintPicker();if(!addressOf(location))node('locationPickerAddress').textContent=tr('Загружаем карту…','რუკის ჩატვირთვა…');errorText('');
  node('locationPickerMap').innerHTML='';node('locationPickerCancel').focus();
  const ticket=++pickerSequence;
  try{const api=await mapsReady();if(!active||ticket!==pickerSequence)return;
   map=new api.Map('locationPickerMap',{center:[location.lat,location.lon],zoom:finitePoint(seed)?15:7,controls:['zoomControl']},{suppressMapOpenBlock:true,balloonAutoPan:false});
   const selectionMap=map;map.balloon?.events?.add('open',()=>selectNativePlace(selectionMap));
   const mobile=window.innerWidth<=768;node('locationPickerPin').hidden=!mobile;
   if(!mobile){marker=new api.Placemark([location.lat,location.lon],{}, {draggable:true,preset:'islands#redDotIcon'});map.geoObjects.add(marker);marker.events.add('dragend',()=>{const coords=marker.geometry.getCoordinates();setCoordinates(coords);map.setCenter(coords);});}
   map.events.add('click',event=>{const coords=event.get('coords');if(coords){map.setCenter(coords);setCoordinates(coords);}});
   map.events.add('boundschange',event=>{const coords=event.get('newCenter')||map.getCenter();if(mobile&&coords&&!map.balloon?.isOpen?.())setCoordinates(coords);});
   map.container?.fitToViewport();node('locationPickerConfirm').disabled=false;
   setCoordinates([location.lat,location.lon]);
  }catch{if(active&&ticket===pickerSequence){errorText(tr('Карта недоступна. Можно выбрать место из подсказок или повторить позже.','რუკა მიუწვდომელია. აირჩიეთ ადგილი მინიშნებებიდან ან სცადეთ მოგვიანებით.'));node('locationPickerAddress').textContent='';}}
 }
 function close(focus=true){
  ++pickerSequence;clearTimeout(reverseTimer);active=null;
  if(map){map.destroy();map=null;}marker=null;
  const overlay=node('locationPickerOverlay');if(overlay)overlay.hidden=true;
  if(focus&&returnFocus)returnFocus.focus();
 }
 async function confirm(){
  if(!active)return;const owner=active,button=node('locationPickerConfirm');if(button.disabled)return;
  const label=node('locationPickerLabel').value.trim();if(!label){errorText(tr('Укажите название места','მიუთითეთ ადგილის სახელი'));node('locationPickerLabel').focus();return;}
  button.disabled=true;errorText('');
  const syncLabel=()=>{const value=node('locationPickerLabel').value.trim();if(value!==String(labelOf(owner.location)).trim()){owner.location.label=value;owner.location.label_mode='custom';owner.labelEdited=true;}else if(owner.location.label_mode==='custom')owner.location.label=value;};
  syncLabel();
  try{const location=copy(owner.location);const [selected]=await Promise.all([resolve(location),owner.contextReady]);if(active!==owner)return;
   if(owner.selectionError)return;
   if(owner.location.lat!==location.lat||owner.location.lon!==location.lon||owner.location.kind!==location.kind||owner.location.key!==location.key){
    errorText(tr('Точка изменилась. Подтвердите её ещё раз.','წერტილი შეიცვალა. დაადასტურეთ ხელახლა.'));button.disabled=false;return;
   }
   // Country tokens bind coordinates, not names. Keep the latest address or
   // manual name if it changed while this same point was being verified.
   const latestLabel=node('locationPickerLabel').value.trim();
   if(!latestLabel){errorText(tr('Укажите название места','მიუთითეთ ადგილის სახელი'));button.disabled=false;node('locationPickerLabel').focus();return;}
   syncLabel();selected.label=owner.location.label;selected.address=owner.location.address||selected.address;
   if(owner.location.label_mode)selected.label_mode=owner.location.label_mode;
   mergePresentation(selected,owner.location);
   apply(owner.field,selected);close();}
  catch(error){if(active===owner){errorText(error.message);button.disabled=false;}}
 }
 function bind(){
  for(const [field,config]of Object.entries(fields)){
   const input=node(config.input);if(!input)continue;
   input.addEventListener('focus',warm);input.addEventListener('keydown',event=>{if(event.key==='Escape')node(config.drop)?.classList.remove('open');});
  }
  document.querySelectorAll('[data-location-field]').forEach(button=>{button.title=tr('Выбрать на карте','არჩევა რუკაზე');button.setAttribute('aria-label',tr('Выбрать место на карте','ადგილის არჩევა რუკაზე'));button.addEventListener('click',()=>open(button.dataset.locationField));});
  node('locationPickerLabel')?.addEventListener('input',()=>{if(active){active.labelEdited=true;active.location.label_mode='custom';active.location.label=node('locationPickerLabel').value.trim();}});
  node('locationPickerConfirm')?.addEventListener('click',confirm);node('locationPickerCancel')?.addEventListener('click',()=>close());
  node('locationPickerOverlay')?.addEventListener('click',event=>{if(event.target===node('locationPickerOverlay'))close();});
  document.addEventListener('keydown',event=>{
   if(!active)return;
   if(event.key==='Escape'){event.preventDefault();event.stopImmediatePropagation();close();return;}
   if(event.key==='Tab'){
    const options=[...node('locationPickerOverlay').querySelectorAll('button:not([disabled]),input')].filter(el=>!el.hidden);
    const first=options[0],last=options[options.length-1];if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
   }
  },true);
 }
 function refreshLanguage(){
  for(const [field,selected]of Object.entries(selections))if(node(fields[field]?.input)?.value===selected.input)apply(field,selected.location);
  for(const [field,entry]of Object.entries(state))if(node(fields[field]?.drop)?.classList.contains('open'))render(field,entry.rows,entry.pending);
  if(active){paintPicker();const config=fields[active.field];node('locationPickerTitle').textContent=config.side==='from'?tr('Место отправления','გაგზავნის ადგილი'):tr('Место доставки','მიწოდების ადგილი');node('locationPickerLabelCaption').textContent=tr('Название места','ადგილის სახელი');node('locationPickerInstruction').textContent=tr('Передвиньте карту или метку и подтвердите точку.','გადაადგილეთ რუკა ან ნიშნული და დაადასტურეთ წერტილი.');node('locationPickerConfirm').textContent=tr('Выбрать эту точку','ამ წერტილის არჩევა');node('locationPickerCancel').textContent=tr('Отмена','გაუქმება');renderNearby();}
  document.querySelectorAll('[data-location-field]').forEach(button=>{button.title=tr('Выбрать на карте','არჩევა რუკაზე');button.setAttribute('aria-label',tr('Выбрать место на карте','ადგილის არჩევა რუკაზე'));});
 }
 window.CaucasLocations={search,warm,read,restore,open,close,choose,preload,objectLocation,normalize,refreshLanguage,hide:field=>node(fields[field]?.drop)?.classList.remove('open')};
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bind,{once:true});else bind();
})();
