from __future__ import annotations

import logging
import math
from typing import Optional

import numpy as np

logger = logging.getLogger("audio_preprocessor")


class _Biquad:
    """Direct Form II Transposed biquad filter."""

    __slots__ = ("_b0", "_b1", "_b2", "_a1", "_a2", "_x1", "_x2", "_y1", "_y2")

    def __init__(self, b0: float, b1: float, b2: float, a1: float, a2: float):
        self._b0 = b0
        self._b1 = b1
        self._b2 = b2
        self._a1 = a1
        self._a2 = a2
        self.reset()

    def reset(self):
        self._x1 = self._x2 = self._y1 = self._y2 = 0.0

    def process(self, x: np.ndarray) -> np.ndarray:
        y = np.empty_like(x)
        for n in range(len(x)):
            y_n = (
                self._b0 * x[n]
                + self._b1 * self._x1
                + self._b2 * self._x2
                - self._a1 * self._y1
                - self._a2 * self._y2
            )
            self._x2 = self._x1
            self._x1 = x[n]
            self._y2 = self._y1
            self._y1 = y_n
            y[n] = y_n
        return y


def _hpf_coeffs(sample_rate: int, cutoff_hz: float):
    """Compute 2nd-order Butterworth HPF biquad coefficients."""
    if sample_rate == 16000 and abs(cutoff_hz - 80.0) < 1.0:
        return {"b0": 0.97547654, "b1": -1.95095308, "b2": 0.97547654,
                "a1": -1.95095308, "a2": 0.95095308}
    try:
        from scipy.signal import butter
        b, a = butter(2, cutoff_hz / (sample_rate / 2), btype="high")
        return {"b0": b[0], "b1": b[1], "b2": b[2], "a1": a[1], "a2": a[2]}
    except ImportError:
        raise RuntimeError(
            f"scipy required for HPF coefficients at {sample_rate}Hz/{cutoff_hz}Hz"
        )


class AudioPreprocessor:
    """Lightweight per-chunk DSP for the audio callback.

    Stages:
      1. DC offset removal (single-pole HPF, ~3 Hz)
      2. High-pass filter (biquad, 80 Hz)
      3. Noise floor estimation (leaky integrator)
      4. Diagnostics capture (RMS, SNR estimate)

    Heavier stages (noise suppression, AGC, limiter, pre-emphasis)
    run in `SegmentEnhancer` on the worker thread.
    """

    def __init__(self, sample_rate: int, settings=None):
        self._sample_rate = sample_rate

        s = settings
        self._enable_dc_removal = getattr(s, "enable_dc_removal", True) if s else True
        self._enable_hpf = getattr(s, "enable_hpf", True) if s else True
        self._calibration_sec = getattr(s, "calibration_duration_sec", 2.0) if s else 2.0

        self._dc_R = 0.999
        self._dc_x1 = 0.0
        self._dc_y1 = 0.0

        self._hpf = (
            _Biquad(*_hpf_coeffs(sample_rate, 80.0).values())
            if self._enable_hpf
            else None
        )

        self._noise_floor = 0.0

        self._calibrated = False
        self._calibration_samples = 0
        self._calibration_rms_sum = 0.0

        self.last_noise_floor = 0.0
        self.last_rms = 0.0
        self.last_snr_estimate = 0.0

    def reset(self):
        self._dc_x1 = 0.0
        self._dc_y1 = 0.0
        if self._hpf:
            self._hpf.reset()
        self._noise_floor = 0.0
        self._calibrated = False
        self._calibration_samples = 0
        self._calibration_rms_sum = 0.0

    @property
    def noise_floor(self) -> float:
        return self._noise_floor

    @property
    def is_calibrated(self) -> bool:
        return self._calibrated

    @property
    def calibration_seconds(self) -> float:
        return self._calibration_sec

    def feed_calibration(self, chunk: np.ndarray) -> None:
        chunk = self._remove_dc(chunk) if self._enable_dc_removal else chunk.copy()
        chunk = self._hpf.process(chunk) if self._hpf else chunk
        rms = float(np.sqrt(np.mean(chunk ** 2)))
        self._calibration_rms_sum += rms
        self._calibration_samples += 1

    def finalize_calibration(self) -> float:
        if self._calibration_samples > 0:
            self._noise_floor = self._calibration_rms_sum / self._calibration_samples
        else:
            self._noise_floor = 0.001
        self._calibrated = True
        logger.info(
            "[audio] Calibration done: noise_floor=%.5f (samples=%d)",
            self._noise_floor, self._calibration_samples,
        )
        return self._noise_floor

    def process(self, chunk: np.ndarray) -> np.ndarray:
        if self._enable_dc_removal:
            chunk = self._remove_dc(chunk)
        if self._hpf:
            chunk = self._hpf.process(chunk)

        self._update_noise_floor(chunk)
        self._capture_diagnostics(chunk)
        return chunk

    def _remove_dc(self, x: np.ndarray) -> np.ndarray:
        R = self._dc_R
        y = np.empty_like(x)
        for n in range(len(x)):
            y[n] = x[n] - (self._dc_x1 if n == 0 else x[n - 1]) + R * (self._dc_y1 if n == 0 else y[n - 1])
        self._dc_x1 = x[-1]
        self._dc_y1 = y[-1]
        return y

    def _update_noise_floor(self, chunk: np.ndarray) -> None:
        rms = float(np.sqrt(np.mean(chunk ** 2)))
        if self._noise_floor > 0:
            self._noise_floor = 0.999 * self._noise_floor + 0.001 * max(rms, 1e-8)

    def _capture_diagnostics(self, chunk: np.ndarray) -> None:
        self.last_rms = float(np.sqrt(np.mean(chunk ** 2)))
        self.last_noise_floor = self._noise_floor
        nf = max(self._noise_floor, 1e-10)
        self.last_snr_estimate = 20.0 * math.log10(self.last_rms / nf)


