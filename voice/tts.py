from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from pathlib import Path
from typing import Optional

from config.settings import get_settings

logger = logging.getLogger(__name__)

_SETTINGS = get_settings()


class TTSModuleError(RuntimeError):
    pass


def detect_language(text: str) -> str:
    for char in text:
        if "\u0600" <= char <= "\u06FF":
            return "ar"
    return "en"


_voice_map = {
    "ar": _SETTINGS.tts.ar_voice,
    "en": _SETTINGS.tts.en_voice,
}


class TTSModule:
    def __init__(self, settings):
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._request_id = 0
        self._is_playing = False

        self._on_playback_start: Optional[callable] = None
        self._on_playback_finish: Optional[callable] = None

        self._pygame = None
        self._pygame_ready = False
        self._init_pygame()

    def _init_pygame(self):
        try:
            import pygame
            self._pygame = pygame
            pygame.mixer.init()
            self._pygame_ready = True
        except Exception as e:
            logger.warning("[TTS] pygame mixer init failed: %s", e)

    def set_callbacks(
        self,
        on_start: Optional[callable] = None,
        on_finish: Optional[callable] = None,
    ) -> None:
        self._on_playback_start = on_start
        self._on_playback_finish = on_finish

    def is_playing(self) -> bool:
        if not self._pygame_ready:
            return False
        try:
            return bool(self._pygame.mixer.music.get_busy())
        except Exception:
            return False

    def stop(self) -> None:
        logger.info("[TTS] Stop requested")
        with self._lock:
            self._stop_event.set()
            self._request_id += 1
            self._is_playing = False
        try:
            if self._pygame_ready:
                self._pygame.mixer.music.stop()
                self._pygame.mixer.music.unload()
        except Exception:
            pass

    def _temp_path(self, request_id: int) -> str:
        temp_dir = _SETTINGS.paths.tts_temp_dir
        temp_dir = Path(temp_dir)
        temp_dir.mkdir(parents=True, exist_ok=True)
        return str(temp_dir / f"tts_{request_id}.mp3")

    async def _generate(self, text: str, voice: str, path: str) -> None:
        import edge_tts
        try:
            communicate = edge_tts.Communicate(text=text, voice=voice)
            await communicate.save(path)
        except edge_tts.exceptions.NoAudioReceived as e:
            logger.error("[TTS] No audio for voice '%s': %s", voice, e)
            raise TTSModuleError(f"No audio received for voice {voice}") from e

    def _play(self, path: str, request_id: int) -> None:
        try:
            if self._stop_event.is_set():
                return

            self._pygame.mixer.music.load(path)
            self._pygame.mixer.music.play()

            while self._pygame.mixer.music.get_busy():
                if self._stop_event.is_set():
                    return
                time.sleep(0.05)

        except Exception as e:
            logger.error("[TTS] Playback error: %s", e, exc_info=True)
        finally:
            try:
                self._pygame.mixer.music.unload()
            except Exception:
                pass
            self._delete_file(path)

    @staticmethod
    def _delete_file(path: str):
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

    def speak(self, text: str, language: Optional[str] = None) -> None:
        if not text or not text.strip():
            raise TTSModuleError("[tts] Text is empty.")

        if language is None:
            language = detect_language(text)

        voice = _voice_map.get(language, _voice_map["en"])

        with self._lock:
            self._stop_event.clear()
            self._request_id += 1
            request_id = self._request_id

        path = self._temp_path(request_id)

        def worker() -> None:
            try:
                if self._stop_event.is_set():
                    return

                asyncio.run(self._generate(text, voice, path))

                with self._lock:
                    if request_id != self._request_id or self._stop_event.is_set():
                        self._delete_file(path)
                        return

                with self._lock:
                    if request_id != self._request_id or self._stop_event.is_set():
                        self._delete_file(path)
                        return
                    self._is_playing = True

                if self._on_playback_start:
                    self._on_playback_start()

                logger.info("[TTS] Starting playback: %s", path)
                self._play(path, request_id)
                logger.info("[TTS] Playback finished")

            except Exception as exc:
                logger.error("[TTS] worker error: %s", exc, exc_info=True)
            finally:
                if self._on_playback_finish:
                    self._on_playback_finish()
                with self._lock:
                    self._is_playing = False

        threading.Thread(target=worker, daemon=True).start()

    def speak_and_wait(self, text: str, language: Optional[str] = None) -> None:
        self.speak(text, language=language)
        for _ in range(100):
            if self.is_playing():
                break
            time.sleep(0.05)
        while self.is_playing():
            time.sleep(0.05)
