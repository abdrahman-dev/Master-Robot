from __future__ import annotations

import logging
from collections import deque
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from config.settings import get_settings

logger = logging.getLogger(__name__)

_FEATURE_PARAMS = dict(
    maxCorners=100,
    qualityLevel=0.3,
    minDistance=7,
    blockSize=7,
)

_LK_PARAMS = dict(
    winSize=(15, 15),
    maxLevel=2,
    criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 10, 0.03),
)


class ObstacleDetector:
    def __init__(
        self,
        enabled: bool = False,
        flow_scale_threshold: float = 3.0,
        min_features: int = 10,
        history_frames: int = 5,
    ):
        self._enabled = enabled
        self._flow_scale_threshold = flow_scale_threshold
        self._min_features = min_features
        self._history_frames = history_frames

        self._prev_gray: Optional[np.ndarray] = None
        self._prev_points: Optional[np.ndarray] = None
        self._frame_counter = 0
        self._direction_history: deque[str] = deque(maxlen=history_frames)
        self._last_result = self._empty_result()

        logger.info("[OBSTACLE] ObstacleDetector ready (Lucas-Kanade)")

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        was = self._enabled
        self._enabled = bool(value)
        if self._enabled and not was:
            self._reset_state()
        logger.info(f"[OBSTACLE] {'Enabled' if self._enabled else 'Disabled'}")

    def process_frame(self, frame: np.ndarray) -> dict:
        if not self._enabled:
            return self._empty_result()

        if frame is None or frame.ndim != 3:
            return self._empty_result()

        self._frame_counter += 1
        return self._detect(frame)

    def close(self):
        self._reset_state()
        logger.info("[OBSTACLE] Closed.")

    def release(self):
        self.close()

    def _reset_state(self):
        self._prev_gray = None
        self._prev_points = None
        self._frame_counter = 0
        self._direction_history.clear()
        self._last_result = self._empty_result()

    def _detect(self, frame: np.ndarray) -> dict:
        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            if self._prev_gray is None:
                self._prev_gray = gray
                self._prev_points = cv2.goodFeaturesToTrack(
                    gray, mask=None, **_FEATURE_PARAMS
                )
                return self._empty_result()

            if self._prev_points is None or len(self._prev_points) < self._min_features:
                self._prev_points = cv2.goodFeaturesToTrack(
                    gray, mask=None, **_FEATURE_PARAMS
                )
                self._prev_gray = gray
                return self._empty_result()

            next_points, status, _ = cv2.calcOpticalFlowPyrLK(
                self._prev_gray, gray, self._prev_points, None, **_LK_PARAMS
            )

            if next_points is None:
                self._prev_points = cv2.goodFeaturesToTrack(
                    gray, mask=None, **_FEATURE_PARAMS
                )
                self._prev_gray = gray
                return self._last_result

            good_prev = self._prev_points[status == 1]
            good_next = next_points[status == 1]

            if len(good_prev) < self._min_features:
                self._prev_points = cv2.goodFeaturesToTrack(
                    gray, mask=None, **_FEATURE_PARAMS
                )
                self._prev_gray = gray
                return self._last_result

            h, w = frame.shape[:2]
            center_x = w // 2

            flow_vectors = good_next - good_prev
            magnitudes = np.linalg.norm(flow_vectors, axis=1)
            directions = np.arctan2(flow_vectors[:, 1], flow_vectors[:, 0])

            if len(good_prev) >= 3:
                mean_pt = np.mean(good_next, axis=0)
                vec_from_center = good_next - mean_pt
                dot_products = np.sum(flow_vectors * vec_from_center, axis=1)
                divergence = np.mean(dot_products) / (np.mean(magnitudes) + 1e-6)
            else:
                divergence = 0.0

            expansion_ratio = max(0, divergence / (self._flow_scale_threshold + 1e-6))
            obstacle_approaching = expansion_ratio > 0.5

            left_count = int(np.sum(good_next[:, 0] < center_x))
            right_count = int(np.sum(good_next[:, 0] >= center_x))
            total = left_count + right_count

            if not obstacle_approaching or total == 0:
                direction = "clear"
                confidence = 0.0
            else:
                left_ratio = left_count / total
                right_ratio = right_count / total
                avg_mag = float(np.mean(magnitudes))

                if avg_mag < 1.0:
                    direction = "clear"
                    confidence = 0.0
                elif obstacle_approaching and expansion_ratio > 1.5:
                    direction = "stop"
                    confidence = min(expansion_ratio / 3.0, 1.0)
                elif right_ratio > 0.65:
                    direction = "left"
                    confidence = min(right_ratio * expansion_ratio, 1.0)
                elif left_ratio > 0.65:
                    direction = "right"
                    confidence = min(left_ratio * expansion_ratio, 1.0)
                else:
                    direction = "clear"
                    confidence = 0.0

            self._direction_history.append(direction)
            smoothed_direction = self._smooth_direction()

            result = {
                "obstacle_detected": smoothed_direction != "clear",
                "direction": smoothed_direction,
                "confidence": round(confidence, 3),
            }
            self._last_result = result

            self._prev_gray = gray
            self._prev_points = good_next.reshape(-1, 1, 2)

            return result

        except Exception as e:
            logger.error(f"[OBSTACLE] Detection error: {e}")
            return self._empty_result()

    def _smooth_direction(self) -> str:
        if not self._direction_history:
            return "clear"
        priority = {"stop": 4, "left": 3, "right": 2, "clear": 1}
        ranked = sorted(
            set(self._direction_history),
            key=lambda d: priority.get(d, 0) * self._direction_history.count(d),
            reverse=True,
        )
        return ranked[0] if ranked else "clear"

    @staticmethod
    def _empty_result() -> dict:
        return {
            "obstacle_detected": False,
            "direction": "clear",
            "confidence": 0.0,
        }
