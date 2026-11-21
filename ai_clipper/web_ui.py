"""StreamGrabber Studio and job-scoped media endpoints."""
import hashlib
import zipfile
import json
import os
import re
import secrets
import shutil
import uuid
from pathlib import Path
from threading import BoundedSemaphore, RLock, Thread

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Literal
from .config import ClipperConfig
from .gemini_review import usage
from .sources import stream_url

app = FastAPI(title="StreamGrabber AI", version="4.1.0")
STATIC = Path(__file__).with_name("studio")
STATE = Path(os.getenv("STREAMGRABBER_STATE_DIR", "output/studio-state")).resolve()
SESSION = uuid.uuid4().hex
ACTIVE = BoundedSemaphore(1)
QUEUE = BoundedSemaphore(4)
MUTEX = RLock()
MAX_UPLOAD = max(1, int(os.getenv("STREAMGRABBER_UPLOAD_MB", "90"))) * 1024 * 1024
app.mount("/studio-assets", StaticFiles(directory=STATIC), name="studio-assets")


class Options(BaseModel):
    url: str = Field(default="", max_length=3000)
    num_clips: int = Field(default=3, ge=1, le=10)
    clip_duration: int = Field(default=30, ge=20, le=45)
    quality: Literal["720p", "1080p"] = "1080p"
    subtitle_font: Literal["Sans","Serif","Mono"] = "Sans"
    enable_overlay: bool = True
    creator_tag: str = Field(default="", max_length=32)
    overlay_badge: str = Field(default="GTA VI", max_length=20)
    frame_style: Literal["blur_bg", "fill_crop"] = "blur_bg"
    scan_mode: Literal["full","quick"] = "full"
    range_start: float = Field(0, ge=0, allow_inf_nan=False)
    range_end: float | None = Field(None, gt=0, allow_inf_nan=False)
    whisper_model: Literal["tiny", "base", "small", "medium", "large"] | None = None


def job_path(job_id):
    if not re.fullmatch(r"[a-f0-9]{32}", job_id):
        raise HTTPException(404, "Job not found")
    return STATE/"jobs"/job_id


