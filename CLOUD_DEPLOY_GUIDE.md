# Hosting Clip Studio

## Native Python on Render

The existing service is at [streamgrabber-ai.onrender.com](https://streamgrabber-ai.onrender.com). The repository's `render.yaml` also describes a free Python web service. The build checks FFmpeg and ffprobe and installs `requirements_web.txt`. The start command is:

```sh
uvicorn stream_downloader.app:app --host 0.0.0.0 --port "$PORT" --workers 1
```

Use a single worker for the local queue. Check `/api/studio/health` for FFmpeg and long-stream support. Gemini is optional. Put rotated credentials and billing-reader credentials in the service's Secrets settings and leave billing disabled on the Gemini project. The CLI and host may use an authorized server cookie file via `YTDLP_COOKIEFILE` if a source legitimately requires sign-in.

Render free services sleep after 15 minutes without inbound traffic and lose local files on restarts, redeploys and spin-downs. The free service is suited to short jobs and trying the UI. Download clips you want to keep. Hugging Face Spaces also sleeps on free CPU hardware. These tiers do not assure an uninterrupted 20-hour job, GPU access or durable job history. [Render free limits](https://render.com/docs/free) · [Spaces lifecycle](https://huggingface.co/docs/hub/spaces-overview#lifecycle-management)

## Sustained long jobs

An already-on PC with available storage can run the same worker without a hosting subscription. A VPS with persistent disk also works; its provider sets the price. Follow the installation in the README. Put `STREAMGRABBER_STATE_DIR` on a persistent disk, leave the process running, and use a service manager on Linux for automatic restart. For multi-GB recordings already on that computer, the CLI seeks directly in the original file. For a private self-hosted browser deployment, set `STREAMGRABBER_UPLOAD_MB` to an appropriate size for that machine and allow sufficient disk space and proxy upload capacity.

Full scans inspect the complete available range. Throughput depends on decode speed, model backend, GPU, bandwidth, source seekability and host access. To estimate your hardware's actual processing time, run a full scan of a representative 10-minute interval using the same models and resolution, then inspect `runtime_sec` in `clips_metadata.json`. No full-duration GPU benchmark is published.
