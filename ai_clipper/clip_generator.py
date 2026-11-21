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
import tempfile
import re
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
        if seg.end <= start_time or seg.start >= end_time:
            continue

        # Clip-relative times
        rel_start = max(0, seg.start - start_time)
        rel_end = min(end_time - start_time, seg.end - start_time)

        # SRT timestamp format
        start_str = _seconds_to_srt_time(rel_start)
        end_str = _seconds_to_srt_time(rel_end)

        srt_lines.append(f"{idx}")
        srt_lines.append(f"{start_str} --> {end_str}")
        srt_lines.append(re.sub(r"[{}<>]", "", seg.text.strip()).replace("\\", "").replace("\n", " "))
        srt_lines.append("")
        idx += 1

    output_path.write_text("\n".join(srt_lines), encoding="utf-8")


def _seconds_to_srt_time(seconds: float) -> str:
    """Seconds ko SRT time format me convert karo (HH:MM:SS,mmm)."""
    total_ms = max(0, round(seconds * 1000))
    secs, millis = divmod(total_ms, 1000)
    minutes, secs = divmod(secs, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _generate_single_clip(video_path, output_path, start_time, end_time, output_width, output_height,
                          output_fps, face_bbox, srt_path, hook_text, subtitle_font_size,
                          subtitle_font_color, hook_font_size, hook_font_color,
                          enable_overlay=True, creator_tag="", badge="GTA VI", frame_style="blur_bg"):
    w, h = output_width, output_height
    # Fixed working filenames keep user-controlled strings out of FFmpeg's filter language.
    with tempfile.TemporaryDirectory() as folder:
        work = Path(folder)
        if frame_style == "fill_crop":
            sw, sh = _get_video_dimensions(video_path)
            cw, ch = min(sw, int(sh*w/h)), min(sh, int(sw*h/w))
            cx = face_bbox[0] + face_bbox[2]/2 if face_bbox else sw/2
            x = max(0, min(sw-cw, int(cx-cw/2)))
            graph = f"[0:v]crop={cw}:{ch}:{x}:(ih-oh)/2,scale={w}:{h},setsar=1[base]"
        else:
            graph = (f"[0:v]split=2[back][front];[back]scale={w//4}:{h//4}:"
                     f"force_original_aspect_ratio=increase,crop={w//4}:{h//4},"
                     f"boxblur=12:2,scale={w}:{h},eq=brightness=-0.10[bg];"
                     f"[front]scale={w}:{h}:force_original_aspect_ratio=decrease:"
                     f"force_divisible_by=2,setsar=1[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[base]")
        layers = []
        def label(name, value, size, position, style):
            plain = " ".join(str(value).split())[:92]
            if plain:
                (work / name).write_text(plain, encoding="utf-8")
                layers.append(f"drawtext=font='DejaVu Sans\\:style=Bold':textfile={name}:expansion=none:"
                              f"fontsize={size}:{position}:{style}")
        if enable_overlay:
            label("badge.txt", badge, round(w*.038), "x=w*.055:y=h*.06",
                  "fontcolor=white:box=1:boxcolor=0xBB3054:boxborderw=7")
            label("creator.txt", creator_tag, round(w*.032), "x=w-tw-w*.055:y=h*.06",
                  "fontcolor=white:box=1:boxcolor=black@.65:boxborderw=7")
            import textwrap
            if hook_text:
                clean_hook = " ".join(str(hook_text).split())
                (work/"hook.txt").write_text("\n".join(textwrap.wrap(clean_hook[:75], 27)), encoding="utf-8")
                layers.append(f"drawtext=font='DejaVu Sans\\:style=Bold':textfile=hook.txt:expansion=none:"
                              f"fontsize={min(hook_font_size,round(w*.046))}:fontcolor=white:borderw=2:"
                              "bordercolor=black:x=(w-tw)/2:y=h*.17:alpha='min(1,max(0,8-t))'")
        if srt_path and Path(srt_path).exists() and Path(srt_path).stat().st_size:
            import shutil
            shutil.copyfile(srt_path, work/"captions.srt")
            layers.append("subtitles=captions.srt:force_style='FontName=DejaVu Sans,Alignment=2,"
                          f"FontSize={max(10,round(subtitle_font_size*288/1080))},MarginV=28,Outline=2'")
        layers += [f"fps={output_fps}", "format=yuv420p"]
        graph += ";[base]" + ",".join(layers) + "[v]"
        target = Path(output_path).resolve()
        temp = target.with_suffix(".part.mp4")
        from .runtime_memory import low_memory
        bounded = low_memory()
        encoder = ["-threads", "1" if bounded else "2", "-preset", "veryfast"]
        if bounded:
            encoder += ["-tune", "zerolatency", "-x264-params", "ref=1:rc-lookahead=0"]
        try:
            cmd = ["ffmpeg", "-v", "error", "-nostdin", "-y", "-threads", "1" if bounded else "2", "-ss", str(start_time),
                   "-i", str(Path(video_path).resolve()), "-t", str(end_time-start_time),
                   "-filter_complex_threads", "1" if bounded else "2", "-filter_complex", graph, "-map", "[v]", "-map", "0:a:0?",
                   "-c:v", "libx264", *encoder, "-crf", "22",
                   "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(temp)]
            subprocess.run(cmd, cwd=work, check=True, capture_output=True, timeout=360)
            temp.replace(target)
        finally:
            temp.unlink(missing_ok=True)


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
