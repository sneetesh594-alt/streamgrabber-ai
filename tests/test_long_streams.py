"""Coverage, seeks, retained live playback and interrupted long recordings."""
import json
import subprocess
import threading
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import m3u8
import pytest
from fastapi.testclient import TestClient

from ai_clipper import live_dvr, sources, web_ui
from ai_clipper.config import ClipperConfig
from ai_clipper.downloader import get_video_info
from ai_clipper.pipeline import run_pipeline


@pytest.mark.parametrize("duration", [72000, 81960])
def test_full_timeline_has_no_gaps_or_unanalyzed_tail(duration):
    scans = sources.inspection_ranges({"duration": duration}, "full", 0, None, 35, 14)
    assert scans[0][0] == 0 and scans[-1][1] == duration
    assert all(20 <= b-a <= 240 for a, b in scans)
    assert all(b-c == 35 for (_, b), (c, _) in zip(scans, scans[1:]))
    assert all(any(a <= t <= b for a,b in scans) for t in range(0,duration+1,300))


def test_quick_and_custom_ranges_extend_through_hour_twenty():
    info = {"duration": 72000, "heatmap": [{"start_time": 69990, "end_time": 70000, "value": .99}]}
    all_rows = sources.inspection_ranges(info, "quick", 0, None, 30, 14)
    assert len(all_rows) < 60
    assert all(any(a < (h+1)*3600 and b > h*3600 for a,b in all_rows) for h in range(20))
    assert any(a <= 69995 <= b for a,b in all_rows)
    chosen = sources.inspection_ranges(info, "full", 19*3600, 72000, 30, 14)
    assert chosen[0][0] == 19*3600 and chosen[-1][1] == 72000
    with pytest.raises(ValueError):
        sources.inspection_ranges(info, "full", 0, None, 240, 14)
    with pytest.raises(ValueError):
        sources.inspection_ranges(info, "full", 71000, 75000, 30, 14)


def track(count=21*60, start_clock="2026-01-02T12:00:00Z", encrypted=False):
    rows = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-TARGETDURATION:60", "#EXT-X-MEDIA-SEQUENCE:300"]
    if start_clock:
        rows.append("#EXT-X-PROGRAM-DATE-TIME:" + start_clock)
    if encrypted:
        rows.append('#EXT-X-KEY:METHOD=AES-128,URI="key"')
    for i in range(count):
        rows.extend(["#EXTINF:60,", f"video{i}.ts"])
    url = "https://cdn.example/game/index.m3u8"
    return live_dvr.Track(m3u8.loads("\n".join(rows), uri=url), url)


def test_retained_20h_uses_playlist_timing_and_correct_segments(tmp_path):
    video = track()
    release = datetime(2026,1,2,11,tzinfo=timezone.utc).timestamp()
    snapshot = live_dvr.LiveDVR(video,release=release)
    assert (snapshot.duration,snapshot.first,snapshot.offset,snapshot.origin)==(72000,3600,7200,"stream start")
    manifest = tmp_path/"cut.m3u8"
    assert video.excerpt(snapshot.first+19*3600+2,snapshot.first+19*3600+31,manifest) == 2
    content = manifest.read_text()
    assert "video1200.ts" in content and "video1199.ts" not in content and "video1201.ts" not in content
    assert live_dvr.LiveDVR(track(50,None)).origin == "retained DVR window"
    with pytest.raises(ValueError, match="unencrypted"):
        track(5,encrypted=True)


def test_live_audio_sync_is_measured_from_the_two_clocks():
    video=track(10)
    sound=track(10, "2026-01-02T12:00:10Z")
    dvr=live_dvr.LiveDVR(video,sound)
    assert (dvr.first,dvr.duration,dvr.audio_delta)==(10,590,-10)
    with pytest.raises(ValueError, match="clocks"):
        live_dvr.LiveDVR(video,track(10,None))


