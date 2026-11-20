"""
Clip Generation Module - FFmpeg se clips cut, crop, subtitle, aur hook add karta hai.

Yeh module final output clips generate karta hai:
1. Video trim (peak ke around)
2. 9:16 vertical crop (face tracking se center)
3. Subtitles burn (Whisper transcript)
4. Hook text overlay
5. Thumbnail generation
"""

import subprocess
import json
import os
from pathlib import Path
from dataclasses import dataclass

from rich.console import Console

console = Console()


@dataclass
class GeneratedClip:
    """Ek generated clip ka info."""
    index: int
    filepath: Path
    thumbnail_path: Path | None
    start_time: float
    end_time: float
    duration: float
    score: float
    title: str
    hook_text: str
    hashtags: list[str]
    subtitle_path: Path | None = None


def generate_clips(
    video_path: Path,
    highlights: list,  # list[HighlightCandidate]
    transcript_segments: list,  # list[TranscriptSegment]
    visual_analysis,  # VisualAnalysis
    text_scores: list,  # list[TextScore]
    output_dir: Path,
    output_width: int = 1080,
    output_height: int = 1920,
    output_fps: int = 30,
    subtitle_font_size: int = 42,
    subtitle_font_color: str = "white",
    subtitle_bg_color: str = "black@0.6",
    hook_font_size: int = 52,
    hook_font_color: str = "yellow",
    default_hashtags: list[str] | None = None,
    video_title: str = "Gameplay",
) -> list[GeneratedClip]:
    """
    Highlight candidates se final vertical clips generate karo.

    Har clip ke liye:
    1. FFmpeg se video trim
    2. 9:16 crop (face/center tracking)
    3. Subtitles add
    4. Hook text add
    5. Thumbnail save

    Args:
        video_path: Source video path
        highlights: Highlight candidates from scorer
        transcript_segments: Whisper transcript segments
        visual_analysis: Visual analysis results
        text_scores: NLP text scores
        output_dir: Output directory for clips
        output_width/height: Output resolution
        output_fps: Output FPS
        subtitle_*: Subtitle styling
        hook_*: Hook text styling
        default_hashtags: Default hashtags
        video_title: Source video title

    Returns:
        List of GeneratedClip objects
    """
    console.print(f"[bold blue]🎬 Generating {len(highlights)} clips...[/]")

    output_dir.mkdir(parents=True, exist_ok=True)
    clips_dir = output_dir / "clips"
    clips_dir.mkdir(exist_ok=True)
    subs_dir = output_dir / "subtitles"
    subs_dir.mkdir(exist_ok=True)
    thumbs_dir = output_dir / "thumbnails"
    thumbs_dir.mkdir(exist_ok=True)

    if default_hashtags is None:
        default_hashtags = ["#Shorts", "#Gaming", "#Highlights"]

    generated = []

    for i, highlight in enumerate(highlights):
        clip_num = i + 1
        console.print(
            f"\n[bold cyan]--- Clip {clip_num}/{len(highlights)} ---[/]"
            f"\n[dim]{highlight.start_time:.1f}s - {highlight.end_time:.1f}s "
            f"(score: {highlight.score:.2f})[/dim]"
        )

        # 1. Generate subtitle file (SRT) for this clip's time range
        srt_path = subs_dir / f"clip_{clip_num:02d}.srt"
        _generate_srt(
            transcript_segments, highlight.start_time, highlight.end_time, srt_path
        )

        # 2. Get hook text from NLP scores
        from .nlp_scorer import get_hook_text_at_time
        hook_text = highlight.hook_text or get_hook_text_at_time(
            text_scores, highlight.peak_time
        )

        # 3. Determine crop position (try to center on face)
        from .visual_analyzer import get_face_bbox_at_time
        face_bbox = get_face_bbox_at_time(visual_analysis, highlight.peak_time)

        # 4. Build FFmpeg command for clip generation
        clip_path = clips_dir / f"clip_{clip_num:02d}.mp4"

        _generate_single_clip(
            video_path=video_path,
            output_path=clip_path,
            start_time=highlight.start_time,
            end_time=highlight.end_time,
            output_width=output_width,
            output_height=output_height,
            output_fps=output_fps,
            face_bbox=face_bbox,
            srt_path=srt_path,
            hook_text=hook_text,
            subtitle_font_size=subtitle_font_size,
            subtitle_font_color=subtitle_font_color,
            hook_font_size=hook_font_size,
            hook_font_color=hook_font_color,
        )

        # 5. Generate thumbnail
        thumb_path = thumbs_dir / f"clip_{clip_num:02d}_thumb.jpg"
        _generate_thumbnail(video_path, highlight.peak_time, thumb_path)

        # 6. Generate title and hashtags
        title = _generate_title(video_title, hook_text, clip_num)
        hashtags = _generate_hashtags(hook_text, default_hashtags)

        generated.append(GeneratedClip(
            index=clip_num,
            filepath=clip_path,
            thumbnail_path=thumb_path,
            start_time=highlight.start_time,
            end_time=highlight.end_time,
            duration=highlight.end_time - highlight.start_time,
            score=highlight.score,
            title=title,
            hook_text=hook_text,
            hashtags=hashtags,
            subtitle_path=srt_path,
        ))

        console.print(f"[bold green]✓ Clip {clip_num} generated:[/] {clip_path.name}")

    console.print(f"\n[bold green]✓ All {len(generated)} clips generated![/]")
    return generated


