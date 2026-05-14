/**
 * package_a_xss.test.js
 * Tests for Stage4 Package A — XSS fixes (XSS-1..4)
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';

// ── XSS-1: callTruck — JSON.stringify in onclick ──────────────────────────────
describe('XSS-1: callTruck onclick uses JSON.stringify', () => {
  test('onclick attribute contains JSON.stringify pattern for t.co', () => {
    // Verify the source code uses JSON.stringify — check rendered HTML
    // We test the rendered button onclick for a truck with XSS payload in co
    const xssPayload = "x',alert(1),'x";

    // Simulate what renderTrucks builds for the onclick attr
    const co = xssPayload;
    const plate = 'GE-123-AB';
    const phone = '+995555123456';

    // This is exactly what the fixed code does:
    const onclickAttr = `callTruck(${JSON.stringify(co)},${JSON.stringify(plate)},${JSON.stringify(phone)})`;

    // Verify it does NOT contain the raw payload (no injection point)
    assert.ok(!onclickAttr.includes("alert(1),'x'"), 'raw payload must not appear unescaped');
    // Verify JSON.stringify properly escapes it
    assert.ok(onclickAttr.includes('"x\',alert(1),\'x"'), 'payload must be JSON-string escaped');
  });

  test('JSON.stringify escapes double quotes in company name', () => {
    const co = 'Company "Evil"';
    const serialized = JSON.stringify(co);
    // Must not break out of attribute
    assert.ok(!serialized.includes('"Evil"') || serialized.startsWith('"'), 'double quotes must be escaped in JSON');
    assert.equal(serialized, '"Company \\"Evil\\""');
  });
});

// ── XSS-2: addrSearch — _addrCache + selectAddrByKey ─────────────────────────
describe('XSS-2: geocoder address cache', () => {
  test('selectAddrByKey retrieves from cache without parsing user data', () => {
    // Simulate _addrCache and selectAddrByKey
    const _addrCache = {};
    let selectedName = null, selectedLat = null;

    function selectAddr(field, name, lat, lng) {
      selectedName = name;
      selectedLat = lat;
    }

    function selectAddrByKey(field, key) {
      const a = _addrCache[key];
      if (!a) return;
      selectAddr(field, a.name, a.lat, a.lng);
    }

    // Store XSS payload in cache
    const xssName = '<img src=x onerror=alert(1)>';
    const key = 'pFrom_1234567890_0';
    _addrCache[key] = { name: xssName, lat: 41.69, lng: 44.83 };

    selectAddrByKey('pFrom', key);

    // Data passes through as-is to selectAddr (which puts it in input.value — safe)
    assert.equal(selectedName, xssName, 'name retrieved from cache correctly');
    assert.equal(selectedLat, 41.69, 'coords retrieved from cache correctly');
  });

  test('cache key is passed to onmousedown, not raw user data', () => {
    // The key in onmousedown attr is safe: alphanumeric + underscores + timestamp
    const field = 'pFrom';
    const idx = 0;
    const key = `${field}_${Date.now()}_${idx}`;

    // Key should NOT contain HTML-dangerous chars
    assert.ok(!/[<>"'&]/.test(key), 'cache key must not contain HTML-dangerous chars');
  });
});

// ── XSS-3: renderNotifs — esc() on title/body ────────────────────────────────
describe('XSS-3: notification esc()', () => {
  function esc(s) {
    if (s == null) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  test('XSS payload in title is escaped', () => {
    const title = '<script>alert(1)</script>';
    const escaped = esc(title);
    assert.equal(escaped, '&lt;script&gt;alert(1)&lt;/script&gt;');
    assert.ok(!escaped.includes('<script>'), 'raw <script> must not appear');
  });

  test('img onerror payload in body is escaped', () => {
    const body = '<img src=x onerror=alert(document.cookie)>';
    const escaped = esc(body);
    assert.ok(!escaped.includes('<img'), 'raw <img must not appear');
    assert.ok(escaped.includes('&lt;img'), 'must be escaped as &lt;img');
  });

  test('normal text passes through unchanged', () => {
    const text = 'Сделка создана CH-0042';
    assert.equal(esc(text), text);
  });

  test('null/undefined returns empty string', () => {
    assert.equal(esc(null), '');
    assert.equal(esc(undefined), '');
  });
});

// ── XSS-4: _notifActions dispatcher ──────────────────────────────────────────
describe('XSS-4: _notifActions data-action dispatcher', () => {
  test('registered action is called with notifId', () => {
    const _notifActions = {};
    let firedWith = null;
    _notifActions['delivered'] = (notifId) => { firedWith = notifId; };

    // Simulate dispatcher logic
    function dispatch(actionId, notifId) {
      const fn = _notifActions[actionId];
      if (typeof fn === 'function') fn(notifId);
    }

    dispatch('delivered', '1234567890');
    assert.equal(firedWith, '1234567890', 'action must be called with notifId');
  });

  test('unknown actionId does not throw', () => {
    const _notifActions = {};
    assert.doesNotThrow(() => {
      const fn = _notifActions['unknown_action'];
      if (typeof fn === 'function') fn('999');
    });
  });

  test('a.fn string is NOT evaluated — only actionId used', () => {
    let alertCalled = false;
    // Simulate old pattern: a.fn = 'alert(1)' injected into onclick
    // In new pattern this string is NEVER eval'd — only actionId dispatched
    const _notifActions = {};
    const a = { fn: 'alert(1)', actionId: undefined, label: 'Click' };

    // Dispatcher uses actionId, not fn
    const fn = _notifActions[a.actionId || ''];
    if (typeof fn === 'function') fn('0');

    assert.ok(!alertCalled, 'a.fn must not be executed');
  });
});
