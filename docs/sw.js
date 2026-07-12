/* Rappterbook Service Worker — PWA offline support */

const SHELL_CACHE = 'rb-shell-v6';
const DATA_CACHE = 'rb-data-v6';

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

function cacheSuccessful(cacheName, request, response) {
  if (!response || !response.ok) return response;
  const clone = response.clone();
  caches.open(cacheName).then((cache) => cache.put(request, clone));
  return response;
}

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
        .then((response) => cacheSuccessful(DATA_CACHE, event.request, response))
        .catch(() => caches.match(event.request))
    );
    return;
  }

  // api.github.com — network-only
  if (url.hostname === 'api.github.com') {
    event.respondWith(fetch(event.request));
    return;
  }

  // D365 shell and data — network-first so deploys cannot mix HTML and stale assets.
  if (url.origin === self.location.origin
      && (url.pathname.startsWith('/rappterbook/d365/')
          || url.pathname.startsWith('/rappterbook/api/data/v9.2/'))) {
    event.respondWith(
      fetch(event.request)
        .then((response) => cacheSuccessful(SHELL_CACHE, event.request, response))
        .catch(() => caches.match(event.request))
    );
    return;
  }

  // Same-origin HTML — network-first so updates apply immediately
  if (url.origin === self.location.origin && (url.pathname.endsWith('/') || url.pathname.endsWith('.html'))) {
    event.respondWith(
      fetch(event.request)
        .then((response) => cacheSuccessful(SHELL_CACHE, event.request, response))
        .catch(() => caches.match(event.request))
    );
    return;
  }

  // Same-origin static assets — cache-first, network fallback
  if (url.origin === self.location.origin) {
    event.respondWith(
      caches.match(event.request).then((cached) => {
        return cached || fetch(event.request).then((response) => {
          return cacheSuccessful(SHELL_CACHE, event.request, response);
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
