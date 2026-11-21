"""Build reviewable windows from measured visual, audio and transcript evidence."""
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .nlp_scorer import score_transcript_segments
from .scene_detector import get_scene_at_time
from stream_downloader.highlight_ranker import Observation, rank_highlights


@dataclass
class Moment:
    start: float
    end: float
    peak: float
    scan_start: float
    proxy: Path
    audio: float
    text: float
    visual: float
    gameplay: float
    action: float
    fingerprint: tuple
    scene: tuple
    speech: list
    hook: str
    score: float
    evidence: str = ""


def candidates(proxy, offset, duration, visual, energy, speech, scenes, config):
    length = min(config.clip_duration_target_sec, duration, 45)
    if length < 20:
        return []
    texts = score_transcript_segments(speech)
    frames = visual.frame_scores
    # Evaluate windows centered on decoded frames, including source edges.
    step = max(1, round(3 * config.clip_sample_fps))
    rows = []
    starts = set()
    for peak in frames[::step]:
        start = round(max(0, min(duration-length, peak.time_sec - length/2)), 2)
        if start in starts:
            continue
        starts.add(start)
        end = start + length
        window = [f for f in frames if start <= f.time_sec < end]
        if not window:
            continue
        if np.mean([f.menu_probability >= .6 for f in window]) > .15:
            continue
        motion = np.array([f.motion_score for f in window])
        if np.mean([f.black for f in window]) > .18 or (motion > .13).mean() < .48:
            continue
        segments = [s for s in speech if s.end > start and s.start < end]
        negative = ("loading screen", "pause menu", "away from keyboard", "starting soon", "be right back")
        if any(term in seg.text.lower() for seg in segments for term in negative):
            continue
        selected_text = [t for t in texts if t.end_time > start and t.start_time < end]
        strongest = max(selected_text, key=lambda t: t.combined_score, default=None)
        text_score = strongest.combined_score if strongest else 0
        # Traffic moving against a fixed scenic backdrop is common in AFK streams.
        broad_motion = np.mean([f.field_motion > .40 for f in window])
        if broad_motion < .28 and not (strongest and strongest.keyword_score >= .7):
            continue
        hook = (strongest.top_phrase or strongest.text) if strongest else ""
        sampled = [f for f in window if f.gameplay is not None]
        game = float(np.median([f.gameplay for f in sampled])) if sampled else 0.
        action = float(np.mean([f.clip_score for f in sampled])) if sampled else 0.
        audio = 0.
        if energy is not None:
            mask = (energy.times >= start) & (energy.times < end)
            if mask.any() and np.percentile(energy.energy[mask], 85) > .012:
                audio = float(np.percentile(energy.energy_normalized[mask], 85))
        vis = min(1., .64 * float(np.percentile(motion, 70)) + .36 * action)
        peak_frame = max(window, key=lambda f: f.combined_score)
        scene = get_scene_at_time(scenes, peak_frame.time_sec)
        scene_id = (offset, scene.index if scene else -1)
        sig = tuple(window[round((len(window)-1)*fraction)].fingerprint for fraction in (.2, .5, .8))
        score = config.weight_audio*audio + config.weight_visual*vis + config.weight_text*text_score
        rows.append(Moment(offset+start, offset+end, offset+peak_frame.time_sec, offset, proxy, audio,
                           text_score, vis, game, action, sig, scene_id, segments, hook, score))
    return sorted(rows, key=lambda m: m.score, reverse=True)


def duplicate(moment, selected):
    for old in selected:
        overlap = max(0, min(old.end, moment.end) - max(old.start, moment.start))
        if old.scene == moment.scene or overlap/min(old.end-old.start, moment.end-moment.start) > .18:
            return True
        if all((a ^ b).bit_count() <= 7 for a, b in zip(old.fingerprint, moment.fingerprint)):
            return True
    return False


def verify(moment, cloud, config, evidence_source="Gemini · decoded video and audio"):
    # Cloud verdicts and local CLIP probabilities refer to the same measured window.
    if cloud is not None:
        if cloud <= 0:
            return False
        game = cloud
        moment.evidence = evidence_source
    else:
        if moment.gameplay < .58 or moment.action < .43:
            return False
        game = moment.gameplay
        moment.evidence = "Local CLIP · decoded frames"
    observation = Observation(moment.start, moment.end, game, moment.audio, moment.visual,
                              moment.text, evidence_source=moment.evidence)
    verified = rank_highlights([observation], limit=1, min_gameplay=.58,
                               min_score=config.min_highlight_score,
                               weights=(config.weight_audio, config.weight_text, config.weight_visual))
    if verified:
        moment.score = verified[0].score
    return bool(verified)
