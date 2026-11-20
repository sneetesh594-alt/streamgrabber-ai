"""
FastAPI Web UI - Browser se AI Video Clipper chalao.

Endpoints:
  GET  /           → Home page (upload form)
  POST /api/clip   → Start clipping pipeline
  GET  /api/status → Pipeline status check
  GET  /api/clips  → List generated clips
  GET  /clips/{filename} → Download a clip
"""

import asyncio
import uuid
import json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(
    title="AI Video Clipper",
    description="Automatic highlight detection and clip generation",
    version="0.1.0",
)

# In-memory job tracking
jobs: dict[str, dict] = {}

OUTPUT_BASE = Path("./output")
UPLOAD_DIR = Path("./uploads")


@app.get("/", response_class=HTMLResponse)
async def home():
    """Home page with upload form and URL input."""
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>🎬 AI Video Clipper</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: linear-gradient(135deg, #0f0c29, #302b63, #24243e);
                color: #fff;
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
            }
            .container {
                max-width: 700px;
                width: 90%;
                padding: 40px;
                background: rgba(255,255,255,0.08);
                border-radius: 20px;
                backdrop-filter: blur(10px);
                border: 1px solid rgba(255,255,255,0.15);
            }
            h1 { text-align: center; font-size: 2.2em; margin-bottom: 10px; }
            .subtitle { text-align: center; color: #aaa; margin-bottom: 30px; }
            .form-group { margin-bottom: 20px; }
            label { display: block; margin-bottom: 8px; font-weight: 600; color: #ccc; }
            input[type="text"], input[type="number"], select {
                width: 100%; padding: 12px 16px;
                background: rgba(255,255,255,0.1);
                border: 1px solid rgba(255,255,255,0.2);
                border-radius: 10px; color: #fff; font-size: 16px;
            }
            input::placeholder { color: #666; }
            .or-divider {
                text-align: center; color: #666; margin: 20px 0;
                position: relative;
            }
            .or-divider::before, .or-divider::after {
                content: ""; position: absolute; top: 50%;
                width: 40%; height: 1px; background: rgba(255,255,255,0.2);
            }
            .or-divider::before { left: 0; }
            .or-divider::after { right: 0; }
            .file-upload {
                border: 2px dashed rgba(255,255,255,0.3);
                border-radius: 12px; padding: 30px;
                text-align: center; cursor: pointer;
                transition: border-color 0.3s;
            }
            .file-upload:hover { border-color: #7c4dff; }
            .file-upload input { display: none; }
            .options-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }
            button {
                width: 100%; padding: 14px;
                background: linear-gradient(90deg, #7c4dff, #448aff);
                border: none; border-radius: 12px;
                color: white; font-size: 18px; font-weight: 700;
                cursor: pointer; margin-top: 20px;
                transition: transform 0.2s, opacity 0.2s;
            }
            button:hover { transform: translateY(-2px); opacity: 0.9; }
            button:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }
            #status {
                margin-top: 20px; padding: 15px;
                background: rgba(255,255,255,0.05);
                border-radius: 10px; display: none;
            }
            .progress-bar {
                height: 6px; background: rgba(255,255,255,0.1);
                border-radius: 3px; overflow: hidden; margin-top: 10px;
            }
            .progress-fill {
                height: 100%; background: linear-gradient(90deg, #7c4dff, #448aff);
                width: 0%; transition: width 0.5s;
            }
            #clips-list { margin-top: 20px; }
            .clip-card {
                background: rgba(255,255,255,0.08);
                border-radius: 10px; padding: 15px;
                margin-bottom: 10px; display: flex;
                align-items: center; gap: 15px;
            }
            .clip-card img { width: 120px; height: 68px; border-radius: 6px; object-fit: cover; }
            .clip-info { flex: 1; }
            .clip-info h3 { font-size: 14px; margin-bottom: 4px; }
            .clip-info p { font-size: 12px; color: #aaa; }
            .download-btn {
                padding: 8px 16px; background: #7c4dff;
                border: none; border-radius: 8px;
                color: white; cursor: pointer; font-size: 13px;
                text-decoration: none;
            }
            .disclaimer {
                margin-top: 25px; padding: 12px;
                background: rgba(255,165,0,0.1);
                border-left: 3px solid orange;
                border-radius: 6px; font-size: 12px; color: #ccc;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🎬 AI Video Clipper</h1>
            <p class="subtitle">Auto-detect highlights and generate vertical Shorts</p>

            <form id="clipForm">
                <div class="form-group">
                    <label>📎 YouTube URL</label>
                    <input type="text" id="url" name="url"
                           placeholder="https://youtube.com/watch?v=...">
                </div>

                <div class="or-divider">OR</div>

                <div class="form-group">
                    <div class="file-upload" onclick="document.getElementById('file').click()">
                        <p>📁 Click to upload video file</p>
                        <p style="font-size:12px;color:#666;margin-top:5px">MP4, MKV, AVI, MOV</p>
                        <input type="file" id="file" name="file" accept="video/*">
                    </div>
                    <p id="fileName" style="margin-top:8px;color:#7c4dff;font-size:13px"></p>
                </div>

                <div class="options-grid">
                    <div class="form-group">
                        <label>Max Clips</label>
                        <input type="number" id="maxClips" value="10" min="1" max="50">
                    </div>
                    <div class="form-group">
                        <label>Clip Duration (sec)</label>
                        <input type="number" id="clipDuration" value="30" min="10" max="120">
                    </div>
                    <div class="form-group">
                        <label>Quality</label>
                        <select id="quality">
                            <option value="480p">480p</option>
                            <option value="720p" selected>720p</option>
                            <option value="1080p">1080p</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Whisper Model</label>
                        <select id="whisperModel">
                            <option value="tiny">Tiny (fastest)</option>
                            <option value="base" selected>Base</option>
                            <option value="small">Small</option>
                            <option value="medium">Medium</option>
                            <option value="large">Large (best)</option>
                        </select>
                    </div>
                </div>

                <button type="submit" id="startBtn">🚀 Start Clipping</button>
            </form>

            <div id="status">
                <p id="statusText">Processing...</p>
                <div class="progress-bar">
                    <div class="progress-fill" id="progressFill"></div>
                </div>
            </div>

            <div id="clips-list"></div>

            <div class="disclaimer">
                ⚖️ <strong>Disclaimer:</strong> Only process videos you own or have permission
                to use. This tool is for personal/educational use only. Adding subtitles or
                cropping does not clear copyright.
            </div>
        </div>

        <script>
        document.getElementById('file').addEventListener('change', function(e) {
            document.getElementById('fileName').textContent =
                e.target.files[0] ? '📄 ' + e.target.files[0].name : '';
        });

        document.getElementById('clipForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            const btn = document.getElementById('startBtn');
            const statusDiv = document.getElementById('status');
            btn.disabled = true;
            btn.textContent = '⏳ Processing...';
            statusDiv.style.display = 'block';

            const formData = new FormData();
            const url = document.getElementById('url').value;
            const file = document.getElementById('file').files[0];

            if (url) formData.append('url', url);
            if (file) formData.append('file', file);
            formData.append('max_clips', document.getElementById('maxClips').value);
            formData.append('clip_duration', document.getElementById('clipDuration').value);
            formData.append('quality', document.getElementById('quality').value);
            formData.append('whisper_model', document.getElementById('whisperModel').value);

            try {
                const resp = await fetch('/api/clip', { method: 'POST', body: formData });
                const data = await resp.json();

                if (data.job_id) {
                    pollStatus(data.job_id);
                } else {
                    document.getElementById('statusText').textContent = '❌ ' + (data.error || 'Failed');
                    btn.disabled = false;
                    btn.textContent = '🚀 Start Clipping';
                }
            } catch(err) {
                document.getElementById('statusText').textContent = '❌ Error: ' + err.message;
                btn.disabled = false;
                btn.textContent = '🚀 Start Clipping';
            }
        });

        async function pollStatus(jobId) {
            const statusText = document.getElementById('statusText');
            const progressFill = document.getElementById('progressFill');

            const interval = setInterval(async () => {
                try {
                    const resp = await fetch('/api/status?job_id=' + jobId);
                    const data = await resp.json();

                    statusText.textContent = data.stage || 'Processing...';
                    progressFill.style.width = (data.progress || 0) + '%';

                    if (data.status === 'complete') {
                        clearInterval(interval);
                        statusText.textContent = '✅ Done! ' + data.num_clips + ' clips generated';
                        progressFill.style.width = '100%';
                        document.getElementById('startBtn').disabled = false;
                        document.getElementById('startBtn').textContent = '🚀 Start Clipping';
                        loadClips(jobId);
                    } else if (data.status === 'error') {
                        clearInterval(interval);
                        statusText.textContent = '❌ Error: ' + data.error;
                        document.getElementById('startBtn').disabled = false;
                        document.getElementById('startBtn').textContent = '🚀 Start Clipping';
                    }
                } catch(e) { /* retry */ }
            }, 3000);
        }

        async function loadClips(jobId) {
            const resp = await fetch('/api/clips?job_id=' + jobId);
            const data = await resp.json();
            const container = document.getElementById('clips-list');
            container.innerHTML = '<h2 style="margin:20px 0 10px">Generated Clips</h2>';

            for (const clip of data.clips) {
                container.innerHTML += `
                    <div class="clip-card">
                        <img src="/thumbs/${clip.thumbnail}" alt="thumb" onerror="this.style.display='none'">
                        <div class="clip-info">
                            <h3>${clip.title}</h3>
                            <p>${clip.duration.toFixed(1)}s | Score: ${clip.score.toFixed(2)}</p>
                            <p>${clip.hashtags.join(' ')}</p>
                        </div>
                        <a href="/clips/${clip.file}" class="download-btn" download>⬇ Download</a>
                    </div>`;
            }
        }
        </script>
    </body>
    </html>
    """


@app.post("/api/clip")
async def start_clipping(
    background_tasks: BackgroundTasks,
    url: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    max_clips: int = Form(10),
    clip_duration: float = Form(30.0),
    quality: str = Form("720p"),
    whisper_model: str = Form("base"),
):
    """Start the clipping pipeline (runs in background)."""
    if not url and not file:
        raise HTTPException(400, "Provide a URL or upload a file")

    job_id = str(uuid.uuid4())[:8]
    job_dir = OUTPUT_BASE / job_id

    # Save uploaded file if provided
    source = url
    if file:
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        file_path = UPLOAD_DIR / f"{job_id}_{file.filename}"
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)
        source = str(file_path)

    jobs[job_id] = {
        "status": "starting",
        "stage": "Initializing...",
        "progress": 0,
        "num_clips": 0,
        "error": None,
    }

    background_tasks.add_task(
        _run_pipeline_job, job_id, source, job_dir,
        max_clips, clip_duration, quality, whisper_model
    )

    return {"job_id": job_id, "status": "started"}


async def _run_pipeline_job(
    job_id: str, source: str, output_dir: Path,
    max_clips: int, clip_duration: float, quality: str, whisper_model: str,
):
    """Background pipeline task."""
    from .config import ClipperConfig
    from .pipeline import run_pipeline

    try:
        jobs[job_id]["status"] = "running"
        jobs[job_id]["stage"] = "Starting pipeline..."
        jobs[job_id]["progress"] = 5

        config = ClipperConfig(
            output_dir=output_dir,
            max_clips=max_clips,
            clip_duration_target_sec=clip_duration,
            preferred_quality=quality,
            whisper_model=whisper_model,
        )

        # Run the synchronous pipeline in a thread
        import asyncio
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, run_pipeline, source, str(output_dir), config
        )

        if result.errors:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = "; ".join(result.errors)
        else:
            jobs[job_id]["status"] = "complete"
            jobs[job_id]["num_clips"] = len(result.clips)
            jobs[job_id]["progress"] = 100
            jobs[job_id]["clips"] = [
                {
                    "file": c.filepath.name,
                    "thumbnail": c.thumbnail_path.name if c.thumbnail_path else "",
                    "title": c.title,
                    "duration": c.duration,
                    "score": c.score,
                    "hashtags": c.hashtags,
                }
                for c in result.clips
            ]

    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(e)


@app.get("/api/status")
async def get_status(job_id: str):
    """Check pipeline job status."""
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    return jobs[job_id]


@app.get("/api/clips")
async def get_clips(job_id: str):
    """List generated clips for a job."""
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    return {"clips": jobs[job_id].get("clips", [])}


@app.get("/clips/{filename}")
async def download_clip(filename: str):
    """Download a generated clip."""
    # Search in output directories
    for job_dir in OUTPUT_BASE.iterdir():
        clip_path = job_dir / "clips" / filename
        if clip_path.exists():
            return FileResponse(clip_path, media_type="video/mp4", filename=filename)
    raise HTTPException(404, "Clip not found")


@app.get("/thumbs/{filename}")
async def get_thumbnail(filename: str):
    """Get clip thumbnail."""
    for job_dir in OUTPUT_BASE.iterdir():
        thumb_path = job_dir / "thumbnails" / filename
        if thumb_path.exists():
            return FileResponse(thumb_path, media_type="image/jpeg")
    raise HTTPException(404, "Thumbnail not found")
