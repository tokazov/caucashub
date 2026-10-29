const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {pathToFileURL}=require('node:url');
const vm=require('node:vm');
const frontend=path.resolve(__dirname,'../../../frontend');
const source=fs.readFileSync(path.join(frontend,'index.html'),'utf8');
const worker=import(pathToFileURL(path.join(frontend,'_worker.js')).href);
function assets(html=source){const calls=[];return{calls,env:{ASSETS:{fetch:async request=>{
 const url=new URL(request.url);calls.push({path:url.pathname,query:url.search,method:request.method});
 if(url.pathname==='/styles.css')return new Response('body{}',{headers:{'content-type':'text/css'}});
 if(url.pathname.endsWith('.js'))return new Response('// script',{headers:{'content-type':'application/javascript'}});
 return new Response(html,{headers:{'content-type':'text/html','x-fixture':'assets','cache-control':'public,max-age=300'}});
}}}};}
test('Georgian direct HTML resolves local scripts and styles from root',async()=>{
 const fixture=assets(),w=(await worker).default;
 const response=await w.fetch(new Request('https://preview.example.test/ka/'),fixture.env);
 const html=await response.text();
 assert.equal(response.status,200);assert.match(html,/<html lang="ka">/);
 assert.equal((html.match(/<base\b/g)||[]).length,1);assert.match(html,/<base href="\/">/);
 for(const relative of ['styles.css?v=1','main.js','api.js','mari-avatar-v2.webp']){
  assert.equal(new URL(relative,new URL('/', 'https://preview.example.test/ka/')).pathname,'/'+relative.split('?')[0]);
 }
 assert.doesNotMatch(html,/_forceLangGe|setTimeout\(_forceLangGe/);
 assert.match(response.headers.get('cache-control'),/no-store/);
 assert.equal(response.headers.get('x-fixture'),'assets');
});
test('root and Georgian page serve the same functional HTML after refresh',async()=>{
 const w=(await worker).default;
 for(const route of ['/','/ka/','/ka/']){
  const fixture=assets(),response=await w.fetch(new Request('https://preview.example.test'+route),fixture.env);
  const html=await response.text();
  assert.match(html,/id="sec-loads"/);assert.match(html,/id="sec-trucks"/);
  assert.match(html,/<base href="\/">/);assert.equal(fixture.calls[0].path,'/');
 }
});
test('old language URL and missing slash redirect inside preview without dropping attribution',async()=>{
 const w=(await worker).default;
 for(const input of ['/?lang=ge&utm_source=pilot','/ka?utm_source=pilot']){
  const response=await w.fetch(new Request('https://preview.example.test'+input),assets().env);
  assert.equal(response.status,301);assert.equal(response.headers.get('location'),'https://preview.example.test/ka/?utm_source=pilot');
 }
});
test('previously cached Georgian HTML still gets CSS/JS with correct MIME',async()=>{
 const w=(await worker).default;
 for(const [name,type] of [['styles.css','text/css'],['main.js','application/javascript'],['api.js','application/javascript']]){
  const fixture=assets(),r=await w.fetch(new Request('https://preview.example.test/ka/'+name+'?v=123'),fixture.env);
  assert.equal(r.headers.get('content-type'),type);
  assert.deepEqual(fixture.calls,[{path:'/'+name,query:'?v=123',method:'GET'}]);
 }
});
test('missing/failed index response is not disguised as successful locale HTML',async()=>{
 const w=(await worker).default,env={ASSETS:{fetch:async()=>new Response('unavailable',{status:503})}};
 const r=await w.fetch(new Request('https://preview.example.test/ka/'),env);assert.equal(r.status,503);
});
test('POST is never converted into a successful HTML page',async()=>{
 const w=(await worker).default,fixture=assets();
 await w.fetch(new Request('https://preview.example.test/ka/',{method:'POST'}),fixture.env);
 assert.equal(fixture.calls[0].method,'POST');assert.equal(fixture.calls[0].path,'/ka/');
});
test('HEAD keeps an empty response body',async()=>{
 const w=(await worker).default,r=await w.fetch(new Request('https://preview.example.test/ka/',{method:'HEAD'}),assets().env);
 assert.equal(await r.text(),'');assert.equal(r.status,200);
});
test('both SEO locales omit unsupported first-place and count claims',async()=>{
 const w=await worker;
 for(const lang of ['ru','ge']){
  const html=w.injectSEO(source,lang);
  assert.doesNotMatch(html,/первая|Первый|Первая|პირველი|120\+/);
  assert.match(html,new RegExp('<html lang="'+(lang==='ge'?'ka':'ru')+'">'));
 }
});
test('early locale initialization recognizes /ka even with a saved Russian preference',()=>{
 const marker=source.indexOf('// Определяем язык');
 const start=source.lastIndexOf('<script>',marker)+8;
 const end=source.indexOf('</script>',marker);
 const store=new Map([['ch_lang','ru']]);
 const document={documentElement:{lang:'ru'},addEventListener(){},querySelector(){return null;}};
 const window={};
 vm.runInNewContext(source.slice(start,end),{location:{pathname:'/ka/',search:''},localStorage:{getItem:k=>store.get(k),setItem:(k,v)=>store.set(k,v)},document,window});
 assert.equal(window._initLang,'ge');assert.equal(store.get('ch_lang'),'ge');assert.equal(document.documentElement.lang,'ka');
});
