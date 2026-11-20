"""
AI Video Clipper - Basic Tests.

Yeh test file pipeline ke individual components ko test karti hai.
Run: python -m pytest tests/ -v
"""

import sys
import pytest
import numpy as np
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestConfig:
    """Config module tests."""

    def test_default_config(self):
        from ai_clipper.config import ClipperConfig
        config = ClipperConfig()
        assert config.output_width == 1080
        assert config.output_height == 1920
        assert config.whisper_model == "base"
        assert config.weight_audio + config.weight_text + config.weight_visual == pytest.approx(1.0)

    def test_custom_config(self):
        from ai_clipper.config import ClipperConfig
        config = ClipperConfig(
            whisper_model="tiny",
            max_clips=5,
            weight_audio=0.5,
            weight_text=0.25,
            weight_visual=0.25,
        )
        assert config.whisper_model == "tiny"
        assert config.max_clips == 5


class TestNLPScorer:
    """NLP Scoring tests."""

    def test_keyword_scoring(self):
        from ai_clipper.nlp_scorer import _keyword_score

        # High excitement keyword
        score_high, phrase = _keyword_score("Oh my god that was incredible!")
        assert score_high > 0.5

        # No keywords
        score_low, _ = _keyword_score("the quick brown fox")
        assert score_low == 0.0

    def test_heuristic_sentiment(self):
        from ai_clipper.nlp_scorer import _heuristic_sentiment

        # Excited text
        score_excited = _heuristic_sentiment("WOW!!! AMAZING PLAY!!!")
        assert score_excited > 0.3

        # Calm text
        score_calm = _heuristic_sentiment("walking down the street")
        assert score_calm < 0.2

    def test_extract_phrase(self):
        from ai_clipper.nlp_scorer import _extract_phrase

        text = "And then he got the most incredible headshot ever"
        phrase = _extract_phrase(text, "incredible")
        assert "incredible" in phrase


class TestScorer:
    """Signal Fusion & Peak Scoring tests."""

    def test_remove_overlaps(self):
        from ai_clipper.scorer import _remove_overlaps, HighlightCandidate

        highlights = [
            HighlightCandidate(peak_time=10, score=0.9, start_time=5, end_time=20),
            HighlightCandidate(peak_time=15, score=0.7, start_time=10, end_time=25),  # Overlaps
            HighlightCandidate(peak_time=50, score=0.8, start_time=45, end_time=60),  # No overlap
        ]
        filtered = _remove_overlaps(highlights)
        assert len(filtered) == 2
        assert filtered[0].peak_time == 10  # Highest score kept
        assert filtered[1].peak_time == 50

    def test_timeline_building(self):
        from ai_clipper.scorer import TimelinePoint

        point = TimelinePoint(
            time_sec=10.0,
            audio_score=0.8,
            text_score=0.6,
            visual_score=0.7,
        )
        # Weighted combination
        combined = 0.3 * 0.8 + 0.35 * 0.6 + 0.35 * 0.7
        assert abs(combined - 0.695) < 0.001


class TestClipGenerator:
    """Clip Generation tests."""

    def test_srt_time_format(self):
        from ai_clipper.clip_generator import _seconds_to_srt_time

        assert _seconds_to_srt_time(0) == "00:00:00,000"
        assert _seconds_to_srt_time(65.5) == "00:01:05,500"
        assert _seconds_to_srt_time(3661.123) == "01:01:01,123"

    def test_title_generation(self):
        from ai_clipper.clip_generator import _generate_title

        title = _generate_title("GTA6 Stream", "Epic car chase!", 1)
        assert "Epic car chase!" in title
        assert "GTA6" in title

    def test_hashtag_generation(self):
        from ai_clipper.clip_generator import _generate_hashtags

        tags = _generate_hashtags(
            "amazing car chase explosion",
            ["#Shorts", "#Gaming"]
        )
        assert "#Shorts" in tags
        assert "#Gaming" in tags
        assert len(tags) <= 8


