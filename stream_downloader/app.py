import os
import sys
import uuid
import json
import shutil
import asyncio
import subprocess
import wave
import struct
import math
import re
from pathlib import Path
from typing import Optional, Dict, Any, List

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

import yt_dlp
from yt_dlp.postprocessor.ffmpeg import FFmpegPostProcessor

# Set up FFmpeg path (supports Windows local and Linux / Docker)
BIN_DIR = Path(__file__).resolve().parent.parent / "bin"
ffmpeg_win = BIN_DIR / "ffmpeg.exe"
if ffmpeg_win.exists():
    FFMPEG_EXE = str(ffmpeg_win)
    os.environ["PATH"] = str(BIN_DIR) + os.pathsep + os.environ.get("PATH", "")
else:
    FFMPEG_EXE = shutil.which("ffmpeg") or "ffmpeg"

try:
    FFmpegPostProcessor._ffmpeg_location.set(FFMPEG_EXE)
except Exception:
    pass

# Base Directories
BASE_DIR = Path(__file__).resolve().parent
DOWNLOADS_DIR = BASE_DIR / "downloads"
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
CLIPS_DIR = DOWNLOADS_DIR / "ai_shorts"
CLIPS_DIR.mkdir(parents=True, exist_ok=True)

TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

# Keep the existing downloader alongside the shared evidence-based studio.
from ai_clipper.web_ui import app
from ai_clipper.sources import stream_url

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/media", StaticFiles(directory=str(DOWNLOADS_DIR)), name="media")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# In-memory storage for download & AI jobs
JOBS: Dict[str, Dict[str, Any]] = {}



class VideoInfoRequest(BaseModel):
    url: str


class DownloadRequest(BaseModel):
    url: str
    quality: str = "720p"
    format_type: str = "mp4"
    start_time: Optional[str] = None
    end_time: Optional[str] = None


def find_node_path() -> Optional[str]:
    for cand in [shutil.which("node"), shutil.which("nodejs"), "/usr/bin/node", "/usr/bin/nodejs", "/usr/local/bin/node", r"C:\Program Files\nodejs\node.exe"]:
        if cand and Path(cand).exists():
            return str(cand)
    return None

NODE_PATH = find_node_path()


def normalize_url(url: str) -> str:
    try:
        return stream_url(url)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


def get_ydl_base_opts(for_url: Optional[str] = None) -> Dict[str, Any]:
    """Base options for yt-dlp across YouTube and other platforms."""
    opts: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "remote_components": ["ejs:github"],
        "retries": 10,
        "fragment_retries": 10,
        "socket_timeout": 30,
    }

    is_youtube = True
    if for_url:
        u_low = for_url.lower()
        if not any(k in u_low for k in ["youtube.com", "youtu.be"]):
            is_youtube = False

    if is_youtube:
        opts["extractor_args"] = {
            "youtube": {
                "player_client": ["tv_samsung", "visionos", "android"]
            }
        }
        if NODE_PATH and Path(NODE_PATH).exists():
            opts["js_runtimes"] = {"node": {"path": str(NODE_PATH)}}

    if check_ffmpeg_installed():
        opts["ffmpeg_location"] = FFMPEG_EXE

    # Auto-load cookies.txt if provided (local directory or Render /etc/secrets)
    cookie_candidates = [
        BASE_DIR / "cookies.txt",
        BASE_DIR.parent / "cookies.txt",
        Path("/etc/secrets/cookies.txt"),
    ]
    for cpath in cookie_candidates:
        if cpath.exists():
            opts["cookiefile"] = str(cpath)
            break

    return opts


def check_ffmpeg_installed() -> bool:
    return Path(FFMPEG_EXE).exists() or shutil.which("ffmpeg") is not None


