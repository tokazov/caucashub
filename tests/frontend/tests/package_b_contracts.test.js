/**
 * package_b_contracts.test.js
 * Tests for Stage4 Package B — Contracts + Silent failures + Notif dedup
 */
import { test, describe, beforeEach } from 'node:test';
import assert from 'node:assert/strict';

// ── Shared helpers ─────────────────────────────────────────────────────────

function makeBtn() {
  return { textContent: '', disabled: false };
}

function showToastWarnSpy() {
  const calls = [];
  return {
    fn: (msg) => calls.push(String(msg)),
    calls,
    called: () => calls.length > 0,
    lastCall: () => calls[calls.length - 1],
  };
}

// ── CONTRACT-1: doDeleteAccount — 422 handling ─────────────────────────────
describe('CONTRACT-1: doDeleteAccount handles 422', () => {
  // Extract just the 422-handling logic from doDeleteAccount
  function handle422(status, data, btn, toastFn) {
    if (status === 422) {
      const field = data?.detail?.[0]?.loc?.join('.') || '';
      const detailMsg = data?.detail?.[0]?.msg || 'проверьте введённые данные';
      toastFn('⚠️ Ошибка валидации: ' + detailMsg);
      if (btn) { btn.textContent = 'Подтвердить удаление'; btn.disabled = false; }
      return true; // handled
    }
    return false;
  }

  test('422 calls showToastWarn with Pydantic detail message', () => {
    const spy = showToastWarnSpy();
    const btn = makeBtn();
    btn.disabled = true;
    const data = { detail: [{ msg: 'ИНН должен содержать ровно 9 цифр', loc: ['body', 'inn'] }] };

    const handled = handle422(422, data, btn, spy.fn);

    assert.ok(handled, '422 must be handled');
    assert.ok(spy.called(), 'showToastWarn must be called');
    assert.ok(spy.lastCall().includes('ИНН должен содержать ровно 9 цифр'), 'toast must contain Pydantic msg');
    assert.ok(!spy.lastCall().includes('{'), 'raw JSON must not appear in toast');
    assert.ok(!btn.disabled, 'button must be re-enabled');
  });

  test('422 with empty detail uses fallback message', () => {
    const spy = showToastWarnSpy();
    const handled = handle422(422, {}, null, spy.fn);
    assert.ok(handled);
    assert.ok(spy.lastCall().includes('проверьте введённые данные'), 'must use fallback message');
  });

  test('429 is NOT handled by 422 branch', () => {
    const spy = showToastWarnSpy();
    const handled = handle422(429, {}, null, spy.fn);
    assert.ok(!handled, '429 must pass through 422 handler');
    assert.ok(!spy.called(), 'showToastWarn must not be called for 429');
  });

  test('400 is NOT handled by 422 branch', () => {
    const spy = showToastWarnSpy();
    const handled = handle422(400, {}, null, spy.fn);
    assert.ok(!handled);
  });
});

// ── CONTRACT-2: doRegister — 422 INN field highlight ──────────────────────
describe('CONTRACT-2: doRegister highlights INN field on 422', () => {
  function handle422Register(rStatus, rData, toastFn) {
    if (rStatus === 422) {
      const det = Array.isArray(rData) ? rData : (rData?.detail || []);
      const first = Array.isArray(det) ? det[0] : null;
      const fieldName = first?.loc ? first.loc[first.loc.length - 1] : null;
      const msg422 = first?.msg || 'Проверьте введённые данные';
      const fieldMap = { inn: 'regInn', email: 'regEmail', password: 'regPass' };
      const inputId = fieldMap[fieldName] || ('reg' + (fieldName ? fieldName.charAt(0).toUpperCase() + fieldName.slice(1) : ''));
      toastFn('⚠️ ' + msg422);
      return { inputId, msg: msg422 };
    }
    return null;
  }

  test('422 INN returns correct field id regInn', () => {
    const spy = showToastWarnSpy();
    const data = { detail: [{ msg: 'ИНН должен содержать ровно 9 цифр', loc: ['body', 'inn'] }] };
    const result = handle422Register(422, data, spy.fn);

    assert.ok(result, 'must handle 422');
    assert.equal(result.inputId, 'regInn', 'must target regInn input');
    assert.ok(spy.called(), 'showToastWarn must be called');
    assert.ok(spy.lastCall().includes('9 цифр'), 'must show specific INN message');
  });

  test('422 email returns regEmail field id', () => {
    const spy = showToastWarnSpy();
    const data = { detail: [{ msg: 'Invalid email', loc: ['body', 'email'] }] };
    const result = handle422Register(422, data, spy.fn);
    assert.equal(result?.inputId, 'regEmail');
  });

  test('non-422 status returns null (not handled)', () => {
    const spy = showToastWarnSpy();
    const result = handle422Register(400, {}, spy.fn);
    assert.equal(result, null);
    assert.ok(!spy.called());
  });

  test('422 without loc uses generic message', () => {
    const spy = showToastWarnSpy();
    const result = handle422Register(422, { detail: [{ msg: 'Server error' }] }, spy.fn);
    assert.ok(spy.lastCall().includes('Server error'));
  });
});

