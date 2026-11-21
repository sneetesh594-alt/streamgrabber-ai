import json
import subprocess

from ai_clipper import groq_review


def test_menu_veto_uses_three_actual_frames_and_is_cached(tmp_path, monkeypatch):
    monkeypatch.setenv("STREAMGRABBER_STATE_DIR",str(tmp_path/"state"))
    monkeypatch.setenv("GROQ_API_KEY_1","test-key")
    monkeypatch.setenv("GROQ_CONFIRMED_FREE_PLAN","true")
    monkeypatch.setattr(groq_review,"_model",lambda key:"available-vision-model")
    video=tmp_path/"video.mp4"
    subprocess.run(["ffmpeg","-v","error","-f","lavfi","-i","testsrc2=s=160x90:r=2:d=24",
                    "-c:v","libx264","-threads","1",str(video)],check=True)
    calls=[]
    class Response:
        status_code=200
        headers={}
        def json(self):
            return {"choices":[{"message":{"content":json.dumps({"category":"menu","confidence":.95})}}]}
    def request(url,**kwargs):
        parts=kwargs["json"]["messages"][0]["content"]
        assert len(parts)==4
        assert all(p["image_url"]["url"].startswith("data:image/jpeg;base64,") for p in parts[1:])
        calls.append(1)
        return Response()
    monkeypatch.setattr(groq_review.requests,"post",request)
    for _ in range(2):
        assert groq_review.review(video,0,24,"actual transcript",lambda *a:None,tmp_path/"cache")==0
    assert len(calls)==1
