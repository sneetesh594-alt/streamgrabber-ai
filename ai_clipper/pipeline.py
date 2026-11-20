"""
Main Pipeline Orchestrator - Poora AI Video Clipper pipeline ko coordinate karta hai.

Yeh module sabhi stages ko sequence me run karta hai:
1. Download/Load → 2. Scene Detection → 3. Audio Analysis → 
4. Visual Analysis → 5. NLP Scoring → 6. Signal Fusion → 
7. Clip Generation → 8. Packaging
"""

import json
import shutil
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


def run_pipeline(
    source: str,
    output_dir: str | Path = "./output",
    config=None,
) -> PipelineResult:
    """
    Full AI Video Clipper pipeline run karo.

    Args:
        source: YouTube URL ya local file path
        output_dir: Output directory for generated clips
        config: ClipperConfig instance (default: global config)

    Returns:
        PipelineResult with generated clips and metadata
    """
    if config is None:
        from .config import config as default_config
        config = default_config

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = output_dir / "temp"
    temp_dir.mkdir(exist_ok=True)

    result = PipelineResult(output_dir=output_dir)
    start_time = time.time()

    console.print("\n[bold magenta]" + "=" * 60 + "[/]")
    console.print("[bold magenta]  🎬 AI VIDEO CLIPPER PIPELINE  [/]")
    console.print("[bold magenta]" + "=" * 60 + "[/]\n")

    try:
        # ============================================================
        # STAGE 1: INGESTION - Video download ya load
        # ============================================================
        console.print("[bold yellow]━━━ STAGE 1: Ingestion ━━━[/]")

        from .downloader import download_video, load_local_video

        source_path = Path(source)
        if source_path.exists():
            video_info = load_local_video(source_path)
        else:
            # Assume it's a URL
            video_info = download_video(
                url=source,
                output_dir=temp_dir,
                quality=config.preferred_quality,
                max_duration_min=config.max_video_length_minutes,
            )

        result.metadata["source"] = source
        result.metadata["title"] = video_info.title
        result.metadata["duration_sec"] = video_info.duration_sec
        result.metadata["resolution"] = f"{video_info.width}x{video_info.height}"

        console.print(
            f"\n[green]✓ Video loaded:[/] {video_info.title} "
            f"({video_info.duration_sec:.0f}s)\n"
        )

        # ============================================================
        # STAGE 2: SCENE DETECTION
        # ============================================================
        console.print("[bold yellow]━━━ STAGE 2: Scene Detection ━━━[/]")

        from .scene_detector import detect_scenes

        scenes = detect_scenes(
            video_path=video_info.filepath,
            threshold=config.scene_threshold,
            min_scene_len_sec=config.min_scene_length_sec,
        )
        result.metadata["num_scenes"] = len(scenes)
        console.print()

        # ============================================================
        # STAGE 3: AUDIO ANALYSIS (Whisper + Energy)
        # ============================================================
        console.print("[bold yellow]━━━ STAGE 3: Audio Analysis ━━━[/]")

        from .audio_analyzer import extract_audio, transcribe_audio, analyze_audio_energy

        audio_path = extract_audio(video_info.filepath, temp_dir / "audio.wav")

        transcript_segments = transcribe_audio(
            audio_path=audio_path,
            model_name=config.whisper_model,
            language=config.whisper_language,
        )

        audio_features = analyze_audio_energy(
            audio_path=audio_path,
            hop_length=config.audio_hop_length,
            frame_length=config.audio_frame_length,
            loudness_percentile=config.loudness_threshold_percentile,
        )

        result.metadata["num_transcript_segments"] = len(transcript_segments)
        result.metadata["num_audio_peaks"] = len(audio_features.peaks)

        # Save transcript
        transcript_file = output_dir / "transcript.json"
        _save_transcript(transcript_segments, transcript_file)
        console.print()

        # ============================================================
        # STAGE 4: VISUAL ANALYSIS (CLIP + Face + Motion)
        # ============================================================
        console.print("[bold yellow]━━━ STAGE 4: Visual Analysis ━━━[/]")

        from .visual_analyzer import analyze_visual

        visual_analysis = analyze_visual(
            video_path=video_info.filepath,
            sample_fps=config.clip_sample_fps,
            clip_prompts=config.clip_prompts,
        )

        result.metadata["num_analyzed_frames"] = len(visual_analysis.frame_scores)
        console.print()

        # ============================================================
        # STAGE 5: NLP SCORING
        # ============================================================
        console.print("[bold yellow]━━━ STAGE 5: NLP Scoring ━━━[/]")

        from .nlp_scorer import score_transcript_segments

        text_scores = score_transcript_segments(transcript_segments)
        console.print()

        # ============================================================
        # STAGE 6: SIGNAL FUSION & PEAK DETECTION
        # ============================================================
        console.print("[bold yellow]━━━ STAGE 6: Signal Fusion ━━━[/]")

        from .scorer import build_scored_timeline, find_highlights

        timeline = build_scored_timeline(
            duration_sec=video_info.duration_sec,
            audio_features=audio_features,
            text_scores=text_scores,
            visual_analysis=visual_analysis,
            weight_audio=config.weight_audio,
            weight_text=config.weight_text,
            weight_visual=config.weight_visual,
        )

        highlights = find_highlights(
            timeline=timeline,
            min_distance_sec=config.peak_min_distance_sec,
            peak_prominence=config.peak_prominence,
            max_clips=config.max_clips,
            clip_duration_min=config.clip_duration_min_sec,
            clip_duration_max=config.clip_duration_max_sec,
            clip_duration_target=config.clip_duration_target_sec,
        )

        # Add hook text from NLP
        from .nlp_scorer import get_hook_text_at_time
        for h in highlights:
            h.hook_text = get_hook_text_at_time(text_scores, h.peak_time)

        console.print()

        # ============================================================
        # STAGE 7: CLIP GENERATION
        # ============================================================
        console.print("[bold yellow]━━━ STAGE 7: Clip Generation ━━━[/]")

        from .clip_generator import generate_clips

        generated_clips = generate_clips(
            video_path=video_info.filepath,
            highlights=highlights,
            transcript_segments=transcript_segments,
            visual_analysis=visual_analysis,
            text_scores=text_scores,
            output_dir=output_dir,
            output_width=config.output_width,
            output_height=config.output_height,
            output_fps=config.output_fps,
            subtitle_font_size=config.subtitle_font_size,
            subtitle_font_color=config.subtitle_font_color,
            subtitle_bg_color=config.subtitle_bg_color,
            hook_font_size=config.hook_font_size,
            hook_font_color=config.hook_font_color,
            default_hashtags=config.default_hashtags,
            video_title=video_info.title,
        )

        result.clips = generated_clips
        console.print()

        # ============================================================
        # STAGE 8: PACKAGING & METADATA
        # ============================================================
        console.print("[bold yellow]━━━ STAGE 8: Packaging ━━━[/]")

        _save_metadata(result, output_dir)
        console.print()

    except Exception as e:
        result.errors.append(str(e))
        console.print(f"\n[bold red]❌ Pipeline error: {e}[/]")
        import traceback
        traceback.print_exc()

    finally:
        result.runtime_sec = time.time() - start_time

    # Print summary
    _print_summary(result)

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
        "pipeline_version": "0.1.0",
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
