// Unshacklarr's service worker: shows its push notifications, even with the app closed.
self.addEventListener("push", (event) => {
  let msg = {};
  try { msg = event.data ? event.data.json() : {}; } catch { msg = { title: "Unshacklarr", body: event.data?.text() || "" }; }
  event.waitUntil(self.registration.showNotification(msg.title || "Unshacklarr", {
    body: msg.body || "", icon: "/icon-192.png", badge: "/icon-192.png", tag: msg.title, data: { url: "/#/inbox" },
  }));
});
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((wins) => {
    const open = wins.find((w) => new URL(w.url).origin === self.location.origin);
    const url = event.notification.data.url;
    // navigate() rejects for a window this worker does not control: open the page in a new one then
    return open ? open.focus().then((w) => w.navigate(url)).catch(() => self.clients.openWindow(url)) : self.clients.openWindow(url);
  }));
});
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));
