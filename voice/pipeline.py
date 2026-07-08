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
from voice.audio_preprocessor import AudioPreprocessor, SegmentEnhancer, resample_chunk
from voice.tts import TTSModule
from llm.module import LLMModule, LLMModuleError

FILLER_PHRASES = {
    "ar": [
        "لحظة بفكر...",
        "سؤال حلو، خليني أفكر...",
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

FALLBACK_MESSAGES = {
    "ar": [
        "عذرًا، لا أستطيع الاتصال بالخادم في الوقت الحالي.",
        "يرجى المحاولة مرة أخرى بعد قليل.",
        "أعتذر، يوجد خلل مؤقت في الاتصال.",
    ],
    "en": [
        "Sorry, I'm unable to connect right now.",
        "Please try again in a moment.",
        "I'm having trouble reaching the server.",
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
    mobile_source: bool = False


class VoicePipeline:
    def __init__(
        self,
        llm: LLMModule,
        tts_module: TTSModule,
        session_id: str,
        face_set_state: Optional[Callable] = None,
        motor_controller=None,
        vision_context_getter=None,
        academic_context=None,
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
        self._academic_context = academic_context

        self._latest_turn_id = 0
        self._turn_lock = threading.Lock()

        self._running = False
        self._segment_queue: queue.Queue = queue.Queue(maxsize=8)
        self._worker_thread: Optional[threading.Thread] = None
        self._stream_thread: Optional[threading.Thread] = None

        self._dropped_segments = 0
        self._total_segments = 0

        self._segment_enhancer = SegmentEnhancer(self._sample_rate, _SETTINGS.audio)

        self._watchdog_ping: Optional[Callable] = None
        self._ping_counter = 0
        self._diag_count = 0
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
        pass

    def _enqueue_segment(self, segment: Segment) -> None:
        self._total_segments += 1
        try:
            self._segment_queue.put(segment, timeout=0.5)
        except queue.Full:
            self._dropped_segments += 1
            logger.warning("[queue] Full after 0.5s timeout, dropping segment (dropped=%d)", self._dropped_segments)

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
        if segment.turn_id < self._get_latest_turn_id() - 1:
            logger.debug("[worker] Stale turn %d (latest=%d), skipping", segment.turn_id, self._get_latest_turn_id())
            return

        if segment.mobile_source:
            self._wake_word_active = True

        try:
            logger.info("[ASR] Transcribing speech segment...")
            audio_bytes = b"".join(segment.audio_chunks)

            audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            self._segment_enhancer.reset()
            audio_np = self._segment_enhancer.process(audio_np)
            audio_np = np.clip(audio_np, -1.0, 1.0)
            audio_bytes = (audio_np * 32767.0).astype(np.int16).tobytes()

            logger.info(
                "[diag] segment_len=%.2fs agc_gain=%.2f peak_db=%.1f",
                len(audio_np) / self._sample_rate,
                self._segment_enhancer.last_agc_gain,
                self._segment_enhancer.last_peak_db,
            )

            t0 = time.monotonic()
            text, detected_lang = asr.transcribe(
                audio_bytes,
                samplerate=self._sample_rate,
                language="ar",  # Fixed to Arabic — change to _SETTINGS.asr.language_mode for auto-detect
            )
            asr_time = time.monotonic() - t0
            logger.info("[ASR] result=%r lang=%r time=%.2fs", text, detected_lang, asr_time)

            if not text:
                if self._face_set_state:
                    self._face_set_state("LISTENING" if self._wake_word_active else "IDLE")
                return

            if segment.turn_id < self._get_latest_turn_id() - 1:
                if self._face_set_state:
                    self._face_set_state("LISTENING" if self._wake_word_active else "IDLE")
                return

            if self._tts.is_playing():
                if _is_wake_word(text):
                    logger.info("[voice] Wake word during TTS, interrupting")
                    self._tts.stop_playback()
                else:
                    logger.info("[voice] Non-wake-word during TTS, ignoring")
                    return

            if _is_wake_word(text):
                logger.info("[voice] Wake word detected")
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
                logger.info("[voice] Motor command: %s(%s)", method_name, duration_ms)

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

            academic_ctx = None
            if self._academic_context and self._academic_context.is_active():
                academic_ctx = self._academic_context.get_formatted(detected_lang)

            t0 = time.monotonic()
            try:
                response = self._llm.chat(
                    self._session_id, text,
                    vision_context=vision_context,
                    academic_context=academic_ctx,
                )
            except LLMModuleError:
                logger.warning("[LLM] OpenRouter unavailable, using fallback")
                lang = detected_lang if detected_lang in ("ar", "en") else "en"
                response = random.choice(FALLBACK_MESSAGES[lang])
            llm_time = time.monotonic() - t0
            logger.info("[LLM] response_time=%.2fs", llm_time)

            if segment.turn_id < self._get_latest_turn_id() - 1:
                if self._face_set_state:
                    self._face_set_state("LISTENING" if self._wake_word_active else "IDLE")
                return

            if detected_lang:
                logger.info("[TTS] Starting playback (lang=%s)", detected_lang)
                self._tts.stop()
                self._tts.speak(response, language=detected_lang)
            else:
                logger.warning("[TTS] No detected language, skipping playback")
                if self._face_set_state:
                    self._face_set_state("IDLE")

            self._wake_word_active = False

        except (asr.ASRModuleError, tts.TTSModuleError) as exc:
            logger.exception("[worker] Processing failed: %s", exc)
            if self._face_set_state:
                self._face_set_state("IDLE")
        except Exception as exc:
            logger.exception("[worker] Unexpected error: %s", exc)
            if self._face_set_state:
                self._face_set_state("IDLE")

    def enqueue_mobile_audio(self, audio: np.ndarray, sample_rate: int) -> dict:
        """Preprocess mobile audio and enqueue for the worker thread.

        Runs lightweight preprocessing (resample, DC removal, HPF, VAD)
        synchronously in the caller's thread, then enqueues a ``Segment``
        for the existing worker thread to handle the rest (SegmentEnhancer,
        ASR, wake word, LLM, TTS) — exactly the same path as USB mic audio.

        Returns ``{"success": True}`` on enqueue or
        ``{"success": False, "reason": "no_speech"}`` if VAD rejects.
        """
        try:
            # 1. Resample to pipeline rate
            if sample_rate != self._sample_rate:
                audio = resample_chunk(audio, sample_rate, self._sample_rate)

            # 2. AudioPreprocessor (DC removal, HPF, noise floor, diagnostics)
            preprocessor = AudioPreprocessor(self._sample_rate, _SETTINGS.audio)
            cal_samples = min(int(self._sample_rate * 0.5), len(audio))
            if cal_samples > 0:
                preprocessor.feed_calibration(audio[:cal_samples])
            preprocessor.finalize_calibration()
            audio = preprocessor.process(audio)

            # 3. VAD — reject silence early
            if not vad.is_speech(audio):
                logger.info("[voice] Mobile audio rejected by VAD")
                return {"success": False, "reason": "no_speech"}

            # 4. Convert to int16 bytes and enqueue
            chunk_bytes = float32_chunk_to_int16_bytes(audio)
            turn_id = self._next_turn_id()
            segment = Segment(
                turn_id=turn_id,
                audio_chunks=[chunk_bytes],
                mobile_source=True,
            )
            self._enqueue_segment(segment)
            logger.info("[voice] Mobile audio enqueued (turn=%d, len=%.2fs)",
                        turn_id, len(audio) / max(self._sample_rate, 1))
            return {"success": True}

        except Exception as exc:
            logger.exception("[voice] Enqueue mobile audio failed: %s", exc)
            return {"success": False, "reason": "internal_error"}

    def run_forever(self) -> None:
        # Ensure logging is visible when running standalone (not via main.py)
        root = logging.getLogger()
        if not root.hasHandlers():
            handler = logging.StreamHandler()
            handler.setLevel(logging.INFO)
            handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
            root.addHandler(handler)
            root.setLevel(logging.INFO)

        if not _SETTINGS.general.mic_enabled:
            logger.info("[voice] Microphone disabled via ROBOT_MIC_ENABLED=false")
            return
        if not self._mic_available:
            logger.warning("[voice] Microphone unavailable, audio pipeline disabled")
            return

        try:
            import sounddevice as sd
        except Exception as exc:
            logger.error("[voice] sounddevice import failed: %s", exc)
            self._mic_available = False
            return

        from voice import audio_device as ad

        device_index = ad.get_sounddevice_index()
        if device_index is None:
            logger.warning("[voice] No audio device found, disabling microphone")
            self._mic_available = False
            return

        device_sample_rate = self._sample_rate
        try:
            device_sample_rate = ad.get_device_sample_rate(device_index) or self._sample_rate
            logger.info(
                "[voice] Device %d samplerate: %d Hz (target: %d Hz)",
                device_index, device_sample_rate, self._sample_rate,
            )
        except Exception as exc:
            logger.warning("[voice] Could not query device samplerate: %s, using %d Hz", exc, self._sample_rate)

        needs_resample = device_sample_rate != self._sample_rate
        device_chunk_size = int(device_sample_rate * _SETTINGS.vad.chunk_duration_ms / 1000)
        if device_chunk_size <= 0:
            device_chunk_size = 1024

        self._resample_parts: List[np.ndarray] = []
        self._resample_total = 0

        if needs_resample:
            import math
            gcd = math.gcd(device_sample_rate, self._sample_rate)
            up, down = self._sample_rate // gcd, device_sample_rate // gcd
            logger.info(
                "[voice] Resampling: %d Hz -> %d Hz (ratio=%d/%d)",
                device_sample_rate, self._sample_rate, up, down,
            )

        preprocessor = AudioPreprocessor(self._sample_rate, _SETTINGS.audio)
        calibrating = True
        calibration_start = time.monotonic()

        pre_buffer: Deque[bytes] = deque(maxlen=self._pre_chunks)
        segment_chunks: Optional[Deque[bytes]] = None
        silence_chunks = 0
        speech_chunks = 0
        current_turn_id: Optional[int] = None

        def callback(indata, frames, time_info, status) -> None:
            try:
                nonlocal segment_chunks, silence_chunks, speech_chunks, current_turn_id, pre_buffer
                nonlocal calibrating, calibration_start
                if not self._running:
                    return
                if status:
                    logger.debug("[voice] Audio stream status: %s", status)
                if indata is None or len(indata) == 0:
                    return

                self._ping_counter += 1
                if self._ping_counter % 50 == 0 and self._watchdog_ping:
                    self._watchdog_ping()

                raw_chunk = np.asarray(indata[:, 0], dtype=np.float32)
                if needs_resample:
                    raw_chunk = resample_chunk(raw_chunk, device_sample_rate, self._sample_rate)

                self._resample_parts.append(raw_chunk)
                self._resample_total += len(raw_chunk)

                while self._resample_total >= self._chunk_size:
                    if len(self._resample_parts) == 1:
                        big = self._resample_parts[0]
                    else:
                        big = np.concatenate(self._resample_parts, dtype=np.float32)
                    chunk_16k = big[:self._chunk_size]
                    leftover = big[self._chunk_size:]
                    self._resample_parts = [leftover] if len(leftover) > 0 else []
                    self._resample_total = len(leftover)

                    if calibrating:
                        preprocessor.feed_calibration(chunk_16k)
                        elapsed = time.monotonic() - calibration_start
                        if elapsed >= preprocessor.calibration_seconds:
                            preprocessor.finalize_calibration()
                            calibrating = False
                            logger.info(
                                "[voice] Calibration done: noise_floor=%.5f",
                                preprocessor.noise_floor,
                            )
                        continue

                    chunk_16k = preprocessor.process(chunk_16k)

                    if self._diag_count < 5 or self._ping_counter % 100 == 0:
                        self._diag_count += 1
                        logger.info(
                            "[diag] noise_floor=%.5f rms=%.5f snr=%.1fdB gate=%.5f",
                            preprocessor.last_noise_floor,
                            preprocessor.last_rms,
                            preprocessor.last_snr_estimate,
                            max(preprocessor.noise_floor * _SETTINGS.audio.noise_gate_floor_multiplier,
                                _SETTINGS.audio.noise_gate_floor_min),
                        )

                    chunk_bytes = float32_chunk_to_int16_bytes(chunk_16k)

                    rms = preprocessor.last_rms
                    gate_threshold = max(
                        preprocessor.noise_floor * _SETTINGS.audio.noise_gate_floor_multiplier,
                        _SETTINGS.audio.noise_gate_floor_min,
                    )
                    if segment_chunks is None and rms < gate_threshold:
                        pre_buffer.append(chunk_bytes)
                        continue

                    speech_now = vad.is_speech(chunk_16k)

                    if segment_chunks is None:
                        if speech_now:
                            current_turn_id = self._next_turn_id()
                            if self._face_set_state and not self._tts.is_playing():
                                self._face_set_state("LISTENING")
                            logger.info("[VAD] Speech detected (turn=%s)", current_turn_id)
                            segment_chunks = deque(pre_buffer)
                            segment_chunks.append(chunk_bytes)
                            speech_chunks = 1
                            silence_chunks = 0
                            pre_buffer.clear()
                        else:
                            pre_buffer.append(chunk_bytes)
                        continue

                    assert current_turn_id is not None
                    segment_chunks.append(chunk_bytes)
                    speech_chunks += 1
                    if speech_now:
                        silence_chunks = 0
                    else:
                        silence_chunks += 1
                    adaptive_silence = self._silence_timeout_chunks
                    if speech_chunks >= self._min_speech_chunks * 4:
                        extra = speech_chunks // 4
                        adaptive_silence = max(self._silence_timeout_chunks, extra)
                        adaptive_silence = min(adaptive_silence, 75)
                    if (silence_chunks >= adaptive_silence
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
            except Exception as e:
                logger.error("[voice] Audio callback error: %s", e, exc_info=True)

        if self._face_set_state:
            self._face_set_state("IDLE")
        logger.info("[voice] Listening...")

        sd.stop()
        time.sleep(0.2)

        try:
            with sd.InputStream(
                device=device_index,
                samplerate=device_sample_rate if needs_resample else self._sample_rate,
                channels=1,
                dtype="float32",
                blocksize=device_chunk_size,
                callback=callback,
            ):
                while self._running:
                    time.sleep(0.5)
        except sd.PortAudioError as e:
            logger.warning("[voice] No microphone available: %s", e)
            self._mic_available = False
        except Exception as e:
            logger.exception("[voice] Stream error: %s", e)
        finally:
            self._resample_parts = []
            self._resample_total = 0
            preprocessor.reset()

        logger.info("[voice] Audio stream closed")

    def start(self) -> None:
        # Preload ASR + VAD models before starting audio, eliminating first-utterance latency
        asr.preload()
        vad.warmup()
        self._running = True
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=False)
        self._worker_thread.start()
        self._stream_thread = threading.Thread(target=self.run_forever, daemon=False)
        self._stream_thread.start()
        logger.info("[voice] Started")

    def stop(self) -> None:
        logger.info("[voice] Stopping...")
        self._running = False
        if self._stream_thread:
            self._stream_thread.join(timeout=3)
            self._stream_thread = None
        if self._worker_thread:
            self._worker_thread.join(timeout=5)
            self._worker_thread = None
        logger.info("[voice] Stopped (total=%d, dropped=%d)",
                     self._total_segments, self._dropped_segments)

    def process_text(self, text: str, language: str = "ar") -> None:
        logger.info("[dev] Text input: %s", text)

        if self._face_set_state:
            self._face_set_state("THINKING")

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

        academic_ctx = None
        if self._academic_context and self._academic_context.is_active():
            academic_ctx = self._academic_context.get_formatted(language)

        try:
            response = self._llm.chat(
                self._session_id, text,
                vision_context=vision_context,
                academic_context=academic_ctx,
            )
        except LLMModuleError:
            logger.warning("[LLM] OpenRouter unavailable, using fallback")
            lang = language if language in ("ar", "en") else "en"
            response = random.choice(FALLBACK_MESSAGES[lang])

        self._tts.stop()
        self._tts.speak_and_wait(response, language=language)

        if self._face_set_state:
            self._face_set_state("IDLE")