def source_time(seconds):
    hours, remainder = divmod(int(seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    return (f"{hours}:" if hours else "") + f"{minutes:02}:{seconds:02}"


def update(folder, **changes):
    file = folder/"job.json"
    with MUTEX:
        item = json.loads(file.read_text()) if file.exists() else {"job_id": folder.name, "session": SESSION}
        item.update(changes)
        pending = folder/"job.tmp"
        pending.write_text(json.dumps(item, ensure_ascii=False))
        pending.replace(file)


def read_job(job_id):
    file = job_path(job_id)/"job.json"
    if not file.is_file():
        raise HTTPException(404, "Job not found")
    item = json.loads(file.read_text())
    if item.pop("session", "") != SESSION and item["status"] in ("running", "queued", "paused"):
        item.update(status="error", error="The processing server restarted. Resume a saved recording scan or submit a fresh live DVR snapshot.")
    return item


@app.get("/", response_class=HTMLResponse)
def home():
    return FileResponse(STATIC/"index.html", media_type="text/html")


@app.get("/api/studio/health")
def health():
    from .runtime_memory import low_memory
    return {"service": "streamgrabber-ai", "studio_version": 4, "evidence_required": True,
            "low_memory": low_memory(),
            "long_streams": True, "live_dvr_hours": 20, "scan_modes": ["full","quick"],
            "ffmpeg": bool(shutil.which("ffmpeg")), "max_upload_mb": MAX_UPLOAD//1024//1024}


@app.get("/api/studio/usage")
def quota():
    from .provider_quota import GROQ_KEYS, pending, audio_usage
    configured=sum(bool(os.getenv(k)) for k in GROQ_KEYS)
    return {**usage(),**audio_usage(),"groq_slots":configured, "reserve_percent":1,"paused":pending(),
            "groq_enabled":bool(configured and os.getenv("GROQ_CONFIRMED_FREE_PLAN","").lower()=="true")}


def process(folder, source, opts, source_name):
    from .pipeline import run_pipeline
    def report(pct, msg):
        change = {"resumable":False} if msg == "Reading retained live DVR" else {}
        if msg.startswith("Paused for "):
            stage,reset,section=msg.split(" | ")
            update(folder,status="paused",percent=pct,progress=pct,stage=f"{stage} · {section}",reset_at=reset)
        else:
            update(folder, status="running", percent=pct, progress=pct, stage=msg, reset_at=None, **change)
    try:
        with ACTIVE:
            size = 1080 if opts.quality=="1080p" else 720
            kwargs = dict(output_width=size, output_height=size*16//9, preferred_quality=opts.quality,
                          max_clips=opts.num_clips, clip_duration_target_sec=opts.clip_duration,subtitle_font=opts.subtitle_font,
                          enable_overlay=opts.enable_overlay, creator_tag=opts.creator_tag or os.getenv("CLIPPER_CREATOR_TAG", ""),
                          overlay_badge=opts.overlay_badge, frame_style=opts.frame_style,
                          scan_mode=opts.scan_mode, range_start=opts.range_start, range_end=opts.range_end)
            if opts.whisper_model:
                kwargs["whisper_model"] = opts.whisper_model
            result = run_pipeline(str(source), folder, ClipperConfig(**kwargs), progress=report)
            if result.errors:
                update(folder, status="error", stage="Processing stopped", error=result.errors[0])
                return
            clips = []
            for c in result.clips:
                base = f"/api/studio/jobs/{folder.name}/media/"
                clips.append(dict(id=c.index, title=c.title, duration=c.duration, score=c.score,
                                  start=c.start_time, end=c.end_time, evidence=c.evidence, hashtags=c.hashtags,
                                  file=c.filepath.name, filename=c.filepath.name, thumbnail=c.thumbnail_path.name,
                                  media_url=base+c.filepath.name, download_url=base+c.filepath.name+"?download=1",
                                  thumb_url=base+c.thumbnail_path.name, hook=c.hook_text,
                                  srt_url=base+c.filepath.stem+".srt", captions=bool(c.subtitle_path and c.subtitle_path.stat().st_size),
                                  time_range=f"{source_time(c.start_time)} – {source_time(c.end_time)}"))
            update(folder, status="completed", percent=100, progress=100,
                   stage="Clips ready" if clips else "No qualifying gameplay found",
                   num_clips=len(clips), clips=clips, resumable=False,
                   transcript_url=f"/api/studio/jobs/{folder.name}/transcript",
                   scan_mode=result.metadata.get("scan_mode"), timeline_origin=result.metadata.get("timeline_origin"),
                   available_range=result.metadata.get("available_range"),
                   zip_url=f"/api/studio/jobs/{folder.name}/bundle" if clips else None, video_title=source_name or result.metadata.get("title"),
                   scanned_ranges=result.metadata.get("scanned_ranges", []), warnings=result.metadata.get("warnings",[]))
    except Exception:
        update(folder, status="error", stage="Processing stopped", error="The worker could not complete this job.")
    finally:
        if read_job(folder.name)["status"] == "completed":
            if isinstance(source, Path):
                source.unlink(missing_ok=True)
            shutil.rmtree(folder/".scan", ignore_errors=True)
            (folder/"request.json").unlink(missing_ok=True)
        QUEUE.release()


async def enqueue(opts, tasks, upload=None):
    if (upload is None) == (not opts.url):
        raise HTTPException(422, "Provide one stream URL or one video file.")
    try:
        source = stream_url(opts.url) if opts.url else None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    if opts.range_end is not None and opts.range_end - opts.range_start < 20:
        raise HTTPException(422, "Choose an interval of at least 20 seconds.")
    if not QUEUE.acquire(blocking=False):
        raise HTTPException(429, "The processing queue is full. Try again after the active job finishes.")
    folder = job_path(uuid.uuid4().hex)
    try:
        folder.mkdir(parents=True)
        name = ""
        if upload:
            name = Path(upload.filename or "Gameplay").stem[:100]
            ext = Path(upload.filename or "").suffix.lower()
            if ext not in (".mp4", ".mov", ".mkv", ".webm", ".m4v"):
                raise HTTPException(422, "Choose an MP4, MOV, MKV or WebM recording.")
            source = folder / ("recording"+ext)
            total = 0
            with source.open("wb") as out:
                while chunk := await upload.read(1024*1024):
                    if total == 0 and not (chunk[4:8] in (b"ftyp",b"moov",b"mdat",b"wide") or chunk.startswith(b"\x1a\x45\xdf\xa3")):
                        raise HTTPException(422, "The file is not a supported video container.")
                    total += len(chunk)
                    if total > MAX_UPLOAD:
                        raise HTTPException(413, f"Uploads are limited to {MAX_UPLOAD//1024//1024} MB on this worker. Use the stream link for larger recordings.")
                    out.write(chunk)
                if not total:
                    raise HTTPException(422, "The recording is empty.")
        (folder/"request.json").write_text(json.dumps({"options":opts.model_dump(), "source_name":name,
                                                    "upload":source.name if isinstance(source,Path) else None}))
        update(folder, status="queued",resumable=True, stage="Queued for analysis", percent=1, progress=1,
               num_clips=0, clips=[], error=None)
        tasks.add_task(process, folder, source, opts, name)
        return {"success": True, "status": "started", "job_id": folder.name}
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        QUEUE.release()
        raise


def recover_paused():
    """Resume durable recording jobs when an idle or restarted worker starts again."""
    for path in (STATE/"jobs").glob("*/job.json"):
        try:
            item=json.loads(path.read_text())
            if item.get("status")!="paused" or item.get("session")==SESSION or not item.get("resumable"):
                continue
            folder=path.parent
            saved=json.loads((folder/"request.json").read_text())
            opts=Options(**saved["options"])
            source=folder/saved["upload"] if saved["upload"] else opts.url
            if isinstance(source,Path) and not source.is_file():
                continue
            with MUTEX:
                current=json.loads(path.read_text())
                if current.get("session")==SESSION or current.get("status")!="paused":
                    continue
                if not QUEUE.acquire(blocking=False):
                    continue
                update(folder,session=SESSION,status="queued",stage="Restoring paused scan")
            process(folder,source,opts,saved["source_name"])
        except (OSError, ValueError, KeyError):
            continue


@app.on_event("startup")
def restore_jobs():
    Thread(target=recover_paused,daemon=True,name="restore-paused-jobs").start()


@app.post("/api/studio/jobs/{job_id}/resume")
def resume_job(job_id: str, background_tasks: BackgroundTasks):
    folder = job_path(job_id)
    with MUTEX:
        state = read_job(job_id)
        if state["status"] != "error" or not state.get("resumable") or not (folder/"request.json").is_file():
            raise HTTPException(409, "This job cannot be resumed. Start a new scan.")
        saved = json.loads((folder/"request.json").read_text())
        opts = Options(**saved["options"])
        source = folder/saved["upload"] if saved["upload"] else opts.url
        if isinstance(source,Path) and not source.is_file():
            raise HTTPException(410, "The worker no longer has this recording.")
        if not QUEUE.acquire(blocking=False):
            raise HTTPException(429,"The processing queue is full.")
        update(folder,session=SESSION,status="queued",stage="Resuming saved sections",error=None)
    background_tasks.add_task(process,folder,source,opts,saved["source_name"])
    return {"job_id":job_id,"status":"queued"}


@app.post("/api/ai-shorts")
@app.post("/api/studio/jobs")
async def start_url(req: Options, background_tasks: BackgroundTasks):
    return await enqueue(req, background_tasks)


@app.post("/api/clip")
@app.post("/api/studio/upload")
async def start_upload(background_tasks: BackgroundTasks, url: str = Form(""), file: UploadFile | None=File(None),
                       max_clips: int=Form(3, ge=1, le=10), clip_duration: int=Form(30, ge=20, le=45),
                       quality: Literal["720p","1080p"]=Form("1080p"), enable_overlay: bool=Form(True),
                       creator_tag: str=Form("", max_length=32), overlay_badge: str=Form("GTA VI", max_length=20),
                       subtitle_font: Literal["Sans","Serif","Mono"]=Form("Sans"),
                       frame_style: Literal["blur_bg","fill_crop"]=Form("blur_bg"),
                       scan_mode: Literal["full","quick"]=Form("full"), range_start: float=Form(0,ge=0,allow_inf_nan=False),
                       range_end: float | None=Form(None,gt=0,allow_inf_nan=False),
                       whisper_model: Literal["tiny","base","small","medium","large"] | None=Form(None)):
    opts = Options(url=url, num_clips=max_clips, clip_duration=clip_duration, quality=quality,
                   enable_overlay=enable_overlay, creator_tag=creator_tag, overlay_badge=overlay_badge,
                   subtitle_font=subtitle_font,frame_style=frame_style, whisper_model=whisper_model,scan_mode=scan_mode,
                   range_start=range_start,range_end=range_end)
    return await enqueue(opts, background_tasks, file)


@app.get("/api/ai-shorts/progress/{job_id}")
@app.get("/api/studio/jobs/{job_id}")
def status(job_id: str):
    return read_job(job_id)


@app.get("/api/status")
def legacy_status(job_id: str):
    result = read_job(job_id)
    if result["status"] == "completed":
        result["status"] = "complete"
    return result


@app.get("/api/clips")
def clips(job_id: str):
    return {"clips": read_job(job_id)["clips"]}


@app.get("/api/studio/jobs/{job_id}/transcript")
def transcript(job_id: str):
    path=job_path(job_id)/"transcript.json"
    if read_job(job_id)["status"]!="completed" or not path.is_file():
        raise HTTPException(404,"Transcript unavailable")
    return FileResponse(path, media_type="application/json",filename="transcript.json")


@app.get("/api/studio/jobs/{job_id}/media/{filename}")
def media(job_id: str, filename: str, download: bool=False):
    folder = job_path(job_id)
    if re.fullmatch(r"clip_\d{2}\.mp4", filename):
        path, mime = folder/"clips"/filename, "video/mp4"
    elif re.fullmatch(r"clip_\d{2}\.srt",filename):
        path, mime = folder/"subtitles"/filename, "application/x-subrip"
    elif re.fullmatch(r"clip_\d{2}_thumb\.jpg", filename):
        path, mime = folder/"thumbnails"/filename, "image/jpeg"
    else:
        raise HTTPException(404, "Media not found")
    if not path.is_file():
        raise HTTPException(404, "Media not found")
    return FileResponse(path, media_type=mime, filename=filename if download else None)


@app.get("/api/studio/jobs/{job_id}/bundle")
def bundle(job_id: str):
    job = read_job(job_id)
    if not job["clips"]:
        raise HTTPException(404, "No clips to download")
    folder = job_path(job_id)
    target = folder/"highlights.zip"
    with MUTEX:
        if not target.exists():
            tmp = folder/"bundle.tmp"
            with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_STORED) as archive:
                for clip in job["clips"]:
                    archive.write(folder/"clips"/clip["file"], clip["file"])
            tmp.replace(target)
    return FileResponse(target, media_type="application/zip", filename="StreamGrabber-highlights.zip")


@app.post("/api/studio/jobs/{job_id}/share/{clip_id}")
def make_share(job_id: str, clip_id: int, request: Request):
    if not any(c["id"] == clip_id for c in read_job(job_id)["clips"]):
        raise HTTPException(404, "Clip not found")
    origin = os.getenv("PUBLIC_BASE_URL") or str(request.base_url)
    token = secrets.token_urlsafe(24)
    share_dir = STATE/"shares"
    share_dir.mkdir(parents=True, exist_ok=True)
    data = {"job":job_id, "clip":clip_id}
    (share_dir/hashlib.sha256(token.encode()).hexdigest()).write_text(json.dumps(data))
    return {"url":origin.rstrip("/")+"/s/"+token}


@app.get("/s/{token}")
def shared_clip(token: str):
    if not re.fullmatch(r"[A-Za-z0-9_-]{32}", token):
        raise HTTPException(404, "Shared clip unavailable")
    pointer = STATE/"shares"/hashlib.sha256(token.encode()).hexdigest()
    if not pointer.is_file():
        raise HTTPException(404, "Shared clip unavailable")
    item = json.loads(pointer.read_text())
    return media(item["job"], f"clip_{item['clip']:02d}.mp4")
