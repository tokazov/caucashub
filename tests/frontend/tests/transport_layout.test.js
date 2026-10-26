import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
const source=path=>readFileSync(new URL('../../../'+path,import.meta.url),'utf8');
// Source CSS cascade fixture: media, specificity, important and inline priority.
// No browser geometry/native-crash claim; actual stylesheets are evaluated.
function rules(css,width,out=[]){
 css=css.replace(/\/\*[\s\S]*?\*\//g,'');let pos=0;
 while(pos<css.length){
  const open=css.indexOf('{',pos);if(open<0)break;
  let depth=1,end=open+1,quote='';
  for(;end<css.length&&depth;end++){const ch=css[end];
   if(quote){if(ch===quote&&css[end-1]!=='\\')quote='';}
   else if(ch==='"'||ch==="'")quote=ch;else if(ch==='{')depth++;else if(ch==='}')depth--;
  }
  const selector=css.slice(pos,open).trim(),body=css.slice(open+1,end-1);
  if(selector.startsWith('@media')){
   const min=/min-width\s*:\s*(\d+)px/.exec(selector),max=/max-width\s*:\s*(\d+)px/.exec(selector);
   if((!min||width>=+min[1])&&(!max||width<=+max[1]))rules(body,width,out);
  }else if(!selector.startsWith('@'))for(const s of selector.split(','))out.push({selector:s.trim(),body});
  pos=end;
 }return out;
}
function simple(el,s){
 if(!el||!/^[\w.#*-]+$/.test(s))return false;
 const tag=/^[\w*-]+/.exec(s)?.[0];if(tag&&tag!=='*'&&tag!==el.tag)return false;
 return [...s.matchAll(/([.#])([\w-]+)/g)].every(([,kind,v])=>kind==='#'?el.id===v:el.classes.includes(v));
}
function matches(el,selector){
 const parts=selector.replace(/\s*>\s*/g,' > ').trim().split(/\s+/);
 function at(cur,i){if(!simple(cur,parts[i]))return false;if(!i)return true;
  if(parts[i-1]==='>')return at(cur.parent,i-2);
  for(let p=cur.parent;p;p=p.parent)if(at(p,i-1))return true;return false;
 }return at(el,parts.length-1);
}
function computed(el,property,rs){
 let winner;
 const greater=(a,b)=>{for(let i=0;i<a.length;i++){if(a[i]!==b[i])return a[i]>b[i];}return true;};
 function add(body,specificity,order){for(const part of body.split(';')){
  const colon=part.indexOf(':');if(part.slice(0,colon).trim()!==property)continue;
  const raw=part.slice(colon+1).trim(),rank=[/!important\s*$/.test(raw)?1:0,...specificity,order];
  if(!winner||greater(rank,winner.rank))winner={rank,value:raw.replace(/\s*!important\s*$/,'')};
 }}
 rs.forEach(({selector,body},order)=>{if(matches(el,selector))add(body,
  [0,(selector.match(/#/g)||[]).length,(selector.match(/\./g)||[]).length,
   selector.split(/[ >]+/).filter(s=>/^[a-z]/.test(s)).length],order);
 });add(el.inline||'',[1,0,0,0],rs.length);return winner?.value;
}
function fixture(prefix,width){
 const html=source(prefix+'index.html'),css=source(prefix+'styles.css');
 const sheet=[...html.matchAll(/<style[^>]*>([\s\S]*?)<\/style>|<link\b[^>]*href="styles\.css[^"]*"[^>]*>/g)]
  .map(m=>m[1]===undefined?css:m[1]).join('\n');
 const el=(id,classes=[],parent=null,inline='')=>({tag:'div',id,classes,parent,inline});
 const transport=el('sec-trucks',['section','active']),list=el('transportList',['transport-list'],transport),
  card=el('',['card-load','transport-card'],list),loads=el('sec-loads',['section']),
  cargo=el('cargoList',[],loads),cargoCard=el('',['card-load'],cargo);
 return{html,rs:rules(sheet,width),
  row:el('',['row-desktop'],card,'grid-template-columns:2fr 1.5fr 0.8fr 0.8fr 1fr 1fr 100px'),
  header:el('',['thead','transport-thead'],transport,'display:grid;grid-template-columns:2fr 1.5fr 0.8fr 0.8fr 1fr 1fr 100px'),
  mobile:el('',['row-mobile'],card),cargoRow:el('',['row-desktop'],cargoCard),cargoHeader:el('',['thead'],loads)};
}
const tracks=value=>value?.match(/minmax\([^)]*\)|[^\s]+/g)||[];
for(const prefix of['','frontend/']){
 test(prefix+'desktop seven transport tracks survive cargo and inline CSS',()=>{
  const f=fixture(prefix,1280);
  for(const e of[f.row,f.header]){const cols=tracks(computed(e,'grid-template-columns',f.rs));
   assert.equal(cols.length,7);assert.ok(cols.every(v=>/^minmax\(0,\s*[^)]+\)$/.test(v)),cols.join(' '));
   assert.equal(computed(e,'display',f.rs),'grid');
  }
  assert.equal(tracks(computed(f.cargoRow,'grid-template-columns',f.rs)).length,6);
  assert.equal(tracks(computed(f.cargoHeader,'grid-template-columns',f.rs)).length,6);
 });
 test(prefix+'mobile keeps cards and hides desktop rows',()=>{const f=fixture(prefix,390);
  assert.equal(computed(f.row,'display',f.rs),'none');assert.equal(computed(f.mobile,'display',f.rs),'block');
 });
 test(prefix+'HTML identifies transport list and refreshes stylesheet',()=>{const{html}=fixture(prefix,1280);
  assert.match(html,/id="transportList" class="transport-list"/);assert.match(html,/href="styles\.css\?v=20261026-transport-layout"/);
 });
}
test('frontend transport and cargo headers stay hidden on phones',()=>{const f=fixture('frontend/',390);
 assert.equal(computed(f.header,'display',f.rs),'none');
 assert.equal(computed(f.cargoHeader,'display',f.rs),'none');
});
