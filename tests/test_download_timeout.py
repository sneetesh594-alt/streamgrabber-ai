import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from ai_clipper.process_runner import run


@pytest.mark.skipif(os.name != "posix", reason="POSIX extractor process group")
def test_extractor_timeout_terminates_ffmpeg_child(tmp_path):
    child_file = tmp_path/"child.pid"
    code = (
        "import subprocess,sys,time,pathlib;"
        "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
        "pathlib.Path(sys.argv[1]).write_text(str(p.pid));time.sleep(60)"
    )
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        run([sys.executable,"-c",code,str(child_file)],timeout=.5)
    assert time.monotonic()-started < 5
    proc = Path("/proc")/child_file.read_text()/"stat"
    assert not proc.exists() or proc.read_text().split()[2] == "Z"


def test_video_identity_is_reported_before_media_failure(tmp_path,monkeypatch):
    from ai_clipper import sources
    from ai_clipper.config import ClipperConfig
    from ai_clipper.pipeline import run_pipeline
    monkeypatch.setattr(sources,"metadata",lambda url:dict(title="Actual supplied video",id="tvT6ZVHOtWs",
                                                          uploader="Actual creator",duration=30))
    def rejected(*args):
        raise sources.SourceAccessError("forbidden","HTTP 403")
    monkeypatch.setattr(sources,"fetch_section",rejected)
    info=[]
    result=run_pipeline("https://www.youtube.com/watch?v=tvT6ZVHOtWs",tmp_path,ClipperConfig(),on_details=info.append)
    assert result.source_error=="forbidden"
    assert info[0]["title"]=="Actual supplied video"
    assert info[0]["channel"]=="Actual creator"
