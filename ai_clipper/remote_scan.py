"""Queue YouTube scans for a trusted, outbound-only Python worker."""
import json
import os
import re
import secrets
import time
from urllib.parse import urlsplit
from pathlib import Path
from threading import RLock

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

LOCK = RLock()
LEASE = 300
last_poll = 0.
ARTIFACT = re.compile(r"(?:clips/clip_\d{2}\.mp4|subtitles/clip_\d{2}\.srt|thumbnails/clip_\d{2}_thumb\.jpg|transcript\.json)")


def enabled(url):
    return bool(os.getenv("STUDIO_WORKER_SHA256") and url and
                urlsplit(str(url)).hostname == "www.youtube.com")


def waiting():
    return time.time()-last_poll > LEASE


def install(app, state_dir, job_path, update):
    def pending():
        root = state_dir()/"jobs"
        for file in sorted(root.glob("*/remote.json"),key=lambda p:p.parent.name):
            yield file, json.loads(file.read_text())

    def save(file, record):
        tmp=file.with_suffix(".tmp")
        tmp.write_text(json.dumps(record))
        tmp.replace(file)

    def owned(folder, request):
        file=folder/"remote.json"
        if not file.exists():
            raise HTTPException(409,"Job is no longer leased")
        record=json.loads(file.read_text())
        if not secrets.compare_digest(record.get("lease",""),request.headers.get("x-lease","!")):
            raise HTTPException(409,"Worker lease changed")
        return file,record

    @app.post("/worker/claim")
    def claim():
        global last_poll
        with LOCK:
            last_poll=time.time()
            for file, record in pending():
                if record.get("until",0)>last_poll:
                    continue
                job=json.loads((file.parent/"job.json").read_text())
                if job["status"] in ("error","completed"):
                    file.unlink(missing_ok=True)
                    continue
                lease=secrets.token_hex(24)
                save(file,{"lease":lease,"until":last_poll+LEASE})
                update(file.parent, session=job.get("session",""),status="running",stage="Private worker is reading the YouTube recording")
                return {"job_id":file.parent.name,"lease":lease,"options":json.loads((file.parent/"request.json").read_text())["options"]}
        return {}

    @app.post("/worker/{job_id}/status")
    async def report(job_id:str, request:Request):
        global last_poll
        folder=job_path(job_id)
        status=await request.json()
        with LOCK:
            file,record=owned(folder,request)
            last_poll=time.time()
            save(file,{**record,"until":last_poll+LEASE})
            status={k:v for k,v in status.items() if k in {
                "status","stage","percent","progress","reset_at","error","source_error","clips","num_clips","resumable",
                "analysis","channel","video_id","duration_sec","transcript_url","scan_mode","timeline_origin","available_range","zip_url","video_title","scanned_ranges","warnings"}}
            if status.get("status") not in ("running","paused","completed","error"):
                raise HTTPException(422,"Invalid worker state")
            update(folder,**status)
            if status["status"] in ("completed","error"):
                file.unlink()
        return {"ok":True}

    @app.put("/worker/{job_id}/files/{name:path}")
    async def artifact(job_id:str,name:str,request:Request):
        folder=job_path(job_id)
        if not ARTIFACT.fullmatch(name):
            raise HTTPException(422,"Unsupported output")
        with LOCK:
            owned(folder,request)
        dest=folder/name
        dest.parent.mkdir(exist_ok=True)
        temp=dest.with_name("."+secrets.token_hex(12)+".part")
        try:
            total=0
            with temp.open("xb") as out:
                async for block in request.stream():
                    total+=len(block)
                    if total>200*1024**2:
                        raise HTTPException(413,"Clip exceeds transfer limit")
                    out.write(block)
            with LOCK:
                owned(folder,request)
                temp.replace(dest)
        finally:
            temp.unlink(missing_ok=True)
        return JSONResponse({"ok":True})


def enqueue(folder, update):
    with LOCK:
        if sum(1 for _ in folder.parent.glob("*/remote.json"))>=4:
            raise HTTPException(429,"The private worker queue is full. Try again after a scan finishes.")
        update(folder,status="queued", stage="Waiting for the private worker to connect" if waiting() else "Queued on the private worker")
        (folder/"remote.json").write_text("{}")
