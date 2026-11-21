"""Bound the working set on CPU hosts shared by FastAPI, models and FFmpeg."""
import ctypes
import gc
import os


def low_memory():
    return os.getenv("CLIPPER_LOW_MEMORY", "true").lower() in ("true","1","yes")


def release_models():
    if not low_memory():
        return
    from .audio_analyzer import _speech_model
    from .vision_models import classifier
    for factory in (classifier, _speech_model):
        clear = getattr(factory, "cache_clear", None)
        if clear:
            clear()
    gc.collect()
    # glibc may otherwise retain freed model pages throughout the following encode.
    trim = getattr(ctypes.CDLL(None), "malloc_trim", None)
    if trim is not None:
        trim(0)
