/* Navigation while the external map SDK is pending; isolated localhost only. */
const assert = require('node:assert/strict');
const path = require('node:path');

module.exports = async function searchMapSteps(page, { name, artifacts }) {
  const map = page.locator('#mapWrap');
  const canvas = page.locator('#routeMap');
  const section = async tab => {
    const selector = `[onclick^="showSection('${tab}',"]`;
    const desktop = page.locator('.nav-tab' + selector);
    await (await desktop.isVisible() ? desktop : page.locator('.bitem' + selector)).click();
    await page.locator('#sec-' + tab + '.active').waitFor();
  };
  // Leave provider startup pending, so no map/network service can mask the bug.
  await page.evaluate(() => {
    window.__searchMapTest = { loader: window.loadYmapsLazy, pending: 0 };
    window.loadYmapsLazy = () => { window.__searchMapTest.pending++; };
  });
  try {
    for (const language of ['ru', 'ge']) {
      await page.getByRole('button', { name: language.toUpperCase(), exact: true }).click();
      await section('loads');
      for (const [id, city] of [['fFrom', 'Тбилиси'], ['fTo', 'Батуми']]) {
        await page.locator('#' + id).click();
        await page.locator('#' + id).fill(city);
      }
      await page.locator('#loadSearchBtn').click();
      await map.waitFor({ state: 'visible' });
      assert.ok(await page.evaluate(() => window.__searchMapTest.pending > 0));
      await page.mouse.move(0, 0);
      const loadColor = await page.locator('.load-post-btn').evaluate(el => getComputedStyle(el).backgroundColor);
      const findColor = await page.locator('#loadSearchBtn').evaluate(el => getComputedStyle(el).backgroundColor);
      await section('trucks');
      await map.waitFor({ state: 'hidden' });
      assert.equal(await map.evaluate(el => el.getBoundingClientRect().height), 0, 'Hidden map must leave no blank space');
      assert.ok(await canvas.evaluate(el => el.getBoundingClientRect().width > 0 && el.getBoundingClientRect().height > 0), 'Pending map must retain usable canvas dimensions');
      assert.equal(await page.locator('#btnOfferTransport').evaluate(el => getComputedStyle(el).backgroundColor), loadColor);
      assert.equal(await page.locator('#btnFindTransport').evaluate(el => getComputedStyle(el).backgroundColor), findColor);
      await page.screenshot({ path: path.join(artifacts, name + '-transport-without-load-map-' + language + '.png') });
      await section('rates');
      await map.waitFor({ state: 'hidden' });
      await section('loads');
      await map.waitFor({ state: 'visible' });
      assert.equal(await page.locator('#fFrom').inputValue(), 'Тбилиси');
      assert.equal(await page.locator('#fTo').inputValue(), 'Батуми');
      await page.locator('.load-search-reset').click();
      await map.waitFor({ state: 'hidden' });
    }
  } finally {
    await page.evaluate(() => {
      window.loadYmapsLazy = window.__searchMapTest.loader;
      delete window.__searchMapTest;
    });
    await page.getByRole('button', { name: 'RU', exact: true }).click();
  }
  console.log(name + ': pending load map stays within Loads, route survives navigation, publication colors match in RU/GE');
};
