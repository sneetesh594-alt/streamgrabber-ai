@echo off
title StreamGrabber AI - Git Push Helper
echo ========================================================
echo    StreamGrabber AI - Cloud Git Deployment Setup
echo ========================================================
echo.

cd /d "%~dp0"

echo [1/3] Initializing Git repository...
git init
git branch -M main

echo [2/3] Adding project files...
git add .
git commit -m "StreamGrabber AI Cloud Ready with Docker, FFmpeg, and Node"

echo.
echo ========================================================
echo [3/3] Ready to push to GitHub or Hugging Face!
echo ========================================================
echo.
echo Agar aapne GitHub par nayi repo banayi hai toh niche
echo di gayi command copy karke chalayein:
echo.
echo   git remote add origin https://github.com/APNA_USERNAME/streamgrabber-ai.git
echo   git push -u origin main
echo.
echo Ya Hugging Face Spaces par direct files upload karein:
echo Dekhein guide: CLOUD_DEPLOY_GUIDE.md
echo ========================================================
echo.
pause
