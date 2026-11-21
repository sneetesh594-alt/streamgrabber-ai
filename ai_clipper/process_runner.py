"""Bound extractor subprocesses together with their FFmpeg children."""
import os
import signal
import subprocess


def run(arguments, timeout):
    process = subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, start_new_session=os.name == "posix")
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)],
                           capture_output=True, timeout=10)
            process.kill()
        process.communicate(timeout=10)
        raise
    return subprocess.CompletedProcess(arguments, process.returncode, stdout, stderr)
