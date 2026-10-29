/* Deterministic Yandex SDK boundary for isolated browser tests only.
 * This file is supplied only by Playwright route.fulfill, never a production asset.
 * It renders an interactive map surface so tests use ordinary clicks/pans.
 */
(function(){
 'use strict';
 const reverseFails=__REVERSE_FAILS__;
 const mapScale=__MAP_SCALE__;
 const props=data=>({get:key=>key.split('.').reduce((obj,part)=>obj?.[part],data),set:(key,value)=>{data[key]=value;}});
 class Events{constructor(){this.handlers={};}add(name,callback){(this.handlers[name]??=[]).push(callback);return this;}emit(name,data){for(const cb of this.handlers[name]||[])cb({get:key=>data[key]});}}
 class GeoCollection{constructor(rows=[]){this.rows=rows;}add(row){this.rows.push(row);return this;}removeAll(){this.rows=[];}get(i){return this.rows[i];}getLength(){return this.rows.length;}each(cb){this.rows.forEach(cb);}}
 function object(point,label,city,address){return{geometry:{getCoordinates:()=>point.slice()},getAddressLine:()=>address,getLocalities:()=>city?[city]:[],getCountryCode:()=>point[0]>42.78?'RU':'GE',properties:props({name:label,description:city,metaDataProperty:{GeocoderMetaData:{Address:{country_code:point[0]>42.78?'RU':'GE',formatted:address,Components:city?[{kind:'country',name:'Грузия'},{kind:'locality',name:city}]:[{kind:'country',name:'Грузия'},{kind:'street',name:'С-3'}]}}}})};}
 class Placemark{constructor(coords){this.point=coords.slice();this.events=new Events();this.properties=props({});this.options=props({});this.geometry={setCoordinates:value=>{this.point=value.slice();},getCoordinates:()=>this.point.slice()};}}
 class TestMap{constructor(target,options){this.target=typeof target==='string'?document.getElementById(target):target;this.center=options.center.slice();this.zoom=options.zoom;this.events=new Events();this.geoObjects=new GeoCollection();this.controls={add:()=>this.controls};this.container={fitToViewport:()=>{}};
  const surface=document.createElement('div');surface.setAttribute('data-test-map-surface','1');surface.setAttribute('role','img');surface.setAttribute('aria-label','Изолированная карта: нажмите или переместите');surface.style.cssText='position:absolute;inset:0;touch-action:none;background-color:#d9e8dc;background-image:linear-gradient(#ffffff80 1px,transparent 1px),linear-gradient(90deg,#ffffff80 1px,transparent 1px);background-size:35px 35px;';
  const caption=document.createElement('span');caption.textContent='ТЕСТОВАЯ КАРТА · внешних запросов нет';caption.style.cssText='position:absolute;left:12px;top:12px;color:#284830;font:12px sans-serif;pointer-events:none';surface.appendChild(caption);this.target.appendChild(surface);this.surface=surface;this.stamp();
  let down=null,moved=false;
  surface.addEventListener('pointerdown',event=>{down={x:event.clientX,y:event.clientY,center:this.center.slice()};moved=false;surface.setPointerCapture?.(event.pointerId);});
  surface.addEventListener('pointermove',event=>{if(!down)return;const dx=event.clientX-down.x,dy=event.clientY-down.y;if(Math.abs(dx)+Math.abs(dy)>3)moved=true;this.center=[down.center[0]+dy*mapScale,down.center[1]-dx*mapScale];this.stamp();});
  surface.addEventListener('pointerup',event=>{if(!down)return;if(moved)this.events.emit('boundschange',{newCenter:this.center.slice(),newZoom:this.zoom});down=null;});
  surface.addEventListener('click',event=>{if(moved){moved=false;return;}const r=surface.getBoundingClientRect();const coords=[this.center[0]+(r.height/2-(event.clientY-r.top))*mapScale,this.center[1]+((event.clientX-r.left)-r.width/2)*mapScale];this.events.emit('click',{coords});});
 }
 stamp(){this.target.dataset.testMapCenter=JSON.stringify(this.center);this.target.dataset.testMapZoom=String(this.zoom);this.target.dataset.testMapScale=String(mapScale);}
 getCenter(){return this.center.slice();}getZoom(){return this.zoom;}getBounds(){return[[this.center[0]-.05,this.center[1]-.05],[this.center[0]+.05,this.center[1]+.05]];}
 setCenter(value,zoom){this.center=value.slice();if(zoom!=null)this.zoom=zoom;this.stamp();this.events.emit('boundschange',{newCenter:this.center.slice(),newZoom:this.zoom});return Promise.resolve();}
 setBounds(){return Promise.resolve();}destroy(){this.target.innerHTML='';}
 }
 function geocode(query){const reverse=Array.isArray(query);return new Promise((resolve,reject)=>setTimeout(()=>{
  if(reverse&&reverseFails){reject(new Error('isolated reverse provider unavailable'));return;}
  let rows=[];
  if(reverse){rows=[object(query,'С-3','','Грузия, С-3')];}
  else if(/склад|warehouse|საწყობ/i.test(String(query))){rows=[object([41.708123,44.812345],'С-3','Тбилиси','Грузия, Тбилиси, улица Складская, 7')];}
  else if(/тбилиси|tbilisi|თბილისი/i.test(String(query))){rows=[object([41.6941,44.8337],'Тбилиси','Тбилиси','Грузия, Тбилиси')];}
  else if(/батуми|batumi|ბათუმი/i.test(String(query))){rows=[object([41.6424,41.6355],'Батуми','Батуми','Грузия, Батуми')];}
  resolve({geoObjects:new GeoCollection(rows)});
 },60));}
 window.ymaps={ready:cb=>cb(),Map:TestMap,Placemark,geocode,GeoObjectCollection:GeoCollection,Polyline:class{},util:{bounds:{fromPoints:points=>[points[0],points.at(-1)]}}};
})();
