"""Timestamped transcription of actual candidate audio using a shared free-plan budget."""
import hashlib
import json
import os
import wave
from dataclasses import asdict
from pathlib import Path

import requests

from .audio_analyzer import TranscriptSegment
from .provider_quota import GROQ_KEYS, observe_groq, reserve_audio, wait_for_reset


def transcribe(audio, language, cache, report):
    keys=list(dict.fromkeys(os.environ[k] for k in GROQ_KEYS if os.getenv(k)))
    if not keys or os.getenv("GROQ_CONFIRMED_FREE_PLAN","").lower()!="true":
        return None
    digest=hashlib.sha256(b"speech-confidence-v2"+audio.read_bytes()+(language or "auto").encode()).hexdigest()
    cache.mkdir(parents=True,exist_ok=True)
    entry=cache/(digest+".json")
    if entry.is_file():
        return [TranscriptSegment(**s) for s in json.loads(entry.read_text())]
    # Assign different sections deterministically. A rate limit pauses every slot.
    key=keys[int(digest[:12],16)%len(keys)]
    with wave.open(str(audio),"rb") as inp:
        seconds=max(1,round(inp.getnframes()/inp.getframerate()+.5))
    data={"model":"whisper-large-v3-turbo","response_format":"verbose_json","timestamp_granularities[]":"segment"}
    if language:
        data["language"]=language
    while True:
        wait_for_reset(report)
        if not reserve_audio(seconds):
            continue
        try:
            with audio.open("rb") as src:
                response=requests.post("https://api.groq.com/openai/v1/audio/transcriptions",
                    headers={"Authorization":"Bearer "+key},data=data,files={"file":("audio.wav",src,"audio/wav")},
                    allow_redirects=False,timeout=(8,60))
            observe_groq(response.headers,response.status_code)
            if response.status_code==429:
                continue
            if response.status_code!=200:
                wait_for_reset(report)
                return None
            result=response.json()
            segments=[TranscriptSegment(float(s["start"]),float(s["end"]),s["text"].strip(),
                      result.get("language") or language or "und") for s in result["segments"]
                      if 0<=float(s["start"])<float(s["end"])<=seconds+1 and s["text"].strip()
                      and float(s.get("no_speech_prob",0)) < .6
                      and float(s.get("avg_logprob",0)) >= -1.
                      and float(s.get("compression_ratio",0)) <= 2.4]
        except (requests.RequestException,KeyError,ValueError,TypeError):
            wait_for_reset(report)
            return None
        tmp=entry.with_suffix(".tmp")
        tmp.write_text(json.dumps([asdict(s) for s in segments],ensure_ascii=False))
        tmp.replace(entry)
        wait_for_reset(report)
        return segments
