"""
Signal Fusion & Peak Scoring Module - Sab signals combine karke best moments find karta hai.

Yeh module audio, text, aur visual scores ko ek unified timeline me merge karta hai,
phir peaks dhundta hai jo highlight candidates ban sakte hain.
"""

import numpy as np
from dataclasses import dataclass, field
from scipy.signal import find_peaks

from rich.console import Console

console = Console()


@dataclass
class TimelinePoint:
    """Timeline pe ek single point ka score."""
    time_sec: float
    audio_score: float = 0.0
    text_score: float = 0.0
    visual_score: float = 0.0
    combined_score: float = 0.0


@dataclass
class HighlightCandidate:
    """Ek potential highlight/clip candidate."""
    peak_time: float          # Peak moment ka time (seconds)
    score: float              # Combined score (0-1)
    start_time: float = 0.0   # Clip start time
    end_time: float = 0.0     # Clip end time
    hook_text: str = ""       # Hook text for the clip
    audio_score: float = 0.0
    text_score: float = 0.0
    visual_score: float = 0.0

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time


@dataclass
class ScoredTimeline:
    """Full scored timeline with highlight candidates."""
    points: list[TimelinePoint] = field(default_factory=list)
    highlights: list[HighlightCandidate] = field(default_factory=list)
    duration_sec: float = 0.0


def build_scored_timeline(
    duration_sec: float,
    audio_features,      # AudioFeatures from audio_analyzer
    text_scores: list,   # list[TextScore] from nlp_scorer
    visual_analysis,     # VisualAnalysis from visual_analyzer
    weight_audio: float = 0.30,
    weight_text: float = 0.35,
    weight_visual: float = 0.35,
    resolution_sec: float = 1.0,
) -> ScoredTimeline:
    """
    Sab signals ko ek unified timeline me combine karo.

    Har second ke liye audio, text, aur visual scores ko weighted combine
    karke ek final score generate karta hai.

    Args:
        duration_sec: Total video duration in seconds
        audio_features: AudioFeatures object
        text_scores: List of TextScore objects
        visual_analysis: VisualAnalysis object
        weight_audio: Weight for audio score
        weight_text: Weight for text score
        weight_visual: Weight for visual score
        resolution_sec: Timeline resolution (score every N seconds)

    Returns:
        ScoredTimeline with per-second scores
    """
    console.print(f"[bold blue]📊 Building scored timeline...[/]")
    console.print(
        f"[dim]Weights: audio={weight_audio:.0%}, text={weight_text:.0%}, "
        f"visual={weight_visual:.0%}[/dim]"
    )

    # Import helper functions
    from .audio_analyzer import get_energy_at_time
    from .nlp_scorer import get_text_score_at_time
    from .visual_analyzer import get_visual_score_at_time

    points = []
    time_steps = np.arange(0, duration_sec, resolution_sec)

    for t in time_steps:
        audio_s = get_energy_at_time(audio_features, t)
        text_s = get_text_score_at_time(text_scores, t)
        visual_s = get_visual_score_at_time(visual_analysis, t)

        combined = (
            weight_audio * audio_s +
            weight_text * text_s +
            weight_visual * visual_s
        )

        points.append(TimelinePoint(
            time_sec=t,
            audio_score=audio_s,
            text_score=text_s,
            visual_score=visual_s,
            combined_score=combined,
        ))

    console.print(f"[bold green]✓ Timeline built:[/] {len(points)} scored points")

    return ScoredTimeline(
        points=points,
        highlights=[],
        duration_sec=duration_sec,
    )


