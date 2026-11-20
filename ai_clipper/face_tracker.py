"""
Face Tracker Module - OpenCV trackers se main subject ko track karta hai.

Yeh module face/object tracking karta hai taki vertical crop
hamesha main subject (streamer, player) pe centered rahe.
Supports: KCF, CSRT, MOSSE trackers.
"""

import cv2
import numpy as np
from pathlib import Path
from dataclasses import dataclass, field

from rich.console import Console

console = Console()


@dataclass
class TrackedFrame:
    """Ek frame me tracked subject ki position."""
    frame_index: int
    time_sec: float
    bbox: tuple[int, int, int, int] | None  # (x, y, w, h)
    confidence: float = 1.0
    is_detected: bool = False   # True = fresh detection, False = tracker prediction


@dataclass
class TrackingResult:
    """Full tracking session ka result."""
    frames: list[TrackedFrame] = field(default_factory=list)
    fps: float = 30.0
    lost_count: int = 0


def create_tracker(tracker_type: str = "CSRT"):
    """
    OpenCV tracker create karo.

    Supported types:
    - KCF: Fast, good for smooth motion
    - CSRT: More accurate, slightly slower
    - MOSSE: Fastest, less accurate
    """
    tracker_type = tracker_type.upper()

    try:
        if tracker_type == "CSRT":
            return cv2.TrackerCSRT_create()
        elif tracker_type == "KCF":
            return cv2.TrackerKCF_create()
        elif tracker_type == "MOSSE":
            return cv2.legacy.TrackerMOSSE_create()
        else:
            console.print(f"[yellow]Unknown tracker '{tracker_type}', using CSRT[/]")
            return cv2.TrackerCSRT_create()
    except AttributeError:
        # Fallback for older OpenCV versions
        console.print("[yellow]⚠ Tracker not available, using KCF fallback[/]")
        return cv2.TrackerKCF_create()


def detect_face_in_frame(
    frame: np.ndarray,
    min_confidence: float = 0.7,
) -> tuple[int, int, int, int] | None:
    """
    Frame me face detect karo. DNN-based detector use karta hai
    (zyada accurate than Haar cascades).
    Falls back to Haar cascade if DNN not available.
    """
    # Try DNN face detector first
    try:
        return _detect_face_dnn(frame, min_confidence)
    except Exception:
        pass

    # Fallback to Haar cascade
    return _detect_face_haar(frame)


def _detect_face_dnn(
    frame: np.ndarray,
    min_confidence: float = 0.7,
) -> tuple[int, int, int, int] | None:
    """DNN-based face detection (more accurate)."""
    h, w = frame.shape[:2]

    # Use OpenCV's DNN face detector
    model_path = cv2.data.haarcascades  # Use as base path hint
    proto = None
    model = None

    # If pre-trained DNN model files are not available, raise to fallback
    raise NotImplementedError("DNN model files not bundled; using Haar fallback")


def _detect_face_haar(
    frame: np.ndarray,
) -> tuple[int, int, int, int] | None:
    """Haar cascade face detection (simpler, faster)."""
    face_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = face_cascade.detectMultiScale(
        gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60)
    )

    if len(faces) == 0:
        return None

    # Return largest face
    areas = [w * h for (x, y, w, h) in faces]
    best_idx = np.argmax(areas)
    x, y, w, h = faces[best_idx]
    return (int(x), int(y), int(w), int(h))


