/* Real password UI and account-isolation regression on a disposable localhost fixture.
 * CARRIER_PROFILE_REPO_ROOT=/checkout node tests/browser/auth_recovery.cjs --spawn-server
 * No production accounts, provider messages, or non-loopback traffic are allowed.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {spawn} = require('node:child_process');
const BASE = new URL('http://127.0.0.1:8765');
const ROOT = path.resolve(process.env.CARRIER_PROFILE_REPO_ROOT || path.join(__dirname, '../..'));
const {chromium} = require(require.resolve('playwright', {paths: [ROOT, __dirname]}));
const ARTIFACTS = path.resolve(process.env.CARRIER_AUTH_ARTIFACTS || path.join(ROOT, 'artifacts/auth-recovery'));
const ORIGINAL = 'AuthBrowserOriginal84!';
const RECOVERED = 'AuthBrowserRecovered85!';
const CHANGED = 'AuthBrowserChanged86!';
const results = [];
const diagnostics = {productionApiAttempts: 0, blockedHosts: [], pages: [], mutations: []};
const blocked = new Set();
let browser, server, serverError;
fs.mkdirSync(ARTIFACTS, {recursive: true});
const delay = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));

function marker(headers) {
  return typeof headers.get === 'function'
    ? headers.get('x-carrier-test-only') : headers['x-carrier-test-only'];
}

async function ready() {
  const deadline = Date.now() + 60000;
  while (Date.now() < deadline) {
    if (serverError) throw serverError;
    if (server && server.exitCode !== null) throw Error('Local auth fixture exited before readiness');
    try {
      const response = await fetch(new URL('/__test__/ready', BASE), {signal: AbortSignal.timeout(1000)});
      const data = await response.json();
      assert.equal(marker(response.headers), '1');
      assert.equal(data.test_only, true);
      assert.equal(data.isolated_sqlite, true);
      assert.equal(data.actual_profile_routers, true);
      assert.equal(data.auth_test, true);
      assert.equal(data.notification_test, false);
      assert.equal(data.origin, BASE.origin);
      assert.equal(data.ready, true);
      const specResponse = await fetch(new URL('/openapi.json', BASE), {signal: AbortSignal.timeout(1000)});
      assert.equal(marker(specResponse.headers), '1');
      const spec = await specResponse.json();
      for (const endpoint of ['/api/auth/register', '/api/auth/login', '/api/auth/forgot-password',
        '/api/auth/reset-password', '/api/auth/change-password', '/api/loads/']) {
        assert.ok(spec.paths[endpoint]?.post, 'Actual auth/publication router required: ' + endpoint);
      }
      return;
    } catch {
      await delay(250);
    }
  }
  throw Error('No verified isolated auth fixture on 127.0.0.1:8765');
}

async function clickResponse(page, selector, endpoint, status) {
  const pending = page.waitForResponse(response =>
    response.url().split('?')[0] === new URL(endpoint, BASE).href &&
    response.request().method() === 'POST');
  await page.locator(selector).click();
  const response = await pending;
  assert.equal(marker(response.headers()), '1');
  assert.equal(response.status(), status, endpoint + ' returned unexpected HTTP status');
  return response.json();
}

async function localApi(page, endpoint, options = {}) {
  assert.equal(new URL(endpoint, BASE).origin, BASE.origin);
  const result = await page.evaluate(async ({origin, endpoint, options}) => {
    const token = options.token === undefined ? localStorage.getItem('ch_token') : options.token;
    const headers = {};
    if (token) headers.Authorization = 'Bearer ' + token;
    if (options.body !== undefined) headers['Content-Type'] = 'application/json';
    const response = await fetch(origin + endpoint, {
      method: options.method || 'GET', headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
    return {status: response.status, marker: response.headers.get('x-carrier-test-only'),
      data: await response.json().catch(() => null)};
  }, {origin: BASE.origin, endpoint, options});
  assert.equal(result.marker, '1');
  return result;
}

async function mailboxCode(recipient) {
  assert.ok(recipient.endsWith('@example.test'), 'Synthetic mailbox required');
  const target = new URL('/__test__/emails', BASE);
  target.searchParams.set('recipient', recipient);
  const deadline = Date.now() + 10000;
  while (Date.now() < deadline) {
    const response = await fetch(target, {
      headers: {'X-Carrier-Test-Only': '1'}, signal: AbortSignal.timeout(1000),
    });
    assert.equal(marker(response.headers), '1');
    assert.equal(response.status, 200);
    const data = await response.json();
    assert.equal(data.test_only, true);
    assert.ok(Array.isArray(data.emails));
    const match = data.emails.slice().reverse().find(email =>
      email.to === recipient && typeof email.html === 'string' &&
      /(?<![0-9])[0-9]{6}(?![0-9])/.test(email.html));
    if (match) {
      const code = match.html.match(/(?<![0-9])[0-9]{6}(?![0-9])/)[0];
      assert.equal(code.length, 6);
      return code;
    }
    await delay(100);
  }
  throw Error('No recovery code in the real local email body');
}

async function loggedOut(page) {
  await page.waitForFunction(() => localStorage.getItem('ch_token') === null &&
    localStorage.getItem('ch_user') === null);
  await page.locator('#userAvatar').waitFor({state: 'hidden'});
  assert.equal(await page.locator('#loginPass').inputValue(), '');
}

async function openLogin(page) {
  if (await page.locator('#authOverlay').isVisible()) {
    await page.locator('#tabLogin').click();
  } else {
    await page.locator('#btnLogin').click();
  }
  await page.locator('#formLogin').waitFor({state: 'visible'});
}

async function login(page, email, password, status = 200) {
  await openLogin(page);
  await page.locator('#loginEmail').fill(email);
  await page.locator('#loginPass').fill(password);
  const data = await clickResponse(page, '#formLogin button[onclick="doLogin()"]', '/api/auth/login', status);
  if (status !== 200) {
    await page.locator('#loginErrorMsg').waitFor({state: 'visible'});
    assert.equal(await page.evaluate(() => localStorage.getItem('ch_token')), null);
    return data;
  }
  await page.locator('#authOverlay').waitFor({state: 'hidden'});
  await page.locator('#userAvatar').waitFor({state: 'visible'});
  await page.waitForFunction(expected => {
    const user = JSON.parse(localStorage.getItem('ch_user') || '{}');
    return Number(user.userId) === Number(expected);
  }, data.user_id);
  const profile = await localApi(page, '/api/users/me');
  assert.equal(profile.status, 200);
  assert.equal(profile.data.email.toLowerCase(), email.toLowerCase());
  return data;
}

async function logout(page) {
  await page.locator('#userAvatar').click();
  await page.locator('#profileOverlay button[onclick="doLogout()"]').click();
  await loggedOut(page);
}

async function register(page, configuration, index, suffix) {
  if (await page.locator('#authOverlay').isVisible()) {
    await page.locator('#tabRegister').click();
  } else {
    await page.locator('#btnReg').click();
  }
  await page.locator('#rtShipperCo').click();
  const account = {
    email: 'auth.' + configuration.name + '.' + suffix + '.' + Date.now() + '@example.test',
    name: 'Isolated auth ' + configuration.name + ' account ' + suffix,
  };
  await page.locator('#regName').fill(account.name);
  await page.locator('#regPhone').fill('+99559993' + String(index).padStart(4, '0'));
  await page.locator('#regEmail').fill(account.email);
  await page.locator('#regInn').fill('404123456');
  await page.locator('#regOrgType').selectOption('ООО');
  await page.locator('#regCity').fill('Тбилиси');
  await page.locator('#regPass').fill(ORIGINAL);
  assert.equal(new URL(page.url()).origin, BASE.origin);
  // Acceptance applies only to this disposable localhost copy and synthetic account.
  await page.locator('#regAgree').check();
  const result = await clickResponse(page, '#formRegister button[onclick="doRegister()"]', '/api/auth/register', 200);
  await page.locator('#authOverlay').waitFor({state: 'hidden'});
  await page.locator('#userAvatar').waitFor({state: 'visible'});
  const profile = await localApi(page, '/api/users/me');
  assert.equal(profile.status, 200);
  assert.equal(profile.data.id, result.user_id);
  assert.equal(profile.data.email, account.email);
  return {...account, id: result.user_id};
}

async function section(page, configuration, name) {
  await page.locator((configuration.mobile ? '.bitem' : '.nav-tab') +
    '[onclick*="showSection"][onclick*="' + name + '"]').first().click();
  await page.locator('#sec-' + name + '.active').waitFor({state: 'visible'});
}

async function cabinetLoads(page, configuration) {
  await section(page, configuration, 'orders');
  await page.locator('.cab-tab[onclick*="switchCabTab"][onclick*="loads"]').first().click();
  await page.locator('#cabTab-loads').waitFor({state: 'visible'});
}

function editMarker(loadId) {
  return '#myLoadsList button[onclick="editMyLoad(' + loadId + ')"]';
}

async function publishOwnCargo(page, configuration) {
  await page.locator(configuration.mobile ? '.bitem-post' : '.load-post-btn').click();
  await page.locator('#postOverlay').waitFor({state: 'visible'});
  await page.locator('#pFromAddr').fill('Тбилиси');
  await page.locator('#pToAddr').fill('Батуми');
  await page.locator('#pWeight').fill('3000');
  await page.locator('#pPrice').fill('500');
  await page.locator('#pTruck').selectOption('tent');
  await page.locator('#pDate').fill(new Date(Date.now() + 86400000).toISOString().slice(0, 10));
  await page.locator('#pDate2').fill(new Date(Date.now() + 3 * 86400000).toISOString().slice(0, 10));
  await page.locator('#pDesc').fill('Synthetic auth account-isolation cargo');
  const data = await clickResponse(page, '#postOverlay .btn-primary', '/api/loads/', 200);
  assert.ok(data.id);
  await page.locator('#postOverlay').waitFor({state: 'hidden'});
  await cabinetLoads(page, configuration);
  await page.locator(editMarker(data.id)).waitFor({state: 'visible'});
  return data.id;
}

async function openSettings(page) {
  await page.locator('#userAvatar').click();
  await page.locator('#profileOverlay button[onclick="openSettings()"]').click();
  await page.locator('#settingsOverlay').waitFor({state: 'visible'});
}

async function screenshot(page, name) {
  await page.screenshot({path: path.join(ARTIFACTS, name + '.png'), fullPage: true});
}

async function run(configuration, index) {
  const context = await browser.newContext({
    viewport: {width: configuration.width, height: configuration.height},
    isMobile: configuration.mobile, hasTouch: configuration.mobile,
    serviceWorkers: 'block', locale: 'ru-RU',
  });
  await context.addInitScript(() => {
    localStorage.setItem('ch_lang', 'ru');
    localStorage.setItem('pwa_dismissed', '1');
  });
  await context.route('**/*', route => {
    const request = route.request(), url = new URL(request.url());
    if (url.origin === BASE.origin) {
      if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method())) {
        diagnostics.mutations.push({viewport: configuration.name, method: request.method(), path: url.pathname});
      }
      return route.continue();
    }
    blocked.add(url.hostname || url.protocol);
    if (url.hostname === 'api-production-f3ea.up.railway.app') diagnostics.productionApiAttempts++;
    return route.abort('blockedbyclient');
  });
  const page = await context.newPage();
  page.setDefaultTimeout(15000);
  const log = {viewport: configuration.name, pageErrors: [], dialogs: []};
  diagnostics.pages.push(log);
  page.on('pageerror', error => log.pageErrors.push(error.message));
  page.on('dialog', async dialog => {
    log.dialogs.push({type: dialog.type(), message: dialog.message()});
    await dialog.dismiss();
  });
  let releaseHeldResponse = () => {};
  try {
    await page.goto(BASE.href, {waitUntil: 'domcontentloaded'});
    assert.equal(new URL(page.url()).origin, BASE.origin);
    const accountA = await register(page, configuration, index * 2 + 1, 'A');
    const loadId = await publishOwnCargo(page, configuration);
    const originalToken = await page.evaluate(() => localStorage.getItem('ch_token'));
    assert.ok(originalToken);
    await logout(page);
    assert.equal(await page.locator(editMarker(loadId)).count(), 0, 'Logout must clear private cabinet HTML');

    await openLogin(page);
    await page.locator('#formLogin a[onclick="showForgotForm()"]').click();
    await page.locator('#forgotEmail').fill(accountA.email);
    const notice = await clickResponse(page, '#btnForgotSend', '/api/auth/forgot-password', 200);
    assert.equal(typeof notice.message, 'string');
    await page.locator('#forgotStep2').waitFor({state: 'visible'});
    assert.equal(await page.locator('#forgotCode').inputValue(), '', 'The UI must never invent or prefill a recovery code');
    assert.equal(await page.locator('#btnResendCode').isDisabled(), true);
    const code = await mailboxCode(accountA.email);
    const wrongCode = code === '000000' ? '999999' : '000000';
    await page.locator('#forgotCode').fill(wrongCode);
    await page.locator('#forgotNewPass').fill(RECOVERED);
    await page.locator('#forgotNewPass2').fill(RECOVERED);
    await clickResponse(page, '#btnForgotReset', '/api/auth/reset-password', 400);
    await page.locator('#forgotError2').waitFor({state: 'visible'});
    await page.locator('#forgotStep2').waitFor({state: 'visible'});
    assert.equal(await page.evaluate(() => localStorage.getItem('ch_token')), null);
    await screenshot(page, configuration.name + '-wrong-recovery-code');

    await page.locator('#forgotCode').fill(code);
    await clickResponse(page, '#btnForgotReset', '/api/auth/reset-password', 200);
    await page.locator('#forgotSuccess').waitFor({state: 'visible'});
    await loggedOut(page);
    assert.equal(await page.locator('#loginEmail').inputValue(), accountA.email);
    for (const field of ['forgotCode', 'forgotNewPass', 'forgotNewPass2']) {
      assert.equal(await page.locator('#' + field).inputValue(), '');
    }
    assert.equal((await localApi(page, '/api/users/me', {token: originalToken})).status, 401);
    assert.equal((await localApi(page, '/api/auth/reset-password', {
      method: 'POST', token: null,
      body: {email: accountA.email, code, new_password: CHANGED},
    })).status, 400, 'A consumed code must never reset a second time');
    await screenshot(page, configuration.name + '-recovery-success-logged-out');
    await login(page, accountA.email, ORIGINAL, 401);
    await login(page, accountA.email, RECOVERED);
    const recoveredToken = await page.evaluate(() => localStorage.getItem('ch_token'));
    await cabinetLoads(page, configuration);
    await page.locator(editMarker(loadId)).waitFor({state: 'visible'});

    await openSettings(page);
    await page.locator('#passwordChangeBlock summary').click();
    await page.locator('#changeOldPass').fill('WrongExistingPassword!');
    await page.locator('#changeNewPass').fill(CHANGED);
    await page.locator('#changeNewPass2').fill(CHANGED);
    await clickResponse(page, '#btnChangePassword', '/api/auth/change-password', 400);
    await page.locator('#changePasswordError').waitFor({state: 'visible'});
    assert.equal(await page.evaluate(() => localStorage.getItem('ch_token')), recoveredToken);
    await page.locator('#changeOldPass').fill(RECOVERED);
    await clickResponse(page, '#btnChangePassword', '/api/auth/change-password', 200);
    await page.locator('#settingsOverlay').waitFor({state: 'hidden'});
    await page.locator('#formLogin').waitFor({state: 'visible'});
    await loggedOut(page);
    assert.equal((await localApi(page, '/api/users/me', {token: recoveredToken})).status, 401);
    await screenshot(page, configuration.name + '-change-success-logged-out');
    await login(page, accountA.email, RECOVERED, 401);
    await login(page, accountA.email, CHANGED);
    const currentAToken = await page.evaluate(() => localStorage.getItem('ch_token'));
    await cabinetLoads(page, configuration);
    await page.locator(editMarker(loadId)).waitFor({state: 'visible'});

    // Hold a genuine authorized A response, then deliver it after the same tab
    // switches to B. The response body is fetched from the real local router.
    let heldResolve;
    const held = new Promise(resolve => { heldResolve = resolve; });
    const gate = new Promise(resolve => { releaseHeldResponse = resolve; });
    let intercepted = false;
    const myLoadsUrl = new URL('/api/loads/my/loads', BASE).href;
    await page.route(myLoadsUrl, async route => {
      if (!intercepted && route.request().headers().authorization === 'Bearer ' + currentAToken) {
        intercepted = true;
        const response = await route.fetch();
        assert.equal(response.status(), 200);
        heldResolve();
        await gate;
        await route.fulfill({response});
      } else {
        await route.continue();
      }
    });
    await section(page, configuration, 'loads');
    await cabinetLoads(page, configuration);
    await Promise.race([held, delay(10000).then(() => { throw Error('No actual A cabinet response to hold'); })]);
    await logout(page);
    assert.equal(await page.locator(editMarker(loadId)).count(), 0);
    const accountB = await register(page, configuration, index * 2 + 2, 'B');
    const delayed = page.waitForResponse(response =>
      response.url().split('?')[0] === myLoadsUrl &&
      response.request().headers().authorization === 'Bearer ' + currentAToken);
    releaseHeldResponse();
    await (await delayed).finished();
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    await cabinetLoads(page, configuration);
    await page.locator('#myLoadsList .cab-empty').waitFor({state: 'visible'});
    assert.equal(await page.locator(editMarker(loadId)).count(), 0, 'Delayed A data must not enter B cabinet');
    assert.equal(await page.locator('#myLoadsList .cab-load-card').count(), 0);
    assert.ok(!(await page.locator('#cabinetPanel').innerText()).includes(accountA.email));
    const mineB = await localApi(page, '/api/loads/my/loads');
    assert.equal(mineB.status, 200);
    assert.deepEqual(mineB.data.loads, []);
    await openSettings(page);
    assert.equal(await page.locator('#sEmail').inputValue(), accountB.email);
    assert.equal(await page.locator('#sName').inputValue(), accountB.name);
    await page.locator('#settingsOverlay .close-btn').click();
    await screenshot(page, configuration.name + '-account-B-isolated');

    assert.deepEqual(log.pageErrors, [], 'Browser JS errors must be fixed, not hidden');
    assert.deepEqual(log.dialogs, [], 'Unexpected alert/confirm during password flow');
    assert.equal(diagnostics.productionApiAttempts, 0, 'All production API origins must be rewritten');
    results.push({viewport: configuration.name, status: 'passed', recovery: true, wrongCode: true,
      singleUse: true, oldTokensRevoked: true, change: true, freshLogin: true, accountSwitch: true,
      delayedCabinetResponseIsolated: true});
    console.log(configuration.name + ': recovery, password change, session revocation and cabinet isolation passed');
  } catch (error) {
    await screenshot(page, configuration.name + '-failure').catch(() => {});
    results.push({viewport: configuration.name, status: 'failed', error: error.message});
    throw error;
  } finally {
    releaseHeldResponse();
    await context.close();
  }
}

