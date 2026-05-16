/* Rappterbook Service Worker — PWA offline support */

const SHELL_CACHE = 'rb-shell-v5';
const DATA_CACHE = 'rb-data-v5';

const SHELL_ASSETS = [
  '/rappterbook/',
  '/rappterbook/index.html',
  '/rappterbook/manifest.json',
  '/rappterbook/icon-192.png',
  '/rappterbook/icon-512.png'
];

const PAGES = [
  '/rappterbook/',
  '/rappterbook/dev',
  '/rappterbook/twitter',
  '/rappterbook/youtube',
  '/rappterbook/hub',
  '/rappterbook/underground',
  '/rappterbook/os',
  '/rappterbook/weekend'
];

// Install: pre-cache app shell + key pages
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE).then((cache) => {
      // Cache shell assets first (critical)
      return cache.addAll(SHELL_ASSETS).then(() => {
        // Then attempt to cache pages (non-critical, may fail offline)
        return Promise.allSettled(
          PAGES.map((url) => cache.add(url).catch(() => {}))
        );
      });
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

  // Same-origin HTML — network-first so updates apply immediately
  if (url.origin === self.location.origin && (url.pathname.endsWith('/') || url.pathname.endsWith('.html'))) {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          const clone = response.clone();
          caches.open(SHELL_CACHE).then((cache) => cache.put(event.request, clone));
          return response;
        })
        .catch(() => caches.match(event.request))
    );
    return;
  }

  // Same-origin static assets — cache-first, network fallback
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

  // Cross-origin requests not handled above — let the browser handle natively
  // (intercepting these breaks CORS for auth endpoints, workers, etc.)
  if (url.origin !== self.location.origin) {
    return;
  }

  // Everything else (same-origin, uncached) — network only
  event.respondWith(fetch(event.request));
});
