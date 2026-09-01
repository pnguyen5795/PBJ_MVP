const CACHE = "pbj-shell-v9";
const SHELL = [
  "/static/app.css",
  "/static/workflow.css",
  "/static/mobile-v2.css",
  "/static/troy-foundation.css",
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
  if (!url.pathname.startsWith("/static/")) return;
  event.respondWith(caches.match(event.request).then(hit => hit || fetch(event.request)));
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
