"""Freeze the publicly playable HLS DVR window at the time a job starts."""
import math
import re
import subprocess
import tempfile
import urllib.request
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import m3u8


def _remote(base, uri):
    url = urljoin(base, uri)
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password or any(c in url for c in '\r\n"'):
        raise ValueError("The live stream contains an unsupported media address.")
    return url


def _playlist(url):
    request = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=20) as res:
            raw = res.read(16_000_001)
            if len(raw) > 16_000_000 or not raw.lstrip().startswith(b"#EXTM3U"):
                raise ValueError("The provider did not return a readable DVR playlist.")
            return m3u8.loads(raw.decode("utf-8-sig"), uri=res.geturl()), res.geturl()
    except OSError:
        raise ValueError("The provider refused the DVR playlist. Use the saved VOD or a local recording.") from None


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    uri: str
    byte_range: str
    init: tuple
    discontinuity: bool


class Track:
    def __init__(self, playlist, base):
        self.segments = []
        self.clock = None
        self.sequence = int(playlist.media_sequence or 0)
        cursor, previous_uri, previous_end = 0., None, None
        for entry in playlist.segments:
            if getattr(entry,"gap_tag",False):
                raise ValueError("This live playlist has missing media. Retry with the completed VOD.")
            if entry.key and entry.key.method not in ("NONE", None):
                raise ValueError("Use an unencrypted creator recording for this live stream.")
            length = float(entry.duration)
            if not math.isfinite(length) or length <= 0:
                raise ValueError("The live host returned invalid segment timing.")
            uri = _remote(base, entry.uri)
            byte_range = entry.byterange or ""
            if byte_range:
                fields = re.fullmatch(r"(\d+)(?:@(\d+))?", byte_range)
                if not fields or (fields[2] is None and (previous_uri != uri or previous_end is None)):
                    raise ValueError("The live host returned an incomplete byte-range segment.")
                offset = int(fields[2]) if fields[2] is not None else previous_end
                previous_end = offset + int(fields[1])
                byte_range = f"{fields[1]}@{offset}"
            else:
                previous_end = None
            init = ()
            if entry.init_section:
                init_range = entry.init_section.byterange or ""
                if init_range and not re.fullmatch(r"\d+@\d+", init_range):
                    raise ValueError("This live initialization range needs an explicit offset.")
                init = (_remote(base, entry.init_section.uri), init_range)
            if self.clock is None and entry.program_date_time:
                self.clock = entry.program_date_time.timestamp() - cursor
            self.segments.append(Segment(cursor, cursor+length, uri, byte_range, init, entry.discontinuity))
            previous_uri, cursor = uri, cursor+length
        if not self.segments:
            raise ValueError("The live provider has no completed DVR segments yet.")
        self.ends = [seg.end for seg in self.segments]
        self.duration = cursor

    def excerpt(self, start, end, file):
        first = bisect_right(self.ends, start + .00001)
        last = bisect_right(self.ends, end - .00001) + 1
        items = self.segments[first:last]
        if not items:
            raise ValueError("This part of the live recording is no longer available.")
        lines = ["#EXTM3U", "#EXT-X-VERSION:7", "#EXT-X-PLAYLIST-TYPE:VOD",
                 f"#EXT-X-TARGETDURATION:{math.ceil(max(s.end-s.start for s in items))}",
                 f"#EXT-X-MEDIA-SEQUENCE:{self.sequence+first}"]
        previous_init = None
        for seg in items:
            if seg.discontinuity:
                lines.append("#EXT-X-DISCONTINUITY")
            if seg.init and seg.init != previous_init:
                url, size = seg.init
                lines.append(f'#EXT-X-MAP:URI="{url}"' + (f',BYTERANGE="{size}"' if size else ""))
                previous_init = seg.init
            lines.append(f"#EXTINF:{seg.end-seg.start:.6f},")
            if seg.byte_range:
                lines.append("#EXT-X-BYTERANGE:"+seg.byte_range)
            lines.append(seg.uri)
        file.write_text("\n".join(lines+["#EXT-X-ENDLIST",""]), encoding="utf-8")
        return max(0., start-items[0].start)


