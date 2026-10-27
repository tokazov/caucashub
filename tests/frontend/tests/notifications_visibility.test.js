import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const read=path=>readFileSync(new URL('../../../'+path,import.meta.url),'utf8');
function attributes(text){
 const result={};for(const match of text.matchAll(/([\w-]+)\s*=\s*"([^"]*)"/g))result[match[1]]=match[2];return result;
}
function style(text=''){
 return Object.fromEntries(text.split(';').map(value=>value.split(':').map(x=>x.trim())).filter(parts=>parts.length===2));
}
function actualHeader(html){
 const ids=new Map(),nodes=[],stack=[];
 const start=html.indexOf('<div class="header">');assert.ok(start>=0);
 for(const match of html.slice(start).matchAll(/<(\/?)([a-z][\w-]*)\b([^>]*)>/gi)){
  const closing=match[1],tag=match[2].toLowerCase();
  if(closing){stack.pop();if(!stack.length)break;continue;}
  const attrs=attributes(match[3]);
  const node={tag,attrs,style:style(attrs.style),parentElement:stack.at(-1)||null,textContent:'',innerHTML:''};
  nodes.push(node);if(attrs.id)ids.set(attrs.id,node);
  if(!['br','img','input','meta','link','hr'].includes(tag))stack.push(node);
 }
 // Populate actual out-of-header IDs used by the real auth UI functions.
 for(const match of html.matchAll(/<([a-z][\w-]*)\b([^>]*\bid="[^"]+"[^>]*)>/gi)){
  const attrs=attributes(match[2]);if(!ids.has(attrs.id))ids.set(attrs.id,{attrs,style:style(attrs.style),textContent:'',innerHTML:''});
 }
 return{ids,nodes};
}
for(const prefix of ['', 'frontend/'])test(prefix+'header HTML/CSS and real auth handlers make the existing bell visible only while signed in',()=>{
 const html=read(prefix+'index.html'),css=read(prefix+'styles.css'),source=read(prefix+'main.js');
 const {ids}=actualHeader(html),bell=ids.get('notifBtn'),avatar=ids.get('userAvatar');
 assert.ok(bell&&avatar);assert.equal(bell.parentElement,avatar.parentElement,'Preserve the existing header position beside the avatar');
 const defaultRule=css.match(/\.notif-btn\s*\{([^}]+)\}/);assert.ok(defaultRule);
 const defaults=style(defaultRule[1]);assert.equal(defaults.display,'none','Anonymous initial state comes from the actual stylesheet');
 const effectiveDisplay=node=>node.style.display||((node.attrs.class||'').split(/\s+/).includes('notif-btn')?defaults.display:'block');
 const visible=()=>{
  for(let node=bell;node;node=node.parentElement)if(effectiveDisplay(node)==='none')return false;
  return true;
 };
 const context={user:{userId:7,name:'QA carrier'},currentUserId:7,lang:'ru',TRANSLATIONS:{ru:{}},
  document:{getElementById:id=>ids.get(id)||null},getPlanBadge:()=>'',_lsDel(){},closeModal(){},setToken(){}};
 vm.createContext(context);
 const begin=source.indexOf('function showUserState(){'),end=source.indexOf('function openProfile(){',begin);
 assert.ok(begin>=0&&end>begin);vm.runInContext(source.slice(begin,end),context);
 assert.equal(visible(),false,'The untouched HTML/CSS hides the anonymous bell');
 context.showUserState();
 assert.equal(visible(),true,'The real login handler must override CSS display:none, not merely remove an inline style');
 assert.equal(bell.style.display,'inline-flex');assert.equal(avatar.style.display,'flex');
 context.doLogout();assert.equal(visible(),false,'The same DOM element must be hidden again on logout');
 context.user={userId:8,name:'Second account'};context.currentUserId=8;context.showUserState();
 assert.equal(visible(),true,'A subsequent account can use the same existing header bell');
});
