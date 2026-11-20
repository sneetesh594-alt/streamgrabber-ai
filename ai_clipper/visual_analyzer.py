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

    # Initialize CLIP if requested
    clip_model = None
    clip_preprocess = None
    clip_tokenizer = None
    clip_text_features = None
    device = "cpu"

    if use_clip:
        clip_model, clip_preprocess, clip_tokenizer, clip_text_features, device = (
            _init_clip(clip_prompts)
        )

    # Initialize face detector
    face_cascade = None
    if use_face_detection:
        face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )

    # Analyze frames
    frame_scores = []
    prev_gray = None
    frame_idx = 0

    with Progress() as progress:
        task = progress.add_task("[cyan]Analyzing frames...", total=total_frames)

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % sample_interval == 0:
                time_sec = frame_idx / video_fps
                score = FrameScore(time_sec=time_sec, frame_index=frame_idx)

                # --- CLIP Scoring ---
                if clip_model is not None:
                    score.clip_score = _score_frame_clip(
                        frame, clip_model, clip_preprocess, clip_text_features, device
                    )

                # --- Face Detection ---
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                if face_cascade is not None:
                    score.face_score, score.face_bbox = _detect_face(frame, gray, face_cascade)

                # --- Motion Detection ---
                if use_motion_detection and prev_gray is not None:
                    score.motion_score = _detect_motion(prev_gray, gray)

                prev_gray = gray

                # Combined score (simple average for now; weighted in scorer module)
                scores = []
                if use_clip:
                    scores.append(score.clip_score)
                if use_face_detection:
                    scores.append(score.face_score)
                if use_motion_detection:
                    scores.append(score.motion_score)
                score.combined_score = np.mean(scores) if scores else 0.0

                frame_scores.append(score)

            frame_idx += 1
            progress.update(task, advance=1)

    cap.release()

    console.print(f"[bold green]✓ Analyzed {len(frame_scores)} frames[/]")

    return VisualAnalysis(
        frame_scores=frame_scores,
        fps=video_fps,
        total_frames=total_frames,
    )


def _init_clip(prompts: list[str] | None = None):
    """CLIP model initialize karo."""
    try:
        import open_clip
        import torch

        device = "cuda" if torch.cuda.is_available() else "cpu"
        console.print(f"[dim]Loading CLIP model on {device}...[/dim]")

        model, _, preprocess = open_clip.create_model_and_transforms(
            "ViT-B-32", pretrained="laion2b_s34b_b79k"
        )
        model = model.to(device).eval()
        tokenizer = open_clip.get_tokenizer("ViT-B-32")

        # Pre-compute text features for prompts
        default_prompts = prompts or [
            "an exciting action scene",
            "a dramatic moment",
            "an explosion or crash",
            "a funny moment",
            "a person celebrating",
            "a car chase",
            "a fight scene",
            "a beautiful cinematic shot",
        ]

        with torch.no_grad():
            text_tokens = tokenizer(default_prompts).to(device)
            text_features = model.encode_text(text_tokens)
            text_features /= text_features.norm(dim=-1, keepdim=True)

        console.print(f"[dim]CLIP ready with {len(default_prompts)} prompts[/dim]")
        return model, preprocess, tokenizer, text_features, device

    except ImportError:
        console.print("[yellow]⚠ open_clip not installed. CLIP scoring disabled.[/]")
        return None, None, None, None, "cpu"


def _score_frame_clip(frame, model, preprocess, text_features, device) -> float:
    """
    Ek frame ko CLIP se score karo.
    Frame ko text prompts ke saath compare karke similarity score deta hai.
    """
    import torch
    from PIL import Image

    try:
        # Convert OpenCV BGR to RGB PIL Image
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil_image = Image.fromarray(rgb)

        # Preprocess and encode
        with torch.no_grad():
            image_input = preprocess(pil_image).unsqueeze(0).to(device)
            image_features = model.encode_image(image_input)
            image_features /= image_features.norm(dim=-1, keepdim=True)

            # Cosine similarity with all text prompts
            similarity = (image_features @ text_features.T).squeeze(0)

            # Take max similarity across prompts, normalize to 0-1
            max_sim = similarity.max().item()
            # CLIP similarities are typically 0.15-0.35, normalize
            score = np.clip((max_sim - 0.15) / 0.25, 0.0, 1.0)

        return float(score)

    except Exception as e:
        console.print(f"[dim red]CLIP scoring error: {e}[/dim red]")
        return 0.0


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


def _detect_motion(prev_gray, curr_gray) -> float:
    """
    Do frames ke beech motion detect karo using optical flow magnitude.
    High motion = action scene.
    """
    try:
        flow = cv2.calcOpticalFlowFarneback(
            prev_gray, curr_gray,
            None,
            pyr_scale=0.5, levels=3, winsize=15,
            iterations=3, poly_n=5, poly_sigma=1.2, flags=0
        )
        magnitude = np.sqrt(flow[..., 0] ** 2 + flow[..., 1] ** 2)
        mean_motion = np.mean(magnitude)

        # Normalize (typical values are 0-20, high action can be 50+)
        score = np.clip(mean_motion / 15.0, 0.0, 1.0)
        return float(score)

    except Exception:
        return 0.0


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
