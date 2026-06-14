from __future__ import annotations

import logging
import queue
import random
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, List, Optional, Callable

import numpy as np
from rapidfuzz import fuzz

from config.settings import get_settings
from voice import asr, tts, vad
from voice.tts import TTSModule
from llm.module import LLMModule, LLMModuleError

FILLER_PHRASES = {
    "ar": [
        "لحظة بفكر...",
        "سؤال حلو، خليني أفكر...",
        "ثواني كدا اظبطها في دماغي و اقولك...",
        "تمام، بفكر معاك...",
        "اكيد, بفكر شويه...",
        "ثواني بفكر في الموضوع...",
        "حلو، خليني أفكر شويه...",
        "ثواني بفكر في جواب مناسب...",
        "خليني اشوف كدا..."
    ],
    "en": [
        "Let me think...",
        "Good question, one moment...",
        "Hmm, let me see...",
        "Sure, thinking...",
    ],
}

WAKE_WORDS = ["يا روبو", "روبو", "ropo", "hey robo", "ok robo"]

MOVE_COMMANDS = {
    "تعالي":    ("forward",     2000),
    "اقترب":    ("forward",     2000),
    "ارجع":     ("backward",    2000),
    "يمين":     ("turn_right",  1000),
    "شمال":     ("turn_left",   1000),
    "وقف":      ("stop",        0),
    "استنى":    ("stop",        0),
    "دور":      ("turn_right",  3000),
    "come here":("forward",     2000),
    "go back":  ("backward",    2000),
    "stop":     ("stop",        0),
    "turn right":("turn_right", 1000),
    "turn left": ("turn_left",  1000),
}

_SETTINGS = get_settings()

logger = logging.getLogger("voice_pipeline")


def _is_wake_word(text: str) -> bool:
    if not text:
        return False
    text_lower = text.lower().strip()
    for w in WAKE_WORDS:
        if fuzz.partial_ratio(w, text_lower) >= 70:
            return True
    return False


def _extract_move_command(text: str):
    if not text:
        return None
    text_lower = text.lower()
    for keyword, action in MOVE_COMMANDS.items():
        if keyword in text_lower:
            return action
    return None


def float32_chunk_to_int16_bytes(chunk: np.ndarray) -> bytes:
    chunk_clipped = np.clip(chunk, -1.0, 1.0)
    chunk_i16 = (chunk_clipped * 32767.0).astype(np.int16, copy=False)
    return chunk_i16.tobytes()


@dataclass
class Segment:
    turn_id: int
    audio_chunks: List[bytes]


