// Service Worker：快取 App 檔案，沒有網路也能開啟。
// 策略：先用快取立刻顯示，同時在背景抓新版更新快取（下次開啟就是新版）。
// 新增或改名檔案時，記得更新 ASSETS 並把 VERSION 加 1。
const VERSION = 1;
const CACHE = `ledger-v${VERSION}`;

const ASSETS = [
  './',
  './index.html',
  './manifest.webmanifest',
  './css/style.css',
  './icons/icon.svg',
  './icons/icon-180.png',
  './icons/icon-192.png',
  './icons/icon-512.png',
  './js/app.js',
  './js/router.js',
  './js/defaults.js',
  './js/storage/db.js',
  './js/domain/csv.js',
  './js/domain/format.js',
  './js/domain/stats.js',
  './js/domain/validate.js',
  './js/services/backup.js',
  './js/services/categories.js',
  './js/services/ledger.js',
  './js/views/charts.js',
  './js/views/components.js',
  './js/views/edit.js',
  './js/views/home.js',
  './js/views/list.js',
  './js/views/settings.js',
  './js/views/stats.js',
];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)));
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith('ledger-') && k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET' || new URL(req.url).origin !== location.origin) return;

  e.respondWith(
    caches.open(CACHE).then(async (cache) => {
      const cached = await cache.match(req, { ignoreSearch: req.mode === 'navigate' });
      const network = fetch(req)
        .then((res) => {
          if (res.ok) cache.put(req, res.clone());
          return res;
        })
        .catch(() => cached ?? Response.error());
      e.waitUntil(network.catch(() => {}));
      return cached || network;
    }),
  );
});
