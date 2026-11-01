/* 班务通 Service Worker：只负责接推送、点通知回页面，不做离线缓存。 */
self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("push", (event) => {
  let payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch (error) {
    payload = { title: "班务通", body: event.data ? event.data.text() : "" };
  }
  const title = payload.title || "班务通";
  const options = {
    body: payload.body || "",
    icon: "/static/icon-192.png",
    badge: "/static/icon-192.png",
    tag: payload.tag || undefined,
    data: { url: payload.url || "/" },
    requireInteraction: true,
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    self.clients
      .matchAll({ type: "window", includeUncontrolled: true })
      .then((windows) => {
        for (const client of windows) {
          if (client.url.indexOf(self.location.origin) === 0) {
            client.navigate(target);
            return client.focus();
          }
        }
        return self.clients.openWindow(target);
      }),
  );
});
