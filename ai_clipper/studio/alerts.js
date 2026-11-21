// The open Studio page detects quota events. Android displays notifications through this worker.
self.addEventListener('install',event=>event.waitUntil(self.skipWaiting()));
self.addEventListener('notificationclick',event=>{
  event.notification.close();
  event.waitUntil((async()=>{
    const pages=await self.clients.matchAll({type:'window',includeUncontrolled:true});
    const studio=pages.find(page=>new URL(page.url).origin===self.location.origin);
    if(studio)return studio.focus();
    return self.clients.openWindow('/#library');
  })());
});
