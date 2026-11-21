"""Read an authorized VOD in bounded, seekable sections."""
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlsplit, urlunsplit

from .downloader import get_video_info
from .process_runner import run as run_extractor

PLATFORMS = ("youtube.com", "youtu.be", "twitch.tv", "kick.com", "instagram.com",
             "tiktok.com", "x.com", "twitter.com", "facebook.com", "fb.watch")
ACTION_TERMS = ("chase", "heist", "stunt", "escape", "race", "crash", "clutch", "explosion")


def stream_url(value: str) -> str:
    parts = urlsplit(value.strip())
    host = (parts.hostname or "").lower()
    if (parts.scheme not in ("http", "https") or parts.username or parts.password or
            parts.port not in (None, 80, 443) or
            not any(host == h or host.endswith("." + h) for h in PLATFORMS)):
        raise ValueError("Paste a video link from one of the supported platforms.")
    if host == "youtu.be" or host.endswith(".youtu.be"):
        return "https://www.youtube.com/watch?v=" + parts.path.strip("/").split("/")[0]
    if host == "youtube.com" or host.endswith(".youtube.com"):
        video = parse_qs(parts.query).get("v", [None])[0]
        if parts.path.startswith(("/live/", "/shorts/", "/embed/")):
            video = parts.path.split("/")[2]
        if video and len(video) == 11 and all(c.isalnum() or c in "-_" for c in video):
            return "https://www.youtube.com/watch?v=" + video
    return urlunsplit(("https", host, parts.path, parts.query, ""))


def _options():
    args = [sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-playlist",
            "--no-progress", "--no-warnings", "--socket-timeout", "15",
            "--remote-components", "ejs:github",
            "--retries", "1", "--fragment-retries", "1", "--extractor-retries", "1"]
    if os.getenv("SSL_CERT_FILE"):
        args += ["--compat-options", "no-certifi"]
    node = shutil.which("node")
    if node:
        args += ["--js-runtimes", "node:" + node]
    for candidate in (os.environ.get("YTDLP_COOKIEFILE"), "/etc/secrets/cookies.txt", "cookies.txt"):
        if candidate and Path(candidate).is_file():
            args += ["--cookies", candidate]
            break
    return args


class SourceAccessError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _yt(arguments, timeout):
    try:
        opts = _options()
        with tempfile.TemporaryDirectory(prefix="studio-extract-") as tmp:
            if "--cookies" in opts:
                # yt-dlp writes back its jar. Render secret files can be read-only.
                idx = opts.index("--cookies") + 1
                jar = Path(tmp)/"cookies.txt"
                shutil.copyfile(opts[idx], jar)
                jar.chmod(0o600)
                opts[idx] = str(jar)
            proc = run_extractor(opts + arguments, timeout)
    except subprocess.TimeoutExpired:
        raise ValueError("The video host timed out. Retry or upload your recording.") from None
    if proc.returncode:
        reason = proc.stderr.lower()
        if any(term in reason for term in ("not a bot","not a robot","confirm you’re human","confirm you are human")):
            raise SourceAccessError("verification", "The platform requires verification before this server can read the video.")
        if any(term in reason for term in ("private video","members-only","members only","sign in","login required","log in","http error 401")):
            raise SourceAccessError("restricted", "The platform requires an account with access to this video.")
        if "429" in reason or "too many requests" in reason:
            raise SourceAccessError("rate_limit", "The platform temporarily rate-limited this server. Wait before retrying this recording.")
        if "certificate verify failed" in reason:
            raise SourceAccessError("certificate", "The worker could not validate the video host certificate. Check the worker trusted certificates.")
        if "403" in reason or "forbidden" in reason:
            raise SourceAccessError("forbidden", "The platform refused this server’s request for the video (HTTP 403).")
        raise ValueError("The video host could not provide this recording. Check its access or upload the file.")
    return proc.stdout


def metadata(url):
    info = json.loads(_yt(["--skip-download", "--dump-single-json", "--", stream_url(url)], 90))
    duration = float(info.get("duration") or 0)
    if info.get("live_status") == "is_upcoming":
        raise ValueError("The stream has not started yet.")
    if not info.get("is_live") and info.get("live_status") != "is_live" and (not math.isfinite(duration) or duration<=0):
        raise ValueError("The host did not provide a usable recording duration.")
    return info