# ── Noise suppression backends ─────────────────────────────────────────

class _NSBackend:
    def process(self, chunk: np.ndarray) -> np.ndarray:
        raise NotImplementedError
    def process_segment(self, audio: np.ndarray) -> np.ndarray:
        raise NotImplementedError


class _NullNSBackend(_NSBackend):
    def process(self, chunk):
        return chunk
    def process_segment(self, audio):
        return audio


class _RNNoiseBackend(_NSBackend):
    """RNNoise — 480-sample frames (30ms at 16kHz)."""

    FRAME_SIZE = 480

    def __init__(self):
        import rnnoise
        self._model = rnnoise.RNNoise()

    def process(self, chunk: np.ndarray) -> np.ndarray:
        return self.process_segment(chunk)

    def process_segment(self, audio: np.ndarray) -> np.ndarray:
        frames = len(audio) // self.FRAME_SIZE
        if frames == 0:
            return audio
        trimmed = audio[:frames * self.FRAME_SIZE]
        out = np.empty(frames * self.FRAME_SIZE, dtype=np.float32)
        for i in range(frames):
            start = i * self.FRAME_SIZE
            out[start:start + self.FRAME_SIZE] = self._model.process_frame(
                trimmed[start:start + self.FRAME_SIZE]
            )
        return out


class _WebRTCBackend(_NSBackend):
    """WebRTC Noise Suppression — 160-sample frames (10ms at 16kHz)."""

    FRAME_SIZE = 160

    def __init__(self, sample_rate: int, aggressiveness: int = 2):
        from webrtc_noise import NoiseSuppression
        self._ns = NoiseSuppression(sample_rate=sample_rate, aggressiveness=aggressiveness)

    def process(self, chunk: np.ndarray) -> np.ndarray:
        return self.process_segment(chunk)

    def process_segment(self, audio: np.ndarray) -> np.ndarray:
        frames = len(audio) // self.FRAME_SIZE
        if frames == 0:
            return audio
        trimmed = audio[:frames * self.FRAME_SIZE]
        int16_max = np.iinfo(np.int16).max
        out = np.empty(frames * self.FRAME_SIZE, dtype=np.float32)
        for i in range(frames):
            start = i * self.FRAME_SIZE
            frame_i16 = (trimmed[start:start + self.FRAME_SIZE] * int16_max).astype(np.int16)
            processed_i16 = self._ns.process_frame(frame_i16)
            out[start:start + self.FRAME_SIZE] = processed_i16.astype(np.float32) / int16_max
        return out


def _create_ns_backend(sample_rate: int, aggressiveness: int = 2) -> _NSBackend:
    try:
        backend = _RNNoiseBackend()
        logger.info("[audio] NS backend: RNNoise")
        return backend
    except ImportError:
        logger.debug("[audio] RNNoise unavailable, trying WebRTC NS")

    try:
        backend = _WebRTCBackend(sample_rate, aggressiveness)
        logger.info("[audio] NS backend: WebRTC NS")
        return backend
    except ImportError:
        logger.debug("[audio] WebRTC NS unavailable")

    logger.warning("[audio] No NS backend — install rnnoise or webrtc-noise")
    return _NullNSBackend()


# ── Resampling ─────────────────────────────────────────────────────────

