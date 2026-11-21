"""Run with python -m ai_clipper.private_worker on a machine with FFmpeg."""
import json
import logging
import os
from pathlib import Path
from threading import Thread
import time
from urllib.parse import urlsplit

import requests

from . import web_ui
from .remote_scan import ARTIFACT
from .sources import stream_url

LOG = logging.getLogger("private-worker")


def run_job(origin, token, claim):
    job = claim["job_id"]
    opts = web_ui.Options(**claim["options"])
    source = stream_url(opts.url)
    if urlsplit(source).hostname != "www.youtube.com":
        raise ValueError("Unsupported private-worker source")
    folder = web_ui.job_path(job)
    folder.mkdir(parents=True,exist_ok=True)
    headers = {"Authorization":"Bearer "+token,"X-Lease":claim["lease"]}
    url = f"{origin}/worker/{job}"
    def send(method, endpoint, **kwargs):
        for attempt in range(4):
            try:
                if "data" in kwargs:
                    kwargs["data"].seek(0)
                response = requests.request(method,url+endpoint,headers=headers,timeout=(15,90),**kwargs)
                response.raise_for_status()
                return
            except requests.RequestException as exc:
                if (exc.response is not None and exc.response.status_code<500) or attempt==3:
                    raise
                time.sleep(3*(attempt+1))

    def evaluate():
        web_ui.QUEUE.acquire()
        web_ui.process(folder,source,opts,"")

    # Reuse the pipeline's exact job schema, checkpoints and source timestamps.
    previous = web_ui.read_job(job) if (folder/"job.json").is_file() else {}
    if previous.get("status") != "completed":
        web_ui.update(folder,session=web_ui.SESSION,status="running",stage="Reading source metadata",percent=1,progress=1,
                      num_clips=0, clips=[], error=None, resumable=True)
        worker = Thread(target=evaluate)
        worker.start()
        while worker.is_alive():
            state = web_ui.read_job(job)
            if state["status"] in ("running","paused"):
                send("POST","/status",json=state)
            worker.join(10)
    state = web_ui.read_job(job)
    if state["status"]=="completed":
        for path in folder.rglob("*"):
            name=path.relative_to(folder).as_posix()
            if path.is_file() and ARTIFACT.fullmatch(name):
                send("POST","/status",json={"status":"running","stage":"Uploading clip results","percent":99})
                with path.open("rb") as video:
                    send("PUT","/files/"+name,data=video)
    send("POST","/status",json=state)
    LOG.info("Job %s finished with %s",job,state["status"])


def main():
    logging.basicConfig(level=logging.INFO)
    origin=os.environ["STUDIO_GATEWAY"].rstrip("/")
    if urlsplit(origin).scheme!="https":
        raise ValueError("The gateway must use HTTPS")
    token=os.environ["STUDIO_WORKER_TOKEN"]
    while True:
        try:
            response=requests.post(origin+"/worker/claim",headers={"Authorization":"Bearer "+token},timeout=30)
            response.raise_for_status()
            claim=response.json()
            if claim:
                run_job(origin,token,claim)
                continue
        except (requests.RequestException, ValueError, OSError) as exc:
            LOG.warning("Worker connection or job failed: %s",type(exc).__name__)
        time.sleep(12)


if __name__=="__main__":
    main()
