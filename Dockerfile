FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    nodejs \
    npm \
    fonts-dejavu-core \
    fonts-freefont-ttf \
    curl \
    git \
    && (which node || ln -s /usr/bin/nodejs /usr/local/bin/node || true) \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements_web.txt .
RUN pip install --no-cache-dir -r requirements_web.txt

COPY stream_downloader/ /app/stream_downloader/
COPY ai_clipper/ /app/ai_clipper/

RUN mkdir -p /app/downloads/ai_shorts

ENV CLIPPER_WHISPER_MODEL=tiny
ENV PORT=7860
EXPOSE 7860

CMD ["sh", "-c", "uvicorn stream_downloader.app:app --host 0.0.0.0 --port ${PORT:-7860}"]
