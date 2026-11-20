"""
Scene Detection Module - PySceneDetect se video ko scenes/shots me split karta hai.

Yeh module video me cuts/fades detect karke scene boundaries identify karta hai,
taki baad me har scene ko independently analyze kar sakein.
"""

import subprocess
from pathlib import Path
from dataclasses import dataclass

from rich.console import Console

console = Console()


@dataclass
class Scene:
    """Ek detected scene ka representation."""
    index: int
    start_time: float    # seconds
    end_time: float      # seconds
    start_frame: int
    end_frame: int

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time

    @property
    def midpoint(self) -> float:
        return (self.start_time + self.end_time) / 2.0


def detect_scenes(
    video_path: Path,
    threshold: float = 27.0,
    min_scene_len_sec: float = 2.0,
) -> list[Scene]:
    """
    PySceneDetect se video me scenes detect karo.

    ContentDetector use karta hai jo frame-by-frame pixel changes dekhta hai.
    Jab bhi significant change aaye (cut/fade), woh ek scene boundary mark karta hai.

    Args:
        video_path: Path to video file
        threshold: ContentDetector sensitivity (lower = more scenes)
        min_scene_len_sec: Minimum scene length in seconds

    Returns:
        List of Scene objects with timestamps
    """
    console.print(f"[bold blue]🎬 Detecting scenes...[/] (threshold={threshold})")

    try:
        from scenedetect import open_video, SceneManager
        from scenedetect.detectors import ContentDetector

        video = open_video(str(video_path))
        scene_manager = SceneManager()
        scene_manager.add_detector(
            ContentDetector(
                threshold=threshold,
                min_scene_len=int(min_scene_len_sec * video.frame_rate),
            )
        )

        # Detect scenes
        scene_manager.detect_scenes(video, show_progress=True)
        scene_list = scene_manager.get_scene_list()

        scenes = []
        for i, (start, end) in enumerate(scene_list):
            scenes.append(Scene(
                index=i,
                start_time=start.get_seconds(),
                end_time=end.get_seconds(),
                start_frame=start.get_frames(),
                end_frame=end.get_frames(),
            ))

        console.print(f"[bold green]✓ Found {len(scenes)} scenes[/]")
        return scenes

    except ImportError:
        console.print("[yellow]⚠ scenedetect not installed, using FFmpeg fallback...[/]")
        return _detect_scenes_ffmpeg(video_path, threshold, min_scene_len_sec)


def _detect_scenes_ffmpeg(
    video_path: Path,
    threshold: float = 0.3,
    min_scene_len_sec: float = 2.0,
) -> list[Scene]:
    """
    FFmpeg scene detection fallback.
    Uses the 'select' filter with scene change detection.
    """
    import json

    # FFmpeg scene detection threshold is 0-1 (normalize from PySceneDetect scale)
    ff_threshold = min(threshold / 100.0, 0.9)

    cmd = [
        "ffprobe", "-v", "quiet",
        "-show_frames",
        "-print_format", "json",
        "-f", "lavfi",
        f"movie={str(video_path)},select='gt(scene,{ff_threshold})'",
    ]

    # Simpler approach: use ffprobe to get duration and split uniformly as fallback
    duration_cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        str(video_path)
    ]

    result = subprocess.run(duration_cmd, capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    total_duration = float(data["format"]["duration"])

    # Create uniform scenes as a simple fallback
    scenes = []
    scene_len = max(min_scene_len_sec, 5.0)  # 5-second scenes
    t = 0.0
    idx = 0
    while t < total_duration:
        end = min(t + scene_len, total_duration)
        scenes.append(Scene(
            index=idx,
            start_time=t,
            end_time=end,
            start_frame=int(t * 30),  # Approximate
            end_frame=int(end * 30),
        ))
        t = end
        idx += 1

    console.print(f"[bold green]✓ Created {len(scenes)} uniform scenes (FFmpeg fallback)[/]")
    return scenes


def get_scene_at_time(scenes: list[Scene], time_sec: float) -> Scene | None:
    """Given time pe kaun sa scene hai, woh return karo."""
    for scene in scenes:
        if scene.start_time <= time_sec <= scene.end_time:
            return scene
    return None
