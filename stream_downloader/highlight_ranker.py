"""Evidence-based highlight ranking. No timestamps inferred from video duration.

The upstream analyzer must supply observations from actually decoded media.
"""
from dataclasses import dataclass
from typing import Iterable

@dataclass(frozen=True)
class Observation:
    start: float
    end: float
    gameplay_probability: float
    audio_action: float
    visual_action: float
    speech_excitement: float
    loading_probability: float = 0.0
    menu_probability: float = 0.0
    evidence_source: str = ""

@dataclass(frozen=True)
class Highlight:
    start: float
    end: float
    score: float
    evidence_source: str

def rank_highlights(observations: Iterable[Observation], limit: int = 5,
                    min_gameplay: float = 0.75, min_score: float = 0.48,
                    max_overlap_ratio: float = 0.2,
                    weights=(0.30, 0.35, 0.35)) -> list[Highlight]:
    """Reject non-gameplay, low-evidence and overlapping moments.

    Input probabilities must be derived from inspected video/audio, never metadata.
    Empty evidence yields no clips rather than fabricated timestamps.
    """
    if limit <= 0:
        return []
    wa, wt, wv = weights
    candidates = []
    for o in observations:
        if not o.evidence_source or o.end <= o.start or o.start < 0:
            continue
        if not all(0 <= x <= 1 for x in (
            o.gameplay_probability, o.audio_action, o.visual_action,
            o.speech_excitement, o.loading_probability, o.menu_probability
        )):
            continue
        if (o.gameplay_probability < min_gameplay or
                o.loading_probability > 0.25 or o.menu_probability > 0.25):
            continue
        score = (wv * o.visual_action + wa * o.audio_action +
                 wt * o.speech_excitement)
        if score >= min_score:
            candidates.append(Highlight(o.start, o.end, round(score, 4), o.evidence_source))
    selected = []
    for c in sorted(candidates, key=lambda x: x.score, reverse=True):
        if any(max(0.0, min(c.end, x.end) - max(c.start, x.start)) /
               min(c.end - c.start, x.end - x.start) > max_overlap_ratio for x in selected):
            continue
        selected.append(c)
        if len(selected) >= max(0, limit):
            break
    return sorted(selected, key=lambda x: x.start)