def _generate_srt(
    segments: list,
    start_time: float,
    end_time: float,
    output_path: Path,
):
    """
    Clip ke time range ke liye SRT subtitle file banao.
    Whisper segments ko filter karke relative timestamps me convert karta hai.
    """
    srt_lines = []
    idx = 1

    for seg in segments:
        # Check if segment overlaps with clip time range
        if seg.end < start_time or seg.start > end_time:
            continue

        # Clip-relative times
        rel_start = max(0, seg.start - start_time)
        rel_end = min(end_time - start_time, seg.end - start_time)

        # SRT timestamp format
        start_str = _seconds_to_srt_time(rel_start)
        end_str = _seconds_to_srt_time(rel_end)

        srt_lines.append(f"{idx}")
        srt_lines.append(f"{start_str} --> {end_str}")
        srt_lines.append(seg.text.strip())
        srt_lines.append("")
        idx += 1

    output_path.write_text("\n".join(srt_lines), encoding="utf-8")


def _seconds_to_srt_time(seconds: float) -> str:
    """Seconds ko SRT time format me convert karo (HH:MM:SS,mmm)."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _generate_single_clip(
    video_path: Path,
    output_path: Path,
    start_time: float,
    end_time: float,
    output_width: int,
    output_height: int,
    output_fps: int,
    face_bbox: tuple | None,
    srt_path: Path,
    hook_text: str,
    subtitle_font_size: int,
    subtitle_font_color: str,
    hook_font_size: int,
    hook_font_color: str,
):
    """
    FFmpeg se single clip generate karo with crop, subtitles, hook text.

    FFmpeg filter chain:
    1. Crop to 9:16 (centered on face if detected)
    2. Scale to output resolution
    3. Add subtitles (SRT)
    4. Add hook text overlay at top
    """
    duration = end_time - start_time

    # --- Build crop filter ---
    # For 9:16 from a 16:9 source: crop width = height * 9/16
    # We need to know source dimensions
    source_info = _get_video_dimensions(video_path)
    src_w, src_h = source_info

    # Calculate crop dimensions for 9:16 aspect ratio
    target_ratio = 9 / 16
    source_ratio = src_w / src_h

    if source_ratio > target_ratio:
        # Source is wider than 9:16 → crop width
        crop_h = src_h
        crop_w = int(src_h * target_ratio)
    else:
        # Source is taller → crop height
        crop_w = src_w
        crop_h = int(src_w / target_ratio)

    # Determine crop position
    if face_bbox:
        fx, fy, fw, fh = face_bbox
        face_center_x = fx + fw // 2
        # Center crop on face horizontally
        crop_x = max(0, min(face_center_x - crop_w // 2, src_w - crop_w))
        crop_y = 0  # Usually keep vertical centered
    else:
        # Center crop
        crop_x = (src_w - crop_w) // 2
        crop_y = (src_h - crop_h) // 2

    # --- Escape SRT path for FFmpeg (Windows compatibility) ---
    srt_escaped = str(srt_path).replace("\\", "/").replace(":", "\\:")

    # --- Build filter chain ---
    filters = []

    # 1. Crop to 9:16
    filters.append(f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y}")

    # 2. Scale to output resolution
    filters.append(f"scale={output_width}:{output_height}")

    # 3. Add subtitles
    if srt_path.exists() and srt_path.stat().st_size > 0:
        filters.append(
            f"subtitles='{srt_escaped}':force_style="
            f"'FontSize={subtitle_font_size},"
            f"PrimaryColour=&Hffffff&,"
            f"BackColour=&H80000000&,"
            f"BorderStyle=4,"
            f"Outline=0,"
            f"Shadow=0,"
            f"MarginV=80'"
        )

    # 4. Add hook text at top
    if hook_text:
        # Escape single quotes for FFmpeg
        safe_hook = hook_text.replace("'", "\\'").replace(":", "\\:")
        # Limit to 50 chars
        if len(safe_hook) > 50:
            safe_hook = safe_hook[:47] + "..."
        filters.append(
            f"drawtext=text='{safe_hook}':"
            f"fontsize={hook_font_size}:"
            f"fontcolor={hook_font_color}:"
            f"borderw=3:bordercolor=black:"
            f"x=(w-text_w)/2:y=80:"
            f"enable='between(t,0,5)'"  # Show for first 5 seconds
        )

    filter_str = ",".join(filters)

    # --- FFmpeg command ---
    cmd = [
        "ffmpeg",
        "-ss", str(start_time),
        "-i", str(video_path),
        "-t", str(duration),
        "-vf", filter_str,
        "-r", str(output_fps),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        "-y",
        str(output_path)
    ]

    console.print(f"[dim]Running FFmpeg...[/dim]")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        # Try without subtitles if that fails
        console.print(f"[yellow]⚠ FFmpeg failed with subtitles, retrying without...[/]")
        simple_filter = f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y},scale={output_width}:{output_height}"
        cmd_simple = [
            "ffmpeg",
            "-ss", str(start_time),
            "-i", str(video_path),
            "-t", str(duration),
            "-vf", simple_filter,
            "-r", str(output_fps),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            "-y",
            str(output_path)
        ]
        result = subprocess.run(cmd_simple, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg clip generation failed:\n{result.stderr}")


def _generate_thumbnail(
    video_path: Path, time_sec: float, output_path: Path
):
    """Video se thumbnail frame extract karo."""
    cmd = [
        "ffmpeg",
        "-ss", str(time_sec),
        "-i", str(video_path),
        "-vframes", "1",
        "-q:v", "2",
        "-y",
        str(output_path)
    ]
    subprocess.run(cmd, capture_output=True, text=True)


def _get_video_dimensions(video_path: Path) -> tuple[int, int]:
    """FFprobe se video dimensions get karo."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-select_streams", "v:0",
        str(video_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    stream = data["streams"][0]
    return int(stream["width"]), int(stream["height"])


def _generate_title(video_title: str, hook_text: str, clip_num: int) -> str:
    """Clip ke liye YouTube Shorts title generate karo."""
    # Clean up hook text
    clean_hook = hook_text.strip()
    if len(clean_hook) > 60:
        clean_hook = clean_hook[:57] + "..."

    if clean_hook and clean_hook != "🔥 Highlight Moment":
        return f"{clean_hook} | {video_title} Highlights"
    else:
        return f"{video_title} - Best Moment #{clip_num}"


def _generate_hashtags(hook_text: str, default_tags: list[str]) -> list[str]:
    """Context-based hashtags generate karo."""
    tags = list(default_tags)

    # Add content-specific tags based on keywords
    text_lower = hook_text.lower()
    keyword_tags = {
        "explosion": "#Explosion",
        "crash": "#CrashScene",
        "chase": "#CarChase",
        "fight": "#FightScene",
        "win": "#Winner",
        "clutch": "#ClutchPlay",
        "headshot": "#Headshot",
        "police": "#PoliceChase",
        "heist": "#Heist",
    }
    for keyword, tag in keyword_tags.items():
        if keyword in text_lower and tag not in tags:
            tags.append(tag)
            break  # Only add one extra tag

    return tags[:8]  # Max 8 hashtags
