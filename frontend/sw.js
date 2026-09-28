/**
 * CaucasHub Service Worker v4
 * - HTML: network-first (не кэшируется)
 * - Статика (js/css): network-first (всегда свежая)
 * - API: network-only (passthrough — без respondWith)
 *
 * fix: TypeError "Failed to convert value to 'Response'" —
 *   caches.match() возвращает undefined если ресурса нет в кеше,
 *   SW не может передать undefined как Response → краш fetch.
 *   Решение: если сеть недоступна и кеша нет — возвращаем 503.
 */

const CACHE_NAME = 'caucashub-v4';

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

  // API и внешние ресурсы — пропускаем без вмешательства
  if (
    url.hostname.includes('railway.app') ||
    url.pathname.startsWith('/api/') ||
    url.hostname !== self.location.hostname
  ) {
    return; // браузер обрабатывает сам
  }

  // Только GET для нашего домена — network-first
  if (e.request.method === 'GET') {
    e.respondWith(
      fetch(e.request).catch(function() {
        // Сеть недоступна — пробуем кеш
        return caches.match(e.request).then(function(cached) {
          // Если кеша нет — возвращаем 503 вместо undefined (fix: TypeError)
          return cached || new Response('Offline', {
            status: 503,
            statusText: 'Service Unavailable',
            headers: {'Content-Type': 'text/plain'}
          });
        });
      })
    );
  }
});
