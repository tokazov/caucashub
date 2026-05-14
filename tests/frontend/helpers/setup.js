/**
 * helpers/setup.js
 * Creates a jsdom window environment for testing vanilla JS functions.
 * Injects minimal globals needed by main.js/api.js without loading the full file.
 */
import { JSDOM } from 'jsdom';
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const FRONTEND_DIR = join(__dirname, '../../../frontend');

/**
 * Creates a fresh jsdom window with minimal globals.
 * @param {object} opts
 * @param {string[]} [opts.loadFiles] - relative paths under frontend/ to eval into window
 * @param {object} [opts.fetchMock] - map of url-pattern → {status, body} for fetch mock
 * @returns {{ window, document, calls }} — calls.toastWarn[], calls.alerts[], calls.confirms[]
 */
export function createEnv({ loadFiles = [], fetchMock = {} } = {}) {
  const dom = new JSDOM('<!DOCTYPE html><html><body></body></html>', {
    url: 'https://caucashub.ge',
    runScripts: 'dangerously',
  });
  const { window } = dom;
  const { document } = window;

  // Track calls to alert/confirm/showToastWarn for assertions
  const calls = { toastWarn: [], alerts: [], confirms: [], openAuth: [] };

  // ── Minimal globals ──────────────────────────────────────────────
  window.alert   = (msg) => { calls.alerts.push(String(msg)); };
  window.confirm = (msg) => { calls.confirms.push(String(msg)); return true; };

  // showToastWarn stub — records calls
  window.showToastWarn = (msg) => { calls.toastWarn.push(String(msg)); };

  // localStorage stub
  const _ls = {};
  window.localStorage = {
    getItem:    (k) => _ls[k] ?? null,
    setItem:    (k, v) => { _ls[k] = v; },
    removeItem: (k) => { delete _ls[k]; },
    clear:      () => { Object.keys(_ls).forEach(k => delete _ls[k]); },
  };

  // TRANSLATIONS stub (minimal RU)
  window.TRANSLATIONS = {
    ru: {
      warn_login: '⚠️ Войдите в аккаунт',
      warn_network: '⚠️ Ошибка сети.',
      btn_delete_confirm: 'Подтвердить удаление',
      confirm_delete_load: 'Удалить груз из биржи?',
    },
    ge: {}
  };
  window.lang = 'ru';

  // API_BASE stub
  window.API_BASE = 'https://api-production-f3ea.up.railway.app';

  // getToken / setToken stubs
  window.getToken = () => window.localStorage.getItem('ch_token');
  window.setToken = (t) => { if(t) window.localStorage.setItem('ch_token', t); else window.localStorage.removeItem('ch_token'); };

  // openAuth stub
  window.openAuth = (mode) => { calls.openAuth.push(mode); };

  // fetch mock
  window.fetch = async (url, opts) => {
    for (const [pattern, resp] of Object.entries(fetchMock)) {
      if (String(url).includes(pattern)) {
        const body = typeof resp.body === 'string' ? resp.body : JSON.stringify(resp.body);
        return {
          ok: resp.status >= 200 && resp.status < 300,
          status: resp.status,
          json: async () => JSON.parse(body),
          text: async () => body,
        };
      }
    }
    // Default: network error
    throw new Error('fetch: no mock for ' + url);
  };

  // Other stubs used by main.js
  window.pushNotif = () => {};
  window.renderLoads = () => {};
  window.renderNotifs = () => {};
  window._renderOrders = () => {};
  window.persistMyLoads = () => {};
  window.loadCabinetData = () => {};
  window.showSection = () => {};
  window.switchCabTab = () => {};
  window.closeModal = () => {};
  window.openAuth = (mode) => { calls.openAuth.push(mode); };
  window.esc = (s) => {
    if (s == null) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  };

  // Load requested files into window context
  for (const relPath of loadFiles) {
    const code = readFileSync(join(FRONTEND_DIR, relPath), 'utf8');
    // We use a Function to avoid top-level 'use strict' issues
    const fn = new window.Function(code); // eslint-disable-line no-new-func
    try { fn.call(window); } catch(e) { /* ignore parse/init errors for stubs */ }
  }

  return { window, document, calls };
}