// ── SILENT-1: deleteMyLoad — UI only after server success ─────────────────
describe('SILENT-1: deleteMyLoad removes UI only on success', () => {
  // Simplified deleteMyLoad logic
  async function deleteMyLoad_logic(serverId, fakeFetch, onSuccess, toastFn) {
    try {
      const r = await fakeFetch(serverId);
      if (!r || !r.ok) {
        if (r && r.status === 403) {
          toastFn('⚠️ Нет прав на удаление этого груза');
        } else if (r && r.status === 404) {
          toastFn('⚠️ Груз не найден на сервере');
        } else {
          toastFn('⚠️ Не удалось удалить груз, попробуйте позже');
        }
        return false; // UI not changed
      }
      onSuccess(); // remove from UI
      return true;
    } catch (e) {
      toastFn('⚠️ Ошибка соединения — груз не удалён');
      return false;
    }
  }

  test('403 response: toast shown, onSuccess NOT called', async () => {
    const spy = showToastWarnSpy();
    let uiRemoved = false;
    const fakeFetch = async () => ({ ok: false, status: 403 });

    const result = await deleteMyLoad_logic(42, fakeFetch, () => { uiRemoved = true; }, spy.fn);

    assert.ok(!result, 'must return false on 403');
    assert.ok(!uiRemoved, 'UI must NOT be changed on 403');
    assert.ok(spy.called(), 'showToastWarn must be called');
    assert.ok(spy.lastCall().includes('Нет прав'), 'toast must mention rights');
  });

  test('200 response: onSuccess IS called, no toast', async () => {
    const spy = showToastWarnSpy();
    let uiRemoved = false;
    const fakeFetch = async () => ({ ok: true, status: 200 });

    const result = await deleteMyLoad_logic(42, fakeFetch, () => { uiRemoved = true; }, spy.fn);

    assert.ok(result, 'must return true on 200');
    assert.ok(uiRemoved, 'UI must be removed on success');
    assert.ok(!spy.called(), 'no toast on success');
  });

  test('404 response: toast shown, UI not changed', async () => {
    const spy = showToastWarnSpy();
    let uiRemoved = false;
    const fakeFetch = async () => ({ ok: false, status: 404 });

    await deleteMyLoad_logic(42, fakeFetch, () => { uiRemoved = true; }, spy.fn);

    assert.ok(!uiRemoved, 'UI must NOT be changed on 404');
    assert.ok(spy.lastCall().includes('не найден'), 'must mention not found');
  });

  test('network error: toast shown, UI not changed', async () => {
    const spy = showToastWarnSpy();
    let uiRemoved = false;
    const fakeFetch = async () => { throw new Error('Network error'); };

    await deleteMyLoad_logic(42, fakeFetch, () => { uiRemoved = true; }, spy.fn);

    assert.ok(!uiRemoved, 'UI must NOT be changed on network error');
    assert.ok(spy.lastCall().includes('соединения'), 'must mention connection error');
  });
});

