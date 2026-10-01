// Offline support. Online: always fetch the newest version (so updates show up on the next
// open). Offline or slow network: fall back to the cached copy.
const VERSION = "bt-web-1.7.0";
const SHELL = ["./", "index.html", "app.js", "engine.js", "lock.js", "styles.css", "manifest.webmanifest",
  "icons/icon-180.png", "icons/icon-192.png", "icons/icon-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  if (e.request.method !== "GET" || new URL(e.request.url).origin !== location.origin) return;
  e.respondWith(caches.open(VERSION).then(async (cache) => {
    const hit = await cache.match(e.request, { ignoreSearch: true });
    const net = fetch(e.request, { cache: "no-cache" })
      .then((res) => { if (res.ok) cache.put(e.request, res.clone()); return res; });
    if (!hit) return net;
    // give the network 3 seconds, then use the cached copy
    const timeout = new Promise((resolve) => setTimeout(() => resolve(hit), 3000));
    return Promise.race([net.catch(() => hit), timeout]);
  }));
});
