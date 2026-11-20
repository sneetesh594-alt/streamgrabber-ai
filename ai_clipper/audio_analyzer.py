"""
Audio Analysis Module - Whisper transcription + audio energy/loudness analysis.

Yeh module do kaam karta hai:
1. Whisper se speech-to-text (with timestamps)
2. Librosa se audio energy/loudness peaks detect karta hai
"""

import subprocess
import json
from pathlib import Path
from dataclasses import dataclass, field

import numpy as np
from rich.console import Console

console = Console()


@dataclass
class TranscriptSegment:
    """Ek transcribed text segment with timestamps."""
    start: float       # seconds
    end: float         # seconds
    text: str
    language: str = "en"
    confidence: float = 1.0


@dataclass
class AudioFeatures:
    """Audio analysis ka result."""
    times: np.ndarray           # Time points in seconds
    energy: np.ndarray          # RMS energy at each time point
    energy_normalized: np.ndarray  # 0-1 normalized energy
    peaks: list[float] = field(default_factory=list)  # Peak times in seconds
    sample_rate: int = 22050


def extract_audio(video_path: Path, output_path: Path | None = None) -> Path:
    """
    Video se audio extract karo (WAV format me).

    Args:
        video_path: Input video file
        output_path: Output audio path (default: same dir with .wav extension)

    Returns:
        Path to extracted audio file
    """
    if output_path is None:
        output_path = video_path.with_suffix(".wav")

    if output_path.exists():
        console.print(f"[dim]Audio already extracted: {output_path.name}[/dim]")
        return output_path

    console.print(f"[bold blue]🔊 Extracting audio...[/]")

    cmd = [
        "ffmpeg", "-i", str(video_path),
        "-vn",  # No video
        "-acodec", "pcm_s16le",  # WAV format
        "-ar", "16000",  # 16kHz for Whisper
        "-ac", "1",  # Mono
        "-y",  # Overwrite
        str(output_path)
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg audio extraction failed:\n{result.stderr}")

    console.print(f"[bold green]✓ Audio extracted:[/] {output_path.name}")
    return output_path


def transcribe_audio(
    audio_path: Path,
    model_name: str = "base",
    language: str | None = None,
) -> list[TranscriptSegment]:
    """
    Whisper se audio transcribe karo with timestamps.

    Args:
        audio_path: Path to audio file (WAV recommended)
        model_name: Whisper model (tiny/base/small/medium/large)
        language: Language code (None = auto-detect)

    Returns:
        List of TranscriptSegment with start/end times and text
    """
    console.print(f"[bold blue]🎙 Transcribing with Whisper ({model_name})...[/]")

    try:
        import whisper

        model = whisper.load_model(model_name)

        # Transcribe options
        options = {"verbose": False}
        if language:
            options["language"] = language

        result = model.transcribe(str(audio_path), **options)

        segments = []
        detected_lang = result.get("language", "en")
        for seg in result.get("segments", []):
            segments.append(TranscriptSegment(
                start=seg["start"],
                end=seg["end"],
                text=seg["text"].strip(),
                language=detected_lang,
                confidence=seg.get("avg_logprob", 0),
            ))

        console.print(
            f"[bold green]✓ Transcribed {len(segments)} segments[/] "
            f"(Language: {detected_lang})"
        )
        return segments

    except ImportError:
        console.print("[yellow]⚠ Whisper not installed. Using empty transcript.[/]")
        return []


def analyze_audio_energy(
    audio_path: Path,
    hop_length: int = 512,
    frame_length: int = 2048,
    loudness_percentile: float = 75.0,
) -> AudioFeatures:
    """
    Audio ki energy/loudness analyze karo.

    RMS energy compute karke peaks dhundta hai - jahan audio loud hai
    (explosions, cheers, excited commentary), woh peaks hain.

    Args:
        audio_path: Path to audio file
        hop_length: Hop length for STFT
        frame_length: Frame length for STFT
        loudness_percentile: Percentile above which = "loud"

    Returns:
        AudioFeatures with energy timeline and peak timestamps
    """
    console.print(f"[bold blue]📊 Analyzing audio energy...[/]")

    try:
        import librosa

        # Load audio
        y, sr = librosa.load(str(audio_path), sr=22050)

        # Compute RMS energy
        rms = librosa.feature.rms(y=y, frame_length=frame_length, hop_length=hop_length)[0]

        # Time points for each RMS value
        times = librosa.frames_to_time(
            np.arange(len(rms)),
            sr=sr,
            hop_length=hop_length
        )

        # Normalize to 0-1
        rms_min = rms.min()
        rms_max = rms.max()
        if rms_max - rms_min > 0:
            rms_normalized = (rms - rms_min) / (rms_max - rms_min)
        else:
            rms_normalized = np.zeros_like(rms)

        # Find peaks above percentile threshold
        threshold = np.percentile(rms_normalized, loudness_percentile)
        from scipy.signal import find_peaks
        peak_indices, _ = find_peaks(
            rms_normalized,
            height=threshold,
            distance=int(30 * sr / hop_length),  # Min 30 sec between peaks
            prominence=0.1,
        )
        peak_times = times[peak_indices].tolist()

        features = AudioFeatures(
            times=times,
            energy=rms,
            energy_normalized=rms_normalized,
            peaks=peak_times,
            sample_rate=sr,
        )

        console.print(
            f"[bold green]✓ Audio analysis complete:[/] "
            f"{len(peak_times)} loud peaks found"
        )
        return features

    except ImportError:
        console.print("[yellow]⚠ librosa not installed. Skipping audio analysis.[/]")
        return AudioFeatures(
            times=np.array([0.0]),
            energy=np.array([0.0]),
            energy_normalized=np.array([0.0]),
            peaks=[],
        )


def get_transcript_at_time(
    segments: list[TranscriptSegment],
    time_sec: float,
    window_sec: float = 5.0,
) -> str:
    """Given time ke around ka transcript text return karo."""
    texts = []
    for seg in segments:
        if seg.start <= time_sec + window_sec and seg.end >= time_sec - window_sec:
            texts.append(seg.text)
    return " ".join(texts)


def get_energy_at_time(features: AudioFeatures, time_sec: float) -> float:
    """Given time pe audio energy score (0-1) return karo."""
    if len(features.times) == 0:
        return 0.0
    idx = np.searchsorted(features.times, time_sec)
    idx = min(idx, len(features.energy_normalized) - 1)
    return float(features.energy_normalized[idx])
