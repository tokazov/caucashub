/* Isolated, real-browser carrier profile regression. Never run against production. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { chromium } = require('playwright');

const REPOSITORY = path.resolve(process.env.CARRIER_PROFILE_REPO_ROOT || path.join(__dirname, '../..'));
const BASE = new URL('http://127.0.0.1:8765');
const ARTIFACTS = path.resolve(process.env.CARRIER_PROFILE_ARTIFACTS || path.join(REPOSITORY, 'artifacts/carrier-profile'));
fs.mkdirSync(ARTIFACTS, { recursive: true });
let server;
let serverError;
let browser;
const results = [];
const diagnostics = { blockedHosts: [], productionApiAttempts: 0, pages: [] };
const blockedHosts = new Set();
const sleep = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));

async function waitForFixture() {
  const deadline = Date.now() + 60000;
  while (Date.now() < deadline) {
    if (serverError) throw serverError;
    if (server && server.exitCode !== null) throw new Error('Local test server exited before readiness');
    try {
      const response = await fetch(new URL('/__test__/ready', BASE), { signal: AbortSignal.timeout(1000) });
      const data = await response.json();
      assert.equal(response.headers.get('x-carrier-test-only'), '1');
      assert.equal(data.test_only, true);
      assert.equal(data.isolated_sqlite, true);
      assert.equal(data.actual_profile_routers, true);
      assert.equal(data.origin, BASE.origin);
      assert.equal(data.ready, true);
      return;
    } catch {
      await sleep(250);
    }
  }
  throw new Error('No verified isolated carrier-profile fixture on 127.0.0.1:8765');
}

function assertProfile(profile, type, tonnes) {
  assert.equal(profile.truck_type, type);
  assert.equal(profile.tonnage, tonnes);
}

async function realResponse(page, selector, endpoint, method) {
  const responsePromise = page.waitForResponse(response =>
    response.url().split('?')[0] === new URL(endpoint, BASE).href &&
    response.request().method() === method);
  await page.locator(selector).click();
  const response = await responsePromise;
  const data = await response.json();
  assert.equal(response.status(), 200, endpoint + ' returned ' + response.status() + ': ' + JSON.stringify(data));
  assert.equal(response.headers()['x-carrier-test-only'], '1');
  return data;
}

async function backendProfile(page) {
  const result = await page.evaluate(async origin => {
    const token = localStorage.getItem('ch_token');
    const response = await fetch(origin + '/api/users/me', {
      headers: { Authorization: 'Bearer ' + token }
    });
    return { status: response.status, data: await response.json() };
  }, BASE.origin);
  assert.equal(result.status, 200, 'Real profile endpoint must succeed');
  return result.data;
}

async function waitForCachedProfile(page, profile) {
  await page.waitForFunction(expected => {
    const user = JSON.parse(localStorage.getItem('ch_user') || '{}');
    return Number(user.userId) === Number(expected.id) &&
      user.truckType === (expected.truck_type ?? '') &&
      (expected.tonnage === null ? user.tonnage === '' : Number(user.tonnage) === expected.tonnage);
  }, profile);
}

async function openSettings(page) {
  await page.locator('#userAvatar').waitFor({ state: 'visible' });
  await page.locator('#userAvatar').click();
  await page.locator('#profileOverlay button[onclick="openSettings()"]').click();
  await page.locator('#settingsOverlay').waitFor({ state: 'visible' });
}

async function checkSettings(page, type, tonnes) {
  assert.equal(await page.locator('#sTruckType').inputValue(), type ?? '');
  assert.equal(await page.locator('#sTonnage').inputValue(), tonnes === null ? '' : String(tonnes));
}

async function closeSettings(page) {
  await page.locator('#settingsOverlay button.close-btn').click();
  await page.locator('#settingsOverlay').waitFor({ state: 'hidden' });
}

async function logout(page) {
  await page.locator('#userAvatar').click();
  await page.locator('#profileOverlay button[onclick="doLogout()"]').click();
  await page.locator('#btnLogin').waitFor({ state: 'visible' });
  assert.equal(await page.evaluate(() => localStorage.getItem('ch_token')), null);
  assert.equal(await page.evaluate(() => localStorage.getItem('ch_user')), null);
}

async function login(page, email, password) {
  await page.locator('#btnLogin').click();
  await page.locator('#loginEmail').fill(email);
  await page.locator('#loginPass').fill(password);
  const hydrated = page.waitForResponse(response =>
    response.url().split('?')[0] === new URL('/api/users/me', BASE).href &&
    response.request().method() === 'GET');
  await realResponse(page, '#formLogin button[onclick="doLogin()"]', '/api/auth/login', 'POST');
  const profile = await hydrated;
  assert.equal(profile.status(), 200);
  await waitForCachedProfile(page, await profile.json());
  await page.locator('#authOverlay').waitFor({ state: 'hidden' });
  await page.locator('#userAvatar').waitFor({ state: 'visible' });
}

async function saveSettings(page, type, tonnes) {
  await page.locator('#sTruckType').selectOption(type ?? '');
  await page.locator('#sTonnage').fill(tonnes === null ? '' : String(tonnes));
  const profile = await realResponse(page, '#settingsOverlay button[onclick="saveSettings()"]', '/api/users/me', 'PUT');
  assertProfile(profile, type, tonnes);
  await page.locator('#settingsOverlay').waitFor({ state: 'hidden' });
  assertProfile(await backendProfile(page), type, tonnes);
}

async function screenshot(page, label) {
  await page.screenshot({ path: path.join(ARTIFACTS, label + '.png'), fullPage: true });
}

async function journey(configuration, index) {
  const context = await browser.newContext({
    viewport: { width: configuration.width, height: configuration.height },
    isMobile: configuration.mobile,
    hasTouch: configuration.mobile,
    serviceWorkers: 'block',
    locale: 'ru-RU'
  });
  // UI preferences only: auth/profile state is created through the real forms.
  await context.addInitScript(() => {
    localStorage.setItem('ch_lang', 'ru');
    localStorage.setItem('pwa_dismissed', '1');
  });
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin === BASE.origin) return route.continue();
    blockedHosts.add(url.hostname || url.protocol);
    if (url.hostname === 'api-production-f3ea.up.railway.app') diagnostics.productionApiAttempts++;
    return route.abort('blockedbyclient');
  });
  const page = await context.newPage();
  page.setDefaultTimeout(15000);
  const pageLog = { viewport: configuration.name, pageErrors: [], dialogs: [] };
  diagnostics.pages.push(pageLog);
  page.on('pageerror', error => pageLog.pageErrors.push(error.message));
  page.on('dialog', async dialog => {
    pageLog.dialogs.push({ type: dialog.type(), message: dialog.message() });
    await dialog.dismiss();
  });
  const email = 'carrier.' + configuration.name + '.' + Date.now() + '@example.test';
  const password = 'CarrierBrowser37!';
  try {
    await page.goto(BASE.href, { waitUntil: 'domcontentloaded' });
    assert.equal(new URL(page.url()).origin, BASE.origin);
    await page.locator('#btnReg').click();
    await page.locator('#rtCarrier').click();
    await page.locator('#regName').fill('Isolated carrier ' + configuration.name);
    await page.locator('#regPhone').fill('+99559991000' + index);
    await page.locator('#regEmail').fill(email);
    await page.locator('#regTruckType').selectOption('ref');
    await page.locator('#regTonnage').fill('3.5');
    await page.locator('#regPass').fill(password);
    // This is a disposable localhost copy with synthetic data, never real Terms.
    assert.equal(new URL(page.url()).origin, BASE.origin);
    await page.locator('#regAgree').check();
    const registered = await realResponse(page, '#formRegister button[onclick="doRegister()"]', '/api/auth/register', 'POST');
    assertProfile(registered, 'ref', 3.5);
    await page.locator('#authOverlay').waitFor({ state: 'hidden' });
    assertProfile(await backendProfile(page), 'ref', 3.5);
    await openSettings(page);
    await checkSettings(page, 'ref', 3.5);
    await screenshot(page, configuration.name + '-registered');

    await saveSettings(page, 'tent', 12.5);
    await openSettings(page);
    await checkSettings(page, 'tent', 12.5);
    await screenshot(page, configuration.name + '-updated');
    await closeSettings(page);

    const restored = page.waitForResponse(response =>
      response.url().split('?')[0] === new URL('/api/users/me', BASE).href &&
      response.request().method() === 'GET');
    await page.reload({ waitUntil: 'domcontentloaded' });
    const restoredResponse = await restored;
    assert.equal(restoredResponse.status(), 200);
    await waitForCachedProfile(page, await restoredResponse.json());
    await openSettings(page);
    await checkSettings(page, 'tent', 12.5);
    await screenshot(page, configuration.name + '-reloaded');
    await closeSettings(page);

    await logout(page);
    await login(page, email, password);
    await openSettings(page);
    await checkSettings(page, 'tent', 12.5);
    await screenshot(page, configuration.name + '-new-login');
    await saveSettings(page, null, null);
    await openSettings(page);
    await checkSettings(page, null, null);
    await screenshot(page, configuration.name + '-cleared');
    await closeSettings(page);

    await logout(page);
    await login(page, email, password);
    await openSettings(page);
    await checkSettings(page, null, null);
    assertProfile(await backendProfile(page), null, null);
    await screenshot(page, configuration.name + '-cleared-new-login');
    assert.equal(diagnostics.productionApiAttempts, 0, 'All production API origins must be rewritten in the temporary copy');
    assert.deepEqual(pageLog.dialogs, [], 'Unexpected UI alert/confirm');
    assert.deepEqual(pageLog.pageErrors, [], 'Browser JavaScript errors must be fixed, not hidden by this fixture');
    results.push({ viewport: configuration.name, width: configuration.width, status: 'passed' });
    console.log(configuration.name + ': registration, update, reload, new login and clearing passed');
  } catch (error) {
    await screenshot(page, configuration.name + '-failure').catch(() => {});
    results.push({ viewport: configuration.name, width: configuration.width, status: 'failed', error: error.message });
    throw error;
  } finally {
    await context.close();
  }
}

(async () => {
  try {
    if (process.argv.includes('--spawn-server')) {
      const log = fs.createWriteStream(path.join(ARTIFACTS, 'server.log'));
      server = spawn(process.env.PYTHON || 'python', [path.join(REPOSITORY, 'tests/browser/carrier_profile_server.py')], {
        cwd: REPOSITORY,
        env: { ...process.env, PYTHONUNBUFFERED: '1' },
        stdio: ['ignore', 'pipe', 'pipe']
      });
      server.stdout.pipe(log, { end: false });
      server.stderr.pipe(log, { end: false });
      server.once('error', error => { serverError = error; });
      server.once('close', () => log.end());
    }
    await waitForFixture();
    browser = await chromium.launch({
      headless: true,
      args: ['--disable-background-networking', '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1']
    });
    const configurations = [
      { name: 'desktop', width: 1280, height: 900, mobile: false },
      { name: 'mobile', width: 390, height: 844, mobile: true }
    ];
    for (let index = 0; index < configurations.length; index++) {
      try {
        await journey(configurations[index], index + 1);
      } catch (error) {
        console.error(configurations[index].name + ': ' + (error.stack || error.message));
        process.exitCode = 1;
      }
    }
  } catch (error) {
    console.error(error.stack || error.message);
    process.exitCode = 1;
  } finally {
    if (browser) await browser.close().catch(() => {});
    if (server && server.exitCode === null) server.kill('SIGTERM');
    diagnostics.blockedHosts = [...blockedHosts].sort();
    fs.writeFileSync(path.join(ARTIFACTS, 'results.json'), JSON.stringify({ results, diagnostics }, null, 2));
  }
})();