class VoicePipeline:
    def __init__(
        self,
        llm: LLMModule,
        tts_module: TTSModule,
        session_id: str,
        face_set_state: Optional[Callable] = None,
        motor_controller=None,
        vision_context_getter=None,
    ):
        self._mic_available = True

        if _SETTINGS.vad.sample_rate != _SETTINGS.asr.sample_rate:
            raise RuntimeError(
                "VAD sample_rate and ASR sample_rate must match. "
                f"Got vad={_SETTINGS.vad.sample_rate}, asr={_SETTINGS.asr.sample_rate}."
            )

        self._sample_rate = _SETTINGS.vad.sample_rate
        self._chunk_size = int(self._sample_rate * _SETTINGS.vad.chunk_duration_ms / 1000)
        self._chunk_seconds = self._chunk_size / float(self._sample_rate)

        if self._chunk_size <= 0:
            raise RuntimeError("Invalid VAD chunk size computed.")

        self._pre_chunks = max(1, int(_SETTINGS.vad.pre_speech_buffer_seconds / self._chunk_seconds))
        self._min_speech_chunks = max(1, int(_SETTINGS.vad.min_speech_seconds / self._chunk_seconds))
        self._silence_timeout_chunks = max(1, int(_SETTINGS.vad.silence_timeout_seconds / self._chunk_seconds))

        logger.info(
            "Config: sample_rate=%s chunk_size=%s pre_chunks=%s "
            "min_speech_chunks=%s silence_timeout_chunks=%s",
            self._sample_rate, self._chunk_size, self._pre_chunks,
            self._min_speech_chunks, self._silence_timeout_chunks,
        )

        vad.set_threshold(_SETTINGS.vad.initial_threshold)

        self._tts = tts_module
        self._face_set_state = face_set_state

        if self._face_set_state:
            self._tts.set_callbacks(
                on_start=lambda: self._face_set_state("SPEAKING"),
                on_finish=lambda: self._face_set_state("IDLE"),
            )

        self._llm = llm
        self._session_id = session_id
        self._motor = motor_controller
        self._vision_context_getter = vision_context_getter

        self._latest_turn_id = 0
        self._turn_lock = threading.Lock()

        self._running = False
        self._segment_queue: queue.Queue = queue.Queue(maxsize=3)
        self._worker_thread: Optional[threading.Thread] = None
        self._stream_thread: Optional[threading.Thread] = None

        self._dropped_segments = 0
        self._total_segments = 0

        self._watchdog_ping: Optional[Callable] = None
        self._ping_counter = 0
        self._wake_word_active = False
        self._wake_word_count = 0

    def set_watchdog_ping(self, fn: Callable) -> None:
        self._watchdog_ping = fn

    def _next_turn_id(self) -> int:
        with self._turn_lock:
            self._latest_turn_id += 1
            return self._latest_turn_id

    def _get_latest_turn_id(self) -> int:
        with self._turn_lock:
            return self._latest_turn_id

    def _maybe_stop_tts_on_interrupt(self) -> None:
        if self._tts.is_playing():
            logger.info("[interrupt] Stopping TTS playback")
            self._tts.stop()

    def _enqueue_segment(self, segment: Segment) -> None:
        self._total_segments += 1
        try:
            self._segment_queue.put(segment, block=False)
        except queue.Full:
            self._dropped_segments += 1
            logger.warning("[queue] Full, dropping oldest (dropped=%d)", self._dropped_segments)
            try:
                self._segment_queue.get_nowait()
                self._segment_queue.put(segment, block=False)
            except queue.Empty:
                pass

    def _worker_loop(self) -> None:
        logger.info("[worker] Segment processing worker started")
        while self._running:
            try:
                segment = self._segment_queue.get(timeout=0.5)
                if self._watchdog_ping:
                    self._watchdog_ping()
                self._process_segment(segment)
            except queue.Empty:
                continue
            except Exception as e:
                logger.error("[worker] Unexpected error: %s", e, exc_info=True)
        logger.info("[worker] Segment processing worker stopped")

    def _process_segment(self, segment: Segment) -> None:
        if segment.turn_id != self._get_latest_turn_id():
            logger.debug("[segment] Stale turn %d, skipping", segment.turn_id)
            return

        try:
            logger.info("[ASR] Transcribing speech segment...")
            audio_bytes = b"".join(segment.audio_chunks)
            t0 = time.monotonic()
            text, detected_lang = asr.transcribe(
                audio_bytes,
                samplerate=self._sample_rate,
                language=_SETTINGS.asr.language_mode,
            )
            asr_time = time.monotonic() - t0
            logger.info("[ASR] result=%r lang=%r time=%.2fs", text, detected_lang, asr_time)

            if not text:
                if self._face_set_state:
                    self._face_set_state("IDLE")
                return

            if segment.turn_id != self._get_latest_turn_id():
                if self._face_set_state:
                    self._face_set_state("IDLE")
                return

            if _is_wake_word(text):
                logger.info("[pipeline] Wake word detected")
                if self._face_set_state:
                    self._face_set_state("LISTENING")
                self._wake_word_active = True
                if self._wake_word_count == 0:
                    greeting = "أنا روبو، مساعدك الذكي! كيف أقدر أساعدك؟"
                else:
                    greeting = "نعم"
                self._wake_word_count += 1
                self._tts.speak(greeting, "ar")
                return

            if not self._wake_word_active:
                if self._face_set_state:
                    self._face_set_state("IDLE")
                return

            cmd = _extract_move_command(text)
            if cmd is not None and self._motor is not None and self._motor.is_available():
                method_name, duration_ms = cmd
                getattr(self._motor, method_name)(duration_ms)
                logger.info("[pipeline] Motor command: %s(%s)", method_name, duration_ms)

            if self._face_set_state:
                self._face_set_state("THINKING")

            filler = random.choice(FILLER_PHRASES.get(detected_lang, FILLER_PHRASES["ar"]))
            self._tts.speak(filler, detected_lang)

            vision_context = None
            if self._vision_context_getter:
                ctx = self._vision_context_getter()
                faces = ctx.get("faces", [])
                objects = ctx.get("objects", {}).get("objects", [])
                obstacle = ctx.get("obstacle", {}).get("obstacle_detected", False)
                gesture = ctx.get("gesture", {}).get("gesture", "none")
                emotion = ctx.get("emotion", {}).get("emotion", "neutral")
                has_real_data = (
                    len(faces) > 0 or
                    len(objects) > 0 or
                    obstacle or
                    gesture not in ("none", "", "unknown") or
                    emotion not in ("neutral", "", "none")
                )
                if has_real_data:
                    vision_context = ctx

            t0 = time.monotonic()
            try:
                response = self._llm.chat(self._session_id, text, vision_context=vision_context)
            except LLMModuleError:
                logger.warning("[LLM] OpenRouter unavailable, using fallback")
                response = "I am having trouble connecting right now. Please try again."
            llm_time = time.monotonic() - t0
            logger.info("[LLM] response_time=%.2fs", llm_time)

            if segment.turn_id != self._get_latest_turn_id():
                if self._face_set_state:
                    self._face_set_state("IDLE")
                return

            if detected_lang:
                logger.info("[TTS] Starting playback (lang=%s)", detected_lang)
                t0 = time.monotonic()
                self._tts.stop()
                self._tts.speak_and_wait(response, language=detected_lang)
                tts_time = time.monotonic() - t0
                logger.info("[TTS] playback_time=%.2fs", tts_time)
            else:
                logger.warning("[TTS] No detected language, skipping playback")
                if self._face_set_state:
                    self._face_set_state("IDLE")

            self._wake_word_active = False

        except (asr.ASRModuleError, tts.TTSModuleError) as exc:
            logger.error("[segment] Processing failed: %s", exc, exc_info=True)
            if self._face_set_state:
                self._face_set_state("IDLE")
        except Exception as exc:
            logger.error("[segment] Unexpected error: %s", exc, exc_info=True)
            if self._face_set_state:
                self._face_set_state("IDLE")

    def run_forever(self) -> None:
        if not self._mic_available:
            logger.warning("[pipeline] Microphone unavailable, audio pipeline disabled")
            return

        try:
            import sounddevice as sd
        except Exception as exc:
            logger.error("[pipeline] sounddevice import failed: %s", exc)
            self._mic_available = False
            return

        pre_buffer: Deque[bytes] = deque(maxlen=self._pre_chunks)
        segment_chunks: Optional[Deque[bytes]] = None
        silence_chunks = 0
        speech_chunks = 0
        current_turn_id: Optional[int] = None

        def callback(indata, frames, time_info, status) -> None:
            nonlocal segment_chunks, silence_chunks, speech_chunks, current_turn_id, pre_buffer
            if not self._running:
                return
            if status:
                logger.debug("[stream] Audio status: %s", status)
            if indata is None or len(indata) == 0:
                return

            self._ping_counter += 1
            if self._ping_counter % 50 == 0 and self._watchdog_ping:
                self._watchdog_ping()

            chunk = np.asarray(indata[:, 0], dtype=np.float32)
            speech_now = vad.is_speech(chunk)
            chunk_bytes = float32_chunk_to_int16_bytes(chunk)

            if segment_chunks is None:
                if speech_now:
                    current_turn_id = self._next_turn_id()
                    self._maybe_stop_tts_on_interrupt()
                    if self._face_set_state:
                        self._face_set_state("LISTENING")
                    logger.info("[VAD] Speech detected (turn=%s)", current_turn_id)
                    segment_chunks = deque(pre_buffer)
                    segment_chunks.append(chunk_bytes)
                    speech_chunks = 1
                    silence_chunks = 0
                    pre_buffer.clear()
                else:
                    pre_buffer.append(chunk_bytes)
                return

            assert current_turn_id is not None
            segment_chunks.append(chunk_bytes)
            speech_chunks += 1
            if speech_now:
                silence_chunks = 0
            else:
                silence_chunks += 1
            if (silence_chunks >= self._silence_timeout_chunks
                    and speech_chunks >= self._min_speech_chunks):
                audio_chunks = list(segment_chunks)
                finished_turn_id = current_turn_id
                segment_chunks = None
                silence_chunks = 0
                speech_chunks = 0
                current_turn_id = None
                logger.info("[VAD] Segment ended (turn=%s, chunks=%d)",
                             finished_turn_id, len(audio_chunks))
                self._enqueue_segment(Segment(turn_id=finished_turn_id, audio_chunks=audio_chunks))

        if self._face_set_state:
            self._face_set_state("IDLE")
        logger.info("[pipeline] Listening...")

        try:
            with sd.InputStream(
                samplerate=self._sample_rate,
                channels=1,
                dtype="float32",
                blocksize=self._chunk_size,
                callback=callback,
            ):
                while self._running:
                    time.sleep(0.5)
        except sd.PortAudioError as e:
            logger.warning("[pipeline] No microphone available: %s", e)
            self._mic_available = False
        except Exception as e:
            logger.error("[pipeline] Stream error: %s", e, exc_info=True)

        logger.info("[pipeline] Audio stream closed")

    def start(self) -> None:
        self._running = True
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=False)
        self._worker_thread.start()
        self._stream_thread = threading.Thread(target=self.run_forever, daemon=False)
        self._stream_thread.start()
        logger.info("[pipeline] Started")

    def stop(self) -> None:
        logger.info("[pipeline] Stopping...")
        self._running = False
        if self._stream_thread:
            self._stream_thread.join(timeout=3)
            self._stream_thread = None
        if self._worker_thread:
            self._worker_thread.join(timeout=5)
            self._worker_thread = None
        logger.info("[pipeline] Stopped (total=%d, dropped=%d)",
                     self._total_segments, self._dropped_segments)
