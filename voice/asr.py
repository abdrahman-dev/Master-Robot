import logging
from typing import Optional, Tuple

import speech_recognition as sr

from config.settings import get_settings

logger = logging.getLogger(__name__)

_SETTINGS = get_settings()
_ASR = _SETTINGS.asr

TARGET_SAMPLE_RATE = _ASR.sample_rate
SUPPORTED_LANGUAGES = _ASR.supported_languages


class ASRModuleError(RuntimeError):
    pass


def transcribe(
    audio_bytes: bytes,
    samplerate: int = TARGET_SAMPLE_RATE,
    language: str = _ASR.language_mode,
) -> Tuple[Optional[str], Optional[str]]:
    if audio_bytes is None or len(audio_bytes) == 0:
        raise ASRModuleError(
            "[asr.transcribe] No audio data provided."
        )

    if _ASR.provider != "google":
        raise ASRModuleError(
            f"[asr.transcribe] Unsupported ASR provider '{_ASR.provider}'. "
            "Only 'google' is supported."
        )

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
            logger.info(f"[ASR] Attempting recognition with {lang} ({lang_code})...")
            text = recognizer.recognize_google(audio_data, language=lang_code)
            logger.info(f"[ASR] Success: recognized {lang}")
            return text, lang

        except sr.UnknownValueError:
            logger.debug(f"[ASR] No speech detected in {lang}")
            continue

        except sr.RequestError as e:
            raise ASRModuleError(
                "[asr.transcribe] Google Speech API request failed. "
                f"Reason: {e}. Check internet connection and API quota."
            ) from e

        except Exception as e:
            raise ASRModuleError(
                f"[asr.transcribe] Unexpected error: {e}."
            ) from e

    logger.warning("[ASR] Speech not detected in any language")
    return None, None
