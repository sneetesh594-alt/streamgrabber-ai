"""
Main Pipeline Orchestrator - Poora AI Video Clipper pipeline ko coordinate karta hai.

Yeh module sabhi stages ko sequence me run karta hai:
1. Download/Load → 2. Scene Detection → 3. Audio Analysis → 
4. Visual Analysis → 5. NLP Scoring → 6. Signal Fusion → 
7. Clip Generation → 8. Packaging
"""

import json
import shutil
import os
import tempfile
import subprocess
from dataclasses import replace
import time
from pathlib import Path
from dataclasses import dataclass, field, asdict

from rich.console import Console
from rich.table import Table

console = Console()


@dataclass
class PipelineResult:
    """Full pipeline run ka result."""
    clips: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    output_dir: Path | None = None
    runtime_sec: float = 0.0
    errors: list[str] = field(default_factory=list)


def run_pipeline(source, output_dir="./output", config=None, progress=None):
    from .config import config as defaults
    from .downloader import get_video_info
    from .sources import metadata, scan_ranges, fetch_section, make_proxy
    from .audio_analyzer import extract_audio, transcribe_audio, analyze_audio_energy
    from .visual_analyzer import analyze_visual
    from .scene_detector import detect_scenes
    from .moments import candidates, duplicate, verify
    from .gemini_review import review
    from .clip_generator import (GeneratedClip, _generate_single_clip, _generate_srt,
                                 _generate_thumbnail, _generate_title, _generate_hashtags)
    config = config or defaults
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    result = PipelineResult(output_dir=output_dir)
    report = progress or (lambda n, msg: console.print(f"[cyan]{n}%[/] {msg}"))
    started = time.monotonic()
    warnings, observations, covered, all_speech = [], [], [], []
    remote = str(source).startswith(("https://", "http://"))
    try:
        with tempfile.TemporaryDirectory(prefix="studio-") as tmp:
            temp = Path(tmp)
            report(4, "Reading source metadata")
            if remote:
                info = metadata(source)
                title, duration = info.get("title", "Gameplay"), float(info["duration"])
                coverage = scan_ranges(info, config.scan_budget)
            else:
                source = Path(source).resolve()
                info = get_video_info(source)
                title, duration = info.title, info.duration_sec
                # Process local recordings completely, with overlap at batch edges.
                coverage = scan_ranges({"duration": duration}, max(2, int(duration/48)+3))
            if duration > config.max_video_length_minutes * 60:
                raise ValueError("Recording exceeds the configured maximum duration.")
            result.metadata.update(title=title, duration_sec=duration, source="platform VOD" if remote else "uploaded recording")
            report(9, f"Inspecting {len(coverage)} source sections")
            for index, (start, end) in enumerate(coverage):
                progress_n = 10 + round(60*index/len(coverage))
                report(progress_n, f"Reading section {index+1} of {len(coverage)}")
                proxy = temp / f"scan-{index}.mp4"
                if remote:
                    section = temp / f"source-{index}.mp4"
                    try:
                        fetch_section(source, start, end, section, 360)
                    except ValueError as exc:
                        if "refused access" in str(exc) or len(coverage) == 1:
                            raise
                        warnings.append(f"Section {index+1} was unavailable.")
                        continue
                    make_proxy(section, proxy, 0, end-start)
                    section.unlink()
                else:
                    make_proxy(source, proxy, start, end-start)
                actual = min(get_video_info(proxy).duration_sec, end-start)
                covered.append([start, start+actual])
                report(progress_n+1, f"Measuring motion and gameplay in section {index+1}")
                visual = analyze_visual(proxy, sample_fps=config.clip_sample_fps, use_clip=config.use_clip,
                                        use_face_detection=False)
                if not any(f.gameplay is not None for f in visual.frame_scores) and config.use_clip:
                    warnings.append("Local gameplay model unavailable. Cloud verification is required for these frames.")
                if sum(f.motion_score > .13 and not f.black for f in visual.frame_scores) < 4:
                    continue
                scenes = detect_scenes(proxy, config.scene_threshold, config.min_scene_length_sec)
                speech, energy = [], None
                audio_stream = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0",
                     "-show_entries", "stream=index", "-of", "csv=p=0", str(proxy)], capture_output=True, check=True)
                if audio_stream.stdout.strip():
                    audio = extract_audio(proxy, temp / f"audio-{index}.wav")
                    energy = analyze_audio_energy(audio, config.audio_hop_length, config.audio_frame_length)
                    try:
                        speech = transcribe_audio(audio, config.whisper_model, config.whisper_language)
                    except (OSError, RuntimeError, ImportError, ValueError):
                        warnings.append("Speech model unavailable; captions could not be generated for this section.")
                    all_speech.extend(replace(seg,start=seg.start+start,end=seg.end+start) for seg in speech)
                    audio.unlink(missing_ok=True)
                observations.extend(candidates(proxy, start, actual, visual, energy, speech, scenes, config))
            if not covered:
                raise ValueError("The video host did not return any inspectable sections.")
            result.metadata["scanned_ranges"] = covered
            result.metadata["warnings"] = list(dict.fromkeys(warnings))
            report(72, "Verifying and deduplicating candidate moments")
            selected = []
            for moment in sorted(observations, key=lambda m: -m.score):
                if duplicate(moment, selected) or moment.score < config.min_highlight_score:
                    continue
                verdict = None
                if os.getenv("GEMINI_REVIEW_ENABLED", "").lower() == "true":
                    preview = temp/"review.mp4"
                    make_proxy(moment.proxy, preview, moment.start-moment.scan_start, moment.end-moment.start, 224)
                    verdict = review(preview, " ".join(s.text for s in moment.speech))
                if verify(moment, verdict, config):
                    selected.append(moment)
                    if len(selected) >= config.max_clips:
                        break
            for folder in ("clips", "subtitles", "thumbnails"):
                (output_dir/folder).mkdir(exist_ok=True)
            for idx, moment in enumerate(selected, 1):
                report(78 + int(20*(idx-1)/len(selected)), f"Rendering clip {idx} of {len(selected)}")
                original, cut_start = source, moment.start
                if remote:
                    original = temp/f"export-{idx}.mp4"
                    fetch_section(source, moment.start, moment.end, original, config.output_height)
                    cut_start = 0
                basename = f"clip_{idx:02d}"
                subs = output_dir/"subtitles"/(basename+".srt")
                _generate_srt(moment.speech, moment.start-moment.scan_start, moment.end-moment.scan_start, subs)
                path = output_dir/"clips"/(basename+".mp4")
                thumb = output_dir/"thumbnails"/(basename+"_thumb.jpg")
                w, h = config.output_width, config.output_height
                box = None
                if config.frame_style == "fill_crop" and config.use_face:
                    from .face_tracker import track_subject_in_clip
                    track = track_subject_in_clip(original, cut_start, cut_start+moment.end-moment.start,
                                                  config.tracker_type, config.face_detection_interval)
                    tracked = sorted((f.bbox for f in track.frames if f.bbox), key=lambda b: b[0]+b[2]/2)
                    if tracked:
                        box = tracked[len(tracked)//2]
                _generate_single_clip(original, path, cut_start, cut_start+moment.end-moment.start, w,h,
                    config.output_fps, box, subs, moment.hook, config.subtitle_font_size, config.subtitle_font_color,
                    config.hook_font_size, config.hook_font_color, config.enable_overlay, config.creator_tag,
                    config.overlay_badge, config.frame_style)
                _generate_thumbnail(original, cut_start+moment.peak-moment.start, thumb)
                clip = GeneratedClip(idx, path, thumb, moment.start, moment.end, moment.end-moment.start,
                    moment.score, _generate_title(title, moment.hook, idx), moment.hook,
                    _generate_hashtags(moment.hook, config.default_hashtags), subs)
                clip.evidence = moment.evidence
                result.clips.append(clip)
            unique_speech = {(round(s.start,1),s.text): s for s in all_speech}
            _save_transcript(sorted(unique_speech.values(), key=lambda s:s.start), output_dir/"transcript.json")
            result.runtime_sec = time.monotonic()-started
            _save_metadata(result, output_dir)
            report(100, "Clips ready" if selected else "No qualifying gameplay found in the inspected footage")
    except (ValueError, FileNotFoundError) as exc:
        result.errors.append(str(exc) if isinstance(exc, ValueError) else "Input or processing dependency is unavailable.")
    except Exception as exc:
        result.errors.append(f"Processing failed ({type(exc).__name__}). Check installed models and FFmpeg.")
    result.runtime_sec = time.monotonic()-started
    return result


def _save_transcript(segments: list, filepath: Path):
    """Transcript ko JSON file me save karo."""
    data = []
    for seg in segments:
        data.append({
            "start": seg.start,
            "end": seg.end,
            "text": seg.text,
            "language": seg.language,
        })
    filepath.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"[dim]Transcript saved: {filepath.name}[/dim]")