def test_live_dvr_real_http_segments_and_vertical_export(tmp_path,monkeypatch):
    from ai_clipper import audio_analyzer, vision_models
    subprocess.run(["ffmpeg","-v","error","-f","lavfi","-i","testsrc2=s=320x180:r=10",
        "-f","lavfi","-i","sine=frequency=800","-t","34","-c:v","libx264","-threads","1",
        "-g","20","-sc_threshold","0","-c:a","aac","-f","hls","-hls_time","2","-hls_list_size","0",
        "-hls_segment_filename",str(tmp_path/"chunk%03d.ts"),str(tmp_path/"events.m3u8")],check=True)
    class Silent(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    server=ThreadingHTTPServer(("127.0.0.1",0),partial(Silent,directory=str(tmp_path)))
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    url=f"http://127.0.0.1:{server.server_port}/events.m3u8"
    info={"is_live":True,"title":"Fixture broadcast","formats":[{"protocol":"m3u8_native","url":url,
            "height":180,"vcodec":"h264","acodec":"aac"}]}
    try:
        dvr=live_dvr.open_dvr(info,360)
        section=tmp_path/"only-requested.mp4"
        dvr.fetch(3,25,section,180)
        assert get_video_info(section).duration_sec == pytest.approx(22,abs=.2)
        monkeypatch.setattr(sources,"metadata",lambda url:info)
        monkeypatch.setattr(vision_models,"classifier",lambda:lambda rgb:(.96,.96))
        monkeypatch.setattr(audio_analyzer,"transcribe_audio",lambda *args:[audio_analyzer.TranscriptSegment(1,7,"What an incredible car chase!")])
        monkeypatch.setenv("CLIPPER_AUDIO_BACKEND","pcm")
        monkeypatch.setenv("GEMINI_REVIEW_ENABLED","false")
        out=run_pipeline("https://twitch.tv/example",tmp_path/"result",ClipperConfig(max_clips=1,
            clip_duration_target_sec=20,min_highlight_score=.28,output_width=720,output_height=1280,output_fps=5))
        assert out.errors==[] and len(out.clips)==1
        assert out.metadata["source"]=="live DVR" and out.metadata["timeline_origin"]=="retained DVR window"
        assert out.metadata["available_range"]==[0,34]
        assert get_video_info(out.clips[0].filepath).width==720
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


def test_saved_section_resumes_after_restart(tmp_path,monkeypatch):
    src=tmp_path/"black.mp4"
    subprocess.run(["ffmpeg","-v","error","-f","lavfi","-i","color=s=160x90:r=4:d=24",
                    "-c:v","libx264","-threads","1",str(src)],check=True)
    cfg=ClipperConfig(use_clip=False)
    out=tmp_path/"out"
    assert not run_pipeline(src,out,cfg).errors
    checkpoints=list((out/".scan").glob("*/*.json"))
    assert len(checkpoints)==1 and json.loads(checkpoints[0].read_text())["covered"]==[0,24]
    monkeypatch.setattr(sources,"make_proxy",lambda *a:pytest.fail("A completed section was decoded again"))
    messages=[]
    result=run_pipeline(src,out,cfg,lambda n,msg:messages.append(msg))
    assert not result.errors and "Resumed section 1 of 1" in messages


def test_resume_api_cannot_start_the_same_job_twice(tmp_path,monkeypatch):
    monkeypatch.setattr(web_ui,"STATE",tmp_path)
    folder=web_ui.job_path("a"*32)
    folder.mkdir(parents=True)
    (folder/"request.json").write_text(json.dumps({"options":{"url":"https://twitch.tv/test"},"source_name":"","upload":None}))
    web_ui.update(folder,status="running",session="previous-server",resumable=True)
    called=[]
    def started(*args):
        called.append(args)
        web_ui.QUEUE.release()
    monkeypatch.setattr(web_ui,"process",started)
    client=TestClient(web_ui.app)
    endpoint=f"/api/studio/jobs/{folder.name}/resume"
    assert client.post(endpoint).status_code==200
    assert client.post(endpoint).status_code==409 and len(called)==1
    assert client.post("/api/studio/jobs",json={"url":"https://twitch.tv/test","range_start":72000,"range_end":72010}).status_code==422
