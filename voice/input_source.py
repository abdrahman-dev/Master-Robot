from __future__ import annotations

import logging
from typing import Callable, Optional

import numpy as np

logger = logging.getLogger(__name__)


class VoiceInputSource:
    """Abstract audio source for the voice pipeline.

    Subclasses deliver mono float32 audio at the pipeline's configured sample rate.
    """

    def start(self, chunk_callback: Callable[[np.ndarray], None],
              sample_rate: int, chunk_size: int) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError


class LocalMicrophoneInput(VoiceInputSource):
    """Wraps the existing sounddevice-based microphone input.

    Currently a placeholder — the pipeline's ``run_forever()`` uses sounddevice
    directly.  This class documents the interface that production code should
    migrate toward.
    """

    def start(self, chunk_callback: Callable[[np.ndarray], None],
              sample_rate: int, chunk_size: int) -> None:
        logger.debug("[source] LocalMicrophoneInput.start() — not yet wired")

    def stop(self) -> None:
        logger.debug("[source] LocalMicrophoneInput.stop() — not yet wired")


class MobileMicrophoneInput(VoiceInputSource):
    """Receives audio from the mobile application.

    The ``/voice`` endpoint decodes the upload, resamples to the pipeline's
    sample rate, then calls ``feed_audio()``.  Audio is passed directly to
    ``VoicePipeline.feed_external_audio()`` for synchronous processing.
    """

    def __init__(self) -> None:
        self._pipeline = None
        self._running = False

    def attach_pipeline(self, pipeline) -> None:
        self._pipeline = pipeline

    def start(self, chunk_callback: Callable[[np.ndarray], None],
              sample_rate: int, chunk_size: int) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False

    def feed_audio(self, audio: np.ndarray, sample_rate: int) -> dict:
        if self._pipeline is None:
            return {"success": False, "reason": "pipeline_not_attached"}
        return self._pipeline.enqueue_mobile_audio(audio, sample_rate)