def _save_metadata(result: PipelineResult, output_dir: Path):
    """Clips metadata aur summary save karo."""
    metadata = {
        "pipeline_version": "4.0",
        "scanned_ranges": result.metadata.get("scanned_ranges", []),
        "warnings": result.metadata.get("warnings", []),
        "source": result.metadata.get("source", ""),
        "title": result.metadata.get("title", ""),
        "runtime_sec": result.runtime_sec,
        "num_clips": len(result.clips),
        "clips": [],
    }

    for clip in result.clips:
        metadata["clips"].append({
            "index": clip.index,
            "file": str(clip.filepath.name),
            "thumbnail": str(clip.thumbnail_path.name) if clip.thumbnail_path else None,
            "start_time": clip.start_time,
            "end_time": clip.end_time,
            "duration": clip.duration,
            "score": clip.score,
            "title": clip.title,
            "hook_text": clip.hook_text,
            "hashtags": clip.hashtags,
            "evidence": getattr(clip, "evidence", ""),
        })

    metadata_path = output_dir / "clips_metadata.json"
    metadata_path.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    console.print(f"[dim]Metadata saved: {metadata_path.name}[/dim]")


def _print_summary(result: PipelineResult):
    """Pipeline result ka summary print karo."""
    console.print("\n[bold magenta]" + "=" * 60 + "[/]")
    console.print("[bold magenta]  📋 PIPELINE SUMMARY  [/]")
    console.print("[bold magenta]" + "=" * 60 + "[/]\n")

    table = Table(title="Generated Clips")
    table.add_column("#", style="cyan")
    table.add_column("Time Range", style="green")
    table.add_column("Duration", style="yellow")
    table.add_column("Score", style="magenta")
    table.add_column("Title", style="white", max_width=40)

    for clip in result.clips:
        table.add_row(
            str(clip.index),
            f"{clip.start_time:.1f}s - {clip.end_time:.1f}s",
            f"{clip.duration:.1f}s",
            f"{clip.score:.2f}",
            clip.title[:40],
        )

    console.print(table)
    console.print(
        f"\n[bold green]✓ {len(result.clips)} clips generated in "
        f"{result.runtime_sec:.1f}s[/]"
    )
    if result.output_dir:
        console.print(f"[bold]📁 Output: {result.output_dir}[/]")

    if result.errors:
        console.print(f"\n[bold red]⚠ {len(result.errors)} error(s):[/]")
        for err in result.errors:
            console.print(f"  [red]• {err}[/]")

    # Legal disclaimer
    console.print(
        "\n[dim]⚖ DISCLAIMER: Only process videos you own or have rights to. "
        "This tool is for personal/educational use. Adding subtitles or cropping "
        "does not clear copyright. Refer to YouTube policies for monetization.[/dim]"
    )
