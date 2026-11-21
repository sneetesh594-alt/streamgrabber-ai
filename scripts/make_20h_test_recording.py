"""Create a compact 20-hour seek fixture from a permitted gameplay file with audio."""
import argparse
from pathlib import Path
import subprocess
import tempfile


def build(source, output, start):
    source, output = source.resolve(), output.resolve()
    if output.exists():
        raise SystemExit("Choose a new output filename.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as tmp:
        root = Path(tmp)

        def ff(*args):
            subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-n", *args], cwd=root, check=True)

        def index(name, intro, action):
            (root/name).write_text(f"ffconcat version 1.0\nfile '{intro}'\nduration 71955\nfile '{action}'\n")

        vcodec = ["-c:v", "libx264", "-preset", "ultrafast", "-bf", "0", "-threads", "1",
                  "-video_track_timescale", "1000", "-an"]
        ff("-f", "lavfi", "-i", "color=black:s=192x108:r=1/15", "-t", "71955",
           "-g", "12", *vcodec, "intro.mp4")
        ff("-ss", str(start), "-i", str(source), "-t", "45", "-vf", "scale=192:108,fps=15",
           "-g", "16", *vcodec, "action.mp4")
        index("video.ffconcat", "intro.mp4", "action.mp4")
        ff("-f", "concat", "-i", "video.ffconcat", "-c:v", "copy", "-video_track_timescale",
           "1000", "-movflags", "faststart", "video.mp4")
        ff("-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono", "-t", "71955",
           "-c:a", "aac", "-b:a", "8k", "intro.m4a")
        ff("-ss", str(start), "-i", str(source), "-t", "45", "-vn", "-ar", "8000",
           "-ac", "1", "-c:a", "aac", "-b:a", "24k", "action.m4a")
        index("audio.ffconcat", "intro.m4a", "action.m4a")
        ff("-i", "video.mp4", "-f", "concat", "-i", "audio.ffconcat",
           "-map", "0:v", "-map", "1:a", "-c", "copy", "-video_track_timescale", "1000",
           "-movflags", "faststart", "fixture.mp4")
        (root/"fixture.mp4").replace(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Recording containing at least 45 seconds of gameplay and audio")
    parser.add_argument("output", type=Path)
    parser.add_argument("--start", type=float, default=0, help="Where the 45-second excerpt begins in the original")
    args = parser.parse_args()
    build(args.source, args.output, args.start)
