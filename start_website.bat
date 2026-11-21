@echo off
setlocal
cd /d "%~dp0"
title StreamGrabber AI Clip Studio
where ffmpeg >nul 2>&1 || (echo Install FFmpeg and add its bin directory to PATH. & pause & exit /b 1)
where ffprobe >nul 2>&1 || (echo Add ffprobe to PATH. & pause & exit /b 1)
if not exist ".venv\Scripts\python.exe" python -m venv .venv
if errorlevel 1 exit /b 1
".venv\Scripts\python" -m pip install -r requirements_web.txt
if errorlevel 1 (pause & exit /b 1)
echo Open http://127.0.0.1:8000 in your browser.
".venv\Scripts\python" -m uvicorn stream_downloader.app:app --host 127.0.0.1 --port 8000 --workers 1
pause
