import json
import wave
from datetime import datetime,timezone

import pytest
from fastapi.testclient import TestClient
from ai_clipper import groq_speech, provider_quota as quota, web_ui


def test_shared_reserve_and_retry_after(tmp_path,monkeypatch):
    monkeypatch.setenv("STREAMGRABBER_STATE_DIR",str(tmp_path))
    clock=[100000.]
    monkeypatch.setattr(quota.time,"time",lambda:clock[0])
    monkeypatch.setattr(quota.time,"sleep",lambda n:clock.__setitem__(0,clock[0]+n))
    assert all(quota.reserve_audio(1) for _ in range(19))
    assert not quota.reserve_audio(1)
    notices=[]
    quota.wait_for_reset(lambda p,until:notices.append((p,until)))
    assert notices and quota.reserve_audio(1)
    quota.observe_groq({"x-ratelimit-limit-requests":"1000","x-ratelimit-remaining-requests":"10","x-ratelimit-reset-requests":"2m3s"},200)
    assert quota.pending()[1]==clock[0]+123


def test_groq_success_cached_before_pause(tmp_path,monkeypatch):
    monkeypatch.setenv("STREAMGRABBER_STATE_DIR",str(tmp_path))
    for i in range(1,5):
        monkeypatch.setenv(f"GROQ_API_KEY_{i}",f"dummy-{i}")
    monkeypatch.setenv("GROQ_CONFIRMED_FREE_PLAN","true")
    audio=tmp_path/"a.wav"
    with wave.open(str(audio),"wb") as f:
        f.setparams((1,2,16000,0,"NONE","not compressed"))
        f.writeframes(bytes(32000))
    class Response:
        status_code=200
        headers={"x-ratelimit-limit-requests":"100","x-ratelimit-remaining-requests":"1","x-ratelimit-reset-requests":"1s"}
        def json(self):
            return {"segments":[{"start":0,"end":1,"text":"Great chase!"},
                                {"start":0,"end":1,"text":"Uncertain words","avg_logprob":-2.}],"language":"en"}
    calls=[]
    def send(url,**kwargs):
        calls.append(url)
        assert kwargs['headers']['Authorization'].startswith('Bearer dummy-') and kwargs['files']['file'][1].read(4)==b'RIFF'
        return Response()
    monkeypatch.setattr(groq_speech.requests,"post",send)
    notices=[]
    for _ in range(2):
        rows=groq_speech.transcribe(audio,None,tmp_path/"cache",lambda *evt:notices.append(evt))
        assert len(rows)==1 and rows[0].text=="Great chase!"
    assert len(calls)==1 and notices


def test_transcript_srt_and_font_validation(tmp_path,monkeypatch):
    monkeypatch.setattr(web_ui,"STATE",tmp_path)
    client=TestClient(web_ui.app)
    folder=web_ui.job_path("a"*32)
    (folder/"subtitles").mkdir(parents=True)
    web_ui.update(folder,status="completed")
    (folder/"transcript.json").write_text('[{"start":22,"end":24,"text":"A chase"}]')
    (folder/"subtitles/clip_01.srt").write_text("caption")
    url="/api/studio/jobs/"+folder.name
    assert client.get(url+"/transcript").json()[0]["start"]==22
    assert client.get(url+"/media/clip_01.srt?download=1").text=="caption"
    assert client.post("/api/studio/jobs",json={"url":"https://twitch.tv/example","subtitle_font":"unknown"}).status_code==422