def get_bold_font_path() -> str:
    """Returns absolute path to a bold font on Windows or Linux / Docker for FFmpeg drawtext."""
    candidates = [
        # Windows fonts
        "C:/Windows/Fonts/arialbd.ttf",   # Arial Bold
        "C:/Windows/Fonts/segoeuib.ttf",  # Segoe UI Bold
        "C:/Windows/Fonts/impact.ttf",    # Impact
        "C:/Windows/Fonts/arial.ttf",      # Arial Regular
        # Linux / Docker standard font locations
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    ]
    for c in candidates:
        if Path(c).exists():
            return c.replace(":", r"\:")
    return "Sans:style=Bold"


@app.get("/downloader", response_class=HTMLResponse)
async def index(request: Request):
    has_ffmpeg = check_ffmpeg_installed()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"has_ffmpeg": has_ffmpeg}
    )


@app.post("/api/info")
async def get_video_info(data: VideoInfoRequest):
    """Fetches video/stream metadata for YouTube, Twitch, Kick, and Social Media."""
    url = normalize_url(data.url)
    if not url:
        raise HTTPException(status_code=400, detail="URL cannot be empty")

    ydl_opts = get_ydl_base_opts(for_url=url)
    ydl_opts["skip_download"] = True
    ydl_opts["extract_flat"] = False

    try:
        loop = asyncio.get_event_loop()
        def extract():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=False)

        info = await loop.run_in_executor(None, extract)

        is_live = info.get("is_live", False)
        was_live = info.get("was_live", False)

        duration_sec = info.get("duration", 0)
        if duration_sec:
            m, s = divmod(int(duration_sec), 60)
            h, m = divmod(m, 60)
            duration_str = f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
        else:
            duration_str = "LIVE STREAM" if is_live else "Unknown"

        uploader = (
            info.get("uploader") or 
            info.get("channel") or 
            info.get("creator") or 
            info.get("uploader_id") or 
            "Creator"
        )

        return {
            "success": True,
            "id": info.get("id"),
            "title": info.get("title", "Stream / Video"),
            "uploader": uploader,
            "thumbnail": info.get("thumbnail"),
            "duration": duration_str,
            "duration_sec": duration_sec or 0,
            "is_live": is_live,
            "was_live": was_live,
            "view_count": info.get("view_count", 0),
            "description": (info.get("description") or "")[:250],
        }

    except Exception as e:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": str(e)}
        )


def _progress_hook(job_id: str):
    def hook(d):
        if job_id not in JOBS:
            return

        status = d.get("status")
        if status == "downloading":
            total_bytes = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes", 0)
            speed = d.get("speed") or 0
            eta = d.get("eta") or 0

            percent = 0.0
            if total_bytes > 0:
                percent = round((downloaded / total_bytes) * 100, 1)
            elif downloaded > 0:
                percent = min(95.0, round((downloaded / (100 * 1024 * 1024)) * 10, 1))

            if speed > 1024 * 1024:
                speed_str = f"{speed / (1024 * 1024):.2f} MB/s"
            elif speed > 1024:
                speed_str = f"{speed / 1024:.1f} KB/s"
            else:
                speed_str = f"{speed} B/s"

            if eta:
                eta_m, eta_s = divmod(int(eta), 60)
                eta_str = f"{eta_m}m {eta_s}s" if eta_m else f"{eta_s}s"
            else:
                eta_str = "calculating..."

            JOBS[job_id].update({
                "status": "downloading",
                "percent": percent,
                "downloaded_bytes": downloaded,
                "total_bytes": total_bytes,
                "speed": speed_str,
                "eta": eta_str,
            })

        elif status == "finished":
            JOBS[job_id]["status"] = "processing"
            JOBS[job_id]["percent"] = 99.0
            JOBS[job_id]["eta"] = "merging video and audio..."

    return hook


