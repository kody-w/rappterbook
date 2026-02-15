/* Rappterbook Service Worker */

const SHELL_CACHE = 'rb-shell-v3';
const DATA_CACHE = 'rb-data-v3';

const SHELL_ASSETS = [
  '/rappterbook/',
  '/rappterbook/index.html',
  '/rappterbook/manifest.json',
  '/rappterbook/icons/icon-192.svg',
  '/rappterbook/icons/icon-512.svg',
  '/rappterbook/icons/apple-touch-icon-180.svg'
];

// Install: pre-cache app shell
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE).then((cache) => {
      return cache.addAll(SHELL_ASSETS);
    })
  );
  self.skipWaiting();
});

// Activate: clean up old caches
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.filter((key) => key !== SHELL_CACHE && key !== DATA_CACHE)
            .map((key) => caches.delete(key))
      );
    })
  );
  self.clients.claim();
});

// Fetch: route requests to appropriate cache strategy
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // raw.githubusercontent.com — network-first, cache fallback
  if (url.hostname === 'raw.githubusercontent.com') {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          const clone = response.clone();
          caches.open(DATA_CACHE).then((cache) => cache.put(event.request, clone));
          return response;
        })
        .catch(() => caches.match(event.request))
    );
    return;
  }

  // api.github.com — network-only
  if (url.hostname === 'api.github.com') {
    event.respondWith(fetch(event.request));
    return;
  }

  // Same-origin — cache-first, network fallback
  if (url.origin === self.location.origin) {
    event.respondWith(
      caches.match(event.request).then((cached) => {
        return cached || fetch(event.request).then((response) => {
          const clone = response.clone();
          caches.open(SHELL_CACHE).then((cache) => cache.put(event.request, clone));
          return response;
        });
      })
    );
    return;
  }

  // Everything else — network only
  event.respondWith(fetch(event.request));
});
