# 🎬 AI Video Clipper

> Automatically detect exciting moments in gameplay videos and generate viral-ready 9:16 vertical Shorts — fully local, open-source, AI-powered.

## ✨ Features

- **Multi-Modal Analysis**: Audio (Whisper transcription + loudness), Visual (CLIP scoring + face detection + motion), NLP (keyword/sentiment scoring)
- **Smart Highlight Detection**: Combined signal fusion with configurable weights
- **Vertical 9:16 Output**: Auto-cropped to follow the main subject (face tracking)
- **Subtitles & Hooks**: Auto-generated from Whisper transcript
- **Titles & Hashtags**: Context-aware metadata generation
- **Web UI + CLI**: Browser-based interface and command-line tool
- **Fully Local**: All AI models run on your machine — no data uploaded

## 📐 Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     AI VIDEO CLIPPER                        │
├──────────┬──────────┬──────────┬──────────┬────────────────┤
│  Stage 1 │  Stage 2 │  Stage 3 │  Stage 4 │    Stage 5     │
│ Download │  Scene   │  Audio   │  Visual  │   NLP/Text     │
│ (yt-dlp) │ Detect   │ Analysis │ Analysis │   Scoring      │
│          │(PyScene) │(Whisper+ │ (CLIP +  │  (Keywords+    │
│          │          │ librosa) │ OpenCV)  │  Sentiment)    │
├──────────┴──────────┴──────────┴──────────┴────────────────┤
│                   Stage 6: Signal Fusion                    │
│    audio_score × 0.30 + text_score × 0.35 +                │
│    visual_score × 0.35  →  Peak Detection                  │
├─────────────────────────────────────────────────────────────┤
│              Stage 7: Clip Generation (FFmpeg)              │
│  Trim → Crop 9:16 → Face Track → Subtitles → Hook Text    │
├─────────────────────────────────────────────────────────────┤
│           Stage 8: Packaging & Metadata                     │
│    Titles, Hashtags, Thumbnails, JSON metadata              │
└─────────────────────────────────────────────────────────────┘
```

## 🚀 Quick Start

### 1. Install Dependencies

```bash
# System dependencies
# Windows: Install FFmpeg from https://ffmpeg.org/download.html
# Mac: brew install ffmpeg
# Linux: sudo apt install ffmpeg

# Install yt-dlp
pip install yt-dlp

# Install Python packages
pip install -r requirements.txt

# Or install with pip (editable mode)
pip install -e ".[full,web]"
```

### 2. CLI Usage

```bash
# Basic: Generate clips from a local video
python -m ai_clipper clip gameplay.mp4

# From YouTube URL
python -m ai_clipper clip "https://youtube.com/watch?v=XXXXX" -o ./my_clips

# Custom settings
python -m ai_clipper clip video.mp4 \
    --max-clips 5 \
    --clip-duration 45 \
    --whisper-model medium \
    --weight-audio 0.4 \
    --weight-text 0.3 \
    --weight-visual 0.3

# Analysis only (no clip generation)
python -m ai_clipper analyze video.mp4

# Check system dependencies
python -m ai_clipper info
```

### 3. Web UI

```bash
# Start the web server
uvicorn ai_clipper.web_ui:app --host 0.0.0.0 --port 8000

