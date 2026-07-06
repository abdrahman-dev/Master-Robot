from __future__ import annotations

import logging
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)


class AcademicContext:
    """Thread-safe holder for the current academic lesson context excerpt.
    Stores only the active lesson title and content excerpt — no full PDF,
    no RAG, no persistence. Set by the mobile app via /ask or /context,
    cleared on lesson end. Used to inject context into voice follow-up
    questions without requiring the mobile app to re-send on every utterance."""

    def __init__(self):
        self._title: str = ""
        self._content: str = ""
        self._lock = threading.Lock()
        self._last_activity: float = 0.0
        self._timeout_seconds: float = 600.0  # 10 minutes default

    def set(self, title: str, content: str) -> None:
        with self._lock:
            self._title = title
            self._content = content
            self._last_activity = time.monotonic()
        logger.info("[academic] Context set: title=%r content_len=%d", title, len(content))

    def clear(self) -> None:
        with self._lock:
            self._title = ""
            self._content = ""
        logger.info("[academic] Context cleared")

    def touch(self) -> None:
        """Reset idle timer without changing content."""
        with self._lock:
            self._last_activity = time.monotonic()

    def is_expired(self) -> bool:
        with self._lock:
            if not self._title or not self._content:
                return False
            if self._last_activity == 0.0:
                return False
            return time.monotonic() - self._last_activity > self._timeout_seconds

    def set_timeout(self, seconds: float) -> None:
        with self._lock:
            self._timeout_seconds = seconds
        logger.info("[academic] Timeout set to %.0f minutes", seconds / 60)

    def is_active(self) -> bool:
        with self._lock:
            if not self._title or not self._content:
                return False
            if self._last_activity > 0 and time.monotonic() - self._last_activity > self._timeout_seconds:
                self._title = ""
                self._content = ""
                self._last_activity = 0.0
                logger.info("[academic] Context expired after %.0f minutes of inactivity",
                            self._timeout_seconds / 60)
                return False
            return True

    def get_title(self) -> Optional[str]:
        with self._lock:
            return self._title if self._title else None

    def get_content(self) -> Optional[str]:
        with self._lock:
            return self._content if self._content else None

    def get_formatted(self, language: str = "en") -> Optional[str]:
        with self._lock:
            if not self._title or not self._content:
                return None
            title = self._title
            content = self._content
            self._last_activity = time.monotonic()

        if language == "ar":
            return f"الدرس الحالي: {title}\n\nالمحتوى:\n{content}\n\nأجب عن أسئلة الطالب بناءً على هذا المحتوى فقط. لا تخترع معلومات من خارج هذا النص."
        return f"Current lesson: {title}\n\nContent:\n{content}\n\nAnswer the student's questions based only on this content. Do not make up information outside of this text."