class TestSceneDetector:
    """Scene Detection tests."""

    def test_scene_dataclass(self):
        from ai_clipper.scene_detector import Scene

        scene = Scene(index=0, start_time=0.0, end_time=5.0, start_frame=0, end_frame=150)
        assert scene.duration == 5.0
        assert scene.midpoint == 2.5

    def test_get_scene_at_time(self):
        from ai_clipper.scene_detector import Scene, get_scene_at_time

        scenes = [
            Scene(index=0, start_time=0, end_time=10, start_frame=0, end_frame=300),
            Scene(index=1, start_time=10, end_time=20, start_frame=300, end_frame=600),
        ]
        result = get_scene_at_time(scenes, 5.0)
        assert result is not None
        assert result.index == 0

        result = get_scene_at_time(scenes, 15.0)
        assert result is not None
        assert result.index == 1

        result = get_scene_at_time(scenes, 25.0)
        assert result is None


class TestAudioAnalyzer:
    """Audio Analyzer tests."""

    def test_transcript_segment(self):
        from ai_clipper.audio_analyzer import TranscriptSegment, get_transcript_at_time

        segments = [
            TranscriptSegment(start=0, end=5, text="Hello world"),
            TranscriptSegment(start=5, end=10, text="Amazing play"),
            TranscriptSegment(start=10, end=15, text="Quiet moment"),
        ]

        text = get_transcript_at_time(segments, 7.0, window_sec=3)
        assert "Amazing play" in text

    def test_energy_at_time(self):
        from ai_clipper.audio_analyzer import AudioFeatures, get_energy_at_time

        features = AudioFeatures(
            times=np.array([0, 1, 2, 3, 4, 5], dtype=float),
            energy=np.array([0.1, 0.2, 0.9, 0.3, 0.1, 0.1]),
            energy_normalized=np.array([0.0, 0.1, 1.0, 0.25, 0.0, 0.0]),
        )
        # At time 2.0 (peak)
        score = get_energy_at_time(features, 2.0)
        assert score > 0.9


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])


def test_local_recording_end_to_end(tmp_path,monkeypatch):
    """Real FFmpeg, scene detection, audio energy, fusion, selection and MP4 export.
    Only semantic model inference and speech recognition use controlled test doubles.
    """
    import subprocess
    from ai_clipper import audio_analyzer, vision_models
    from ai_clipper.config import ClipperConfig
    from ai_clipper.pipeline import run_pipeline
    from ai_clipper.scene_detector import detect_scenes
    from ai_clipper.downloader import get_video_info

    monkeypatch.setenv("GEMINI_REVIEW_ENABLED","false")
    monkeypatch.setenv("CLIPPER_AUDIO_BACKEND","pcm")
    monkeypatch.setattr(vision_models,"classifier",lambda: lambda frame:(.98,.95))
    monkeypatch.setattr(audio_analyzer,"transcribe_audio",lambda *a:[audio_analyzer.TranscriptSegment(3,10,"What an incredible car chase!")])
    source=tmp_path/"recording.mp4"
    # A fully black lead-in, then moving pixels and sound. The cut is an observable scene change.
    args=["ffmpeg","-v","error","-f","lavfi","-i","color=black:s=320x180:r=10:d=8","-f","lavfi","-i",
          "testsrc2=s=320x180:r=10:d=28","-f","lavfi","-i","sine=frequency=700:duration=36",
          "-filter_complex","[0:v][1:v]concat=n=2:v=1:a=0[v]","-map","[v]","-map","2:a",
          "-c:v","libx264","-threads","1","-c:a","aac",str(source)]
    subprocess.run(args,check=True)
    scenes=detect_scenes(source,threshold=12)
    assert any(abs(s.start_time-8)<1 for s in scenes)
    result=run_pipeline(str(source),tmp_path/"out",ClipperConfig(max_clips=1,clip_duration_target_sec=20,
        min_highlight_score=.28,output_width=720,output_height=1280,output_fps=8))
    assert not result.errors and len(result.clips)==1
    clip=result.clips[0]
    assert 3 <= clip.start_time < clip.end_time <= 36 and get_video_info(clip.filepath).height==1280
    assert clip.score > 0 and clip.evidence.startswith("Local CLIP")


def test_static_loading_screen_produces_no_clips(tmp_path,monkeypatch):
    import subprocess
    from ai_clipper.config import ClipperConfig
    from ai_clipper.pipeline import run_pipeline
    source=tmp_path/"black.mp4"
    subprocess.run(["ffmpeg","-v","error","-f","lavfi","-i","color=black:s=256x144:r=5:d=23",
                    "-c:v","libx264","-threads","1",str(source)],check=True)
    result=run_pipeline(str(source),tmp_path/"out",ClipperConfig(use_clip=False))
    assert result.errors==[] and result.clips==[] and result.metadata["scanned_ranges"]
