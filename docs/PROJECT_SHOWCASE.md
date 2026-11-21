# 🎬 StreamGrabber AI

**AI-assisted gaming highlight clipping • Python • FastAPI • FFmpeg**

[![Python](https://img.shields.io/badge/Python-3.x-3776AB?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-Backend-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![GitHub](https://img.shields.io/badge/Source-GitHub-181717?logo=github)](https://github.com/sneetesh594-alt/streamgrabber-ai)

> Turn authorized gaming recordings into vertical highlights. The project contains both a modular local clipper and a separate StreamGrabber web application.

## ✨ Product vision

- Accept a supported recording URL or local video (with permission).
- Inspect **real gameplay footage** before selecting moments.
- Reject loading screens, menus, AFK periods, and duplicate highlights.
- Export mobile-friendly 9:16 clips, including 720p/1080p layouts where supported.
- Offer captions, optional creator badges, preview, and download.

## 🧭 Architecture

`Input → Media inspection → Gameplay filtering → Highlight ranking → FFmpeg render → Review & export`

## 🚧 Implementation status

The published Clip Studio uses decoded visual, audio and speech evidence. It supports full and sampled VOD ranges, retained live DVR, source timestamps and resumable recording scans. [Verification](VERIFICATION.md)

## 🔐 Security and creator rights

Never commit API keys, tokens, cookies, or private media. Use server-side environment variables. Only process videos you own or have permission to use.

## 🚀 Getting started

See the [main README](../README.md) for local installation and CLI usage. The web app lives in `stream_downloader/`. Deployment requires a suitable backend and must be validated separately.
