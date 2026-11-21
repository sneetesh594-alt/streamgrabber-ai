"""Shared invite-link access for the studio and its legacy endpoints."""
import hashlib
import os
import secrets

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse

COOKIE = "__Host-studio_access"
PAGE = """<!doctype html><html lang="en"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer"><title>Private StreamGrabber Studio</title>
<style>body{color:#f7f4f3;background:#131317;font:18px system-ui;margin:12vh auto;padding:1.5rem;max-width:34rem}p{color:#cbc4cc}</style>
<h1>Private StreamGrabber Studio</h1><p id="status">Open the complete invite link shared with you to use the clipper.</p>
<script>(async()=>{const token=new URLSearchParams(location.hash.slice(1)).get('invite');
if(!token)return;history.replaceState(null,'',location.pathname);const s=document.getElementById('status');
try{const r=await fetch('/access',{method:'POST',headers:{'Authorization':'Bearer '+token}});
if(r.ok)location.replace('/');else s.textContent='This invite is invalid or has been replaced.';}
catch{ s.textContent='Connection failed. Reopen the original invite to try again.';}})();</script></html>"""


def matches(token, digest):
    return bool(digest and token and len(token) <= 256 and
                secrets.compare_digest(hashlib.sha256(token.encode()).hexdigest(), digest))


def install(app):
    @app.middleware("http")
    async def protect(request: Request, call_next):
        path = request.url.path
        digest = os.getenv("STUDIO_INVITE_SHA256")
        if path.startswith("/worker/"):
            token = request.headers.get("authorization", "").removeprefix("Bearer ")
            if not matches(token, os.getenv("STUDIO_WORKER_SHA256")):
                return JSONResponse({"detail":"Worker authentication required"}, status_code=403)
        elif digest and path != "/api/studio/health":
            if path == "/access" and request.method == "POST":
                token = request.headers.get("authorization", "").removeprefix("Bearer ")
                if not matches(token, digest):
                    return JSONResponse({"detail":"Invalid invite"}, status_code=403)
                response = JSONResponse({"ok":True}, headers={"Cache-Control":"no-store"})
                response.set_cookie(COOKIE,token,httponly=True,secure=True,samesite="strict",max_age=2592000)
                return response
            if not matches(request.cookies.get(COOKIE), digest):
                headers={"Cache-Control":"private, no-store","Referrer-Policy":"no-referrer"}
                if path in ("/","/invite") and request.method in ("GET","HEAD"):
                    return HTMLResponse(PAGE, headers=headers)
                return JSONResponse({"detail":"Open your private studio invite."}, status_code=403,headers=headers)
        response = await call_next(request)
        if digest:
            response.headers["Cache-Control"]="private, no-store"
            response.headers["Referrer-Policy"]="no-referrer"
        return response
