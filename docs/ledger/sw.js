// Service Worker：快取 App 檔案，沒有網路也能開啟。
// 策略：有網路時一律先抓最新版（略過瀏覽器的 HTTP 快取，GitHub Pages 預設會快取 10 分鐘），
// 抓到就更新快取；沒網路或 3 秒內沒回應才用快取。這樣一更新程式，下次打開就是新版。
// 新增或改名檔案時，記得更新 ASSETS 並把 VERSION 加 1。
const VERSION = 7;
const NETWORK_TIMEOUT = 3000;
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
  './js/config.js',
  './js/sample.js',
  './js/router.js',
  './js/defaults.js',
  './js/storage/db.js',
  './js/domain/amount.js',
  './js/domain/budget.js',
  './js/domain/csv.js',
  './js/domain/format.js',
  './js/domain/gmail.js',
  './js/domain/inbox.js',
  './js/domain/recurring.js',
  './js/domain/stats.js',
  './js/domain/validate.js',
  './js/services/backup.js',
  './js/services/budget.js',
  './js/services/categories.js',
  './js/services/inbox.js',
  './js/services/ledger.js',
  './js/services/preview.js',
  './js/services/recurring.js',
  './js/views/applepay.js',
  './js/views/budget.js',
  './js/views/charts.js',
  './js/views/components.js',
  './js/views/edit.js',
  './js/views/home.js',
  './js/views/list.js',
  './js/views/recurring.js',
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
  e.respondWith(networkFirst(e, req));
});

async function networkFirst(e, req) {
  const cache = await caches.open(CACHE);
  const navigate = req.mode === 'navigate';
  // 換頁請求不能帶其他設定重建，只能用網址重新發出
  const fresh = navigate ? fetch(req.url, { cache: 'no-cache' }) : fetch(req, { cache: 'no-cache' });
  const network = fresh.then((res) => {
    if (res.ok) {
      // 換頁的網址可能帶 #，快取時統一存成首頁
      e.waitUntil(cache.put(navigate ? './' : req, res.clone()));
    }
    return res;
  });
  e.waitUntil(network.catch(() => {}));

  const timeout = new Promise((resolve) => setTimeout(resolve, NETWORK_TIMEOUT, null));
  try {
    const res = await Promise.race([network, timeout]);
    if (res) return res;
  } catch {
    // 沒網路：往下用快取
  }
  const cached = navigate ? await cache.match('./') : await cache.match(req);
  return cached ?? network.catch(() => Response.error());
}
