/* Real UI payment-sandbox regression against a separately started disposable fixture.
 * python -m scripts.payment_sandbox --enable-sandbox --port 8878
 * node tests/browser/payment_sandbox.cjs
 * Never uses production accounts, a gateway, a signing-key injection, or real money.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ROOT = path.resolve(__dirname, '../..');
const { chromium } = require(require.resolve('playwright', { paths: [ROOT, __dirname] }));
const BASE = new URL('http://127.0.0.1:8878');
const ARTIFACTS = path.join(ROOT, 'artifacts/payment-sandbox');
const DAY = 86400000;
const checks = [];
const diagnostics = { blockedRequests: [], pageErrors: [], consoleErrors: [], websocketAttempts: [] };
let browser;
let page;
fs.mkdirSync(ARTIFACTS, { recursive: true });

const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function verifyReady() {
  const deadline = Date.now() + 60000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(new URL('/health', BASE), {
        signal: AbortSignal.timeout(1500), redirect: 'error',
      });
      const result = await response.json();
      assert.equal(response.status, 200);
      assert.equal(result.sandbox, true);
      assert.equal(result.enabled, true);
      assert.equal(result.status, 'ok');
      assert.equal(result.project, 'caucashub');
      return;
    } catch {
      await delay(250);
    }
  }
  throw Error('No verified, enabled CaucasHub sandbox at 127.0.0.1:8878');
}

function matches(response, endpoint, method) {
  return response.url() === new URL(endpoint, BASE).href && response.request().method() === method;
}
async function idle() {
  await page.waitForFunction(() => document.body.dataset.busy !== 'true');
}
async function mutate(action, endpoint, expectedStatus = 200, expectState = true) {
  const pending = page.waitForResponse(response => matches(response, endpoint, 'POST'));
  const pendingState = expectState ? page.waitForResponse(response =>
    matches(response, '/api/state', 'GET') && response.status() === 200) : null;
  const combined = Promise.all(pendingState ? [pending, pendingState] : [pending]);
  await action();
  const [response, stateResponse] = await combined;
  const result = await response.json();
  assert.equal(response.status(), expectedStatus,
    endpoint + ': expected ' + expectedStatus + ', received ' + response.status() + ' ' + JSON.stringify(result));
  assert.equal(response.headers()['cache-control'], 'no-store');
  const state = stateResponse ? await stateResponse.json() : null;
  if (state) {
    assert.equal(state.sandbox, true);
    assert.equal(state.project, 'caucashub');
  }
  await idle();
  return { result, state };
}
async function refresh() {
  const pending = page.waitForResponse(response =>
    matches(response, '/api/state', 'GET') && response.status() === 200);
  await page.locator('#refresh-button').click();
  const state = await (await pending).json();
  await idle();
  return state;
}
async function create(productCode, targetId) {
  await page.locator('#product-select').selectOption(productCode);
  if (targetId) await page.locator('#target-select').selectOption(targetId);
  const { result: order, state } = await mutate(
    () => page.locator('#create-button').click(), '/api/orders');
  assert.equal(order.sandbox, true);
  assert.equal(order.project, 'caucashub');
  assert.equal(order.product_code, productCode);
  assert.equal(order.status, 'pending');
  assert.ok(state.orders.some(item => item.id === order.id));
  assert.equal(await page.locator('#order-id').innerText(), order.id);
  assert.equal(await page.locator('#current-order').isVisible(), true);
  return { order, state };
}
async function selectOrder(orderId) {
  await page.locator('#orders-body button[data-order-id="' + orderId + '"]').click();
  assert.equal(await page.locator('#order-id').innerText(), orderId);
}
async function simulate(orderId, outcome, status = 200) {
  assert.equal(await page.locator('#order-id').innerText(), orderId);
  return mutate(
    () => page.locator('#simulation-actions button[data-outcome="' + outcome + '"]').click(),
    '/api/orders/' + encodeURIComponent(orderId) + '/simulate', status, status === 200);
}
function assertPeriod(grant, milliseconds) {
  assert.ok(grant);
  assert.equal(Date.parse(grant.ends_at) - Date.parse(grant.starts_at), milliseconds);
}
async function screenshot(name) {
  await idle();
  await page.evaluate(() => window.scrollTo({top: 0, left: 0, behavior: 'instant'}));
  await page.waitForFunction(() => window.scrollY === 0);
  await page.screenshot({ path: path.join(ARTIFACTS, name), fullPage: true });
}

(async () => {
  await verifyReady();
  browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ baseURL: BASE.href, viewport: { width: 1440, height: 1000 } });
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== BASE.origin) {
      diagnostics.blockedRequests.push(url.href);
      await route.abort('blockedbyclient');
      return;
    }
    await route.continue();
  });
  page = await context.newPage();
  page.setDefaultTimeout(15000);
  page.on('pageerror', error => diagnostics.pageErrors.push(error.message));
  page.on('console', message => {
    if (message.type() === 'error') diagnostics.consoleErrors.push(message.text());
  });
  page.on('websocket', socket => diagnostics.websocketAttempts.push(socket.url()));

  const initialState = page.waitForResponse(response => matches(response, '/api/state', 'GET'));
  const document = await page.goto(BASE.href, { waitUntil: 'domcontentloaded' });
  assert.equal(document.status(), 200);
  assert.match(document.headers()['content-security-policy'], /default-src 'none'/);
  assert.equal((await initialState).status(), 401, 'UI must not silently enter a demo account');
  await idle();
  assert.equal(await page.locator('#start-session-button').isVisible(), true);
  assert.equal(await page.locator('#create-button').isDisabled(), true);
  assert.match(await page.locator('.test-banner').innerText(), /реальные деньги не списываются/);
  checks.push('explicit demo entry; disabled checkout before session');

  await page.locator('#customer-select').selectOption('alice');
  const { state: alice } = await mutate(
    () => page.locator('#start-session-button').click(), '/api/session');
  assert.equal(alice.customer.id, 'alice');
  assert.equal(alice.orders.length, 0, 'A fresh disposable fixture is required');
  assert.equal(alice.grants.length, 0);
  assert.equal(await page.locator('#product-select option[value="business"]').isDisabled(), true);
  assert.equal(await page.locator('#target-select option[value="expired-load"]').count(), 0);
  checks.push('Alice session and server-owned catalogue; Business and expired target unavailable');

  const { order: first } = await create('pro');
  assert.equal(first.customer_id, 'alice');
  assert.equal(first.amount_tetri, 4900);
  assert.equal(first.currency, 'GEL');
  const firstPayment = await simulate(first.id, 'paid');
  assert.equal(firstPayment.result.status, 'paid');
  assert.equal(firstPayment.result.fulfillment_status, 'granted');
  assert.equal(firstPayment.state.grants.length, 1);
  const firstGrant = firstPayment.state.grants[0];
  assert.equal(firstGrant.active, true);
  assertPeriod(firstGrant, 30 * DAY);
  checks.push('Pro test payment grants an actual 30-day period');

  const replay = await simulate(first.id, 'paid');
  assert.equal(replay.state.grants.length, 1);
  assert.equal(replay.state.grants[0].starts_at, firstGrant.starts_at);
  assert.equal(replay.state.grants[0].ends_at, firstGrant.ends_at);
  checks.push('repeated confirmation neither duplicates nor extends a grant');

  const { order: renewal } = await create('pro');
  assert.notEqual(renewal.id, first.id, 'Deliberate second checkout needs a new order');
  const renewalPayment = await simulate(renewal.id, 'paid');
  assert.equal(renewalPayment.state.grants.length, 2);
  const renewalGrant = renewalPayment.state.grants.find(grant => grant.order_id === renewal.id);
  assert.equal(renewalGrant.starts_at, firstGrant.ends_at);
  assert.equal(renewalGrant.active, false);
  assertPeriod(renewalGrant, 30 * DAY);
  checks.push('early renewal creates a different order and the next 30-day period');

  await selectOrder(first.id);
  const rejectedRefund = await simulate(first.id, 'refunded', 409);
  assert.equal(rejectedRefund.result.detail.code, 'refund_latest_only');
  assert.equal(await page.locator('#notice').getAttribute('role'), 'alert');
  const unchanged = await refresh();
  assert.equal(unchanged.grants.filter(grant => !grant.revoked).length, 2);
  assert.equal(await page.locator('#refresh-button').isEnabled(), true);
  await selectOrder(renewal.id);
  const refund = await simulate(renewal.id, 'refunded');
  assert.equal(refund.result.status, 'refunded');
  assert.equal(refund.state.grants.find(grant => grant.order_id === renewal.id).revoked, true);
  assert.equal(refund.state.grants.find(grant => grant.order_id === first.id).active, true);
  checks.push('old renewal refund rejected; latest payment can be refunded without revoking previous access');
  await screenshot('alice-desktop.png');

  const { state: bob } = await mutate(
    () => page.locator('#customer-select').selectOption('bob'), '/api/session');
  assert.equal(bob.customer.id, 'bob');
  assert.equal(bob.orders.length, 0);
  assert.equal(bob.grants.length, 0);
  assert.equal(await page.locator('#current-order').isVisible(), false);
  assert.equal(await page.locator('#orders-body button[data-order-id="' + first.id + '"]').count(), 0);
  assert.equal(await page.locator('#target-select option[value="alice-load"]').count(), 0);
  checks.push('switching demo account clears Alice orders and grants');

  const { order: boost } = await create('promote_24h', 'bob-load');
  assert.equal(boost.customer_id, 'bob');
  assert.equal(boost.target_id, 'bob-load');
  assert.equal(boost.amount_tetri, 500);
  const boostPayment = await simulate(boost.id, 'paid');
  assert.equal(boostPayment.state.grants.length, 1);
  const boostGrant = boostPayment.state.grants[0];
  assert.equal(boostGrant.kind, 'boost');
  assert.equal(boostGrant.target_id, 'bob-load');
  assert.equal(boostGrant.active, true);
  assertPeriod(boostGrant, DAY);
  const repeatedBoost = await simulate(boost.id, 'paid');
  assert.equal(repeatedBoost.state.grants.length, 1);
  assert.equal(repeatedBoost.state.grants[0].ends_at, boostGrant.ends_at);
  checks.push('Bob own-load boost grants 24 hours; replay remains idempotent');

  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('#refresh-button').scrollIntoViewIfNeeded();
  const mobile = await refresh();
  assert.equal(mobile.customer.id, 'bob');
  assert.equal(await page.locator('#order-status').innerText(), 'Оплачен в тесте');
  const layout = await page.evaluate(() => ({ width: window.innerWidth, scrollWidth: document.documentElement.scrollWidth }));
  assert.ok(layout.scrollWidth <= layout.width + 1, 'Mobile content must not overflow: ' + JSON.stringify(layout));
  await page.evaluate(() => window.scrollTo(0, 0));
  await screenshot('bob-mobile.png');
  checks.push('mobile 390px layout preserves checkout, status and history without horizontal overflow');

  assert.deepEqual(diagnostics.blockedRequests, [], 'No external request may be attempted');
  assert.deepEqual(diagnostics.websocketAttempts, [], 'No websocket belongs in this local simulator');
  assert.deepEqual(diagnostics.pageErrors, [], 'Browser JavaScript must not throw');
  fs.writeFileSync(path.join(ARTIFACTS, 'browser-result.json'), JSON.stringify({ ok: true, checks, diagnostics }, null, 2));
  console.log(JSON.stringify({ ok: true, checks: checks.length, screenshots: ['alice-desktop.png', 'bob-mobile.png'], externalRequests: 0 }));
})().catch(async error => {
  if (page) {
    try {await page.screenshot({ path: path.join(ARTIFACTS, 'failure.png'), fullPage: true });} catch {}
  }
  fs.writeFileSync(path.join(ARTIFACTS, 'browser-result.json'), JSON.stringify({ ok: false, error: error.stack || String(error), checks, diagnostics }, null, 2));
  console.error(error.stack || error);
  process.exitCode = 1;
}).finally(async () => {
  if (browser) await browser.close();
});
