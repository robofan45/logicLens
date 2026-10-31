// LogicLens service worker: offline app shell. API calls (/api, /health) are never cached:
// recognition and AI need the live server, and responses can contain user programs.
const CACHE = "logiclens-shell-v2";
const SHELL = ["/", "/analyzer", "/history", "/docs", "/manifest.webmanifest", "/icon.svg", "/icon-192.png", "/icon-512.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/") || url.pathname === "/health") return;
  if (req.mode === "navigate") {
    // network first for pages, fall back to the cached shell when offline
    event.respondWith(fetch(req).catch(() => caches.match("/analyzer").then((r) => r || caches.match("/"))));
    return;
  }
  // hashed build assets: cache first, then network (and remember)
  event.respondWith(
    caches.match(req).then(
      (hit) =>
        hit ||
        fetch(req).then((res) => {
          if (res.ok && url.pathname.startsWith("/assets/")) {
            const copy = res.clone();
            caches.open(CACHE).then((c) => c.put(req, copy));
          }
          return res;
        }),
    ),
  );
});
