import logging
import threading
import time
from typing import Optional, Tuple

import speech_recognition as sr

from config.settings import get_settings

logger = logging.getLogger(__name__)

_SETTINGS = get_settings()
_ASR = _SETTINGS.asr

TARGET_SAMPLE_RATE = _ASR.sample_rate
SUPPORTED_LANGUAGES = _ASR.supported_languages

# Whisper model cache (lazy-loaded)
_whisper_model = None
_whisper_model_lock = threading.Lock()


class ASRModuleError(RuntimeError):
    pass


def preload():
    """Preload the ASR model synchronously to eliminate first-utterance latency.
    
    Call once during pipeline startup, before any audio is processed.
    This is a no-op if the model is already loaded.
    """
    logger.info("[ASR] Preloading model...")
    _get_whisper_model()


def _get_whisper_model():
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model
    with _whisper_model_lock:
        if _whisper_model is None:
            model_size = _ASR.whisper_model_size
            logger.info("[ASR] Loading Whisper model: %s", model_size)
            try:
                from faster_whisper import WhisperModel
            except ImportError:
                raise ASRModuleError(
                    "[asr] faster-whisper not installed. Run: pip install faster-whisper"
                )
            from config.settings import IS_RASPBERRY_PI
            _whisper_model = WhisperModel(
                model_size,
                device="cpu",
                compute_type="int8",
                cpu_threads=1 if IS_RASPBERRY_PI else 2,
                num_workers=1,
            )
            logger.info("[ASR] Whisper model loaded")
    return _whisper_model


def _transcribe_whisper(
    audio_bytes: bytes,
    samplerate: int,
    language: str = "ar",
) -> Tuple[Optional[str], Optional[str]]:
    import numpy as np

    model = _get_whisper_model()

    # Convert int16 bytes to float32 array
    audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0

    # Safety normalization — boost if the segment is too quiet (e.g. low-gain Pi mic)
    peak = np.max(np.abs(audio_np))
    if peak > 0 and peak < 0.3:
        audio_np = audio_np * (0.3 / peak)
        audio_np = np.clip(audio_np, -1.0, 1.0)

    whisper_lang = None if language == "auto" else language

    segments, info = model.transcribe(
        audio_np,
        language=whisper_lang,
        beam_size=5,
        vad_filter=False,
    )

    text = " ".join(seg.text for seg in segments).strip()
    detected_lang = info.language if info.language else (language if language != "auto" else "ar")

    if not text:
        return None, None

    logger.info("[ASR] Whisper result: %r lang=%s prob=%.2f", text[:80], detected_lang, info.language_probability)
    return text, detected_lang


def _transcribe_google(
    audio_bytes: bytes,
    samplerate: int,
    language: str,
) -> Tuple[Optional[str], Optional[str]]:
    audio_data = sr.AudioData(audio_bytes, samplerate, sample_width=2)
    recognizer = sr.Recognizer()

    if language == "auto":
        langs_to_try = ["ar", "en"]
    elif language in SUPPORTED_LANGUAGES:
        langs_to_try = [language]
    else:
        raise ASRModuleError(
            f"[asr.transcribe] Unsupported language '{language}'. "
            f"Use one of {list(SUPPORTED_LANGUAGES.keys())} or 'auto'."
        )

    for lang in langs_to_try:
        try:
            lang_code = SUPPORTED_LANGUAGES[lang]
            logger.info("[ASR] Attempting recognition with %s (%s)...", lang, lang_code)
            text = recognizer.recognize_google(audio_data, language=lang_code)
            logger.info("[ASR] Success: recognized %s", lang)
            return text, lang

        except sr.UnknownValueError:
            logger.debug("[ASR] No speech detected in %s", lang)
            continue

        except sr.RequestError as e:
            logger.warning("[ASR] Google request failed: %s. Retrying once in 2s...", e)
            time.sleep(2)
            try:
                text = recognizer.recognize_google(audio_data, language=lang_code)
                logger.info("[ASR] Success (retry): recognized %s", lang)
                return text, lang
            except sr.RequestError:
                logger.error("[ASR] Retry also failed")
                continue
            except sr.UnknownValueError:
                continue

        except Exception as e:
            raise ASRModuleError(
                f"[asr.transcribe] Unexpected error: {e}."
            ) from e

    logger.warning("[ASR] Speech not detected in any language")
    return None, None


def transcribe(
    audio_bytes: bytes,
    samplerate: int = TARGET_SAMPLE_RATE,
    language: str = _ASR.language_mode,
) -> Tuple[Optional[str], Optional[str]]:
    if audio_bytes is None or len(audio_bytes) == 0:
        raise ASRModuleError(
            "[asr.transcribe] No audio data provided."
        )

    if _ASR.provider == "whisper":
        return _transcribe_whisper(audio_bytes, samplerate, language)
    elif _ASR.provider == "google":
        return _transcribe_google(audio_bytes, samplerate, language)
    else:
        raise ASRModuleError(
            f"[asr.transcribe] Unsupported ASR provider '{_ASR.provider}'. "
            "Use 'google' or 'whisper'."
        )
