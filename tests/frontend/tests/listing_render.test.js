import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

for (const file of ['main.js', 'frontend/main.js']) {
  test(`${file}: transport uses translated types, count and login action`, () => {
    const source = readFileSync(new URL('../../../' + file, import.meta.url), 'utf8');
    const start = source.indexOf('function renderTransportOffers() {');
    const end = source.indexOf('// Открыть модалку отклика на транспортное предложение', start);
    const elements = { transportList: { innerHTML: '' }, transportCount: { textContent: '' } };
    const context = {
      performance: { now: () => 0 }, console: { log: () => {} },
      document: { getElementById: id => elements[id] },
      window: { requestAnimationFrame: fn => fn() },
      lang: 'ge', TRANSLATIONS: { ge: { transport_count_suffix: 'ტრანსპორტის შეთავაზება', btn_login_short: 'შესვლა' }, ru: {} },
      _transportTotal: 1, _transportOffers: [{ id: 1, truck_type: 'tent', capacity_kg: 1000 }],
      getToken: () => null, getTypeLabel: () => 'ტენტი',
      esc: value => String(value),
    };
    vm.createContext(context);
    const escapeStart=source.indexOf('function esc(s) {'),escapeEnd=source.indexOf('// ── SAFE LOCALSTORAGE',escapeStart);
    if(escapeStart>=0&&escapeEnd>escapeStart)vm.runInContext(source.slice(escapeStart,escapeEnd),context);
    vm.runInContext(source.slice(start, end), context);
    vm.runInContext('renderTransportOffers()', context);
    assert.equal(elements.transportCount.textContent, '1 ტრანსპორტის შეთავაზება');
    assert.ok(elements.transportList.innerHTML.includes('ტენტი'));
    assert.ok(elements.transportList.innerHTML.includes("openAuth('login')"));
    assert.ok(!elements.transportList.innerHTML.includes("openAuth('register')"));
    context._transportTotal = 0;
    context._transportOffers = [];
    vm.runInContext('renderTransportOffers()', context);
    assert.equal(elements.transportCount.textContent, '0 ტრანსპორტის შეთავაზება');
  });
}

for (const file of ['api.js', 'frontend/api.js']) {
  test(`${file}: server publication timestamp survives mapping`, () => {
    const source = readFileSync(new URL('../../../' + file, import.meta.url), 'utf8');
    const start = source.indexOf('function mapServerLoad(l){');
    const end = source.indexOf('// FIX: openPlansModal', start);
    const context = {};
    vm.createContext(context);
    vm.runInContext(source.slice(source.indexOf('// Calendar days in Georgia'), source.indexOf('// ── AUTH ─')) + source.slice(start, end), context);
    const mapped = vm.runInContext("mapServerLoad({id: 1, created_at: '2026-04-01T10:00:00Z'})", context);
    assert.equal(mapped.created_at, '2026-04-01T10:00:00Z');
    assert.equal(vm.runInContext('mapServerLoad({id: 2})', context).created_at, null);
  });
}
