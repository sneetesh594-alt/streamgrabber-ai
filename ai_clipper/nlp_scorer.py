"""
NLP Scoring Module - Transcript text me interesting/exciting keywords aur sentiment detect karta hai.

Yeh module Whisper ke transcript ko analyze karke:
1. Exciting keywords/phrases dhundta hai
2. Sentiment/emotion analyze karta hai
3. Har segment ko ek text-score deta hai
"""

import re
from dataclasses import dataclass

import numpy as np
from rich.console import Console

console = Console()


# ===================================================================
# Gaming/Action keywords jo exciting moments indicate karte hain
# (English + Hinglish for GTA-style content)
# ===================================================================
EXCITING_KEYWORDS = {
    # High excitement (weight 1.0)
    "high": [
        "incredible", "unbelievable", "insane", "amazing", "oh my god",
        "omg", "holy", "clutch", "epic", "legendary", "destroyed",
        "killed it", "headshot", "perfect", "flawless", "world record",
        "first ever", "no way", "are you kidding", "what just happened",
        "explosion", "crash", "destroy", "win", "victory", "champion",
        # Hinglish
        "bahut badhiya", "kamaal", "pagal", "maza aa gaya", "fatafat",
        "jeet gaye", "maar diya", "tod diya",
    ],
    # Medium excitement (weight 0.6)
    "medium": [
        "nice", "great", "awesome", "good", "wow", "cool", "close",
        "almost", "so close", "barely", "just in time", "escape",
        "run", "chase", "fight", "attack", "defend", "dodge",
        "police", "cops", "wanted", "stars", "level up",
        # Hinglish
        "accha", "badhiya", "sahi", "chal", "bhag", "maar",
    ],
    # Low excitement (weight 0.3)
    "low": [
        "look", "see", "watch", "check", "here", "there", "okay",
        "alright", "let's go", "come on", "ready", "start",
        # Hinglish
        "dekho", "yahan", "chalo", "shuru",
    ],
}

EXCITEMENT_WEIGHTS = {"high": 1.0, "medium": 0.6, "low": 0.3}


@dataclass
class TextScore:
    """Text analysis ka result for a time segment."""
    start_time: float
    end_time: float
    text: str
    keyword_score: float = 0.0     # Keyword-based excitement score (0-1)
    sentiment_score: float = 0.0   # Sentiment/emotion score (0-1)
    combined_score: float = 0.0    # Overall text score (0-1)
    top_phrase: str = ""           # Most exciting phrase (for hook text)


def score_transcript_segments(
    segments: list,  # list[TranscriptSegment] from audio_analyzer
    use_transformer_sentiment: bool = False,
) -> list[TextScore]:
    """
    Transcript segments ko NLP se score karo.

    Args:
        segments: Whisper transcript segments
        use_transformer_sentiment: HuggingFace sentiment model use kare ya nahi

    Returns:
        List of TextScore for each segment
    """
    console.print(f"[bold blue]📝 Scoring transcript ({len(segments)} segments)...[/]")

    # Optional: Load sentiment model
    sentiment_pipeline = None
    if use_transformer_sentiment:
        sentiment_pipeline = _load_sentiment_model()

    text_scores = []
    for seg in segments:
        score = TextScore(
            start_time=seg.start,
            end_time=seg.end,
            text=seg.text,
        )

        # Keyword-based scoring
        score.keyword_score, score.top_phrase = _keyword_score(seg.text)

        # Sentiment scoring
        if sentiment_pipeline:
            score.sentiment_score = _sentiment_score(seg.text, sentiment_pipeline)
        else:
            # Simple heuristic: exclamation marks, caps, question marks
            score.sentiment_score = _heuristic_sentiment(seg.text)

        # Combined score (keyword-heavy since it's more reliable for gaming)
        score.combined_score = (
            0.7 * score.keyword_score +
            0.3 * score.sentiment_score
        )

        text_scores.append(score)

    # Normalize all scores to 0-1
    max_combined = max((s.combined_score for s in text_scores), default=1.0)
    if max_combined > 0:
        for s in text_scores:
            s.combined_score = s.combined_score / max_combined

    n_exciting = sum(1 for s in text_scores if s.combined_score > 0.5)
    console.print(
        f"[bold green]✓ Text scoring complete:[/] "
        f"{n_exciting} exciting segments found"
    )

    return text_scores


