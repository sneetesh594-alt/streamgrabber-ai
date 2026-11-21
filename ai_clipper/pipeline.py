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
    source_error: str | None = None
    errors: list[str] = field(default_factory=list)


def run_pipeline(source, output_dir="./output", config=None, progress=None, on_details=None):
    from .config import config as defaults
    from .downloader import get_video_info
    from .sources import SourceAccessError, metadata, inspection_ranges, fetch_section, make_proxy
    from . import checkpoints, groq_speech, groq_review
    from .provider_quota import wait_for_reset
    from datetime import datetime, timezone
    from .runtime_memory import low_memory, release_models
    from .live_dvr import open_dvr
    from .audio_analyzer import extract_audio, transcribe_audio, analyze_audio_energy
    from .visual_analyzer import analyze_visual
    from .scene_detector import detect_scenes
    from .moments import candidates, duplicate, verify
    from .gemini_review import review
    from .clip_generator import (GeneratedClip, _generate_single_clip, _generate_srt,
                                 _generate_thumbnail, _generate_title, _generate_hashtags)
    config = config or defaults
    if low_memory():
        import cv2
        cv2.setNumThreads(1)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    result = PipelineResult(output_dir=output_dir)
    report = progress or (lambda n, msg: console.print(f"[cyan]{n}%[/] {msg}"))
    analysis = {"sections_read": 0, "frames_analyzed": 0, "candidate_windows": 0,
                "verified_windows": 0, "speech_segments": 0, "vision": "pending",
                "speech": "pending", "cloud_vision": "not used"}
    result.metadata["analysis"] = analysis
    def details(**changes):
        result.metadata.update(changes)
        if on_details:
            on_details(result.metadata.copy())
    started = time.monotonic()
    dvr, saved_scans = None, None
    retained_sources = {}
    warnings, covered, all_speech = [], [], []
    remote = str(source).startswith(("https://", "http://"))
    try:
        with tempfile.TemporaryDirectory(prefix="studio-") as tmp:
            temp = Path(tmp)
            report(4, "Reading source metadata")
            if remote:
                info = metadata(source)
                title = info.get("title", "Gameplay")
                details(title=title, channel=info.get("uploader") or info.get("channel"),
                        video_id=info.get("id"), duration_sec=info.get("duration"),
                        live_status=info.get("live_status"))
                if info.get("is_live") or info.get("live_status") == "is_live":
                    report(8,"Reading retained live DVR")
                    dvr = open_dvr(info, config.output_width)
                    duration = dvr.duration
                    info = {"duration": duration}
                else:
                    duration = float(info["duration"])
                identity = [source,info.get("id"),duration]
            else:
                source = Path(source).resolve()
                video = get_video_info(source)
                title, duration = video.title, video.duration_sec
                info = {"duration":duration}
                identity = [str(source),source.stat().st_mtime_ns,source.stat().st_size,duration]
            if duration > config.max_video_length_minutes * 60:
                raise ValueError("Recording exceeds the configured maximum duration.")
            start, end = config.range_start, config.range_end
            if dvr and dvr.offset:
                start = max(0., (start or 0)-dvr.offset)
                if end is not None:
                    end -= dvr.offset
            coverage = inspection_ranges(info, config.scan_mode, start, end,
                                         config.clip_duration_target_sec, config.scan_budget)
            timeline_offset = dvr.offset if dvr else 0.
            result.metadata.update(title=title,duration_sec=duration,source="live DVR" if dvr else
                                   ("platform VOD" if remote else "uploaded recording"),
                                   scan_mode=config.scan_mode,timeline_origin=dvr.origin if dvr else "recording start",
                                   available_range=[timeline_offset,timeline_offset+duration])
            details()
            cloud_active = os.getenv("GEMINI_REVIEW_ENABLED","").lower()=="true"
            if not dvr:
                saved_scans = checkpoints.location(output_dir,[identity,config.model_dump(mode="json"),cloud_active,"scan-v3"])
            else:
                warnings.append("Inspected the completed segments the provider exposed when this job started.")
            report(9, f"Inspecting {len(coverage)} source sections")
            selected = []
            def retain(moment):
                if any(old.score >= moment.score and duplicate(moment,[old]) for old in selected):
                    return
                selected[:] = sorted([old for old in selected if not duplicate(moment,[old])] + [moment],
                                     key=lambda m: -m.score)[:config.max_clips]
            for index, (start, end) in enumerate(coverage):
                progress_n = 10 + round(65*index/len(coverage))
                checkpoint = saved_scans/f"{index:05}.json" if saved_scans else None
                def pause(provider, deadline):
                    reset = datetime.fromtimestamp(deadline,timezone.utc).isoformat(timespec="seconds")
                    report(progress_n, f"Paused for {provider} quota | {reset} | section {index+1} of {len(coverage)}")
                wait_for_reset(pause)
                if checkpoint and checkpoint.is_file():
                    previous, transcript, bounds, messages = checkpoints.load(checkpoint)
                    for moment in previous:
                        retain(moment)
                    covered.append(bounds)
                    all_speech.extend(transcript)
                    warnings.extend(messages)
                    report(progress_n, f"Resumed section {index+1} of {len(coverage)}")
                    continue
                report(progress_n, f"Reading section {index+1} of {len(coverage)}")
                # Only the current proxy and high-resolution sections backing retained live clips survive a batch.
                proxy = temp/"scan.mp4"
                section = temp/f"source-{index}.mp4"
                if remote:
                    try:
                        if dvr:
                            dvr.fetch(start,end,section,config.output_width)
                        else:
                            fetch_section(source,start,end,section,360)
                    except ValueError as exc:
                        if isinstance(exc, SourceAccessError) or len(coverage)==1:
                            raise
                        section.unlink(missing_ok=True)
                        warnings.append(f"Section {index+1} was unavailable.")
                        continue
                    make_proxy(section,proxy,0,end-start)
                    if not dvr:
                        section.unlink()
                else:
                    make_proxy(source,proxy,start,end-start)
                actual = min(get_video_info(proxy).duration_sec, end-start)
                bounds = [timeline_offset+start, timeline_offset+start+actual]
                covered.append(bounds)
                analysis["sections_read"] += 1
                batch_warnings = []
                report(progress_n+1, f"Measuring motion and gameplay in section {index+1}")
                visual = analyze_visual(proxy, sample_fps=config.clip_sample_fps, use_clip=config.use_clip,
                                        use_face_detection=False)
                from .vision_models import STATUS as vision_status
                analysis["frames_analyzed"] += len(visual.frame_scores)
                analysis["vision"] = (vision_status["backend"] if any(f.gameplay is not None for f in visual.frame_scores)
                                      else vision_status["state"])
                details()
                if (config.use_clip and any(not f.black and f.motion_score > .13 for f in visual.frame_scores)
                        and not any(f.gameplay is not None for f in visual.frame_scores)):
                    batch_warnings.append("Local gameplay model unavailable. Cloud verification is required for these frames.")
                if sum(f.motion_score > .13 and not f.black for f in visual.frame_scores) < 4:
                    if checkpoint:
                        checkpoints.save(checkpoint,[],[],bounds,batch_warnings)
                    section.unlink(missing_ok=True)
                    warnings.extend(batch_warnings)
                    continue
                release_models()
                report(progress_n+1, f"Checking scene cuts in section {index+1}")
                scenes = detect_scenes(proxy, config.scene_threshold, config.min_scene_length_sec)
                speech, energy = [], None
                audio_stream = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0",
                     "-show_entries", "stream=index", "-of", "csv=p=0", str(proxy)], capture_output=True, check=True)
                if audio_stream.stdout.strip():
                    audio = extract_audio(proxy, temp / f"audio-{index}.wav")
                    energy = analyze_audio_energy(audio, config.audio_hop_length, config.audio_frame_length)
                    report(progress_n+1, f"Transcribing audio in section {index+1}")
                    try:
                        cache = (saved_scans or temp)/"speech"
                        speech = groq_speech.transcribe(audio, config.whisper_language, cache, pause)
                        analysis["speech"] = "Groq Whisper" if speech is not None else "Local Whisper"
                        if speech is None:
                            speech = transcribe_audio(audio, config.whisper_model, config.whisper_language)
                        analysis["speech_segments"] += len(speech)
                    except (OSError, RuntimeError, ImportError, ValueError):
                        analysis["speech"] = "unavailable"
                        batch_warnings.append("Speech model unavailable; captions could not be generated for this section.")
                    finally:
                        release_models()
                    audio.unlink(missing_ok=True)
                transcript = [replace(seg,start=seg.start+start+timeline_offset,end=seg.end+start+timeline_offset)
                              for seg in speech]
                all_speech.extend(transcript)
                rows = candidates(proxy,start,actual,visual,energy,speech,scenes,config)
                analysis["candidate_windows"] += len(rows)
                if not audio_stream.stdout.strip():
                    analysis["speech"] = "no audio track"
                details()
                verified = []
                reviewed = 0
                for moment in rows:
                    if moment.score < config.min_highlight_score:
                        continue
                    if len(verified)>=config.max_clips or duplicate(moment,verified):
                        continue
                    if reviewed >= 3 and groq_review._keys():
                        break
                    verdict = None
                    cloud_source = "Gemini · decoded video and audio"
                    if (reviewed < 3 and groq_review._keys() and
                            (len(selected)<config.max_clips or moment.score>selected[-1].score)):
                        verdict = groq_review.review(proxy,moment.start-start,moment.end-moment.start,
                            " ".join(seg.text for seg in moment.speech),pause,(saved_scans or temp)/"vision-reviews")
                        reviewed += 1
                        if verdict is not None:
                            cloud_source = "Groq vision · source frames and transcript"
                            analysis["cloud_vision"] = "Groq vision"
                            details()
                    if verdict is None and cloud_active and (len(selected)<config.max_clips or moment.score>selected[-1].score):
                        preview = temp/"review.mp4"
                        make_proxy(proxy,preview,moment.start-start,moment.end-moment.start,224)
                        verdict = review(preview," ".join(seg.text for seg in moment.speech),pause,(saved_scans or temp)/"reviews")
                    if verify(moment,verdict,config,evidence_source=cloud_source):
                        analysis["verified_windows"] += 1
                        verified.append(moment)
                        retain(moment)
                if checkpoint:
                    checkpoints.save(checkpoint,verified,transcript,bounds,batch_warnings)
                if dvr:
                    retained_sources[start] = section
                    keep = {m.scan_start for m in selected}
                    for old_start in list(retained_sources):
                        if old_start not in keep:
                            retained_sources.pop(old_start).unlink(missing_ok=True)
                warnings.extend(batch_warnings)
                if config.scan_mode=="quick" and len(selected)>=config.max_clips:
                    warnings.append("Quick scan stopped after finding the requested verified clips. Full timeline mode inspects every section.")
                    break
            if not covered:
                raise ValueError("The video host did not return any inspectable sections.")
            if (not selected and analysis["vision"] == "unavailable" and
                    any("Local gameplay model unavailable" in warning for warning in warnings)):
                raise ValueError("The gameplay AI model could not load and no cloud reviewer verified the footage. Check model downloads and worker memory before retrying.")
            result.metadata["scanned_ranges"] = covered
            result.metadata["warnings"] = list(dict.fromkeys(warnings))
            release_models()
            if not selected:
                warnings.append("No windows passed the gameplay and action checks in the inspected footage.")
                result.metadata["warnings"] = list(dict.fromkeys(warnings))
            details()
            report(76,"Rendering verified highlights")
            for folder in ("clips", "subtitles", "thumbnails"):
                (output_dir/folder).mkdir(exist_ok=True)
            for idx, moment in enumerate(selected, 1):
                report(78 + int(20*(idx-1)/len(selected)), f"Rendering clip {idx} of {len(selected)}")
                original, cut_start = source, moment.start
                if dvr:
                    original,cut_start = retained_sources[moment.scan_start], moment.start-moment.scan_start
                elif remote:
                    original = temp/f"export-{idx}.mp4"
                    fetch_section(source, moment.start, moment.end, original, config.output_width)
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
                    config.overlay_badge, config.frame_style, config.subtitle_font)
                _generate_thumbnail(original, cut_start+moment.peak-moment.start, thumb)
                clip = GeneratedClip(idx, path, thumb, timeline_offset+moment.start, timeline_offset+moment.end, moment.end-moment.start,
                    moment.score, _generate_title(title, moment.hook, idx), moment.hook,
                    _generate_hashtags(moment.hook, config.default_hashtags), subs)
                clip.evidence = moment.evidence
                result.clips.append(clip)
            unique_speech = {(round(s.start,1),s.text): s for s in all_speech}
            _save_transcript(sorted(unique_speech.values(), key=lambda s:s.start), output_dir/"transcript.json")
            result.runtime_sec = time.monotonic()-started
            _save_metadata(result, output_dir)
            report(100, "Clips ready" if selected else "No qualifying gameplay found in the inspected footage")
    except SourceAccessError as exc:
        result.source_error = exc.code
        result.errors.append(str(exc))
    except (ValueError, FileNotFoundError) as exc:
        result.errors.append(str(exc) if isinstance(exc, ValueError) else "Input or processing dependency is unavailable.")
    except Exception as exc:
        result.errors.append(f"Processing failed ({type(exc).__name__}). Check installed models and FFmpeg.")
    finally:
        release_models()
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
        "pipeline_version": "4.1",
        "scanned_ranges": result.metadata.get("scanned_ranges", []),
        "warnings": result.metadata.get("warnings", []),
        "available_range": result.metadata.get("available_range"),
        "timeline_origin": result.metadata.get("timeline_origin"),
        "scan_mode": result.metadata.get("scan_mode"),
        "analysis": result.metadata.get("analysis", {}),
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
