import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError

import pytest
from fastapi.testclient import TestClient

from ai_clipper import gemini_review as gemini, sources, web_ui
from ai_clipper.audio_analyzer import TranscriptSegment
from ai_clipper.clip_generator import _generate_single_clip, _generate_srt


def test_remote_scan_and_exact_sections(tmp_path, monkeypatch):
    info = {"duration": 36000, "heatmap":[{"start_time":1234,"end_time":1240,"value":.98}]}
    rows = sources.scan_ranges(info)
    assert 0 < len(rows) <= 14 and all(0 <= a < b <= 36000 and b-a <= 64 for a,b in rows)
    assert any(a <= 1234 <= b for a,b in rows)
    calls = []
    def extract(args, timeout):
        calls.append(args)
        if len(calls) == 1:
            raise ValueError("The video host refused access.")
        (tmp_path/"section.mp4").touch()
    monkeypatch.setattr(sources,"_yt",extract)
    monkeypatch.setattr(sources,"get_video_info",lambda p:type("Video",(),{"duration_sec":30})())
    sources.fetch_section("https://youtu.be/laJ5g7gMRjk",123,153,tmp_path/"section.mp4",360)
    assert len(calls) == 2
    assert all(c[c.index("--download-sections")+1] == "*123.000-153.000" for c in calls)


@pytest.mark.parametrize("src",["https://notyoutube.com/path","file:///tmp/video","https://youtube.com@localhost/","http://localhost/test.mp4"])
def test_supported_platforms_only(src):
    with pytest.raises(ValueError):
        sources.stream_url(src)


def test_facebook_vid_preserved():
    assert "v=12345" in sources.stream_url("https://www.facebook.com/watch/?v=12345")


@pytest.fixture
def free_review(tmp_path, monkeypatch):
    monkeypatch.setenv("STREAMGRABBER_STATE_DIR",str(tmp_path))
    monkeypatch.setenv("GEMINI_REVIEW_ENABLED","true")
    for i,k in enumerate(gemini.SLOTS):
        monkeypatch.setenv(k,f"test-slot-{i}")
    monkeypatch.setattr(gemini,"_unbilled",lambda key: True)
    f=tmp_path/"clip.mp4"
    f.write_bytes(b"test video bytes")
    return f


def test_two_verified_google_reviewers_receive_video_and_transcript(free_review, monkeypatch):
    invoked=[]
    def request(url, headers, payload=None):
        assert "test-slot" not in url
        if payload is None:
            return {"name":"models/"+gemini.MODEL,"supportedGenerationMethods":["generateContent"]}
        parts=payload["contents"][0]["parts"]
        assert parts[-1]["inline_data"]["mime_type"]=="video/mp4" and "chase" in parts[1]["text"]
        invoked.append(headers["x-goog-api-key"])
        verdict={"confidence":.87,"category":"action" if len(invoked)==1 else "menu"}
        return {"usageMetadata":{"totalTokenCount":21},"candidates":[{"content":{"parts":[{"text":json.dumps(verdict)}]}}]}
    monkeypatch.setattr(gemini,"_request",request)
    assert gemini.review(free_review,"chase") == 0 and len(set(invoked)) == 2
    assert gemini.usage()["tokens"]==42


def test_quota_stops_both_keys_and_concurrent_reservations(free_review,monkeypatch):
    def quota(url,headers,payload=None):
        raise HTTPError(url,429,"quota",{},None)
    monkeypatch.setattr(gemini,"_request",quota)
    assert gemini.review(free_review,"") is None and gemini.usage()["quota_stopped"]
    assert not gemini._reserve(gemini._day())
    monkeypatch.setenv("GEMINI_DAILY_REQUEST_LIMIT","2")
    with ThreadPoolExecutor(max_workers=8) as executor:
        assert sum(executor.map(gemini._reserve, ["independent-test-day"]*10)) == 2


def test_paid_or_unknown_billing_cannot_generate(free_review,monkeypatch):
    monkeypatch.setattr(gemini,"_unbilled",lambda key:False)
    monkeypatch.setattr(gemini,"_request",lambda *a:pytest.fail("Unexpected model request"))
    assert gemini.review(free_review,"") is None and gemini.usage()["requests"]==0


def test_versioned_api_and_scope(tmp_path,monkeypatch):
    monkeypatch.setattr(web_ui,"STATE",tmp_path)
    client=TestClient(web_ui.app)
    assert client.get("/api/studio/health").json()["evidence_required"]
    assert client.post("/api/studio/jobs",json={"url":"/private/file"}).status_code == 422
    assert client.post("/api/studio/jobs",json={"url":"https://twitch.tv/test","num_clips":11}).status_code == 422
    assert client.get("/api/studio/jobs/"+("f"*32)+"/media/clip_01.mp4").status_code==404
    folder=web_ui.job_path("a"*32);(folder/"clips").mkdir(parents=True)
    (folder/"clips"/"clip_01.mp4").write_bytes(b"clip")
    web_ui.update(folder,clips=[{"id":1,"file":"clip_01.mp4"}],status="completed")
    shared=client.post("/api/studio/jobs/"+folder.name+"/share/1").json()
    assert client.get(shared["url"]).content==b"clip"
    assert client.get("/api/studio/jobs/"+folder.name+"/bundle").content.startswith(b"PK")


@pytest.mark.parametrize("size,overlays",[(720,False),(1080,True)])
def test_render_caption_pixels_and_portrait(tmp_path,size,overlays):
    source=tmp_path/"source.mp4"
    subprocess.run(["ffmpeg","-v","error","-f","lavfi","-i","color=c=0x345678:s=320x180:r=5:d=2","-c:v","libx264","-threads","1",str(source)],check=True)
    subs=tmp_path/"subtitle.srt"
    _generate_srt([TranscriptSegment(.1,1.8,"Real caption")],0,2,subs)
    output=tmp_path/"clip.mp4"
    _generate_single_clip(source,output,0,2,size,size*16//9,5,None,subs,"Real words",42,"white",52,"white",overlays,"@creator")
    info=json.loads(subprocess.check_output(["ffprobe","-v","error","-show_streams","-of","json",str(output)]))
    vid=info["streams"][0]
    assert (vid["codec_name"],vid["width"],vid["height"])==("h264",size,size*16//9)
    import cv2
    cap=cv2.VideoCapture(str(output));cap.set(cv2.CAP_PROP_POS_MSEC,800);ok,frame=cap.read();cap.release()
    assert ok and (frame[int(vid["height"]*.70):].min(axis=2)>190).sum()>15
    upper=frame[:int(vid["height"]*.13)]
    assert bool((upper.min(axis=2)>200).sum()>12) is overlays
