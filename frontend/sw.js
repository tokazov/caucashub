/**
 * CaucasHub Service Worker v1
 * - HTML: network-first (не кэшируется)
 * - Статика (js/css/png): cache-first
 * - API: network-only
 */

const CACHE_NAME = 'caucashub-v1';
const STATIC_ASSETS = [
  '/manifest.json',
  '/icon-192.png',
  '/icon-512.png',
  '/styles.css',
];

// Установка — кэшируем статику
self.addEventListener('install', function(e) {
  self.skipWaiting();
  e.waitUntil(
    caches.open(CACHE_NAME).then(function(cache) {
      return cache.addAll(STATIC_ASSETS).catch(function() {});
    })
  );
});

// Активация — удаляем старые кэши
self.addEventListener('activate', function(e) {
  e.waitUntil(
    caches.keys().then(function(keys) {
      return Promise.all(
        keys.filter(function(k) { return k !== CACHE_NAME; })
            .map(function(k) { return caches.delete(k); })
      );
    }).then(function() { return self.clients.claim(); })
  );
});

self.addEventListener('fetch', function(e) {
  const url = new URL(e.request.url);

  // API запросы — только сеть, без кэша
  if (url.hostname.includes('railway.app') || url.pathname.startsWith('/api/')) {
    return;
  }

  // HTML страницы — network-first (не кэшируем)
  if (e.request.mode === 'navigate') {
    e.respondWith(
      fetch(e.request).catch(function() {
        return caches.match('/') || new Response('Нет соединения. Попробуйте позже.', {
          headers: { 'Content-Type': 'text/plain; charset=utf-8' }
        });
      })
    );
    return;
  }

  // Статика — cache-first
  if (e.request.method === 'GET' &&
      (url.pathname.endsWith('.js') || url.pathname.endsWith('.css') ||
       url.pathname.endsWith('.png') || url.pathname.endsWith('.jpg') ||
       url.pathname.endsWith('.svg') || url.pathname.endsWith('.json'))) {
    e.respondWith(
      caches.match(e.request).then(function(cached) {
        return cached || fetch(e.request).then(function(resp) {
          if (resp.ok) {
            const clone = resp.clone();
            caches.open(CACHE_NAME).then(function(c) { c.put(e.request, clone); });
          }
          return resp;
        });
      })
    );
    return;
  }
});
