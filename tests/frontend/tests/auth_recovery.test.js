import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const read=path=>readFileSync(new URL('../../../'+path,import.meta.url),'utf8');
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return{promise,resolve};};
const response=(data,status=200)=>({ok:status>=200&&status<300,status,headers:{get:()=>null},json:async()=>data});
function classes(initial=[]){const set=new Set(initial);return{add:x=>set.add(x),remove:x=>set.delete(x),contains:x=>set.has(x),toggle(x,on){if(on)set.add(x);else set.delete(x);}};}
function auth(path){
 const fields={},calls={requests:[],removed:[],stored:[],warnings:[],intervals:new Map(),resetInbox:0,stopTg:0};
 for(const id of ['loginEmail','loginPass','regPass','forgotEmail','forgotCode','forgotNewPass','forgotNewPass2','forgotEmailShow',
  'forgotError','forgotError2','forgotStep1','forgotStep2','forgotSuccess','btnForgotSend','btnForgotReset','btnResendCode','resendCountdown','resendCooldownText',
  'formLogin','formRegister','formForgot','tabLogin','tabRegister','passwordChangeBlock','changeOldPass','changeNewPass','changeNewPass2',
  'btnChangePassword','changePasswordError','sEmail','deletePasswordInput','onlineDot','btnLogin','btnReg','authBtns','userAvatar',
  'ordersList','ordersEmpty','profileOverlay','settingsOverlay','authOverlay']){
  fields[id]={value:'',textContent:'',innerHTML:'',disabled:false,open:false,style:{},classList:classes(),querySelector:()=>null};
 }
 fields.authOverlay.classList.add('on');fields.settingsOverlay.classList.add('on');fields.formForgot.style.display='none';
 let now=Date.parse('2026-10-27T12:00:00Z'),timer=0;
 class Clock extends Date{static now(){return now;}}
 const context={window:{},user:null,currentUserId:null,token:null,lang:'ru',TRANSLATIONS:{ru:{},ge:{}},API_BASE:'https://local.test',TextEncoder,Date:Clock,Map,
  document:{getElementById:id=>fields[id]||null,querySelector:()=>null},
  getToken:()=>context.token,setToken:value=>{context.token=value;},
  _lsDel:key=>calls.removed.push(key),_lsSet:(key,value)=>calls.stored.push({key,value}),
  closeModal:id=>fields[id]?.classList.remove('on'),
  resetNotifications:()=>calls.resetInbox++,_stopTelegramPolling:()=>calls.stopTg++,
  showToastWarn:value=>calls.warnings.push(value),backToStep1(){},
  openSettings:Object.assign(()=>{},{revision:1}),
  setInterval:(fn,ms)=>{const id=++timer;calls.intervals.set(id,{fn,ms});return id;},clearInterval:id=>calls.intervals.delete(id),
  fetch:(url,options)=>{calls.requests.push({url,options});return context.respond(url,options);},
  respond:async()=>response({message:'Если адрес зарегистрирован, код будет отправлен'})};
 vm.createContext(context);const source=read(path);
 const weakStart=source.indexOf('const _WEAK_PASS'),weakEnd=source.indexOf('function updatePassStrength',weakStart);
 vm.runInContext(source.slice(weakStart,weakEnd),context);
 const start=source.indexOf('// ── PASSWORD RECOVERY & CHANGE'),end=source.indexOf('// ── END PASSWORD RECOVERY & CHANGE',start);
 vm.runInContext(source.slice(start,end),context);
 const cool=source.indexOf('// Recovery resend cooldown applies only after a confirmed request.');
 vm.runInContext(source.slice(cool,source.indexOf('window.dealAction =',cool)),context);
 const logout=source.indexOf('function doLogout(){'),logoutEnd=source.indexOf('function openProfile(){',logout);
 vm.runInContext(source.slice(logout,logoutEnd),context);
 const open=source.indexOf('function openAuth('),openEnd=source.indexOf('// ── PASSWORD RECOVERY & CHANGE',open);
 vm.runInContext(source.slice(open,openEnd),context);
 fields.loginEmail.value='synthetic@example.test';context.showForgotForm();
 return{context,fields,calls,advance(ms){now+=ms;for(const row of [...calls.intervals.values()])row.fn();},
  async requestCode(){await context.doForgotStep1();},resetDraft(){fields.forgotCode.value='123456';fields.forgotNewPass.value='IsolatedRecovery39!';fields.forgotNewPass2.value='IsolatedRecovery39!';},
  signedIn(){context.user={userId:7,email:'synthetic@example.test',name:'Synthetic'};context.currentUserId=7;context.token='old-test-token';fields.sEmail.value=context.user.email;}
 };
}
for(const path of ['main.js','frontend/main.js']){
 test(path+': forgot uses the generic real contract and never exposes a server dev code',async()=>{
  const h=auth(path);h.context.respond=async()=>response({message:'Если адрес зарегистрирован, код будет отправлен',dev_code:'999999'});
  await h.requestCode();assert.equal(h.calls.requests.length,1);
  assert.equal(h.calls.requests[0].url,'https://local.test/api/auth/forgot-password');assert.equal(h.calls.requests[0].options.method,'POST');
  assert.deepEqual(JSON.parse(h.calls.requests[0].options.body),{email:'synthetic@example.test'});
  assert.equal(h.fields.forgotStep2.style.display,'block');assert.equal(h.fields.forgotCode.value,'');
  assert.equal(h.fields.btnResendCode.disabled,true);assert.equal(h.calls.stored.length,0);
 });
 test(path+': failed or malformed code requests never advance or claim that email was sent',async()=>{
  for(const [status,data]of [[503,{detail:'Provider unavailable'}],[429,{detail:'Подождите'}],[200,{}]]){
   const h=auth(path);h.context.respond=async()=>response(data,status);await h.requestCode();
   assert.equal(h.fields.forgotStep1.style.display,'block');assert.equal(h.fields.forgotStep2.style.display,'none');
   assert.equal(h.fields.forgotError.style.display,'block');assert.equal(h.fields.btnForgotSend.disabled,false);
   assert.equal(h.calls.intervals.size,0);
  }
 });
 test(path+': invalid email makes no request and no timer',async()=>{
  const h=auth(path);h.fields.forgotEmail.value='not-an-email';await h.requestCode();
  assert.equal(h.calls.requests.length,0);assert.equal(h.calls.intervals.size,0);assert.equal(h.fields.forgotError.style.display,'block');
 });
 test(path+': pending forgot requests deduplicate and an edited email keeps its draft and retry button',async()=>{
  const h=auth(path),held=deferred();h.context.respond=()=>held.promise;
  const pending=h.context.doForgotStep1();await h.context.doForgotStep1();assert.equal(h.calls.requests.length,1);
  h.fields.forgotEmail.value='other@example.test';held.resolve(response({message:'Generic'}));await pending;
  assert.equal(h.fields.forgotStep2.style.display,'none');assert.equal(h.fields.forgotEmail.value,'other@example.test');
  assert.equal(h.fields.btnForgotSend.disabled,false);
 });
 test(path+': a late code request cannot advance a reopened form or another login session',async()=>{
  for(const mode of ['reopen','login']){
   const h=auth(path),held=deferred();h.context.respond=()=>held.promise;
   const pending=h.context.doForgotStep1();
   if(mode==='reopen')h.context.showForgotForm();else h.signedIn();
   held.resolve(response({message:'Generic'}));await pending;
   assert.equal(h.fields.forgotStep2.style.display,'none');assert.equal(h.calls.intervals.size,0);
  }
 });
 test(path+': resend waits for the real cooldown, keeps the same email and starts cooldown only after success',async()=>{
  const h=auth(path);await h.requestCode();await h.context.doResendCode();assert.equal(h.calls.requests.length,1);
  h.advance(60000);assert.equal(h.fields.btnResendCode.disabled,false);
  h.context.respond=async()=>response({detail:'Try later'},503);await h.context.doResendCode();
  assert.equal(h.calls.requests.length,2);assert.equal(h.fields.btnResendCode.disabled,false);
  h.context.respond=async()=>response({message:'Generic'});await h.context.doResendCode();
  assert.equal(h.calls.requests.length,3);assert.equal(h.fields.btnResendCode.disabled,true);
  assert.equal(JSON.parse(h.calls.requests[2].options.body).email,'synthetic@example.test');
 });
 test(path+': reset requires six ASCII digits and a matching policy-valid password before network',async()=>{
  for(const[code,password,repeat]of [['abcdef','IsolatedRecovery39!','IsolatedRecovery39!'],['１２３４５６','IsolatedRecovery39!','IsolatedRecovery39!'],
   ['123456','short','short'],['123456','password1','password1'],['123456','x'.repeat(73),'x'.repeat(73)],
   ['123456','🙂'.repeat(19),'🙂'.repeat(19)],['123456','IsolatedRecovery39!','Different39!']]){
   const h=auth(path);await h.requestCode();h.fields.forgotCode.value=code;h.fields.forgotNewPass.value=password;h.fields.forgotNewPass2.value=repeat;
   await h.context.doForgotStep2();assert.equal(h.calls.requests.length,1);assert.equal(h.fields.forgotError2.style.display,'block');
  }
 });
 test(path+': policy accepts 72 UTF-8 bytes and does not invent uppercase or numeric requirements',()=>{
  const h=auth(path);
  assert.equal(h.context._newPasswordError('x'.repeat(72)),'');assert.equal(h.context._newPasswordError('🙂'.repeat(18)),'');
  assert.equal(h.context._newPasswordError('abcdefgh!'),'');assert.notEqual(h.context._newPasswordError('🙂'.repeat(19)),'');
 });
 test(path+': invalid or expired reset stays an error and never tries a hidden login',async()=>{
  const h=auth(path);await h.requestCode();h.resetDraft();h.context.respond=async()=>response({detail:'Invalid or expired code'},400);
  await h.context.doForgotStep2();assert.equal(h.calls.requests.length,2);assert.ok(!h.calls.requests.some(x=>x.url.endsWith('/login')));
  assert.equal(h.fields.forgotSuccess.style.display,'none');assert.equal(h.fields.forgotError2.style.display,'block');
  assert.equal(h.fields.btnForgotReset.disabled,false);assert.equal(h.fields.forgotNewPass.value,'IsolatedRecovery39!');
 });
 test(path+': confirmed reset posts the real body, clears authentication and passwords, and shows existing success',async()=>{
  const h=auth(path);h.signedIn();h.context.showForgotForm();await h.requestCode();h.resetDraft();
  h.fields.loginPass.value='OldTyped39!';h.context.respond=async()=>response({message:'Пароль успешно изменён'});
  await h.context.doForgotStep2();
  assert.deepEqual(JSON.parse(h.calls.requests.at(-1).options.body),{email:'synthetic@example.test',code:'123456',new_password:'IsolatedRecovery39!'});
  assert.equal(h.context.token,null);assert.equal(h.context.user,null);assert.equal(h.context.currentUserId,null);
  assert.ok(h.calls.removed.includes('ch_user'));assert.equal(h.fields.forgotSuccess.style.display,'block');
  assert.equal(h.fields.loginEmail.value,'synthetic@example.test');
  for(const id of ['loginPass','forgotCode','forgotNewPass','forgotNewPass2'])assert.equal(h.fields[id].value,'');
  assert.equal(h.calls.stored.length,0);assert.ok(h.calls.resetInbox>0);assert.ok(h.calls.stopTg>0);
 });
 test(path+': reset deduplicates pending sends and never logs out a newer account on late success',async()=>{
  const h=auth(path);await h.requestCode();h.resetDraft();const held=deferred();h.context.respond=()=>held.promise;
  const pending=h.context.doForgotStep2();await h.context.doForgotStep2();assert.equal(h.calls.requests.length,2);
  h.context.user={userId:8,email:'other@example.test'};h.context.token='new-test-token';h.context.currentUserId=8;
  held.resolve(response({message:'Пароль успешно изменён'}));await pending;
  assert.equal(h.context.user.userId,8);assert.equal(h.context.token,'new-test-token');assert.equal(h.calls.removed.length,0);
 });
 test(path+': changed reset draft ignores a late validation error and allows another attempt',async()=>{
  const h=auth(path);await h.requestCode();h.resetDraft();const held=deferred();h.context.respond=()=>held.promise;
  const pending=h.context.doForgotStep2();h.fields.forgotCode.value='654321';
  held.resolve(response({detail:[{msg:'Old invalid code'}]},422));await pending;
  assert.equal(h.fields.forgotError2.style.display,'none');assert.equal(h.fields.forgotCode.value,'654321');assert.equal(h.fields.btnForgotReset.disabled,false);
 });
 test(path+': change password validates fields and keeps the old session when the server rejects it',async()=>{
  const h=auth(path);h.signedIn();h.fields.changeOldPass.value='OldTyped39!';h.fields.changeNewPass.value='IsolatedChange39!';h.fields.changeNewPass2.value='IsolatedChange39!';
  h.context.respond=async()=>response({detail:'Неверный текущий пароль'},400);
  await h.context.changePassword();assert.equal(h.calls.requests[0].url,'https://local.test/api/auth/change-password');
  assert.equal(h.calls.requests[0].options.headers.Authorization,'Bearer old-test-token');
  assert.deepEqual(JSON.parse(h.calls.requests[0].options.body),{old_password:'OldTyped39!',new_password:'IsolatedChange39!'});
  assert.equal(h.context.token,'old-test-token');assert.equal(h.fields.changePasswordError.style.display,'block');assert.equal(h.fields.btnChangePassword.disabled,false);
 });
 test(path+': confirmed password change clears the current session and opens the existing login UI',async()=>{
  const h=auth(path);h.signedIn();h.fields.changeOldPass.value='OldTyped39!';h.fields.changeNewPass.value='IsolatedChange39!';h.fields.changeNewPass2.value='IsolatedChange39!';
  h.context.respond=async()=>response({message:'Пароль успешно изменён'});await h.context.changePassword();
  assert.equal(h.context.user,null);assert.equal(h.context.token,null);assert.equal(h.fields.settingsOverlay.classList.contains('on'),false);
  assert.equal(h.fields.authOverlay.classList.contains('on'),true);assert.equal(h.fields.formLogin.style.display,'block');
  assert.equal(h.fields.loginEmail.value,'synthetic@example.test');assert.equal(h.calls.warnings.length,1);
  for(const id of ['changeOldPass','changeNewPass','changeNewPass2','loginPass'])assert.equal(h.fields[id].value,'');
  assert.equal(h.calls.stored.length,0);
 });
 test(path+': late password-change responses do not log out or report errors to a newer account',async()=>{
  for(const ok of [true,false]){
   const h=auth(path);h.signedIn();h.fields.changeOldPass.value='OldTyped39!';h.fields.changeNewPass.value='IsolatedChange39!';h.fields.changeNewPass2.value='IsolatedChange39!';
   const held=deferred();h.context.respond=()=>held.promise;const pending=h.context.changePassword();await h.context.changePassword();assert.equal(h.calls.requests.length,1);
   h.context.user={userId:8,email:'other@example.test'};h.context.token='new-test-token';
   held.resolve(response(ok?{message:'Changed'}:{detail:'Old failure'},ok?200:400));await pending;
   assert.equal(h.context.user.userId,8);assert.equal(h.context.token,'new-test-token');assert.equal(h.fields.changePasswordError.style.display,'none');
  }
 });
 test(path+': reopening password settings clears only the password fields and pending validation',()=>{
  const h=auth(path);h.fields.passwordChangeBlock.open=true;h.fields.changePasswordError.style.display='block';
  for(const id of ['changeOldPass','changeNewPass','changeNewPass2'])h.fields[id].value='Previously typed';
  h.context._resetPasswordChangeForm();
  assert.equal(h.fields.passwordChangeBlock.open,false);assert.equal(h.fields.changePasswordError.style.display,'none');
  assert.equal(h.fields.changeOldPass.value,'');assert.equal(h.fields.changeNewPass.value,'');assert.equal(h.fields.changeNewPass2.value,'');
 });
}
for(const prefix of ['', 'frontend/'])test(prefix+'actual recovery/change markup exposes the same safe controls and settings placement',()=>{
 const html=read(prefix+'index.html');
 for(const id of ['btnForgotSend','btnForgotReset','btnResendCode','resendCountdown','resendCooldownText','passwordChangeBlock','changeOldPass','changeNewPass','changeNewPass2','btnChangePassword','changePasswordError'])
  assert.equal((html.match(new RegExp('id="'+id+'"','g'))||[]).length,1,id);
 const change=html.indexOf('<details id="passwordChangeBlock"'),save=html.indexOf('onclick="saveSettings()"');
 assert.ok(change>html.indexOf('id="settingsOverlay"')&&change<save,'Keep the functional details inside settings before the existing actions');
 assert.match(html,/id="forgotCode"[^>]*inputmode="numeric"[^>]*pattern="\[0-9\]\{6\}"/);
 assert.match(html,/auth_recovery_notice">Если аккаунт существует/);
 assert.ok(!html.includes('onclick="doForgotStep1()">Отправить код повторно'));
});
for(const path of ['api.js','frontend/api.js'])test(path+': API recovery helpers preserve their exact endpoint body contract',async()=>{
 const calls=[],context={apiRequest:async(method,url,body)=>{calls.push({method,url,body});return{ok:true,data:{message:'Generic'}};}};
 vm.createContext(context);const code=read(path),start=code.indexOf('const CaucasAPI ='),end=code.indexOf('// ── Расшифровка JWT',start);
 vm.runInContext(code.slice(start,end)+';globalThis.client=CaucasAPI;',context);
 await context.client.forgotPassword('synthetic@example.test');await context.client.resetPassword('synthetic@example.test','123456','IsolatedRecovery39!');
 assert.deepEqual(JSON.parse(JSON.stringify(calls)),[
  {method:'POST',url:'/api/auth/forgot-password',body:{email:'synthetic@example.test'}},
  {method:'POST',url:'/api/auth/reset-password',body:{email:'synthetic@example.test',code:'123456',new_password:'IsolatedRecovery39!'}}
 ]);
});

for(const path of ['main.js','frontend/main.js'])test(path+': ordinary logout clears previously typed login, recovery and settings passwords',()=>{
 const h=auth(path);h.signedIn();
 for(const id of ['loginPass','regPass','forgotCode','forgotNewPass','forgotNewPass2','changeOldPass','changeNewPass','changeNewPass2','deletePasswordInput'])h.fields[id].value='Previously typed private data';
 h.context.doLogout();
 for(const id of ['loginPass','regPass','forgotCode','forgotNewPass','forgotNewPass2','changeOldPass','changeNewPass','changeNewPass2','deletePasswordInput'])assert.equal(h.fields[id].value,'',id);
 assert.equal(h.context.user,null);assert.equal(h.context.token,null);
});
