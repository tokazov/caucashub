/* Real tariff open/close lifecycle, run only by the isolated browser fixture. */
const assert = require('node:assert/strict');
const path = require('node:path');

module.exports = async function tariffSteps(page, { name, artifacts }) {
  const overlay = page.locator('#paywallOverlay');
  const modal = page.locator('#paywallOverlay .modal');
  const originalViewport = page.viewportSize();

  async function open() {
    await page.locator('#btnReg').click();
    await page.locator('#authOverlay button[onclick="openPlansModal(event)"]').click();
    await overlay.waitFor({ state: 'visible' });
    await page.waitForFunction(() => {
      const el = document.querySelector('#paywallOverlay .modal');
      return getComputedStyle(el).transform === 'none' && getComputedStyle(el).opacity === '1';
    });
    return modal.evaluate(el => {
      const rect = el.getBoundingClientRect();
      const cards = [...el.querySelectorAll('[data-pw-plan]')];
      return {
        width: rect.width, height: rect.height,
        overflow: el.scrollWidth > el.clientWidth + 1,
        cards: cards.map(card => {
          const box = card.getBoundingClientRect();
          return { x: box.x - rect.x, y: box.y - rect.y, width: box.width,
            clipped: box.left < rect.left || box.right > rect.right + 1 };
        })
      };
    });
  }

  if (originalViewport.width > 768) {
    const colors = await page.locator('.load-post-btn').evaluate(el => ({
      background: getComputedStyle(el).backgroundColor, text: getComputedStyle(el).color
    }));
    const rgb = colors.background.match(/\d+/g).map(Number);
    assert.ok(rgb[1] > rgb[0] && rgb[1] > rgb[2], 'Place load action must be green');
    assert.equal(colors.text, 'rgb(255, 255, 255)');
  }

  // Cover the desktop grid and its narrowest width, plus the phone layout.
  const widths = name === 'desktop' ? [originalViewport.width, 641] : [originalViewport.width, 320];
  for (const width of widths) {
    await page.setViewportSize({ width, height: originalViewport.height });
    for (const language of ['ru', 'ge']) {
      await page.getByRole('button', { name: language.toUpperCase(), exact: true }).click();
      let first;
      for (const closeBy of ['button', 'escape', 'backdrop']) {
        const size = await open();
        assert.equal(size.overflow, false, 'Tariffs must not scroll horizontally');
        assert.equal(size.cards.length, 3);
        assert.ok(size.cards.every(card => !card.clipped), 'Every tariff must fit inside the dialog');
        if (width > 640) {
          assert.ok(size.cards.every(card => Math.abs(card.y - size.cards[0].y) < 1));
        } else {
          assert.ok(size.cards[1].y > size.cards[0].y && size.cards[2].y > size.cards[1].y);
        }
        if (first) {
          assert.ok(Math.abs(size.width - first.width) < 1, 'Reopening must preserve dialog width');
          assert.ok(Math.abs(size.height - first.height) < 1, 'Reopening must preserve dialog height');
        } else first = size;
        if (width === originalViewport.width && closeBy === 'escape') {
          await page.screenshot({ path: path.join(artifacts, name + '-tariffs-' + language + '-reopened.png') });
        }
        if (closeBy === 'button') await overlay.locator('.close-btn').click();
        else if (closeBy === 'escape') await page.keyboard.press('Escape');
        else await overlay.click({ position: { x: 4, y: 4 } });
        await overlay.waitFor({ state: 'hidden' });
      }
    }
  }
  await page.setViewportSize(originalViewport);
  await page.getByRole('button', { name: 'RU', exact: true }).click();
  console.log(name + ': tariff dimensions stable across close/reopen, RU/GE and narrow screens');
};