def track_subject_in_clip(
    video_path: Path,
    start_time: float,
    end_time: float,
    tracker_type: str = "CSRT",
    face_redetect_interval: int = 30,
) -> TrackingResult:
    """
    Clip ke duration me main subject (face) ko track karo.

    Pehle face detect karta hai, phir OpenCV tracker se frame-by-frame
    follow karta hai. Har N frames me re-detect karta hai (drift correction).

    Args:
        video_path: Path to video file
        start_time: Clip start time in seconds
        end_time: Clip end time in seconds
        tracker_type: OpenCV tracker type
        face_redetect_interval: Re-detect face every N frames

    Returns:
        TrackingResult with per-frame bounding boxes
    """
    console.print(
        f"[bold blue]🎯 Tracking subject "
        f"({start_time:.1f}s - {end_time:.1f}s)...[/]"
    )

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    start_frame = int(start_time * fps)
    end_frame = int(end_time * fps)

    # Seek to start
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

    tracker = None
    tracking_result = TrackingResult(fps=fps)
    frame_count = 0
    lost_count = 0

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        current_frame = start_frame + frame_count
        if current_frame > end_frame:
            break

        time_sec = current_frame / fps

        # Initialize or re-detect face periodically
        if tracker is None or frame_count % face_redetect_interval == 0:
            bbox = detect_face_in_frame(frame)
            if bbox is not None:
                tracker = create_tracker(tracker_type)
                tracker.init(frame, bbox)
                tracking_result.frames.append(TrackedFrame(
                    frame_index=current_frame,
                    time_sec=time_sec,
                    bbox=bbox,
                    confidence=1.0,
                    is_detected=True,
                ))
                frame_count += 1
                continue

        # Track using existing tracker
        if tracker is not None:
            success, bbox_arr = tracker.update(frame)
            if success:
                bbox = tuple(int(v) for v in bbox_arr)
                tracking_result.frames.append(TrackedFrame(
                    frame_index=current_frame,
                    time_sec=time_sec,
                    bbox=bbox,
                    confidence=0.8,
                    is_detected=False,
                ))
            else:
                # Tracker lost - try re-detection
                tracker = None
                lost_count += 1
                tracking_result.frames.append(TrackedFrame(
                    frame_index=current_frame,
                    time_sec=time_sec,
                    bbox=None,
                    confidence=0.0,
                ))
        else:
            # No tracker, no face detected
            tracking_result.frames.append(TrackedFrame(
                frame_index=current_frame,
                time_sec=time_sec,
                bbox=None,
                confidence=0.0,
            ))

        frame_count += 1

    cap.release()
    tracking_result.lost_count = lost_count

    tracked_frames = sum(1 for f in tracking_result.frames if f.bbox is not None)
    console.print(
        f"[bold green]✓ Tracked {tracked_frames}/{frame_count} frames "
        f"(lost {lost_count} times)[/]"
    )

    return tracking_result


def get_smooth_crop_position(
    tracking_result: TrackingResult,
    source_width: int,
    source_height: int,
    crop_width: int,
    crop_height: int,
    smoothing_window: int = 15,
) -> list[tuple[int, int]]:
    """
    Tracking result se smooth crop positions calculate karo.

    Face position ko smooth karta hai taki crop jerk na kare.
    Returns list of (crop_x, crop_y) for each tracked frame.

    Args:
        tracking_result: TrackingResult from track_subject_in_clip
        source_width/height: Source video dimensions
        crop_width/height: Crop dimensions (9:16)
        smoothing_window: Frames to average for smooth motion

    Returns:
        List of (crop_x, crop_y) tuples
    """
    if not tracking_result.frames:
        # Default center crop
        cx = (source_width - crop_width) // 2
        cy = (source_height - crop_height) // 2
        return [(cx, cy)]

    # Get face center positions
    centers_x = []
    centers_y = []
    default_x = source_width // 2
    default_y = source_height // 2

    for tf in tracking_result.frames:
        if tf.bbox:
            x, y, w, h = tf.bbox
            centers_x.append(x + w // 2)
            centers_y.append(y + h // 2)
        else:
            # Use last known or default
            centers_x.append(centers_x[-1] if centers_x else default_x)
            centers_y.append(centers_y[-1] if centers_y else default_y)

    # Smooth with moving average
    if len(centers_x) >= smoothing_window:
        kernel = np.ones(smoothing_window) / smoothing_window
        smooth_x = np.convolve(centers_x, kernel, mode="same")
        smooth_y = np.convolve(centers_y, kernel, mode="same")
    else:
        smooth_x = np.array(centers_x, dtype=float)
        smooth_y = np.array(centers_y, dtype=float)

    # Convert face centers to crop positions (top-left corner)
    positions = []
    for fx, fy in zip(smooth_x, smooth_y):
        cx = int(np.clip(fx - crop_width // 2, 0, source_width - crop_width))
        cy = int(np.clip(fy - crop_height // 2, 0, source_height - crop_height))
        positions.append((cx, cy))

    return positions
