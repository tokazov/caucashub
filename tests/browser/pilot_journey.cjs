/* Full current-frontend pilot journey. Disposable SQLite and captured providers only.
 * NODE_PATH must expose Playwright. No user browser profile is reused.
 * Set PYTHON to the existing fixture virtual environment and optionally
 * CARRIER_BROWSER_CHROMIUM_EXECUTABLE_PATH to installed Chrome.
 * Run: node tests/browser/pilot_journey.cjs --spawn-server
 * Without --spawn-server, an already running marked localhost fixture is required.
 */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {spawn}=require('node:child_process');
const ROOT=path.resolve(process.env.CARRIER_PROFILE_REPO_ROOT||path.join(__dirname,'../..'));
const ARTIFACTS=path.resolve(process.env.CARRIER_PUBLICATION_ARTIFACTS||path.join(ROOT,'artifacts/pilot-journey'));
assert.ok(fs.existsSync(path.join(ROOT,'app/routers/transport.py')),'Actual application checkout required');
assert.ok(fs.existsSync(path.join(ROOT,'frontend/index.html')),'Actual frontend checkout required');
fs.mkdirSync(ARTIFACTS,{recursive:true});
const child=spawn(process.execPath,[path.join(__dirname,'publication_journey.cjs'),
 ...(process.argv.includes('--spawn-server')?['--spawn-server']:[])],{
 cwd:ROOT,env:{...process.env,CARRIER_PROFILE_REPO_ROOT:ROOT,CARRIER_PUBLICATION_ARTIFACTS:ARTIFACTS,
  CARRIER_BROWSER_TEMP_ROOT:process.env.CARRIER_BROWSER_TEMP_ROOT||path.join(ARTIFACTS,'.fixture'),
  CARRIER_BROWSER_PUBLICATION:'1',CARRIER_BROWSER_COMPLETION:'1',CARRIER_BROWSER_NOTIFICATIONS:'1',
  CARRIER_BROWSER_AUTH:'0',CARRIER_BROWSER_PILOT:'1'},stdio:['ignore','pipe','pipe']
});
const log=fs.createWriteStream(path.join(ARTIFACTS,'journey.log'));
child.stdout.on('data',chunk=>{process.stdout.write(chunk);log.write(chunk);});
child.stderr.on('data',chunk=>{process.stderr.write(chunk);log.write(chunk);});
child.on('error',error=>{console.error(error);process.exitCode=1;log.end();});
child.on('close',code=>{
 log.end();
 if(code!==0){process.exitCode=code||1;return;}
 try{
  const report=JSON.parse(fs.readFileSync(path.join(ARTIFACTS,'results.json'),'utf8'));
  assert.deepEqual(report.results.map(row=>row.viewport),['desktop','mobile']);
  assert.equal(report.diagnostics.productionApiAttempts,0);
  for(const row of report.results){
   assert.equal(row.status,'passed');assert.equal(row.contactsComplete,true);
   assert.equal(row.completion.length,2);
   for(const source of row.completion){assert.equal(source.completed,true);assert.equal(source.reviewsPersisted,true);}
   assert.equal(row.notifications.notificationsTotal,14);
   assert.equal(row.notifications.externalRequests,24); // Captured by local HTTPX sink.
   assert.equal(row.notifications.externalDeliveriesOnce,true);
  }
  console.log('Pilot journey: desktop + mobile passed; all provider deliveries captured locally.');
 }catch(error){console.error(error.stack||error);process.exitCode=1;}
});
