import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
function modal(path){
 const source=readFileSync(new URL('../../../'+path,import.meta.url),'utf8');
 const start=source.indexOf('function trapFocus('),end=source.indexOf('window.trapFocus',start);
 assert.ok(start>=0&&end>start);
 const timers=[],closed=[],calls={first:0,input:0};
 const context={document:{activeElement:{}},setTimeout:(fn,delay)=>timers.push({fn,delay}),closeModal:id=>closed.push(id)};
 const first={kind:'button',focus(){calls.first++;context.document.activeElement=this;}};
 const input={kind:'input',value:'12.5',focus(){calls.input++;context.document.activeElement=this;}};
 let visible=true;
 const node={isConnected:true,getClientRects:()=>visible?[{}]:[],querySelectorAll:()=>[first,input],addEventListener(){},removeEventListener(){},
  contains:target=>target===first||target===input,closest:()=>({id:'settingsOverlay'})};
 vm.createContext(context);vm.runInContext(source.slice(start,end),context);
 context.trapFocus(node);
 return{context,node,input,first,calls,closed,timers,hide(){visible=false;},flush(){assert.equal(timers[0].delay,50);timers.shift().fn();}};
}
for(const path of ['main.js','frontend/main.js']){
 test(path+': opening a modal still focuses the first control if focus remains outside',()=>{
  const h=modal(path);h.flush();assert.equal(h.context.document.activeElement,h.first);assert.equal(h.calls.first,1);
 });
 test(path+': deferred initial focus does not interrupt a fast carrier-capacity clear',()=>{
  const h=modal(path);
  // Native keyboard input is separate from focus/selection, as in an actual fast edit.
  h.input.focus();h.flush();
  if(h.context.document.activeElement.kind==='input')h.context.document.activeElement.value='';
  assert.equal(h.context.document.activeElement,h.input,'Do not steal an editing field focus');
  assert.equal(h.input.value,'','Delete must still reach the field the user selected');
  assert.equal(h.calls.first,0);
 });
 test(path+': a modal closed before the initial-focus timer does not reclaim focus',()=>{
  const h=modal(path),outside=h.context.document.activeElement;h.hide();h.flush();
  assert.equal(h.context.document.activeElement,outside);assert.equal(h.calls.first,0);
 });
 test(path+': a detached modal does not focus its former first control',()=>{
  const h=modal(path),outside=h.context.document.activeElement;h.node.isConnected=false;h.flush();
  assert.equal(h.context.document.activeElement,outside);assert.equal(h.calls.first,0);
 });
 test(path+': preserving a focused input keeps Tab and Shift+Tab trapped within the modal',()=>{
  const h=modal(path);h.input.focus();h.flush();let prevented=0;
  h.node._trapFocusHandler({key:'Tab',shiftKey:false,preventDefault(){prevented++;}});
  assert.equal(h.context.document.activeElement,h.first);
  h.node._trapFocusHandler({key:'Tab',shiftKey:true,preventDefault(){prevented++;}});
  assert.equal(h.context.document.activeElement,h.input);assert.equal(prevented,2);
 });
 test(path+': Escape still closes the owning settings overlay',()=>{
  const h=modal(path);h.node._trapFocusHandler({key:'Escape'});assert.deepEqual(h.closed,['settingsOverlay']);
 });
}