def resample_chunk(chunk: np.ndarray, orig_rate: int, target_rate: int) -> np.ndarray:
    if orig_rate == target_rate:
        return chunk
    duration = chunk.shape[0] / float(orig_rate)
    target_len = max(1, int(round(duration * target_rate)))
    try:
        from scipy.signal import resample_poly
        gcd = math.gcd(orig_rate, target_rate)
        up = target_rate // gcd
        down = orig_rate // gcd
        return resample_poly(chunk, up, down).astype(np.float32, copy=False)
    except ImportError:
        src_x = np.linspace(0.0, duration, num=chunk.shape[0], endpoint=False, dtype=np.float64)
        dst_x = np.linspace(0.0, duration, num=target_len, endpoint=False, dtype=np.float64)
        return np.interp(dst_x, src_x, chunk).astype(np.float32, copy=False)


# ── Segment enhancer (worker thread) ───────────────────────────────────

class SegmentEnhancer:
    """Per-segment audio enhancement on the worker thread (after VAD).

    Stages:
      1. Pre-emphasis (optional, disabled by default — user preference)
      2. Noise suppression (RNNoise → WebRTC → none)
      3. AGC (dual-timeframe envelope follower)
      4. Soft-knee peak limiter
    """

    def __init__(self, sample_rate: int, settings=None):
        self._sample_rate = sample_rate

        s = settings
        self._enable_pre_emphasis = s.enable_pre_emphasis if s else False
        self._enable_noise_suppression = s.enable_noise_suppression if s else True
        self._enable_agc = s.enable_agc if s else True
        self._enable_limiter = s.enable_limiter if s else True

        self._pre_emphasis_coeff = s.pre_emphasis_coeff if s else 0.97
        ns_aggr = s.noise_suppression_aggressiveness if s else 2

        self._agc_target_rms = s.agc_target_rms if s else 0.15
        self._agc_attack_rate = s.agc_attack_rate if s else 0.2
        self._agc_release_rate = s.agc_release_rate if s else 0.01
        self._agc_max_gain = s.agc_max_gain if s else 10.0
        lim_db = s.limiter_threshold_db if s else -1.0
        self._limiter_threshold = 10.0 ** (lim_db / 20.0)

        self._ns_backend = (
            _create_ns_backend(sample_rate, ns_aggr)
            if self._enable_noise_suppression
            else _NullNSBackend()
        )

        self._pe_x1 = 0.0
        self._agc_envelope = 1e-4
        self._agc_smoothed_gain = 1.0

        self.last_agc_gain = 1.0
        self.last_peak_db = 0.0

    def reset(self):
        self._pe_x1 = 0.0
        self._agc_envelope = 1e-4
        self._agc_smoothed_gain = 1.0

    def process(self, audio_np: np.ndarray) -> np.ndarray:
        x = audio_np

        if self._enable_pre_emphasis:
            x = self._apply_pre_emphasis(x)

        if self._enable_noise_suppression:
            x = self._ns_backend.process_segment(x)
            if len(x) == 0:
                return audio_np

        if self._enable_agc:
            x = self._apply_agc(x)

        if self._enable_limiter:
            x = self._apply_limiter(x)

        return x

    def _apply_pre_emphasis(self, x: np.ndarray) -> np.ndarray:
        out = np.empty_like(x)
        for n in range(len(x)):
            out[n] = x[n] - self._pre_emphasis_coeff * (self._pe_x1 if n == 0 else x[n - 1])
        self._pe_x1 = x[-1]
        return out

    def _apply_agc(self, x: np.ndarray) -> np.ndarray:
        current_rms = float(np.sqrt(np.mean(x ** 2)))
        if current_rms > self._agc_envelope:
            self._agc_envelope += self._agc_attack_rate * (current_rms - self._agc_envelope)
        else:
            self._agc_envelope += self._agc_release_rate * (current_rms - self._agc_envelope)

        desired = self._agc_target_rms / max(self._agc_envelope, 1e-8)
        self._agc_smoothed_gain += 0.1 * (desired - self._agc_smoothed_gain)
        gain = min(self._agc_smoothed_gain, self._agc_max_gain)
        self.last_agc_gain = gain
        return x * gain

    def _apply_limiter(self, x: np.ndarray) -> np.ndarray:
        knee = 10.0 ** (-3.0 / 20.0)
        peak = float(np.max(np.abs(x)))
        self.last_peak_db = 20.0 * math.log10(max(peak, 1e-10))
        if peak > knee:
            x = x * (1.0 / (1.0 + ((peak - knee) / (self._limiter_threshold - knee)) ** 2))
        return np.clip(x, -1.0, 1.0)
