"""
Video Download Module - yt-dlp se video download karta hai.

Supports:
- YouTube URLs (VODs, livestreams)
- Direct video file paths
- Multiple quality options
"""

import subprocess
import shutil
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

from rich.console import Console

console = Console()


@dataclass
class VideoInfo:
    """Downloaded video ki basic info."""
    filepath: Path
    title: str
    duration_sec: float
    width: int
    height: int
    fps: float
    url: Optional[str] = None


def check_dependencies():
    """Check ki yt-dlp aur ffmpeg installed hain ya nahi."""
    missing = []
    if not shutil.which("yt-dlp"):
        missing.append("yt-dlp")
    if not shutil.which("ffmpeg"):
        missing.append("ffmpeg")
    if missing:
        raise RuntimeError(
            f"Missing required tools: {', '.join(missing)}. "
            f"Install them: pip install yt-dlp  |  https://ffmpeg.org/download.html"
        )


def get_video_info(filepath: Path) -> VideoInfo:
    """FFprobe se video ki info nikalta hai."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format", "-show_streams",
        str(filepath)
    ]
    import json
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)

    # Find video stream
    video_stream = None
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            video_stream = stream
            break

    if not video_stream:
        raise ValueError(f"No video stream found in {filepath}")

    # Parse FPS (can be "30/1" or "29.97")
    fps_str = video_stream.get("r_frame_rate", "30/1")
    if "/" in fps_str:
        num, den = fps_str.split("/")
        fps = float(num) / float(den) if float(den) != 0 else 30.0
    else:
        fps = float(fps_str)

    return VideoInfo(
        filepath=filepath,
        title=data.get("format", {}).get("tags", {}).get("title", filepath.stem),
        duration_sec=float(data.get("format", {}).get("duration", 0)),
        width=int(video_stream.get("width", 1920)),
        height=int(video_stream.get("height", 1080)),
        fps=fps,
    )


def download_video(
    url: str,
    output_dir: Path,
    quality: str = "720p",
    max_duration_min: int = 180,
) -> VideoInfo:
    """
    YouTube ya koi bhi supported URL se video download karo.

    Args:
        url: YouTube URL ya koi bhi yt-dlp supported URL
        output_dir: Jahan video save hogi
        quality: Preferred quality (360p/480p/720p/1080p)
        max_duration_min: Maximum allowed duration in minutes

    Returns:
        VideoInfo: Downloaded video ki info
    """
    check_dependencies()
    output_dir.mkdir(parents=True, exist_ok=True)

    # Quality mapping
    quality_map = {
        "360p": "bestvideo[height<=360]+bestaudio/best[height<=360]",
        "480p": "bestvideo[height<=480]+bestaudio/best[height<=480]",
        "720p": "bestvideo[height<=720]+bestaudio/best[height<=720]",
        "1080p": "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
    }
    format_str = quality_map.get(quality, quality_map["720p"])

    # Output template
    output_template = str(output_dir / "%(title)s_%(id)s.%(ext)s")

    console.print(f"[bold blue]⬇ Downloading video from:[/] {url}")
    console.print(f"[dim]Quality: {quality} | Max duration: {max_duration_min} min[/dim]")

    cmd = [
        "yt-dlp",
        "--format", format_str,
        "--merge-output-format", "mp4",
        "--output", output_template,
        "--no-playlist",  # Single video only
        "--print", "after_move:filepath",  # Print final path
        "--match-filter", f"duration<={max_duration_min * 60}",
        url
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(
            f"yt-dlp download failed:\n{result.stderr}"
        )

    # Get the downloaded file path from yt-dlp output
    filepath = Path(result.stdout.strip().split("\n")[-1])

    if not filepath.exists():
        # Fallback: find the most recent mp4 in output_dir
        mp4_files = sorted(output_dir.glob("*.mp4"), key=lambda f: f.stat().st_mtime, reverse=True)
        if mp4_files:
            filepath = mp4_files[0]
        else:
            raise FileNotFoundError(f"Downloaded file not found in {output_dir}")

    console.print(f"[bold green]✓ Downloaded:[/] {filepath.name}")

    info = get_video_info(filepath)
    info.url = url
    return info


def load_local_video(filepath: str | Path) -> VideoInfo:
    """
    Local video file load karo.

    Args:
        filepath: Path to the video file

    Returns:
        VideoInfo: Video ki info
    """
    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(f"Video file not found: {filepath}")

    console.print(f"[bold blue]📂 Loading local video:[/] {filepath.name}")
    info = get_video_info(filepath)
    console.print(f"[bold green]✓ Loaded:[/] {info.title} ({info.duration_sec:.0f}s, {info.width}x{info.height})")
    return info
