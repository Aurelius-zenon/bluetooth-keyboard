/* Service Worker — 导航请求走网络优先，静态资源走缓存 */
const CACHE = 'bt-keyboard-v18';
/* 桥接 API：绝不能走缓存，否则 /diag、/windows 会永远返回第一次的旧数据 */
const API_PATHS = new Set([
  '/ping', '/health', '/diag', '/windows', '/target', '/key', '/hold', '/mouse',
]);
const CORE_ASSETS = [
  './',
  './index.html',
  './manifest.webmanifest',
  './icons/icon-192.png',
  './icons/icon-512.png',
  './icons/icon-maskable-512.png',
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE)
      .then((c) => c.addAll(CORE_ASSETS).catch(() => {}))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  const url = new URL(req.url);

  // 只接管同源 GET
  if (req.method !== 'GET' || url.origin !== self.location.origin) return;
  // 桥接接口不缓存
  if (API_PATHS.has(url.pathname)) return;

  // 页面导航：网络优先，失败回落缓存
  if (req.mode === 'navigate') {
    e.respondWith(
      fetch(req)
        .then((resp) => {
          const copy = resp.clone();
          caches.open(CACHE).then((c) => c.put(req, copy));
          return resp;
        })
        .catch(() => caches.match(req).then((c) => c || caches.match('./index.html')))
    );
    return;
  }

  // 其他静态资源：缓存优先
  e.respondWith(
    caches.match(req).then((cached) => cached || fetch(req).then((resp) => {
      if (resp.ok) {
        const copy = resp.clone();
        caches.open(CACHE).then((c) => c.put(req, copy));
      }
      return resp;
    }).catch(() => cached))
  );
});
