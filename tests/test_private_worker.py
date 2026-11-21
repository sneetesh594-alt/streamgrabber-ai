import hashlib
from fastapi.testclient import TestClient
from ai_clipper import web_ui

def test_invite_and_worker_have_separate_access(monkeypatch,tmp_path):
    monkeypatch.setattr(web_ui,"STATE",tmp_path)
    for name,key in (("STUDIO_INVITE_SHA256","invite-secret"),("STUDIO_WORKER_SHA256","worker-secret")):
        monkeypatch.setenv(name,hashlib.sha256(key.encode()).hexdigest())
    client=TestClient(web_ui.app,base_url="https://testserver")
    assert "complete invite" in client.get("/").text
    assert client.post("/api/ai-shorts",json={}).status_code==403
    assert client.get("/api/studio/jobs/"+"a"*32+"/bundle").status_code==403
    assert client.post("/worker/claim",headers={"Authorization":"Bearer invite-secret"}).status_code==403
    assert client.post("/access",headers={"Authorization":"Bearer invite-secret"}).status_code==200
    r=client.post("/api/studio/jobs",json={"url":"https://www.youtube.com/watch?v=tvT6ZVHOtWs"})
    job=r.json()["job_id"]
    h={"Authorization":"Bearer worker-secret"}
    claim=client.post("/worker/claim",headers=h).json()
    assert job==claim["job_id"]
    assert not client.post("/worker/claim",headers=h).json()
    assert client.post("/worker/"+job+"/status",headers=h,json={"status":"completed"}).status_code==409
    h["X-Lease"]=claim["lease"]
    assert client.put("/worker/"+job+"/files/transcript.json",headers=h,content=b"[]").status_code==200
    assert client.post("/worker/"+job+"/status",headers=h,json={"status":"completed"}).status_code==200
    assert client.get("/api/studio/jobs/"+job+"/transcript").json()==[]
