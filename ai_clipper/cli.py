"""
AI Video Clipper - Command Line Interface.

CLI se poora pipeline run kar sakte ho:
  python -m ai_clipper clip <URL_or_FILE>
  python -m ai_clipper clip --help

Usage examples:
  # YouTube URL se clips banao
  python -m ai_clipper clip "https://youtube.com/watch?v=XXXXX" -o ./my_clips

  # Local file se clips banao
  python -m ai_clipper clip gameplay.mp4 --max-clips 5

  # Custom weights ke sath
  python -m ai_clipper clip video.mp4 --weight-audio 0.4 --weight-text 0.3 --weight-visual 0.3
"""

import sys
import click
from pathlib import Path

from rich.console import Console

console = Console()


@click.group()
@click.version_option(version="4.1.0", prog_name="AI Video Clipper")
def cli():
    """🎬 AI Video Clipper - Automatic highlight detection and clip generation."""
    pass


@cli.command()
@click.argument("source")
@click.option("-o", "--output", default="./output", help="Output directory")
@click.option("--scan-mode",type=click.Choice(["full","quick"]),default="full",show_default=True)
@click.option("--start-seconds",type=click.FloatRange(min=0),default=0.)
@click.option("--end-seconds",type=click.FloatRange(min=0,min_open=True),default=None)
@click.option("--max-clips",type=click.IntRange(1,10), default=10, help="Maximum clips to generate")
@click.option("--clip-duration",type=click.FloatRange(20,45), default=30.0, help="Target clip duration (seconds)")
@click.option("--quality", type=click.Choice(["360p", "480p", "720p", "1080p"]), default="720p", help="1080p or 720p portrait export; 360p and 480p remain 720p aliases.")
@click.option("--whisper-model", default="base", help="Whisper model (tiny/base/small/medium/large)")
@click.option("--language", default=None, help="Language code (en/hi/auto)")
@click.option("--weight-audio", default=0.30, help="Audio score weight (0-1)")
@click.option("--weight-text", default=0.35, help="Text score weight (0-1)")
@click.option("--weight-visual", default=0.35, help="Visual score weight (0-1)")
@click.option("--no-clip", is_flag=True, help="Use CLIP scoring (default on)")
@click.option("--no-face", is_flag=True, help="Disable face tracking")
@click.option("--scene-threshold", default=27.0, help="Scene detection threshold")
@click.option("--subtitle-size", default=42, help="Subtitle font size")
@click.option("--hook-size", default=52, help="Hook text font size")
@click.option("--hashtags", default="#Shorts,#Gaming,#Highlights,#GTA6", help="Comma-separated hashtags")
def clip(
    source, output, max_clips, clip_duration, quality, scan_mode,start_seconds,end_seconds,
    whisper_model, language, weight_audio, weight_text, weight_visual,
    no_clip, no_face, scene_threshold, subtitle_size, hook_size, hashtags,
):
    """
    Video se highlight clips generate karo.

    SOURCE: YouTube URL ya local video file path.

    Examples:
      ai_clipper clip "https://youtube.com/watch?v=XXXXX"
      ai_clipper clip gameplay.mp4 -o ./clips --max-clips 5
      ai_clipper clip stream.mp4 --whisper-model medium --language en
    """
    from .config import ClipperConfig
    from .pipeline import run_pipeline

    # Build config from CLI options
    config = ClipperConfig(
        output_dir=Path(output),scan_mode=scan_mode,range_start=start_seconds, range_end=end_seconds,
        max_clips=max_clips,
        clip_duration_target_sec=clip_duration,
        preferred_quality=quality,
        output_width=1080 if quality == "1080p" else 720,
        output_height=1920 if quality == "1080p" else 1280,
        use_clip=not no_clip, use_face=not no_face,
        whisper_model=whisper_model,
        whisper_language=language,
        weight_audio=weight_audio,
        weight_text=weight_text,
        weight_visual=weight_visual,
        scene_threshold=scene_threshold,
        subtitle_font_size=subtitle_size,
        hook_font_size=hook_size,
        default_hashtags=[t.strip() for t in hashtags.split(",")],
    )

    console.print(f"\n[bold]Source:[/] {source}")
    console.print(f"[bold]Output:[/] {output}")
    console.print(f"[bold]Max clips:[/] {max_clips}")
    console.print()

    result = run_pipeline(
        source=source,
        output_dir=output,
        config=config,
    )

    if result.errors:
        for message in result.errors:
            console.print(message, style="red", markup=False)
        sys.exit(1)


@cli.command()
@click.argument("source")
@click.option("-o", "--output", default="./output", help="Output directory")
def analyze(source, output):
    """
    Video analyze karo bina clips banaye (sirf scoring timeline dekho).

    Useful for debugging and tuning weights.
    """
    from .config import config
    from .downloader import download_video, load_local_video
    from .audio_analyzer import extract_audio, transcribe_audio, analyze_audio_energy
    from .visual_analyzer import analyze_visual
    from .nlp_scorer import score_transcript_segments
    from .scorer import build_scored_timeline, find_highlights

    output_dir = Path(output)
    output_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = output_dir / "temp"
    temp_dir.mkdir(exist_ok=True)

    # Load video
    source_path = Path(source)
    if source_path.exists():
        video_info = load_local_video(source_path)
    else:
        video_info = download_video(source, temp_dir)

    # Audio
    audio_path = extract_audio(video_info.filepath, temp_dir / "audio.wav")
    transcript = transcribe_audio(audio_path, config.whisper_model)
    audio_features = analyze_audio_energy(audio_path)

    # Visual
    visual = analyze_visual(video_info.filepath, sample_fps=0.5)

    # NLP
    text_scores = score_transcript_segments(transcript)

    # Scoring
    timeline = build_scored_timeline(
        video_info.duration_sec, audio_features, text_scores, visual
    )
    highlights = find_highlights(timeline)

    console.print("\n[bold]Analysis complete! Check the highlights above.[/]")
    console.print("[dim]Run 'clip' command to generate actual video clips.[/dim]")


@cli.command()
def info():
    """System info aur dependencies check karo."""
    import shutil

    console.print("[bold]🔧 System Check[/]\n")

    # Check external tools
    tools = {
        "ffmpeg": shutil.which("ffmpeg"),
        "ffprobe": shutil.which("ffprobe"),
        "yt-dlp": shutil.which("yt-dlp"),
    }
    for tool, path in tools.items():
        if path:
            console.print(f"  [green]✓[/] {tool}: {path}")
        else:
            console.print(f"  [red]✗[/] {tool}: NOT FOUND")

    # Check Python packages
    console.print("\n[bold]Python Packages:[/]\n")
    packages = [
        "whisper", "librosa", "cv2", "open_clip",
        "scenedetect", "transformers", "torch", "numpy",
        "click", "rich", "fastapi",
    ]
    for pkg in packages:
        try:
            mod = __import__(pkg)
            version = getattr(mod, "__version__", "✓")
            console.print(f"  [green]✓[/] {pkg}: {version}")
        except ImportError:
            console.print(f"  [red]✗[/] {pkg}: NOT INSTALLED")

    # Check GPU
    console.print("\n[bold]GPU:[/]\n")
    try:
        import torch
        if torch.cuda.is_available():
            console.print(f"  [green]✓[/] CUDA: {torch.cuda.get_device_name(0)}")
        else:
            console.print("  [yellow]⚠[/] No CUDA GPU (CPU mode will be slower)")
    except ImportError:
        console.print("  [red]✗[/] PyTorch not installed")


def main():
    cli()


if __name__ == "__main__":
    main()