# Open http://localhost:8000 in your browser
```

## ⚙️ Configuration

Copy `.env.example` to `.env` and customize:

```bash
cp .env.example .env
```

Key settings:

| Setting | Default | Description |
|---------|---------|-------------|
| `CLIPPER_WHISPER_MODEL` | `base` | Whisper model size (tiny/base/small/medium/large) |
| `CLIPPER_WEIGHT_AUDIO` | `0.30` | Audio energy score weight |
| `CLIPPER_WEIGHT_TEXT` | `0.35` | Transcript/NLP score weight |
| `CLIPPER_WEIGHT_VISUAL` | `0.35` | Visual/CLIP score weight |
| `CLIPPER_MAX_CLIPS` | `10` | Maximum clips to generate |
| `CLIPPER_CLIP_DURATION_TARGET_SEC` | `30` | Target clip duration |
| `CLIPPER_OUTPUT_WIDTH` | `1080` | Output width (9:16) |
| `CLIPPER_OUTPUT_HEIGHT` | `1920` | Output height (9:16) |
| `CLIPPER_TRACKER_TYPE` | `CSRT` | OpenCV tracker (KCF/CSRT/MOSSE) |

## 🏗️ Project Structure

```
ai_clipper/
├── __init__.py          # Package init
├── __main__.py          # CLI entry point
├── cli.py               # Click CLI interface
├── config.py            # Pydantic configuration
├── pipeline.py          # Main pipeline orchestrator
├── downloader.py        # yt-dlp video download
├── scene_detector.py    # PySceneDetect scene detection
├── audio_analyzer.py    # Whisper + librosa audio analysis
├── visual_analyzer.py   # CLIP + OpenCV visual scoring
├── nlp_scorer.py        # NLP keyword/sentiment scoring
├── scorer.py            # Signal fusion & peak detection
├── clip_generator.py    # FFmpeg clip generation
├── face_tracker.py      # OpenCV face tracking
└── web_ui.py            # FastAPI web interface
tests/
└── test_pipeline.py     # Unit tests
```

## 🎯 Scoring Logic

Each moment gets a weighted score from three signals:

```
final_score = (weight_audio × audio_score) +
              (weight_text  × text_score)  +
              (weight_visual × visual_score)
```

- **Audio Score**: RMS energy from librosa — loud moments (explosions, cheers) get high scores
- **Text Score**: Keyword matching (exciting gaming terms) + sentiment analysis of Whisper transcript
- **Visual Score**: CLIP similarity to exciting prompts + face detection + optical flow motion

Peaks in the combined timeline are selected as highlight candidates.

## 📋 MVP Roadmap

1. ✅ **MVP1**: Basic download + scene split + naive clip cutting
2. ✅ **MVP2**: Audio peak scoring (librosa RMS energy)
3. ✅ **MVP3**: Combined text + audio scoring
4. ✅ **MVP4**: Visual scoring (CLIP + face detection)
5. ✅ **MVP5**: FFmpeg clip generation with subtitles and 9:16 crop
6. ✅ **MVP6**: End-to-end pipeline with metadata
7. ✅ **MVP7**: Web UI for browser-based usage

## 💻 Hardware Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| CPU | 4 cores | 8+ cores |
| RAM | 8 GB | 16+ GB |
| GPU | None (CPU works) | NVIDIA GPU with 4+ GB VRAM |
| Storage | 10 GB free | 50+ GB free |

> **Note**: CLIP and Whisper run much faster with a CUDA GPU. Without GPU, processing a 1-hour video may take 30-60 minutes. With GPU, it can be 5-15 minutes.

## ⚖️ Legal Disclaimer

- **Only process videos you own or have explicit permission to use**
- Adding subtitles or cropping does NOT clear copyright
- This tool is for personal and educational use
- Refer to [YouTube's Terms of Service](https://www.youtube.com/t/terms) for monetization policies
- Always respect content creators' rights

## 🔧 Troubleshooting

**FFmpeg not found**: Install from https://ffmpeg.org/download.html and add to PATH

**CUDA out of memory**: Use a smaller Whisper model (`--whisper-model tiny`) or disable CLIP (`--no-clip`)

**yt-dlp errors**: Update with `pip install -U yt-dlp`

**Slow processing**: Reduce `CLIPPER_CLIP_SAMPLE_FPS` to analyze fewer frames

## 📚 Key Libraries

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) - Video download
- [OpenAI Whisper](https://github.com/openai/whisper) - Speech-to-text
- [OpenCLIP](https://github.com/mlfoundations/open_clip) - Visual content scoring
- [PySceneDetect](https://github.com/Breakthrough/PySceneDetect) - Scene detection
- [OpenCV](https://opencv.org/) - Face detection + object tracking
- [librosa](https://librosa.org/) - Audio analysis
- [FFmpeg](https://ffmpeg.org/) - Video processing
- [FastAPI](https://fastapi.tiangolo.com/) - Web UI
- [HuggingFace Transformers](https://huggingface.co/) - NLP models

## License

MIT
