"""
Audio Analysis Module - Whisper transcription + audio energy/loudness analysis.

Yeh module do kaam karta hai:
1. Whisper se speech-to-text (with timestamps)
2. Librosa se audio energy/loudness peaks detect karta hai
"""

import subprocess
import json
import os
from functools import lru_cache
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


@lru_cache(maxsize=1)
def _speech_model(name):
    if os.getenv("CLIPPER_SPEECH_BACKEND") == "whisper":
        import whisper
        return "whisper", whisper.load_model(name)
    from faster_whisper import WhisperModel
    return "faster", WhisperModel(os.getenv("CLIPPER_WHISPER_DIR") or name,
                                  device="cpu", compute_type="int8", cpu_threads=2)


def transcribe_audio(audio_path, model_name="base", language=None):
    backend, model = _speech_model(model_name)
    if backend == "whisper":
        result = model.transcribe(str(audio_path), language=language, verbose=False)
        return [TranscriptSegment(seg["start"], seg["end"], seg["text"].strip(), result["language"])
                for seg in result["segments"] if seg.get("no_speech_prob", 0) < .6]
    import wave
    with wave.open(str(audio_path), "rb") as wav:
        pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype(np.float32) / 32768
    segments, info = model.transcribe(pcm, language=language, beam_size=1,
                                      vad_filter=True, condition_on_previous_text=False)
    return [TranscriptSegment(s.start, s.end, s.text.strip(), info.language) for s in segments
            if s.no_speech_prob < .6 and s.text.strip()]


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
        if os.getenv("CLIPPER_AUDIO_BACKEND") == "pcm":
            raise ImportError
        import librosa
        samples, sr = librosa.load(str(audio_path), sr=None)
        rms = librosa.feature.rms(y=samples, frame_length=frame_length, hop_length=hop_length)[0]
    except ImportError:
        import wave
        with wave.open(str(audio_path), "rb") as wav:
            sr = wav.getframerate()
            pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype(np.float32)/32768
        padded = np.pad(pcm, frame_length//2)
        frames = np.lib.stride_tricks.sliding_window_view(padded, frame_length)[::hop_length]
        rms = np.sqrt(np.einsum("ij,ij->i", frames, frames) / frame_length)
    times = np.arange(len(rms)) * hop_length/sr
    low, high = np.percentile(rms, [10, 95])
    norm = np.clip((rms-low)/max(.018, high-low), 0, 1)
    from scipy.signal import find_peaks
    indexes, _ = find_peaks(norm, height=np.percentile(norm, loudness_percentile), prominence=.1,
                             distance=max(1, int(3*sr/hop_length)))
    return AudioFeatures(times, rms, norm, times[indexes].tolist(), sr)



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
