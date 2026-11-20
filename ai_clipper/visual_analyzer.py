"""
Visual Analysis Module - CLIP scoring + Face/Object tracking.

Yeh module video frames ko analyze karta hai:
1. CLIP embeddings se "interesting content" score karta hai
2. Face detection + tracking se main subject follow karta hai
3. Motion detection se action scenes identify karta hai
"""

import cv2
import numpy as np
from pathlib import Path
from collections import deque
from dataclasses import dataclass, field

from rich.console import Console
from rich.progress import Progress

console = Console()


@dataclass
class FrameScore:
    """Ek frame ka visual analysis result."""
    time_sec: float
    frame_index: int
    clip_score: float = 0.0        # CLIP-based "interesting" score (0-1)
    face_score: float = 0.0        # Face presence/size score (0-1)
    motion_score: float = 0.0      # Motion intensity score (0-1)
    combined_score: float = 0.0    # Weighted combination

    gameplay: float | None = None
    black: bool = False
    fingerprint: int = 0
    field_motion: float = 0.0

    # Face tracking info (for cropping)
    face_bbox: tuple[int, int, int, int] | None = None  # (x, y, w, h)


@dataclass
class VisualAnalysis:
    """Full visual analysis ka result."""
    frame_scores: list[FrameScore] = field(default_factory=list)
    fps: float = 30.0
    total_frames: int = 0


def analyze_visual(
    video_path: Path,
    sample_fps: float = 1.0,
    clip_prompts: list[str] | None = None,
    use_clip: bool = True,
    use_face_detection: bool = True,
    use_motion_detection: bool = True,
) -> VisualAnalysis:
    """
    Video ke frames ko visually analyze karo.

    Args:
        video_path: Path to video file
        sample_fps: Kitne frames per second sample karne hain
        clip_prompts: CLIP text prompts for scoring
        use_clip: CLIP scoring enable/disable
        use_face_detection: Face detection enable/disable
        use_motion_detection: Motion detection enable/disable

    Returns:
        VisualAnalysis with per-frame scores
    """
    console.print(f"[bold blue]👁 Analyzing visual content...[/]")

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    video_fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / video_fps if video_fps > 0 else 0

    # Sample every Nth frame based on desired sample_fps
    sample_interval = max(1, int(video_fps / sample_fps))

    console.print(
        f"[dim]Video: {total_frames} frames, {video_fps:.1f} fps, "
        f"{duration:.1f}s | Sampling every {sample_interval} frames[/dim]"
    )

    from .vision_models import classifier
    classifier_fn = classifier() if use_clip else None

    # Initialize face detector
    face_cascade = None
    if use_face_detection:
        face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )

    # Analyze frames
    frame_scores = []
    prev_gray = None
    short_history = deque(maxlen=max(1, round(video_fps * .25)))
    frame_idx = 0

    with Progress() as progress:
        task = progress.add_task("[cyan]Analyzing frames...", total=total_frames)

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            flow_gray = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (240, 135), interpolation=cv2.INTER_AREA)
            if frame_idx % sample_interval == 0:
                time_sec = frame_idx / video_fps
                score = FrameScore(time_sec=time_sec, frame_index=frame_idx)

                if classifier_fn is not None:
                    score.gameplay, score.clip_score = classifier_fn(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

                # --- Face Detection ---
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                if face_cascade is not None:
                    score.face_score, score.face_bbox = _detect_face(frame, gray, face_cascade)
                small = cv2.resize(gray, (128, 72), interpolation=cv2.INTER_AREA)
                score.black = bool(np.percentile(small, 92) < 24 or small.std() < 3)
                thumb = cv2.resize(small, (9, 8), interpolation=cv2.INTER_AREA)
                score.fingerprint = int.from_bytes(np.packbits(thumb[:, 1:] > thumb[:, :-1]).tobytes(), "big")
                if use_motion_detection and len(short_history) == short_history.maxlen:
                    score.field_motion = _field_motion(short_history[0], flow_gray)
                if use_motion_detection and prev_gray is not None:
                    diff = cv2.absdiff(prev_gray, small)
                    moving = float((diff > 12).mean())
                    score.motion_score = min(1.0, moving * 1.8)
                prev_gray = small
                score.combined_score = .55 * score.motion_score + .45 * score.clip_score

                frame_scores.append(score)

            short_history.append(flow_gray)
            frame_idx += 1
            progress.update(task, advance=1)

    cap.release()

    console.print(f"[bold green]✓ Analyzed {len(frame_scores)} frames[/]")

    return VisualAnalysis(
        frame_scores=frame_scores,
        fps=video_fps,
        total_frames=total_frames,
    )


def _detect_face(frame, gray, face_cascade) -> tuple[float, tuple | None]:
    """
    Frame me face detect karo. Score = face area / frame area.
    Sabse bada face return karta hai (usually main subject).
    """
    faces = face_cascade.detectMultiScale(
        gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60)
    )

    if len(faces) == 0:
        return 0.0, None

    # Sabse bada face
    areas = [w * h for (x, y, w, h) in faces]
    best_idx = np.argmax(areas)
    x, y, w, h = faces[best_idx]

    # Score = face area ratio (0-1), capped
    frame_area = frame.shape[0] * frame.shape[1]
    score = min((w * h) / frame_area * 10, 1.0)  # Scale up small faces

    return float(score), (int(x), int(y), int(w), int(h))


def _field_motion(previous, current):
    """Fraction of tracked features moving across the field in a quarter second."""
    points = cv2.goodFeaturesToTrack(previous, 120, .02, 5)
    if points is None or len(points) < 8:
        return 0.
    moved, ok, _ = cv2.calcOpticalFlowPyrLK(previous, current, points, None)
    if moved is None:
        return 0.
    mask = ok.ravel().astype(bool)
    if mask.sum() < 8:
        return 0.
    displacement = np.linalg.norm((moved[mask] - points[mask]).reshape(-1, 2), axis=1)
    return float((displacement > 1.5).mean())


def get_visual_score_at_time(analysis: VisualAnalysis, time_sec: float) -> float:
    """Given time pe visual score return karo (nearest frame)."""
    if not analysis.frame_scores:
        return 0.0
    times = [fs.time_sec for fs in analysis.frame_scores]
    idx = np.searchsorted(times, time_sec)
    idx = min(idx, len(analysis.frame_scores) - 1)
    return analysis.frame_scores[idx].combined_score


def get_face_bbox_at_time(
    analysis: VisualAnalysis, time_sec: float
) -> tuple[int, int, int, int] | None:
    """Given time pe face bounding box return karo."""
    if not analysis.frame_scores:
        return None
    times = [fs.time_sec for fs in analysis.frame_scores]
    idx = np.searchsorted(times, time_sec)
    idx = min(idx, len(analysis.frame_scores) - 1)
    return analysis.frame_scores[idx].face_bbox
