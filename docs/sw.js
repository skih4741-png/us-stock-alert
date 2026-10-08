// 앱 화면 틀만 저장해요(오프라인에서도 열리게). 주식 데이터는 저장하지 않아요.
const CACHE = "stock-app-v2";
const SHELL = ["./", "index.html", "style.css?v=2", "app.js?v=2", "config.js?v=2", "manifest.webmanifest",
  "icons/icon-192.png", "icons/apple-touch-icon.png", "icons/favicon.png"];
self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.origin !== location.origin) return;  // 로그인 서버 요청은 건드리지 않음
  // 화면 틀: 먼저 새로 받고, 안 되면 저장본
  e.respondWith(fetch(e.request, { cache: "no-cache" }).then(r => {
    const copy = r.clone();
    caches.open(CACHE).then(c => c.put(e.request, copy));
    return r;
  }).catch(() => caches.match(e.request).then(r => r || caches.match("index.html"))));
});
