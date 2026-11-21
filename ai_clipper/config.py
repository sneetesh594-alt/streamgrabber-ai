"""
Configuration settings for the AI Video Clipper pipeline.
Yahan sab default configs hain - weights, thresholds, paths, etc.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

load_dotenv(override=False)
from pydantic import Field
from pathlib import Path
from typing import Optional, Literal


class ClipperConfig(BaseSettings):
    """Master configuration for the entire pipeline."""

    # --- Paths ---
    output_dir: Path = Field(default=Path("./output"), description="Output directory for clips")
    temp_dir: Path = Field(default=Path("./temp"), description="Temporary files directory")
    models_dir: Path = Field(default=Path("./models"), description="Cached models directory")

    # --- Video Download ---
    max_video_length_minutes: int = Field(default=1440, description="Max video length in minutes")
    preferred_quality: str = Field(default="720p", description="Download quality (360p/480p/720p/1080p)")

    # --- Scene Detection ---
    scene_threshold: float = Field(default=27.0, description="PySceneDetect ContentDetector threshold")
    min_scene_length_sec: float = Field(default=2.0, description="Minimum scene length in seconds")

    # --- Whisper (Speech-to-Text) ---
    whisper_model: str = Field(default="base", description="Whisper model size (tiny/base/small/medium/large)")
    whisper_language: Optional[str] = Field(default=None, description="Language code (None=auto-detect)")

    # --- Audio Analysis ---
    audio_hop_length: int = Field(default=512, description="Hop length for audio analysis")
    audio_frame_length: int = Field(default=2048, description="Frame length for audio analysis")
    loudness_threshold_percentile: float = Field(default=75.0, description="Percentile for loud moments")

    # --- CLIP (Visual Analysis) ---
    clip_model_name: str = Field(default="ViT-B-32", description="CLIP model architecture")
    clip_pretrained: str = Field(default="laion2b_s34b_b79k", description="CLIP pretrained weights")
    clip_sample_fps: float = Field(default=1.0, gt=0, le=8, description="Frames per second to sample for CLIP")
    clip_prompts: list[str] = Field(
        default=[
            "an exciting action scene",
            "a dramatic moment",
            "an explosion or crash",
            "a funny moment",
            "a person celebrating",
            "a car chase",
            "a fight scene",
            "a beautiful cinematic shot",
        ],
        description="Text prompts for CLIP scoring"
    )

    # --- Face/Object Tracking ---
    tracker_type: str = Field(default="CSRT", description="OpenCV tracker type (KCF/CSRT/MOSSE)")
    face_detection_confidence: float = Field(default=0.7, description="Min confidence for face detection")
    face_detection_interval: int = Field(default=30, description="Re-detect face every N frames")

    # --- Scoring Weights ---
    weight_audio: float = Field(default=0.30, description="Weight for audio energy score")
    weight_text: float = Field(default=0.35, description="Weight for transcript/NLP score")
    weight_visual: float = Field(default=0.35, description="Weight for visual/CLIP score")

    # --- Peak Detection ---
    peak_min_distance_sec: float = Field(default=30.0, description="Min distance between peaks in seconds")
    peak_prominence: float = Field(default=0.3, description="Min prominence for peak detection")
    max_clips: int = Field(default=10, description="Maximum number of clips to generate")

    # --- Clip Output ---
    clip_duration_min_sec: float = Field(default=20.0, description="Minimum clip duration in seconds")
    clip_duration_max_sec: float = Field(default=45.0, description="Maximum clip duration in seconds")
    clip_duration_target_sec: float = Field(default=30.0, ge=20, le=45, description="Target clip duration in seconds")
    output_width: int = Field(default=1080, description="Output video width (9:16)")
    output_height: int = Field(default=1920, description="Output video height (9:16)")
    output_fps: int = Field(default=30, description="Output video FPS")

    # --- Subtitles ---
    subtitle_font_size: int = Field(default=42, description="Subtitle font size")
    subtitle_font_color: str = Field(default="white", description="Subtitle font color")
    subtitle_bg_color: str = Field(default="black@0.6", description="Subtitle background color")
    subtitle_position: str = Field(default="bottom", description="Subtitle position (top/center/bottom)")

    # --- Hook Text ---
    hook_font_size: int = Field(default=52, description="Hook text font size")
    hook_font_color: str = Field(default="yellow", description="Hook text color")
    hook_position: str = Field(default="top", description="Hook text position")

    # --- Metadata ---
    default_hashtags: list[str] = Field(
        default=["#Shorts", "#Gaming", "#Highlights", "#GTA6", "#Gameplay"],
        description="Default hashtags for generated clips"
    )

    subtitle_font: Literal["Sans", "Serif", "Mono"] = "Sans"
    enable_overlay: bool = True
    creator_tag: str = ""
    overlay_badge: str = "GTA VI"
    frame_style: str = "blur_bg"
    use_clip: bool = True
    use_face: bool = True
    scan_mode: Literal["full", "quick"] = "full"
    range_start: float = Field(default=0, ge=0, allow_inf_nan=False)
    range_end: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    scan_budget: int = Field(default=14, ge=1, le=120)
    min_highlight_score: float = Field(default=.33, ge=0, le=1)
    model_config = SettingsConfigDict(env_prefix="CLIPPER_", env_file=".env", extra="ignore")


config = ClipperConfig()
