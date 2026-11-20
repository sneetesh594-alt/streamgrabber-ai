@echo off
title StreamGrabber AI - YouTube Live Stream & 9:16 Shorts Generator
color 0B

echo =====================================================================
echo          STREAMGRABBER AI - YOUTUBE LIVE & 9:16 SHORTS GENERATOR
echo =====================================================================
echo.

:: 1. Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python aapke system par install nahi hai ya PATH me add nahi hai!
    echo Kripya Python download karein: https://www.python.org/downloads/
    pause
    exit /b
)

echo [1/3] Python detected.
echo.

:: 2. Check and Install Requirements
echo [2/3] Zaroori libraries check aur install kar rahe hain (FastAPI, yt-dlp, FFmpeg)...
python -m pip install -r requirements_web.txt imageio-ffmpeg --quiet >nul 2>&1

echo.
echo [3/3] Website Server start kar rahe hain...
echo.

:: Start Cloudflare Public Tunnel in background if available
if exist "bin\cloudflared.exe" (
    echo [Public Tunnel] Starting Cloudflare Public Tunnel...
    start /b "" "bin\cloudflared.exe" tunnel --url http://127.0.0.1:8000
)

echo =====================================================================
echo [LOCAL URL]  : http://127.0.0.1:8000
echo [NETWORK URL]: http://10.133.36.22:8000
echo (Browser me open ho raha hai...)
echo =====================================================================
echo.

start http://127.0.0.1:8000

cd stream_downloader
python -m uvicorn app:app --host 0.0.0.0 --port 8000 --reload

pause