def _keyword_score(text: str) -> tuple[float, str]:
    """
    Text me exciting keywords dhundo aur score do.
    Returns (score, best_phrase).
    """
    text_lower = text.lower()
    total_weight = 0.0
    best_phrase = ""
    best_weight = 0.0

    for level, keywords in EXCITING_KEYWORDS.items():
        weight = EXCITEMENT_WEIGHTS[level]
        for keyword in keywords:
            if keyword in text_lower:
                total_weight += weight
                if weight > best_weight:
                    best_weight = weight
                    # Extract the sentence containing the keyword
                    best_phrase = _extract_phrase(text, keyword)

    # Cap at 1.0
    score = min(total_weight, 1.0)
    return score, best_phrase


def _extract_phrase(text: str, keyword: str) -> str:
    """Keyword ke around ka phrase extract karo (for hook text)."""
    text_lower = text.lower()
    idx = text_lower.find(keyword)
    if idx == -1:
        return text[:50] if len(text) > 50 else text

    # Take surrounding context (up to 60 chars)
    start = max(0, idx - 20)
    end = min(len(text), idx + len(keyword) + 30)

    # Snap to word boundaries
    while start > 0 and text[start] != " ":
        start -= 1
    while end < len(text) and text[end] != " ":
        end += 1

    phrase = text[start:end].strip()
    return phrase if phrase else text[:50]


def _heuristic_sentiment(text: str) -> float:
    """
    Simple rule-based sentiment scoring.
    Exclamation marks, ALL CAPS, repeated letters = excitement.
    """
    score = 0.0

    # Exclamation marks (each ! adds 0.15)
    excl_count = text.count("!")
    score += min(excl_count * 0.15, 0.5)

    # Question marks (adds some interest)
    if "?" in text:
        score += 0.1

    # ALL CAPS words (excitement/shouting)
    words = text.split()
    caps_ratio = sum(1 for w in words if w.isupper() and len(w) > 2) / max(len(words), 1)
    score += caps_ratio * 0.4

    # Repeated letters (like "nooooo", "yesssss")
    if re.search(r"(.)\1{2,}", text):
        score += 0.2

    # Text length bonus (longer = more content)
    if len(text) > 50:
        score += 0.1

    return min(score, 1.0)


def _load_sentiment_model():
    """HuggingFace sentiment analysis pipeline load karo."""
    try:
        from transformers import pipeline
        console.print("[dim]Loading sentiment model...[/dim]")
        sentiment = pipeline(
            "sentiment-analysis",
            model="distilbert-base-uncased-finetuned-sst-2-english",
            truncation=True,
            max_length=512,
        )
        console.print("[dim]Sentiment model loaded[/dim]")
        return sentiment
    except ImportError:
        console.print("[yellow]⚠ transformers not installed. Using heuristic sentiment.[/]")
        return None


def _sentiment_score(text: str, pipeline_fn) -> float:
    """HuggingFace sentiment pipeline se score nikalo."""
    try:
        if not text.strip():
            return 0.0
        result = pipeline_fn(text[:512])[0]
        # POSITIVE sentiment = exciting, NEGATIVE can also be exciting (fear, anger)
        label = result["label"]
        confidence = result["score"]
        if label == "POSITIVE":
            return confidence * 0.8
        else:
            # Negative emotions can also indicate exciting moments
            return confidence * 0.5
    except Exception:
        return _heuristic_sentiment(text)


def get_text_score_at_time(
    text_scores: list[TextScore], time_sec: float
) -> float:
    """Given time pe text score return karo."""
    for ts in text_scores:
        if ts.start_time <= time_sec <= ts.end_time:
            return ts.combined_score
    return 0.0


def get_hook_text_at_time(
    text_scores: list[TextScore], time_sec: float, window_sec: float = 10.0
) -> str:
    """Given time ke near sabse exciting phrase return karo (hook ke liye)."""
    best_phrase = ""
    best_score = 0.0
    for ts in text_scores:
        if abs(ts.start_time - time_sec) <= window_sec:
            if ts.combined_score > best_score and ts.top_phrase:
                best_score = ts.combined_score
                best_phrase = ts.top_phrase
    return best_phrase if best_phrase else "🔥 Highlight Moment"