(async () => {
  try {
    if (process.argv.includes('--spawn-server')) {
      const log = fs.createWriteStream(path.join(ARTIFACTS, 'server.log'));
      server = spawn(process.env.PYTHON || 'python', [path.join(ROOT, 'tests/browser/carrier_profile_server.py')], {
        cwd: ROOT, windowsHide: true,
        env: {...process.env, PYTHONUNBUFFERED: '1', CARRIER_BROWSER_AUTH: '1',
          CARRIER_BROWSER_PUBLICATION: '1', CARRIER_BROWSER_NOTIFICATIONS: '0'},
        stdio: ['ignore', 'pipe', 'pipe'],
      });
      server.stdout.pipe(log, {end: false});
      server.stderr.pipe(log, {end: false});
      server.once('error', error => { serverError = error; });
      server.once('close', () => log.end());
    }
    await ready();
    browser = await chromium.launch({
      headless: true,
      args: ['--disable-background-networking', '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1'],
    });
    const configurations = [
      {name: 'desktop', width: 1280, height: 900, mobile: false},
      {name: 'mobile', width: 390, height: 844, mobile: true},
    ];
    for (const [index, configuration] of configurations.entries()) {
      try { await run(configuration, index); }
      catch (error) { console.error(error.stack || error.message); process.exitCode = 1; }
    }
    assert.equal(diagnostics.productionApiAttempts, 0);
  } catch (error) {
    console.error(error.stack || error.message);
    process.exitCode = 1;
  } finally {
    if (browser) await browser.close().catch(() => {});
    if (server && server.exitCode === null) server.kill('SIGTERM');
    diagnostics.blockedHosts = [...blocked].sort();
    fs.writeFileSync(path.join(ARTIFACTS, 'results.json'), JSON.stringify({results, diagnostics}, null, 2));
  }
})();
