/* On-demand road distance through the existing Yandex JS SDK. No stored/server metrics. */
(function(){
 'use strict';
 const cache=new Map(),pending=new Map(),queue=[];
 const SUCCESS_TTL=10*60*1000,FAILURE_TTL=30*1000,DEADLINE=8000,MAX_CACHE=30;
 let running=0,sdkPromise=null;
 const normalize=value=>String(value??'').normalize('NFKC').trim().toLocaleLowerCase().replace(/\s+/g,' ');
 function numeric(value){return (typeof value==='number'||typeof value==='string'&&value.trim()!=='')&&Number.isFinite(Number(value));}
 function coordinates(lat,lon){return numeric(lat)&&numeric(lon)&&Math.abs(Number(lat))<=90&&Math.abs(Number(lon))<=180?[Number(lat),Number(lon)]:null;}
 function catalogue(){try{return typeof CITIES!=='undefined'&&Array.isArray(CITIES)?CITIES:[];}catch{return[];}}
 function endpoint(load,side){
  const location=load[side+'_location'];
  // An invalid exact point must never silently become its nearest city.
  if(location!=null){const point=coordinates(location.lat,location.lon);return point?{point,precision:location.kind==='settlement'?'settlement':'exact'}:null;}
  const lat=load[side+'_lat'],lon=load[side+'_lon']??load[side+'_lng'];
  if(lat!=null||lon!=null){const point=coordinates(lat,lon);return point?{point,precision:'exact'}:null;}
  const text=load[side+'_city']||load[side]||'',detail=load[side+'2']||load[side+'_address']||'';
  // Legacy postal/POI text cannot be represented by a city-centre route.
  if(detail&&normalize(detail)!==normalize(text))return null;
  const key=load[side+'_city_key'],id=load[side+'_city_id'],name=normalize(text),cities=catalogue();
  let matches=key?cities.filter(city=>[city.canonical_key,city.key].includes(key)):[];
  if(!matches.length&&id!=null)matches=cities.filter(city=>numeric(city.city_id??city.id)&&Number(city.city_id??city.id)===Number(id));
  if(!matches.length&&name)matches=cities.filter(city=>[city.name,city.name_ru,city.nameGe,city.name_ge,city.name_en,city.nameEn,city.label,...(Array.isArray(city.aliases)?city.aliases:[])].some(alias=>alias!=null&&normalize(alias)===name));
  if(matches.length!==1)return null;
  const city=matches[0],point=coordinates(city.lat,city.lon??city.lng);
  return point?{point,precision:'settlement'}:null;
 }
 function endpoints(load){
  if(!load||typeof load!=='object')return null;
  const from=endpoint(load,'from'),to=endpoint(load,'to');
  return from&&to?{from:from.point,to:to.point,precision:from.precision==='exact'&&to.precision==='exact'?'exact':'settlement'}:null;
 }
 const keyFor=points=>'auto|'+points.from.join(',')+'|'+points.to.join(',');
 function key(load){const points=endpoints(load);return points?keyFor(points):null;}
 function entry(routeKey){
  const found=cache.get(routeKey);if(!found)return null;
  if(Date.now()>=found.expires){cache.delete(routeKey);return null;}
  cache.delete(routeKey);cache.set(routeKey,found);return found;
 }
 function remember(routeKey,value){
  cache.delete(routeKey);cache.set(routeKey,{value,expires:Date.now()+(value?SUCCESS_TTL:FAILURE_TTL)});
  while(cache.size>MAX_CACHE)cache.delete(cache.keys().next().value);
 }
 function peek(load){const routeKey=key(load);return routeKey?entry(routeKey)?.value||null:null;}
 function sdk(){
  if(sdkPromise)return sdkPromise;
  sdkPromise=new Promise((resolve,reject)=>{
   let settled=false;
   const finish=(error,api)=>{if(settled)return;settled=true;clearTimeout(timer);error?reject(error):resolve(api);};
   const timer=setTimeout(()=>finish(Error('Maps unavailable')),7000);
   try{
    if(typeof loadYmapsLazy!=='function')throw Error('Maps unavailable');
    loadYmapsLazy(()=>{
     if(typeof ymaps==='undefined'||typeof ymaps.ready!=='function')return finish(Error('Maps unavailable'));
     try{ymaps.ready(()=>typeof ymaps.route==='function'?finish(null,ymaps):finish(Error('Routing unavailable')));}catch(error){finish(error);}
    },()=>finish(Error('Maps unavailable')));
   }catch(error){finish(error);}
  }).catch(error=>{sdkPromise=null;throw error;});
  return sdkPromise;
 }
 function complete(job,value){
  if(job.finished)return;
  job.finished=true;clearTimeout(job.timer);pending.delete(job.key);remember(job.key,value);job.resolve(value);
  if(job.started){running--;pump();}
 }
 function pump(){
  while(running<2&&queue.length){
   const job=queue.shift();if(job.finished)continue;
   if(Date.now()>=job.expires){complete(job,null);continue;}
   job.started=true;running++;
   sdk().then(api=>job.finished?null:api.route([job.points.from,job.points.to],{multiRoute:true,routingMode:'auto',reverseGeocoding:false})).then(route=>{
    if(job.finished)return;
    const meters=route?.getActiveRoute?.()?.properties?.get?.('distance')?.value;
    const result=typeof meters==='number'&&Number.isFinite(meters)&&meters>=0
     ?Object.freeze({km:meters/1000,meters,source:'yandex_auto',precision:job.points.precision}):null;
    complete(job,result);
   }).catch(()=>complete(job,null));
  }
 }
 function getDistance(load){
  const points=endpoints(load);if(!points)return Promise.resolve(null);
  const routeKey=keyFor(points),cached=entry(routeKey);if(cached)return Promise.resolve(cached.value);
  if(pending.has(routeKey))return pending.get(routeKey).promise;
  const job={key:routeKey,points,started:false,finished:false,expires:Date.now()+DEADLINE};
  job.promise=new Promise(resolve=>{job.resolve=resolve;});
  job.timer=setTimeout(()=>complete(job,null),DEADLINE);
  pending.set(routeKey,job);queue.push(job);pump();return job.promise;
 }
 window.CaucasRouteDistance=Object.freeze({getDistance,endpoints,key,peek});
})();
