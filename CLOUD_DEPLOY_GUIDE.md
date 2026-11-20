# ☁️ StreamGrabber AI — 24/7 Free Cloud Hosting Guide

Aapka laptop band hone ke baad bhi website **24 ghante chalane ke liye**, aap ise **100% Free Cloud** par host kar sakte hain.

Dono best aur aasan tareeqe neeche step-by-step diye gaye hain:

---

## 🌟 Method 1: Hugging Face Spaces (Sabse Best & 100% Free)
> **Kyun Best Hai?**
> - 16 GB RAM + 2 vCPU bilkul FREE milta hai (No Credit Card required).
> - Video cutting aur FFmpeg super fast chalta hai.
> - Aapko permanent 24/7 public link milta hai: `https://<username>-streamgrabber-ai.hf.space`

### Step-by-Step Steps:
1. **Account Banayein:**
   - [huggingface.co/join](https://huggingface.co/join) par jakar free account banayein (1 minute).
2. **New Space Create Karein:**
   - [huggingface.co/new-space](https://huggingface.co/new-space) par jayein.
   - **Space Name:** `streamgrabber-ai`
   - **License:** `apache-2.0` (ya blank)
   - **Space SDK:** Choose **Docker** -> **Blank** (Zaroori: Docker select karein).
   - **Space Hardware:** Free (2 vCPU, 16GB RAM)
   - **Visibility:** **Public**
   - Click **Create Space**.
3. **Files Upload Karein:**
   - Space page par **Files and versions** tab par click karein -> **Add file** -> **Upload files**.
   - `stream_downloader` folder ke andar ki sabhi files aur folders upload karein:
     - `Dockerfile`
     - `requirements.txt`
     - `app.py`
     - `templates/` folder (aur uske andar `index.html`)
     - `static/` folder (aur uske andar `script.js`, `style.css`)
   - Click **Commit changes to main**.
4. **Deploy Ho Gaya!**
   - Hugging Face automatically 1 minute me container build kar dega.
   - Aapko permanent live link mil jayega jo laptop band hone par bhi 24 ghante chalega!

---

## 🚀 Method 2: Render.com (GitHub ke zariye 1-Click Deploy)
> **Kyun Acha Hai?**
> - GitHub se direct connect hota hai. Jab bhi code update karein, automatically live update ho jata hai.
> - Free permanent link: `https://streamgrabber-ai.onrender.com`

### Step-by-Step Steps:
1. **GitHub par Repo Banayein:**
   - [github.com](https://github.com) par free account banakar **New Repository** banayein: `streamgrabber-ai` (Public).
2. **Code Push Karein:**
   - Project folder me `deploy_to_github.bat` run karein ya terminal me ye run karein:
     ```bash
     git init
     git add .
     git commit -m "StreamGrabber AI ready for cloud"
     git branch -M main
     git remote add origin https://github.com/<YOUR_USERNAME>/streamgrabber-ai.git
     git push -u origin main
     ```
3. **Render par Deploy Karein:**
   - [render.com](https://render.com) par free login karein.
   - Click **New +** -> **Web Service**.
   - Apna GitHub repository `streamgrabber-ai` select karein.
   - **Environment:** Select **Docker**.
   - **Instance Type:** **Free**.
   - Click **Deploy Web Service**!
4. Render 2-3 minute me deploy karke aapko permanent link de dega.

---

## 🛠️ Files Already Created:
1. `Dockerfile` — FFmpeg + Node.js + Python 3.11 ready
2. `render.yaml` — 1-Click Render blueprint
3. `requirements_web.txt` / `requirements.txt` — Optimized cloud dependencies
4. `deploy_to_github.bat` — 1-click git helper script
