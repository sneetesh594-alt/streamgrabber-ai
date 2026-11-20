# ============================================
# AI Video Clipper - Setup Script
# ============================================

from setuptools import setup, find_packages

setup(
    name="ai-video-clipper",
    version="0.1.0",
    description="AI-powered video highlight detection and clip generation pipeline",
    author="AI Clipper",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        "click>=8.1.7",
        "rich>=13.7.0",
        "pydantic>=2.5.0",
        "pydantic-settings>=2.1.0",
        "numpy>=1.24.0",
        "pillow>=10.0.0",
        "tqdm>=4.66.0",
        "ffmpeg-python>=0.2.0",
    ],
    extras_require={
        "full": [
            "yt-dlp>=2024.1.0",
            "openai-whisper>=20231117",
            "librosa>=0.10.1",
            "soundfile>=0.12.1",
            "opencv-python>=4.8.0",
            "opencv-contrib-python>=4.8.0",
            "open-clip-torch>=2.24.0",
            "transformers>=4.36.0",
            "torch>=2.1.0",
            "scenedetect[opencv]>=0.6.2",
            "scipy>=1.11.0",
        ],
        "web": [
            "fastapi>=0.104.0",
            "uvicorn>=0.24.0",
            "python-multipart>=0.0.6",
            "jinja2>=3.1.2",
        ],
    },
    entry_points={
        "console_scripts": [
            "ai-clipper=ai_clipper.cli:main",
        ],
    },
)
