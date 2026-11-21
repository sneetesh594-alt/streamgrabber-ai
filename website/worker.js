// The Python worker owns source media, inference and FFmpeg. This edge serves the studio
// and forwards only its versioned API. Browser cookies and authorization are never forwarded.
const upstream = 'https://streamgrabber-ai.onrender.com';

function embedded(asset, request) {
  const [type, encoding, data] = asset;
  const bytes = encoding === 'binary' ? Uint8Array.from(atob(data), c => c.charCodeAt(0)) : new TextEncoder().encode(data);
  const headers = new Headers({'Content-Type':type,'Accept-Ranges':'bytes','X-Content-Type-Options':'nosniff'});
  headers.set('Cache-Control',type.startsWith('text/html') ? 'no-cache' : 'public, max-age=300');
  const range = request.headers.get('Range');
  if (range) {
    const match = /^bytes=(\d*)-(\d*)$/.exec(range);
    const start = match && match[1] ? Number(match[1]) : Math.max(0, bytes.length-Number(match?.[2]));
    const end = match && match[1] && match[2] ? Math.min(Number(match[2]),bytes.length-1) : bytes.length-1;
    if (!match || !match[1] && !match[2] || !Number.isFinite(start) || start>end || start>=bytes.length) {
      headers.set('Content-Range','bytes */'+bytes.length);
      return new Response(null,{status:416,headers});
    }
    headers.set('Content-Range','bytes '+start+'-'+end+'/'+bytes.length);
    headers.set('Content-Length',String(end-start+1));
    return new Response(request.method==='HEAD'?null:bytes.slice(start,end+1),{status:206,headers});
  }
  headers.set('Content-Length',String(bytes.length));
  return new Response(request.method==='HEAD'?null:bytes,{headers});
}
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;
    if (Object.hasOwn(assets,path) && ['GET','HEAD'].includes(request.method)) return embedded(assets[path],request);
    if (!/^\/api\/studio\/(?:health|usage|upload|jobs(?:\/[a-f0-9]{32}(?:\/(?:resume|bundle|media\/clip_\d{2}(?:\.mp4|_thumb\.jpg)|share\/\d{1,2}))?)?)$/.test(path))
      return new Response('Not found',{status:404});
    if (!['GET','POST','HEAD'].includes(request.method)) return new Response(null,{status:405});
    const headers = new Headers();
    for(const name of ['Content-Type','Range','Accept']) if(request.headers.has(name)) headers.set(name,request.headers.get(name));
    const failure = () => Response.json({detail:'The video worker is starting or updating. Retry in a minute. The sample is available now.'},{status:503});
    try {
      const host = new URL(env?.VIDEO_WORKER_ORIGIN || upstream);
      if (host.protocol!=='https:') return failure();
      const remote=await fetch(new URL(path+url.search,host.origin),{
        method:request.method,headers,body:request.method==='POST'?request.body:undefined,redirect:'manual'
      });
      if (remote.status>=500 || remote.status>=300 && remote.status<400 ||
          (path==='/api/studio/health' && remote.status!==200) ||
          (remote.headers.get('content-type')||'').includes('text/html')) return failure();
      const responseHeaders = new Headers();
      for(const name of ['content-type','content-disposition','content-length','content-range','accept-ranges']) {
        if(remote.headers.has(name)) responseHeaders.set(name,remote.headers.get(name));
      }
      responseHeaders.set('Cache-Control','private, no-store');
      return new Response(remote.body,{status:remote.status,headers:responseHeaders});
    }catch {return failure();}
  }
};
