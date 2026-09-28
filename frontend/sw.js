/**
 * CaucasHub Service Worker v5 — minimal passthrough
 *
 * Политика: SW НЕ перехватывает fetch запросы вообще.
 * Его единственная задача — очистить старые кеши от v3/v4 которые
 * возвращали 503 и вешали загрузку транспорта.
 *
 * История проблем:
 * v3: caches.match() → undefined → TypeError: Failed to convert value to 'Response'
 * v4: 503 fallback → ломал загрузку index.html/main.js при мигании сети
 * v5: убираем respondWith полностью — браузер сам управляет кешем
 */

const CACHE_NAME = 'caucashub-v5';

// Установка — сразу активируемся
self.addEventListener('install', function(e) {
  self.skipWaiting();
});

// Активация — удаляем ВСЕ старые кэши (v3, v4, любые)
self.addEventListener('activate', function(e) {
  e.waitUntil(
    caches.keys().then(function(keys) {
      return Promise.all(keys.map(function(k) { return caches.delete(k); }));
    }).then(function() { return self.clients.claim(); })
  );
});

// fetch — НЕ перехватываем, браузер управляет кешем самостоятельно
// self.addEventListener('fetch', ...) — намеренно отсутствует