class LiveDVR:
    def __init__(self, video, audio=None, release=None):
        self.video, self.audio = video, audio
        if audio and (video.clock is None or audio.clock is None):
            raise ValueError("The host does not expose synchronized audio/video DVR clocks. Use the saved VOD.")
        self.audio_delta = (video.clock - audio.clock) if audio else 0.
        left = max(0., -self.audio_delta) if audio else 0.
        right = min(video.duration, audio.duration-self.audio_delta) if audio else video.duration
        self.first = max(left, right-20*3600)
        self.duration = right-self.first
        if self.duration < 20:
            raise ValueError("Fewer than 20 seconds are currently available in the live DVR.")
        offset = video.clock + self.first - release if video.clock is not None and release else None
        self.offset = offset if offset is not None and 0 <= offset <= 30*86400 else 0.
        self.origin = "stream start" if offset is not None and self.offset == offset else "retained DVR window"
        self.identity = f"{video.sequence}:{video.clock}:{video.duration}:{self.first}:{self.duration}"

    def fetch(self, start, end, dest, height):
        if not 0 <= start < end <= self.duration + .02:
            raise ValueError("The requested interval exceeds the retained live window.")
        with tempfile.TemporaryDirectory(dir=dest.parent) as folder:
            args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
            for index, (track, shift) in enumerate([(self.video,0.)]+([(self.audio,self.audio_delta)] if self.audio else [])):
                manifest = Path(folder)/f"track-{index}.m3u8"
                seek = track.excerpt(start+self.first+shift, end+self.first+shift, manifest)
                args += ["-protocol_whitelist","file,http,https,tcp,tls", "-allowed_extensions","ALL",
                         "-rw_timeout","15000000", "-ss",f"{seek:.5f}","-i",str(manifest)]
            args += ["-t",str(end-start),"-map","0:v:0","-map","1:a:0" if self.audio else "0:a:0?",
                     "-vf",f"scale=-2:'min({int(height)},ih)'","-c:v","libx264","-threads","2",
                     "-preset","veryfast","-crf","22","-c:a","aac","-movflags","+faststart",str(dest)]
            try:
                subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=360)
                from .downloader import get_video_info
                if abs(get_video_info(dest).duration_sec - (end-start)) > 2.5:
                    raise ValueError("The provider returned a partial DVR section.")
            except (subprocess.SubprocessError, OSError):
                dest.unlink(missing_ok=True)
                raise ValueError("The requested live segments expired or were refused. Try a newer interval or the saved VOD.") from None


def open_dvr(info, height):
    formats = [f for f in info.get("formats",[]) if str(f.get("protocol","")).startswith("m3u8")
               and f.get("url") and not f.get("has_drm")]
    video = [f for f in formats if f.get("vcodec") != "none"]
    if not video:
        raise ValueError("This active stream has no readable HLS DVR. Try its finished VOD or your recording.")
    def rank(f):
        h = f.get("height") or 0
        return (f.get("acodec") not in (None,"none"), h<=height, h if h<=height else -h)
    selected = max(video,key=rank)
    media, url = _playlist(_remote("",selected["url"]))
    companion = None
    if media.is_variant:
        variants = sorted(media.playlists, key=lambda p:p.stream_info.bandwidth)
        eligible = [v for v in variants if v.stream_info.resolution and v.stream_info.resolution[1]<=height]
        chosen = eligible[-1] if eligible else variants[0]
        group = chosen.stream_info.audio
        companion = next((_remote(url, a.uri) for a in media.media if group and a.group_id==group and a.uri), None)
        media, url = _playlist(_remote(url, chosen.uri))
    elif selected.get("acodec") == "none":
        audio = sorted((f for f in formats if f.get("vcodec")=="none" and f.get("acodec") != "none"),
                       key=lambda f: f.get("abr") or 0)
        if audio:
            companion = _remote("",audio[-1]["url"])
    audio_track = Track(*_playlist(companion)) if companion else None
    return LiveDVR(Track(media,url),audio_track,info.get("release_timestamp"))