def find_highlights(
    timeline: ScoredTimeline,
    min_distance_sec: float = 30.0,
    peak_prominence: float = 0.15,
    max_clips: int = 10,
    clip_duration_min: float = 15.0,
    clip_duration_max: float = 60.0,
    clip_duration_target: float = 30.0,
) -> list[HighlightCandidate]:
    """
    Timeline me peaks dhundo jo highlight candidates ban sakte hain.

    Uses scipy.signal.find_peaks to detect score peaks, then ranks them.
    Overlapping clips ko merge/filter karta hai.

    Args:
        timeline: ScoredTimeline from build_scored_timeline
        min_distance_sec: Minimum distance between peaks
        peak_prominence: Minimum peak prominence
        max_clips: Maximum number of clips to find
        clip_duration_min: Min clip duration in seconds
        clip_duration_max: Max clip duration in seconds
        clip_duration_target: Target clip duration in seconds

    Returns:
        List of HighlightCandidate sorted by score (descending)
    """
    console.print(f"[bold blue]🔍 Finding highlight peaks...[/]")

    if not timeline.points:
        return []

    # Extract scores array
    scores = np.array([p.combined_score for p in timeline.points])
    times = np.array([p.time_sec for p in timeline.points])

    if len(scores) < 3:
        return []

    # Smooth scores with a moving average (reduce noise)
    kernel_size = min(5, len(scores))
    kernel = np.ones(kernel_size) / kernel_size
    smoothed = np.convolve(scores, kernel, mode="same")

    # Find peaks
    resolution = times[1] - times[0] if len(times) > 1 else 1.0
    min_distance_samples = max(1, int(min_distance_sec / resolution))

    peak_indices, properties = find_peaks(
        smoothed,
        distance=min_distance_samples,
        prominence=peak_prominence,
    )

    if len(peak_indices) == 0:
        # Fallback: take top N scoring points
        console.print("[yellow]⚠ No clear peaks found, taking top scoring moments[/]")
        top_indices = np.argsort(scores)[-max_clips:][::-1]
        peak_indices = top_indices

    # Create highlight candidates
    highlights = []
    for idx in peak_indices:
        peak_time = times[idx]
        point = timeline.points[idx]

        # Determine clip boundaries
        # Start slightly before peak, extend to target duration
        half_dur = clip_duration_target / 2
        start = max(0, peak_time - half_dur)
        end = min(timeline.duration_sec, peak_time + half_dur)

        # Adjust if clip is too short
        if end - start < clip_duration_min:
            end = min(timeline.duration_sec, start + clip_duration_min)
        if end - start < clip_duration_min:
            start = max(0, end - clip_duration_min)

        # Cap at max duration
        if end - start > clip_duration_max:
            center = (start + end) / 2
            start = center - clip_duration_max / 2
            end = center + clip_duration_max / 2

        highlights.append(HighlightCandidate(
            peak_time=peak_time,
            score=float(smoothed[idx]),
            start_time=float(start),
            end_time=float(end),
            audio_score=point.audio_score,
            text_score=point.text_score,
            visual_score=point.visual_score,
        ))

    # Sort by score (descending) and take top N
    highlights.sort(key=lambda h: h.score, reverse=True)

    # Remove overlapping clips (keep higher scoring one)
    filtered = _remove_overlaps(highlights)

    # Limit to max_clips
    final = filtered[:max_clips]

    # Sort by time for sequential output
    final.sort(key=lambda h: h.start_time)

    console.print(f"[bold green]✓ Found {len(final)} highlight candidates[/]")
    for i, h in enumerate(final):
        console.print(
            f"  [cyan]Clip {i+1}:[/] {h.start_time:.1f}s - {h.end_time:.1f}s "
            f"(score: {h.score:.2f}) "
            f"[A:{h.audio_score:.2f} T:{h.text_score:.2f} V:{h.visual_score:.2f}]"
        )

    timeline.highlights = final
    return final


def _remove_overlaps(highlights: list[HighlightCandidate]) -> list[HighlightCandidate]:
    """
    Overlapping clips me se sirf best score wala rakhna.
    Sorted by score (descending) expected.
    """
    if not highlights:
        return []

    kept = [highlights[0]]

    for candidate in highlights[1:]:
        overlap = False
        for existing in kept:
            # Check overlap
            if (candidate.start_time < existing.end_time and
                    candidate.end_time > existing.start_time):
                overlap = True
                break
        if not overlap:
            kept.append(candidate)

    return kept
