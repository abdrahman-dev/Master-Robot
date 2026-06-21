from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Optional

import numpy as np
import torch

from config.settings import get_settings

logger = logging.getLogger(__name__)

_SETTINGS = get_settings()
_VAD = _SETTINGS.vad

TARGET_SAMPLE_RATE = _VAD.sample_rate
_MAX_ABS_AMPLITUDE = _VAD.max_abs_amplitude

_MODEL = None
_MODEL_LOCK = threading.Lock()
_UTILS = None
_THRESHOLD = _VAD.initial_threshold


class VADModuleError(RuntimeError):
    pass


def set_threshold(threshold: float) -> None:
    if not (0.0 <= threshold <= 1.0):
        raise VADModuleError(
            "[vad.set_threshold] Invalid threshold."
        )
    global _THRESHOLD
    _THRESHOLD = float(threshold)


def get_threshold() -> float:
    return _THRESHOLD


def _is_valid_local_model_path(path: str) -> bool:
    if not path:
        return False
    if path.strip() != path:
        return False
    if path.startswith("#"):
        return False
    if "/" not in path and "\\" not in path and not any(path.endswith(ext) for ext in (".jit", ".pt", ".onnx")):
        return False
    p = Path(path)
    if not p.exists() or not p.is_file():
        return False
    return True


def _load_model_once():
    global _MODEL, _UTILS

    if _MODEL is not None:
        return _MODEL

    with _MODEL_LOCK:
        if _MODEL is not None:
            return _MODEL

        try:
            torch.set_num_threads(_VAD.torch_threads)
            local_path = _VAD.model_local_path.strip()

            if local_path and _is_valid_local_model_path(local_path):
                logger.info("[VAD] Loading local model from: %s", local_path)
                try:
                    model = torch.jit.load(local_path, map_location="cpu")
                except Exception:
                    model = torch.load(local_path, map_location="cpu")
                utils = None
            else:
                if local_path:
                    logger.warning(
                        "[VAD] ROBOT_VAD_MODEL_LOCAL_PATH is set but invalid or file not found: %r — "
                        "falling back to hub download. Check your .env file for a malformed value "
                        "(e.g. a comment accidentally used as the value).",
                        local_path
                    )
                try:
                    model, utils = torch.hub.load(
                        _VAD.model_hub_repo,
                        _VAD.model_hub_name,
                        trust_repo=_VAD.model_trust_repo,
                    )
                except Exception as hub_err:
                    logger.warning("[VAD] torch.hub load failed: %s", hub_err)
                    fallback_dir = Path(__file__).parent.parent / "config" / "snakers4-silero-vad"
                    if fallback_dir.exists():
                        try:
                            model_path = str(next(fallback_dir.glob("*.jit")))
                            model = torch.jit.load(model_path, map_location="cpu")
                            utils = None
                            logger.info("[VAD] Loaded from local fallback: %s", model_path)
                        except (StopIteration, Exception) as fb_err:
                            raise VADModuleError(
                                "[vad] Silero VAD model unavailable. "
                                "No internet and no local model in config/snakers4-silero-vad/. "
                                f"Hub error: {hub_err}. Fallback error: {fb_err}"
                            ) from fb_err
                    else:
                        raise VADModuleError(
                            "[vad] Silero VAD model unavailable. "
                            "No internet and no config/snakers4-silero-vad/ directory. "
                            f"Hub error: {hub_err}"
                        ) from hub_err

            model.eval()
            _MODEL = model
            _UTILS = utils
            return _MODEL

        except VADModuleError:
            raise
        except Exception as exc:
            raise VADModuleError(
                f"[vad._load_model_once] Failed to load Silero VAD model: {exc}."
            ) from exc


def to_mono_float32(audio: np.ndarray) -> np.ndarray:
    if audio is None:
        raise VADModuleError("[vad.to_mono_float32] audio is None.")
    arr = np.asarray(audio)
    if arr.size == 0:
        raise VADModuleError("[vad.to_mono_float32] audio chunk is empty.")
    if arr.ndim == 2:
        arr = arr.mean(axis=1)
    elif arr.ndim != 1:
        raise VADModuleError(f"Expected 1D or 2D, got {arr.shape}.")
    if arr.dtype != np.float32:
        arr = arr.astype(np.float32, copy=False)
    np.clip(arr, -_MAX_ABS_AMPLITUDE, _MAX_ABS_AMPLITUDE, out=arr)
    return arr


def resample_linear(audio: np.ndarray, orig_sr: int, target_sr: int = TARGET_SAMPLE_RATE) -> np.ndarray:
    if orig_sr <= 0 or target_sr <= 0:
        raise VADModuleError(f"Invalid sample rate: {orig_sr}, {target_sr}.")
    if orig_sr == target_sr:
        return audio
    if audio.size == 0:
        return audio
    duration = audio.shape[0] / float(orig_sr)
    target_len = max(1, int(round(duration * target_sr)))
    src_x = np.linspace(0.0, duration, num=audio.shape[0], endpoint=False, dtype=np.float64)
    dst_x = np.linspace(0.0, duration, num=target_len, endpoint=False, dtype=np.float64)
    return np.interp(dst_x, src_x, audio).astype(np.float32, copy=False)


def prepare_audio_chunk(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    mono = to_mono_float32(audio)
    if sample_rate != TARGET_SAMPLE_RATE:
        mono = resample_linear(mono, orig_sr=sample_rate, target_sr=TARGET_SAMPLE_RATE)
    return mono


def is_speech(audio_chunk: np.ndarray) -> bool:
    try:
        if audio_chunk is None:
            raise VADModuleError("[vad.is_speech] audio_chunk is None.")
        if not isinstance(audio_chunk, np.ndarray):
            chunk = np.asarray(audio_chunk, dtype=np.float32)
        else:
            chunk = audio_chunk
            if chunk.dtype != np.float32:
                chunk = chunk.astype(np.float32, copy=False)
        if chunk.ndim != 1:
            raise VADModuleError(f"Expected 1D mono, got shape {chunk.shape}.")
        if chunk.size == 0:
            return False
        if not chunk.flags["C_CONTIGUOUS"]:
            chunk = np.ascontiguousarray(chunk, dtype=np.float32)

        model = _load_model_once()
        chunk_tensor = torch.from_numpy(chunk)
        speech_prob_tensor = model(chunk_tensor.unsqueeze(0), TARGET_SAMPLE_RATE)
        speech_prob = float(speech_prob_tensor.detach().cpu().numpy().flatten()[0])
        return speech_prob >= _THRESHOLD

    except VADModuleError:
        raise
    except Exception as exc:
        raise VADModuleError(f"[vad.is_speech] Inference failed: {exc}.") from exc
