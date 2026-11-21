# StreamGrabber AI

Turn a saved stream or a playable live replay into vertical gameplay highlights. Paste a supported stream link in [Clip Studio](https://streamgrabber-ai.onrender.com), select **Full timeline** or **Quick scan**, and choose **Generate clips**. The built-in GTA V sample can be played immediately.

## 20-hour streams

| Input | What Studio inspects |
| --- | --- |
| Saved VOD or local recording | Full timeline reads consecutive four-minute sections with a clip-length overlap, including hour 20. Quick scan checks short samples spread across the selected interval and any available replay peaks or action chapters. |
| Ongoing livestream with HLS DVR | A snapshot of the completed replay segments available when the job starts, up to the latest 20 hours. The result shows the actual available interval. Audio and video on separate tracks must share a program clock. |
| Specific match or hour | Open **Choose a time range** and enter hours, minutes and seconds, for example `19:00:00` to `20:00:00`. Recorded sources use time since the recording began. Live sources use time since broadcast start when the provider supplies a clock. Otherwise times refer to the start of the retained replay. |

YouTube, Twitch, Kick, Instagram, TikTok, X and Facebook links go through their yt-dlp extractors. The provider controls which formats, replay segments and permissions it makes available. YouTube says DVR can be limited beyond 12 hours and the broadcast may never be archived. To keep all 20 hours of your own broadcast, record locally while streaming. Use the CLI for a multi-GB local file or raise the upload limit on a worker you host. The public worker accepts browser uploads up to 90 MB. [YouTube DVR](https://support.google.com/youtube/answer/9296823) · [YouTube archives](https://support.google.com/youtube/answer/6247592)

## Laptop par chalao

Use Python 3.11 and install both FFmpeg and ffprobe. On Ubuntu/Debian use `sudo apt install ffmpeg`, on macOS use `brew install ffmpeg`. On Windows install an FFmpeg build, add its `bin` directory to PATH and check `ffmpeg -version` and `ffprobe -version`.

```bash
git clone https://github.com/sneetesh594-alt/streamgrabber-ai.git
cd streamgrabber-ai
python -m venv .venv
# Windows PowerShell uses .venv\Scripts\Activate.ps1
source .venv/bin/activate
python -m pip install -r requirements_web.txt
# Windows PowerShell uses Copy-Item .env.example .env
cp .env.example .env
python -m uvicorn stream_downloader.app:app --host 127.0.0.1 --port 8000 --workers 1
```

Open `http://127.0.0.1:8000`. Pehli run par local CLIP aur Whisper model weights download honge. Full OpenCLIP/PyTorch, Whisper and librosa backends are available through `python -m pip install -r requirements.txt`. For GPU OpenCLIP set `CLIPPER_VISION_BACKEND=openclip`; for PyTorch Whisper set `CLIPPER_SPEECH_BACKEND=whisper`. The default lighter installation uses quantized ONNX CLIP, faster-whisper and PCM RMS. On small workers the app releases inference models before FFmpeg renders the portrait clip. A higher-memory GPU worker can set `CLIPPER_LOW_MEMORY=false` to keep models warm across stages.

```bash
python -m ai_clipper clip "recording.mp4" --scan-mode full --max-clips 5 --quality 1080p -o clips_out
python -m ai_clipper clip "recording.mp4" --start-seconds 68400 --end-seconds 72000 --clip-duration 30 --quality 720p -o hour20
```

If a saved VOD job stops, open **Clip library → job → Resume scan** while worker storage persists. The CLI reuses completed sections when rerun with the same source, settings and output folder. Active replay URLs can expire. Submit a fresh live snapshot to inspect what the host still retains.

## How highlights are selected

1. yt-dlp reads source metadata and requests bounded, seekable VOD ranges. FFmpeg builds one analysis proxy at a time. Live HLS ranges are determined by real playlist timings.
2. PySceneDetect identifies cuts. OpenCV measures dark/static frames, scene-wide motion and perceptual fingerprints. CLIP compares sampled frames with gameplay, chase, stunt, menu, idle and non-gameplay descriptions.
3. Whisper transcribes speech. Audio RMS, gaming phrases and transcript sentiment contribute alongside the visual measurements. The default audio/text/visual weights are 0.30/0.35/0.35.
4. Only qualifying windows with decoded evidence are retained. Overlapping windows, repeated scenes and visually similar moments compete by score. A source may return zero clips.
5. FFmpeg fits the full gameplay frame over a blurred portrait background and encodes an H.264/AAC MP4 when source audio exists, at 720×1280 or 1080×1920. Captions use words actually transcribed. Badges, creator tag and transcript hook are optional. Each result includes its source interval and verification method.

## Backend-only Gemini reviewers

Both slots use Google's Gemini API. In your worker's secret manager or private `.env`, set `GEMINI_API_KEY` and `SECOND_AI_API_KEY` to freshly rotated keys. Leave the example values blank in Git. Set `GEMINI_REVIEW_ENABLED=true` only to enable the review path. Enable read-only Google Application Default Credentials for API Keys lookup and Cloud Billing project status. The worker confirms each key's owning project, disabled billing and model availability before generation.

The reviewers receive the short decoded candidate video with its audio and available transcript. Rejections veto the moment. A shared SQLite quota reserves calls for both slots together. The default is 12 requests per Pacific day, configurable through `GEMINI_DAILY_REQUEST_LIMIT`. A billing or quota rejection stops further generation for the day. Missing credentials, uncertain billing, unavailable models or exhausted budget return to local analysis. **AI usage** shows daily reservations, tokens and estimated cost. Persist `STREAMGRABBER_STATE_DIR` for durable jobs and accounting.

Use only recordings you own or have permission to edit and share. Subtitles, reframing and badges do not change the source rights. The playable GTA V sample is credited to Xusder, CC BY-SA 4.0. [Sample credit and license](ai_clipper/studio/assets/CREDITS.txt)

[Deployment guide](CLOUD_DEPLOY_GUIDE.md) · [Test results and reproduction](docs/VERIFICATION.md)
