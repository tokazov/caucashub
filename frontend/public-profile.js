/* Anonymous public counterpart profiles. Only the public API allowlist is rendered. */
(function(){
 'use strict';
 const node=id=>document.getElementById(id),PAGE_SIZE=10;
 const validId=value=>typeof value==='number'?Number.isSafeInteger(value)&&value>0:typeof value==='string'&&/^[1-9]\d*$/.test(value)&&Number.isSafeInteger(Number(value));
 const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const ge=()=>typeof lang!=='undefined'&&['ge','ka'].includes(lang);
 const tr=(ru,ka)=>ge()?ka:ru;
 const count=value=>Number.isSafeInteger(value)&&value>=0?value:null;
 let current=null,sequence=0,controller=null,returnFocus=null,oldOverflow='',historyMarker=null,ignorePop=false;
 function link(name,id){return validId(id)?'<button type="button" class="public-profile-link" data-public-profile-id="'+Number(id)+'" title="'+tr('Открыть публичный профиль','საჯარო პროფილის გახსნა')+'">'+escape(name||tr('Участник','მომხმარებელი'))+'</button>':escape(name||'');}
 function role(value){return {carrier:tr('Перевозчик','გადამზიდველი'),shipper:tr('Грузовладелец','ტვირთმფლობელი'),both:tr('Грузовладелец и перевозчик','ტვირთმფლობელი და გადამზიდველი')}[value]||tr('Участник','მომხმარებელი');}
 function city(value){if(!value)return '';return typeof translateCity==='function'?translateCity(String(value)):String(value);}
 function date(value){if(typeof value!=='string'||!value)return '—';const parsed=new Date(value);return Number.isFinite(parsed.getTime())?new Intl.DateTimeFormat(ge()?'ka-GE':'ru-RU',{day:'numeric',month:'short',year:'numeric',timeZone:'Asia/Tbilisi'}).format(parsed):'—';}
 function reviewHtml(review){
  const score=Number.isInteger(review.score)&&review.score>=1&&review.score<=5?review.score:null;
  const author=review.author||{},authorName=author.available===true?author.name||tr('Участник','მომხმარებელი'):tr('Участник','მომხმარებელი');
  const authorHtml=author.available===true&&validId(author.id)?link(authorName,author.id):escape(authorName);
  const comment=review.public_comment===true&&author.available===true&&typeof review.comment==='string'?review.comment.trim():'';
  return '<article class="public-profile-review"'+(validId(review.id)?' data-public-review-id="'+Number(review.id)+'"':'')+'><div class="public-profile-review-heading"><span>'+authorHtml+'</span><time data-public-review-date="'+escape(typeof review.created_at==='string'?review.created_at:'')+'">'+escape(date(review.created_at))+'</time></div>'+
   '<div class="public-profile-review-score" data-public-review-score="'+(score||'')+'" aria-label="'+escape(score?tr('Оценка: ','შეფასება: ')+score+'/5':tr('Оценка недоступна','შეფასება მიუწვდომელია'))+'">'+(score?'★'.repeat(score)+'<span aria-hidden="true">'+'☆'.repeat(5-score)+'</span>':'—')+'</div>'+
   (comment?'<p class="public-profile-review-comment">'+escape(comment)+'</p>':'<p class="public-profile-review-no-comment">'+tr('Без публичного комментария','საჯარო კომენტარის გარეშე')+'</p>')+'</article>';
 }
 function render(){
  if(!current)return;
  node('publicProfileTitle').textContent=tr('Публичный профиль','საჯარო პროფილი');
  node('publicProfileClose').setAttribute('aria-label',tr('Закрыть профиль','პროფილის დახურვა'));
  const target=node('publicProfileBody'),data=current.profile;
  if(!data){
   const status=current.error==='notfound'?'notfound':current.error?'unavailable':'loading';
   target.innerHTML='<div class="public-profile-state" data-public-profile-status="'+status+'" '+(status==='loading'?'role="status"':'role="alert"')+'>'+escape(status==='loading'?tr('Загружаем профиль…','პროფილი იტვირთება…'):status==='notfound'?tr('Профиль недоступен','პროფილი მიუწვდომელია'):tr('Не удалось загрузить профиль','პროფილი ვერ ჩაიტვირთა'))+'</div>'+(status==='unavailable'?'<button type="button" class="public-profile-action" data-public-profile-action="retry">'+tr('Повторить','ხელახლა ცდა')+'</button>':'');
   return;
  }
  const reviews=count(data.review_count),rating=typeof data.rating==='number'&&Number.isFinite(data.rating)&&data.rating>=1&&data.rating<=5?data.rating:null;
  const verified=reviews>0&&data.rating_verified===true&&rating!==null;
  const ratingText=verified?'★ '+rating.toLocaleString(ge()?'ka-GE':'ru-RU',{maximumFractionDigits:1})+' · '+tr('Отзывов: ','შეფასებები: ')+reviews:tr('Пока нет подтверждённых отзывов','დადასტურებული შეფასებები ჯერ არ არის');
  const completed=count(data.completed_deals_count),company=data.company_name||data.name||tr('Участник','მომხმარებელი');
  target.innerHTML='<section class="public-profile-summary"><h3>'+escape(company)+'</h3>'+(data.name&&data.name!==company?'<p class="public-profile-name">'+escape(data.name)+'</p>':'')+
   '<p class="public-profile-role" data-public-profile-role="'+escape(['carrier','shipper','both'].includes(data.role)?data.role:'')+'">'+escape(role(data.role))+(data.city?' · '+escape(city(data.city)):'')+'</p>'+
   (data.is_verified===true?'<span class="public-profile-verified">✓ '+tr('Профиль подтверждён','პროფილი დადასტურებულია')+'</span>':'')+
   '<div class="public-profile-metrics"><div><span>'+tr('Рейтинг','რეიტინგი')+'</span><strong data-public-profile-rating>'+escape(ratingText)+'</strong></div><div><span>'+tr('Завершённые перевозки','დასრულებული გადაზიდვები')+'</span><strong data-public-profile-completed>'+escape(completed===null?'—':completed)+'</strong></div></div></section>'+
   '<section class="public-profile-reviews"><h3>'+tr('Отзывы','შეფასებები')+'</h3>'+(current.reviews.length?current.reviews.map(reviewHtml).join(''):'<p class="public-profile-state">'+tr('Отзывов пока нет','შეფასებები ჯერ არ არის')+'</p>')+
   (current.error?'<p class="public-profile-page-error" role="alert">'+tr('Не удалось загрузить следующие отзывы','შემდეგი შეფასებები ვერ ჩაიტვირთა')+'</p><button type="button" class="public-profile-action" data-public-profile-action="retry">'+tr('Повторить','ხელახლა ცდა')+'</button>':current.loading?'<p data-public-profile-status="loading" role="status">'+tr('Загружаем отзывы…','შეფასებები იტვირთება…')+'</p>':current.hasMore?'<button type="button" class="public-profile-action" data-public-profile-action="more">'+tr('Ещё отзывы','მეტი შეფასება')+'</button>':'')+'</section>';
 }
 async function loadPage(offset){
  const owner=current;if(!owner||owner.loading)return;
  owner.loading=true;owner.error=null;owner.retryOffset=offset;render();
  const ticket=++sequence,abort=new AbortController();controller?.abort();controller=abort;
  const timer=setTimeout(()=>abort.abort(),8000);
  try{
   const base=typeof API_BASE!=='undefined'?API_BASE:'';
   const response=await fetch(base+'/api/users/'+owner.id+'/profile?offset='+offset+'&limit='+PAGE_SIZE,{method:'GET',credentials:'omit',headers:{Accept:'application/json'},signal:abort.signal});
   if(current!==owner||sequence!==ticket)return;
   if(!response.ok)throw Object.assign(Error('Public profile unavailable'),{status:response.status});
   const data=await response.json();
   if(current!==owner||sequence!==ticket)return;
   if(!data||!data.profile||Number(data.profile.id)!==owner.id||!Array.isArray(data.reviews)||count(data.offset)!==offset||count(data.total)===null||typeof data.has_more!=='boolean')throw Error('Invalid public profile');
   owner.profile=data.profile;
   const seen=new Set(offset?owner.reviews.map(review=>review.id):[]),rows=data.reviews.filter(review=>review&&typeof review==='object'&&!seen.has(review.id)&&seen.add(review.id));
   owner.reviews=offset?owner.reviews.concat(rows):rows;owner.offset=offset+data.reviews.length;owner.hasMore=data.has_more&&data.reviews.length>0;owner.loading=false;owner.error=null;render();
  }catch(error){
   if(current!==owner||sequence!==ticket)return;
   owner.loading=false;owner.error=error.status===404?'notfound':'unavailable';
   if(error.status===404){owner.profile=null;owner.reviews=[];owner.hasMore=false;}
   render();
  }finally{clearTimeout(timer);if(controller===abort)controller=null;}
 }
 function open(userId,trigger){
  if(!validId(userId)||!node('publicProfileOverlay'))return false;
  const id=Number(userId),wasOpen=!!current;
  controller?.abort();++sequence;
  if(!wasOpen){returnFocus=trigger instanceof Element?trigger:document.activeElement;oldOverflow=document.body.style.overflow;document.body.style.overflow='hidden';historyMarker='public-profile-'+Date.now()+'-'+sequence;
   try{history.pushState({...history.state,caucasPublicProfile:historyMarker},'',location.href);}catch{historyMarker=null;}
  }
  current={id,profile:null,reviews:[],offset:0,hasMore:false,loading:false,error:null,retryOffset:0};
  node('publicProfileOverlay').hidden=false;render();node('publicProfileClose').focus();loadPage(0);return true;
 }
 function dismiss(updateHistory){
  if(!current)return;
  controller?.abort();controller=null;++sequence;current=null;
  node('publicProfileOverlay').hidden=true;node('publicProfileBody').innerHTML='';document.body.style.overflow=oldOverflow;
  if(returnFocus?.isConnected)returnFocus.focus();returnFocus=null;
  if(updateHistory&&historyMarker&&history.state?.caucasPublicProfile===historyMarker){ignorePop=true;history.back();}
  historyMarker=null;
 }
 function close(){dismiss(true);}
 function refreshLanguage(){
  const label=node('publicProfileSelfLabel');if(label)label.textContent=tr('Мой публичный профиль','ჩემი საჯარო პროფილი');
  document.querySelectorAll('[data-public-profile-id]').forEach(button=>button.title=tr('Открыть публичный профиль','საჯარო პროფილის გახსნა'));
  if(current)render();
 }
 function bind(){
  node('publicProfileClose')?.addEventListener('click',close);
  node('publicProfileOverlay')?.addEventListener('click',event=>{if(event.target===node('publicProfileOverlay'))close();});
  node('publicProfileBody')?.addEventListener('click',event=>{const button=event.target.closest('[data-public-profile-action]');if(!button||!current)return;if(button.dataset.publicProfileAction==='more')loadPage(current.offset);else if(button.dataset.publicProfileAction==='retry')loadPage(current.retryOffset);});
  refreshLanguage();
 }
 document.addEventListener('click',event=>{const button=event.target.closest?.('[data-public-profile-id]');if(!button||!validId(button.dataset.publicProfileId))return;event.preventDefault();event.stopImmediatePropagation();open(button.dataset.publicProfileId,button);},true);
 document.addEventListener('keydown',event=>{
  if(!current)return;
  if(event.key==='Escape'){event.preventDefault();event.stopImmediatePropagation();close();return;}
  if(event.key!=='Tab')return;
  const focusable=[...node('publicProfileDialog').querySelectorAll('button:not([disabled]),[href],[tabindex]:not([tabindex="-1"])')].filter(element=>!element.hidden),first=focusable[0],last=focusable.at(-1);
  if(!first)return;
  if(event.shiftKey&&(document.activeElement===first||!node('publicProfileDialog').contains(document.activeElement))){event.preventDefault();last.focus();}
  else if(!event.shiftKey&&(document.activeElement===last||!node('publicProfileDialog').contains(document.activeElement))){event.preventDefault();first.focus();}
 },true);
 document.addEventListener('focusin',event=>{if(current&&!node('publicProfileDialog').contains(event.target))node('publicProfileClose').focus();});
 window.addEventListener('popstate',event=>{if(ignorePop){ignorePop=false;event.stopImmediatePropagation();return;}if(current){event.stopImmediatePropagation();dismiss(false);}},true);
 window.CaucasPublicProfile=Object.freeze({open,close,refreshLanguage,link});
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bind,{once:true});else bind();
})();
