const CACHE = "pbj-shell-v21";
const SHELL = [
  "/offline",
  "/static/app.css?v=21",
  "/static/workflow.css?v=21",
  "/static/mobile-v2.css?v=21",
  "/static/troy-foundation.css?v=21",
  "/static/troy-screens.css?v=21",
  "/static/brand/sandwich-logo.png",
  "/static/brand/sandwich/bottom-bread.png",
  "/static/brand/sandwich/peanut-butter.png",
  "/static/brand/sandwich/jelly.png",
  "/static/brand/sandwich/top-bread.png",
  "/static/icons/pbj-192.png",
  "/static/icons/pbj-512.png"
];

self.addEventListener("install", event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key !== CACHE).map(key => caches.delete(key)))));
  self.clients.claim();
});

self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== location.origin) return;
  if (event.request.mode === "navigate") {
    event.respondWith(fetch(event.request).catch(() => caches.match("/offline")));
    return;
  }
  if (url.pathname.startsWith("/static/")) {
    event.respondWith(
      fetch(event.request).then(response => {
        if (!response.ok) {
          return caches.match(event.request).then(hit => hit || response);
        }
        const copy = response.clone();
        caches.open(CACHE).then(cache => cache.put(event.request, copy));
        return response;
      }).catch(() => caches.match(event.request))
    );
  }
});

self.addEventListener("push", event => {
  const data = event.data ? event.data.json() : {};
  event.waitUntil(self.registration.showNotification(data.title || "PBJ", {
    body: data.body || "Your edit has an update.",
    icon: "/static/icons/pbj-192.png",
    badge: "/static/icons/pbj-192.png",
    data: {url: data.url || "/projects"}
  }));
});

self.addEventListener("notificationclick", event => {
  event.notification.close();
  event.waitUntil(clients.openWindow(event.notification.data.url || "/projects"));
});
