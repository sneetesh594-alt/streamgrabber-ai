FROM python:3.11-slim

# Prevent interactive prompts during package install
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Install FFmpeg, Node.js (for YouTube challenge solving), and Bold Fonts (for GTA VI & @Creator overlays)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    nodejs \
    npm \
    fonts-dejavu-core \
    fonts-freefont-ttf \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install Python requirements
COPY requirements_web.txt .
RUN pip install --no-cache-dir -r requirements_web.txt

# Copy StreamGrabber AI application code
COPY stream_downloader/ /app/

# Ensure downloads directories exist
RUN mkdir -p /app/downloads/ai_shorts

# Port setup (Hugging Face default 7860, Render/Railway default $PORT)
ENV PORT=7860
EXPOSE 7860

# Start FastAPI application
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-7860}"]
