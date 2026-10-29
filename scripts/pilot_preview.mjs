/** Local-only review server for the real Pages Worker + isolated SQLite API.
 * Run the marked carrier_profile_server.py fixture on 8765 first.
 * node scripts/pilot_preview.mjs
 * Never forwards to production; all API requests require the fixture marker.
 */
import http from 'node:http';
import {readFile,stat} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const ROOT=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const FRONTEND=path.join(ROOT,'frontend');
const HOST='127.0.0.1',PORT=8890,ORIGIN='http://127.0.0.1:8890';
const fixturePort=Number(process.env.CARRIER_PREVIEW_FIXTURE_PORT||8765);
if(!Number.isInteger(fixturePort)||fixturePort<1024||fixturePort>65535)throw Error('Invalid local fixture port');
const FIXTURE='http://127.0.0.1:'+fixturePort;
const PRODUCTION_API='https://api-production-f3ea.up.railway.app';
const workerSource=await readFile(path.join(FRONTEND,'_worker.js'),'utf8');
const {default:worker}=await import('data:text/javascript;base64,'+Buffer.from(workerSource).toString('base64'));
const MIME={'.html':'text/html; charset=utf-8','.css':'text/css; charset=utf-8','.js':'application/javascript; charset=utf-8','.json':'application/json; charset=utf-8','.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.webp':'image/webp','.svg':'image/svg+xml','.ico':'image/x-icon','.txt':'text/plain; charset=utf-8','.xml':'application/xml; charset=utf-8','.woff2':'font/woff2'};
async function fixtureReady(){
 const response=await fetch(FIXTURE+'/__test__/ready',{signal:AbortSignal.timeout(2000),redirect:'error'});
 const body=await response.json();
 if(!response.ok||response.headers.get('x-carrier-test-only')!=='1'||body.test_only!==true||body.isolated_sqlite!==true||body.pilot_test!==true||body.actual_city_stats_routers!==true||body.origin!==FIXTURE||body.ready!==true)throw Error('Marked isolated pilot fixture required');
 return body;
}
const ASSETS={async fetch(request){
 const url=new URL(request.url);
 if(!['GET','HEAD'].includes(request.method))return new Response('Method not allowed',{status:405});
 let decoded;try{decoded=decodeURIComponent(url.pathname);}catch{return new Response('Bad path',{status:400});}
 if(decoded.includes('\\')||decoded.includes('\0'))return new Response('Bad path',{status:400});
 let file=path.resolve(FRONTEND,'.'+decoded);
 if(file!==FRONTEND&&!file.startsWith(FRONTEND+path.sep))return new Response('Forbidden',{status:403});
 try{if((await stat(file)).isDirectory())file=path.join(file,'index.html');await stat(file);}
 catch{if(!path.extname(decoded))file=path.join(FRONTEND,'index.html');else return new Response('Not found',{status:404});}
 const ext=path.extname(file),type=MIME[ext]||'application/octet-stream';
 let body=await readFile(file);
 if(ext==='.js'||ext==='.html')body=Buffer.from(body.toString('utf8').split(PRODUCTION_API).join(ORIGIN));
 return new Response(request.method==='HEAD'?null:body,{headers:{'content-type':type,'cache-control':'no-store'}});
}};
const server=http.createServer(async(req,res)=>{
 try{
  if(!['127.0.0.1','::ffff:127.0.0.1','::1'].includes(req.socket.remoteAddress))throw Error('Local review only');
  const url=new URL(req.url,ORIGIN);
  let response;
  if(url.pathname.startsWith('/api/')||url.pathname.startsWith('/__test__/')){
   await fixtureReady(); // Check the actual database target before every forwarded request.
   const parts=[];for await(const part of req)parts.push(part);
   const headers={};for(const name of ['authorization','content-type','accept'])if(req.headers[name])headers[name]=req.headers[name];
   response=await fetch(FIXTURE+url.pathname+url.search,{method:req.method,headers,
    body:['GET','HEAD'].includes(req.method)?undefined:Buffer.concat(parts),redirect:'error',signal:AbortSignal.timeout(20000)});
  }else{
   response=await worker.fetch(new Request(url,{method:req.method}),{ASSETS});
  }
  const headers=Object.fromEntries(response.headers);
  delete headers['content-encoding'];delete headers['content-length'];
  headers['cache-control']='no-store';headers['x-pilot-preview']='isolated-local-review';
  res.writeHead(response.status,headers);
  res.end(req.method==='HEAD'?undefined:Buffer.from(await response.arrayBuffer()));
 }catch(error){res.writeHead(503,{'content-type':'text/plain; charset=utf-8','cache-control':'no-store','x-pilot-preview':'isolated-local-review'});res.end('Local pilot preview unavailable: '+error.message);}
});
server.listen(PORT,HOST,()=>console.log('Local pilot preview: '+ORIGIN+' (isolated fixture required for API; never production)'));
