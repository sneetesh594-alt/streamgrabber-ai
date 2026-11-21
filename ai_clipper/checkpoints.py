"""Atomic progress records for resumable file/VOD scans. No provider URLs are saved here."""
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from .audio_analyzer import TranscriptSegment
from .moments import Moment


def location(work, identity):
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, default=str).encode()).hexdigest()
    folder = work/".scan"/digest
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def save(path, selected, speech, covered, warnings):
    entries = []
    for m in selected:
        data = asdict(m)
        data.pop("proxy", None)
        entries.append(data)
    contents = dict(selected=entries, speech=[asdict(s) for s in speech], covered=covered, warnings=warnings)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(contents, ensure_ascii=False, allow_nan=False),encoding="utf-8")
    tmp.replace(path)


def load(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    moments = []
    for row in data["selected"]:
        row["speech"] = [TranscriptSegment(**s) for s in row["speech"]]
        row["fingerprint"] = tuple(row["fingerprint"])
        row["scene"] = tuple(row["scene"])
        moments.append(Moment(proxy=Path(), **row))
    return moments,[TranscriptSegment(**s) for s in data["speech"]],data["covered"],data["warnings"]
