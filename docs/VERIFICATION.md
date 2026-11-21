# Verification

## Tests you can run

```sh
python -m pip install -r requirements_web.txt pytest httpx
python -m pytest -q --disable-warnings
```

The 39-test run passed. Tests include real FFmpeg scene cuts, portrait sizes, overlay and subtitle pixels, a real HTTP-served HLS playlist converted into a vertical clip, 20h and 22h46m coverage without gaps, late-hour selection, retained-window clock alignment, checkpoint resume, shared Gemini quota and billing rejection. Semantic reviewer test doubles are identified in the tests.

## Measured media runs

| Input | Observed result |
| --- | --- |
| Xusder's GTA V Urban Mayhem recording, 117.63 s | Local CLIP and Whisper pipeline produced two 30 s clips. The built-in sample starts at 41.816 s. No words were transcribed in that window. |
| Controlled 20-hour MP4 | The test container had an extended still lead-in and real, licensed GTA V footage in the final 45 seconds. ffprobe reported 72,000.064 s. A requested scan of 71,955–72,000 s produced one 25.000 s 720×1280 H.264/AAC MP4, source 71,963.5–71,988.5 s, local CLIP score 0.5586. This measures seeking, analysis and export at hour 20. |
| Public 22h46m walkthrough | yt-dlp returned a duration of 81,960 s and a YouTube HLS HTTP 403 warning. Only metadata was verified. The local and controlled-HLS tests exercise the extraction path independently. |

Source and rights for the gameplay test are in the [sample credits](../ai_clipper/studio/assets/CREDITS.txt). The 20-hour fixture is a seek test. A complete 20-hour natural broadcast has not been benchmarked.

```sh
python -m yt_dlp --no-playlist --js-runtimes node --skip-download --print "%(duration)s %(title)s" "https://www.youtube.com/watch?v=vZJSlBiA5kw"
python -m ai_clipper clip "your-20-hour-recording.mp4" --start-seconds 71955 --end-seconds 72000 --clip-duration 25 --max-clips 1 --quality 720p -o hour20
ffprobe -v error -show_entries stream=codec_name,width,height:format=duration -of compact hour20/clips/clip_01.mp4
```

To diagnose a permitted platform recording, fetch a bounded interval and inspect the result. An inaccessible manifest or expired authorization may still produce HTTP 403. Studio retries access once, reports its state, and offers upload. Keep cookies and signed media URLs out of shared logs.

```sh
python -m yt_dlp --no-playlist --js-runtimes node --download-sections "*00:00:30-00:01:05" --force-keyframes-at-cuts -o "section.%(ext)s" "YOUR_OWN_VOD_URL"
```
