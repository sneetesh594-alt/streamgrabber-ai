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
        scene_manager.detect_scenes(video, show_progress=False)
        scene_list = scene_manager.get_scene_list(start_in_scene=True)

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

    import re
    from .downloader import get_video_info
    info = get_video_info(video_path)
    # FFmpeg emits each detected frame's actual presentation time via showinfo.
    proc = subprocess.run(["ffmpeg", "-nostdin", "-i", str(video_path), "-an", "-vf",
                           f"select='gt(scene,{min(threshold/100, .9)})',showinfo",
                           "-f", "null", "-"], capture_output=True, text=True, check=True)
    cuts = [0.]
    for timestamp in re.findall(r"pts_time:([0-9.]+)", proc.stderr):
        t = float(timestamp)
        if t - cuts[-1] >= min_scene_len_sec and t < info.duration_sec:
            cuts.append(t)
    cuts.append(info.duration_sec)
    return [Scene(i, a, b, int(a * info.fps), int(b * info.fps))
            for i, (a, b) in enumerate(zip(cuts, cuts[1:]))]


def get_scene_at_time(scenes: list[Scene], time_sec: float) -> Scene | None:
    """Given time pe kaun sa scene hai, woh return karo."""
    for scene in scenes:
        if scene.start_time <= time_sec <= scene.end_time:
            return scene
    return None