def _run_download(job_id: str, req: DownloadRequest):
    """Background task for downloading full video/audio."""
    target_url = normalize_url(req.url)
    output_template = str(DOWNLOADS_DIR / f"%(title).70s_%(id)s_{job_id[:6]}.%(ext)s")

    height_map = {
        "1080p": "1080",
        "720p": "720",
        "480p": "480",
        "360p": "360",
    }
    target_h = height_map.get(req.quality, "720")

    if req.format_type == "mp3":
        ydl_format = "bestaudio/best"
    else:
        ydl_format = (
            f"bestvideo[height<={target_h}][ext=mp4]+bestaudio[ext=m4a]/"
            f"bestvideo[height<={target_h}]+bestaudio/"
            f"best[height<={target_h}]/"
            f"best"
        )

    ydl_opts = get_ydl_base_opts(for_url=target_url)
    ydl_opts.update({
        "format": ydl_format,
        "outtmpl": output_template,
        "progress_hooks": [_progress_hook(job_id)],
        "live_from_start": True,
        "merge_output_format": "mp4",
        "retries": 10,
        "fragment_retries": 10,
        "socket_timeout": 60,
    })

    if req.format_type == "mp3":
        ydl_opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]

    if req.start_time and req.end_time:
        try:
            ydl_opts["download_ranges"] = yt_dlp.utils.download_range_func(
                None,
                [(req.start_time, req.end_time)]
            )
        except Exception:
            pass

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            extract_info = ydl.extract_info(target_url, download=True)
            
            filename = None
            if "requested_downloads" in extract_info and extract_info["requested_downloads"]:
                filename = Path(extract_info["requested_downloads"][0]["filepath"]).name
            else:
                matches = list(DOWNLOADS_DIR.glob(f"*{job_id[:6]}*"))
                if matches:
                    filename = matches[0].name

            file_size_bytes = 0
            if filename and (DOWNLOADS_DIR / filename).exists():
                file_size_bytes = (DOWNLOADS_DIR / filename).stat().st_size

            JOBS[job_id].update({
                "status": "completed",
                "percent": 100.0,
                "filename": filename,
                "file_size": file_size_bytes,
                "title": extract_info.get("title", "Video"),
            })

    except Exception as e:
        JOBS[job_id].update({
            "status": "error",
            "error": str(e),
        })


@app.post("/api/download")
async def start_download(req: DownloadRequest, background_tasks: BackgroundTasks):
    url = req.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    job_id = str(uuid.uuid4())
    JOBS[job_id] = {
        "job_id": job_id,
        "url": url,
        "status": "queued",
        "percent": 0.0,
        "speed": "0 KB/s",
        "eta": "connecting to stream...",
        "filename": None,
        "error": None,
        "title": "Fetching stream...",
    }

    background_tasks.add_task(_run_download, job_id, req)
    return {"success": True, "job_id": job_id}


@app.get("/api/progress/{job_id}")
async def get_progress(job_id: str):
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    return JOBS[job_id]


# =====================================================================
# AI GEMINI HOOK GENERATOR & ULTRA-FAST SMART SEGMENT CLIPPING
# =====================================================================

@app.get("/api/downloads")
async def list_downloads():
    files = []
    for file_path in sorted(DOWNLOADS_DIR.glob("*"), key=lambda f: f.stat().st_mtime, reverse=True):
        if file_path.is_file() and not file_path.name.endswith(".part"):
            size_mb = round(file_path.stat().st_size / (1024 * 1024), 2)
            files.append({
                "filename": file_path.name,
                "size_mb": size_mb,
                "download_url": f"/download/{file_path.name}",
                "media_url": f"/media/{file_path.name}",
                "is_video": file_path.suffix.lower() in [".mp4", ".mkv", ".webm"],
                "created_at": file_path.stat().st_mtime,
            })
    return {"files": files}


@app.get("/download/{filename}")
async def download_file(filename: str):
    file_path = DOWNLOADS_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type="application/octet-stream"
    )


@app.delete("/api/delete/{filename}")
async def delete_file(filename: str):
    file_path = DOWNLOADS_DIR / filename
    if file_path.exists():
        try:
            file_path.unlink()
            return {"success": True}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    raise HTTPException(status_code=404, detail="File not found")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
