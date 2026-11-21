"""Compare decoded frames with both gameplay and rejection labels in CLIP space."""
import os
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

LABELS = (
    "a screenshot of action gameplay in an open world video game with a player HUD",
    "third person video game footage of a car chase or a stunt race",
    "action video game footage of a police pursuit, a crash or a heist",
    "a player performing a stunt, a jump or a high-speed overtake in a video game",
    "an idle character standing still or uneventful travel in a video game",
    "a video game pause menu, settings, loading screen, lobby, inventory or map",
    "a black screen, a title card, scrolling text or a video editor",
    "a real photograph, a live action movie, or a person talking on a webcam",
)
REPO = "Xenova/clip-vit-base-patch32"
REV = "6b7c523703ae26e39be4b03774966f8571c7f523"
STATUS = {"state": "not_loaded", "backend": "CLIP", "error": None}


def _probabilities(image, text):
    embedding = image.reshape(-1)
    sims = 70 * (text @ (embedding / max(np.linalg.norm(embedding), 1e-9)))
    def probability(positive, negative):
        return float(1 / (1 + np.exp(np.clip(max(negative) - max(positive), -50, 50))))
    return probability(sims[:5], sims[5:]), probability(sims[1:4], sims[4:])


def _onnx_model():
    import onnxruntime as ort
    from huggingface_hub import hf_hub_download
    from tokenizers import Tokenizer

    def model_file(name):
        cache = os.getenv("CLIPPER_ONNX_DIR")
        if cache:
            return str(Path(cache) / Path(name).name)
        return hf_hub_download(REPO, name, revision=REV)

    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 2
    opts.inter_op_num_threads = 1
    opts.enable_cpu_mem_arena = False
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
    def session(name):
        return ort.InferenceSession(model_file("onnx/" + name + "_model_quantized.onnx"),
                                    sess_options=opts, providers=["CPUExecutionProvider"])
    tokenizer = Tokenizer.from_file(model_file("tokenizer.json"))
    tokenizer.enable_padding(pad_id=1, pad_token="<|endoftext|>")
    encoded = tokenizer.encode_batch(list(LABELS))
    ids = np.asarray([t.ids for t in encoded], dtype=np.int64)
    text_model = session("text")
    args = {"input_ids": ids, "attention_mask": np.asarray([t.attention_mask for t in encoded], dtype=np.int64)}
    text = text_model.run(["text_embeds"], {item.name: args[item.name] for item in text_model.get_inputs()})[0]
    del text_model
    text /= np.linalg.norm(text, axis=-1, keepdims=True)
    vision = session("vision")
    mean = np.asarray([.48145466, .4578275, .40821073], dtype=np.float32)
    std = np.asarray([.26862954, .26130258, .27577711], dtype=np.float32)

    def score(rgb):
        frame = ImageOps.fit(Image.fromarray(rgb), (224, 224), method=Image.Resampling.BICUBIC)
        data = ((np.asarray(frame, dtype=np.float32) / 255 - mean) / std).transpose(2, 0, 1)[None, :]
        return _probabilities(vision.run(["image_embeds"], {"pixel_values": data})[0], text)
    return score


@lru_cache(maxsize=1)
def classifier():
    STATUS.update(state="loading", error=None)
    try:
        if os.getenv("CLIPPER_VISION_BACKEND", "onnx") == "openclip":
            import open_clip
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
            model, _, preprocess = open_clip.create_model_and_transforms("ViT-B-32", pretrained="laion2b_s34b_b79k")
            model = model.to(device).eval()
            with torch.inference_mode():
                vectors = model.encode_text(open_clip.get_tokenizer("ViT-B-32")(list(LABELS)).to(device))
                text = torch.nn.functional.normalize(vectors).cpu().numpy()
            def score(rgb):
                with torch.inference_mode():
                    vector = model.encode_image(preprocess(Image.fromarray(rgb)).unsqueeze(0).to(device)).cpu().numpy()
                return _probabilities(vector, text)
            STATUS.update(state="ready", backend="OpenCLIP")
            return score
        score = _onnx_model()
        STATUS.update(state="ready", backend="ONNX CLIP")
        return score
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        STATUS.update(state="unavailable", error=type(exc).__name__)
        return None