def scan_ranges(info, budget=14, span=64):
    """Chapters/heatmaps propose inspection work. Every export still needs decoded evidence."""
    duration = float(info["duration"])
    if duration <= span:
        return [(0., duration)]
    last = duration - span
    if duration <= budget * (span - 16):
        count = math.ceil(last / (span - 16)) + 1
        return [(start, start + span) for start in [last * i / (count - 1) for i in range(count)]]
    starts = []
    def add(center):
        start = round(max(0., min(last, center - span / 2)), 2)
        if all(abs(start - other) >= span / 2 for other in starts):
            starts.append(start)
    heat = sorted((row for row in info.get("heatmap") or [] if row.get("value", 0) > 0),
                  key=lambda row: -row["value"])
    for row in heat[:budget // 3]:
        add((row["start_time"] + row["end_time"]) / 2)
    for row in info.get("chapters") or []:
        if len(starts) >= budget // 2:
            break
        if any(word in (row.get("title") or "").lower() for word in ACTION_TERMS):
            add(float(row["start_time"]) + span / 2)
    # Coverage across the entire VOD when a platform provides no replay heatmap.
    remaining = budget - len(starts)
    for i in range(remaining):
        add((i + 0.5) * duration / remaining)
    return [(s, min(duration, s + span)) for s in sorted(starts[:budget])]


def inspection_ranges(info, mode, start, end, overlap, budget):
    """Select a time interval first; full scans cover every second, including the last frame."""
    duration = float(info["duration"])
    first = float(start or 0)
    last = duration if end is None else float(end)
    if not (0 <= first < last <= duration + .05):
        raise ValueError("The selected time range is outside the available recording.")
    length = last-first
    if length < 20:
        raise ValueError("Select an interval of at least 20 seconds.")
    if mode not in ("full", "quick") or not 20 <= overlap <= 45:
        raise ValueError("Choose a scan mode and a clip length between 20 and 45 seconds.")
    if mode == "full":
        span = 240.
        scans = []
        position = first
        while position < last:
            stop = min(last, position+span)
            scans.append((position,stop))
            if stop >= last:
                break
            position = stop-overlap
        return scans
    local = {"duration":length}
    for key in ("heatmap","chapters"):
        local[key] = [dict(row, start_time=max(0,row["start_time"]-first),
                           end_time=min(length,row["end_time"]-first))
                      for row in info.get(key) or [] if row.get("end_time",0)>first
                      and row.get("start_time",last)<last]
    probes = scan_ranges(local, max(budget, math.ceil(length/3600)*2))
    if length > 64:
        # Inspect both edges; a highlight may occur in the opening or closing minutes.
        probes = sorted(set(probes + [(0.,64.),(length-64.,length)]))
    return [(first+a,first+b) for a,b in probes]


def fetch_section(url, start, end, dest, height):
    fmt = (f"best[height<={height}][vcodec!=none][acodec!=none]/"
           f"bestvideo[height<={height}]+bestaudio/best[height<={height}]/worst")
    def download(selector, target):
        _yt(["--format", selector, "--download-sections", f"*{start:.3f}-{end:.3f}",
             "--force-keyframes-at-cuts", "--downloader", "ffmpeg",
             "--downloader-args", "ffmpeg_i:-rw_timeout 15000000 -threads 1",
             "--downloader-args", "ffmpeg_o:-threads 1 -filter_threads 1 -preset ultrafast",
             "--merge-output-format", "mp4",
             "--remux-video", "mp4", "-o", str(target.with_suffix(".%(ext)s")), "--", stream_url(url)], max(240, 2 * (end-start) + 90))
    try:
        download(fmt, dest)
    except SourceAccessError as exc:
        if exc.code != "forbidden":
            raise
        # Resolve the provider's advertised public HTTP formats afresh. Isolate partial files.
        direct = f"best[protocol=https][height<={height}][vcodec!=none][acodec!=none]/bestvideo[protocol=https][height<={height}]+bestaudio[protocol=https]"
        with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
            target = Path(tmp)/dest.name
            download(direct+"/"+fmt, target)
            if not target.is_file():
                raise ValueError("The platform did not return the requested video section.")
            target.replace(dest)
    if not dest.is_file() or abs(get_video_info(dest).duration_sec - (end - start)) > 2.5:
        raise ValueError("The platform did not return the requested video section.")


def make_proxy(source, dest, start, duration, height=288):
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-y", "-threads", "1", "-ss", f"{start:.3f}",
           "-i", str(source), "-t", f"{duration:.3f}", "-map", "0:v:0", "-map", "0:a:0?",
           "-vf", f"fps=8,scale=-2:'min({height},ih)'", "-c:v", "libx264",
           "-preset", "ultrafast", "-crf", "27", "-threads", "2",
           "-c:a", "aac", "-ac", "1", "-ar", "16000", "-b:a", "32k", str(dest)]
    subprocess.run(cmd, check=True, capture_output=True, timeout=max(180, 2*duration+90))