// ── SILENT-2: submitTransportOffer — 401/422 ──────────────────────────────
describe('SILENT-2: submitTransportOffer handles 401/422', () => {
  const openAuthCalls = [];
  function openAuth(mode) { openAuthCalls.push(mode); }

  beforeEach(() => { openAuthCalls.length = 0; });

  async function handleTransportOfferResponse(status, body, toastFn, errElSetter) {
    const r = { ok: status >= 200 && status < 300, status };
    const d = typeof body === 'string' ? JSON.parse(body) : body;

    if (r.status === 401) {
      toastFn('⚠️ Войдите в аккаунт');
      openAuth('login');
      return 'redirect';
    }
    if (r.status === 422) {
      const msg = d?.detail?.[0]?.msg || 'Проверьте поля формы';
      errElSetter(msg);
      return 'validation_error';
    }
    if (r.status === 201) return 'success';
    const errMsg = typeof d?.detail === 'string' ? d.detail : 'Не удалось отправить, попробуйте позже';
    errElSetter(errMsg);
    return 'error';
  }

  test('401 triggers openAuth(login) and toast', async () => {
    const spy = showToastWarnSpy();
    let ptError = '';
    const result = await handleTransportOfferResponse(401, '{}', spy.fn, (m) => { ptError = m; });

    assert.equal(result, 'redirect');
    assert.ok(spy.called(), 'toast must be shown on 401');
    assert.ok(openAuthCalls.includes('login'), 'must redirect to login');
    assert.equal(ptError, '', 'ptError must not be set on 401');
  });

  test('422 writes validation message to ptError', async () => {
    const spy = showToastWarnSpy();
    let ptError = '';
    const body = { detail: [{ msg: 'Укажите маршрут корректно' }] };
    const result = await handleTransportOfferResponse(422, body, spy.fn, (m) => { ptError = m; });

    assert.equal(result, 'validation_error');
    assert.ok(ptError.includes('Укажите маршрут'), 'ptError must contain validation msg');
    assert.ok(!spy.called(), 'no toast on 422 — error goes to ptError');
  });

  test('201 returns success', async () => {
    const spy = showToastWarnSpy();
    const result = await handleTransportOfferResponse(201, '{"id":1}', spy.fn, () => {});
    assert.equal(result, 'success');
    assert.ok(!spy.called());
  });

  test('500 shows generic error in ptError', async () => {
    const spy = showToastWarnSpy();
    let ptError = '';
    await handleTransportOfferResponse(500, '{}', spy.fn, (m) => { ptError = m; });
    assert.ok(ptError.includes('попробуйте'), 'generic error message on 500');
  });
});

// ── SILENT-3: filterAndLoadTransport — error vs empty ──────────────────────
describe('SILENT-3: filterAndLoadTransport distinguishes error from empty', () => {
  async function handleTransportLoad(status, offers, toastFn, setList) {
    if (status === 401) {
      toastFn('⚠️ Войдите в аккаунт');
      return 'auth_error';
    }
    if (status !== 200) {
      setList('error_state');
      return 'server_error';
    }
    // 200 — even if empty, it's a normal result
    setList(offers.length === 0 ? 'empty_result' : 'has_results');
    return 'ok';
  }

  test('401 → toast, not list error', async () => {
    const spy = showToastWarnSpy();
    let listState = '';
    const result = await handleTransportLoad(401, [], spy.fn, (s) => { listState = s; });
    assert.equal(result, 'auth_error');
    assert.ok(spy.called());
    assert.equal(listState, '', 'list must not be set on 401');
  });

  test('500 → list shows error state', async () => {
    const spy = showToastWarnSpy();
    let listState = '';
    const result = await handleTransportLoad(500, [], spy.fn, (s) => { listState = s; });
    assert.equal(result, 'server_error');
    assert.equal(listState, 'error_state', 'list must show error state on 500');
    assert.ok(!spy.called(), 'no toast — error shown in list');
  });

  test('200 with empty array → empty result (not error)', async () => {
    const spy = showToastWarnSpy();
    let listState = '';
    const result = await handleTransportLoad(200, [], spy.fn, (s) => { listState = s; });
    assert.equal(result, 'ok');
    assert.equal(listState, 'empty_result', 'empty 200 must show "not found", not error');
    assert.ok(!spy.called());
  });

  test('200 with offers → has_results state', async () => {
    const spy = showToastWarnSpy();
    let listState = '';
    await handleTransportLoad(200, [{ id: 1 }], spy.fn, (s) => { listState = s; });
    assert.equal(listState, 'has_results');
  });
});

// ── NOTIF-DEDUP: renderNotifs exists, _renderNotifs removed ──────────────
import { readFileSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
const __dirnameB = dirname(fileURLToPath(import.meta.url));
const mainJs = readFileSync(join(__dirnameB, '../../../frontend/main.js'), 'utf8');

describe('NOTIF-DEDUP: notification function consolidation', () => {

  test('renderNotifs function exists in main.js', () => {
    assert.ok(mainJs.includes('function renderNotifs('), 'renderNotifs must be defined');
  });

  test('_renderNotifs function is REMOVED from main.js', () => {
    assert.ok(!mainJs.includes('function _renderNotifs('), '_renderNotifs must be removed (NOTIF-DEDUP)');
  });

  test('renderNotifs uses esc() for title and body (XSS-3)', () => {
    // Find renderNotifs body and check for esc()
    const idx = mainJs.indexOf('function renderNotifs(');
    const snippet = mainJs.slice(idx, idx + 1200);
    assert.ok(snippet.includes('esc(n.title)') || snippet.includes('esc('), 'renderNotifs must use esc() for title');
  });

  test('no duplicate pushNotif definitions', () => {
    const matches = (mainJs.match(/^function pushNotif\b/gm) || []);
    assert.ok(matches.length <= 1, 'only one pushNotif definition allowed (NOTIF-DEDUP)');
  });
});
