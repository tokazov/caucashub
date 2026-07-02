/**
 * CaucasHub Service Worker v3
 * - HTML: network-first (не кэшируется)
 * - Статика (js/css): network-first (всегда свежая)
 * - API: network-only
 */

const CACHE_NAME = 'caucashub-v3';

// Установка
self.addEventListener('install', function(e) {
  self.skipWaiting();
});

// Активация — удаляем ВСЕ старые кэши
self.addEventListener('activate', function(e) {
  e.waitUntil(
    caches.keys().then(function(keys) {
      return Promise.all(keys.map(function(k) { return caches.delete(k); }));
    }).then(function() { return self.clients.claim(); })
  );
});

self.addEventListener('fetch', function(e) {
  const url = new URL(e.request.url);

  // API запросы — только сеть
  if (url.hostname.includes('railway.app') || url.pathname.startsWith('/api/')) {
    return;
  }

  // Всё остальное — network-first (не кэшируем JS/CSS чтобы не мешать обновлениям)
  if (e.request.method === 'GET') {
    e.respondWith(
      fetch(e.request).catch(function() {
        return caches.match(e.request);
      })
    );
  }
});
