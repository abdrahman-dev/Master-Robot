import cv2
import logging
import numpy as np
from collections import deque
from typing import Optional, List, Tuple
from pathlib import Path

from config.settings import get_settings

logger = logging.getLogger(__name__)


GESTURE_TO_COMMAND = {
    "open_palm": "stop",
    "pointing_up": "continue",
    "none": "none",
}


class GestureDetector:
    def __init__(
        self,
        min_detection_confidence: float = None,
        min_tracking_confidence: float = None,
        max_hands: int = None,
        buffer_size: int = None,
        stability_frames: int = None,
    ):
        settings = get_settings()
        gesture_settings = settings.gesture

        self._buffer = deque(maxlen=buffer_size if buffer_size is not None else gesture_settings.buffer_size)
        self._stability_frames = stability_frames if stability_frames is not None else gesture_settings.stability_frames
        self._stable_gesture = "none"

        self._skin_hsv_lower = np.array(gesture_settings.skin_hsv_lower, dtype=np.uint8)
        self._skin_hsv_upper = np.array(gesture_settings.skin_hsv_upper, dtype=np.uint8)
        self._skin_ycrcb_lower = np.array(gesture_settings.skin_ycrcb_lower, dtype=np.uint8)
        self._skin_ycrcb_upper = np.array(gesture_settings.skin_ycrcb_upper, dtype=np.uint8)
        self._finger_depth_threshold = gesture_settings.finger_depth_threshold
        self._finger_angle_threshold = gesture_settings.finger_angle_threshold
        self._pointing_aspect_ratio = gesture_settings.pointing_aspect_ratio
        self._pointing_top_ratio = gesture_settings.pointing_top_ratio
        self._contour_min_ratio = gesture_settings.contour_min_ratio
        self._contour_max_ratio = gesture_settings.contour_max_ratio

        logger.info("GestureDetector (OpenCV) ready - no model files needed.")

    def process_frame(self, frame: np.ndarray) -> dict:
        if frame is None or frame.ndim != 3:
            return self._result("none", False, None)

        raw_gesture, hand_found, landmarks = self._detect(frame)

        self._buffer.append(raw_gesture)
        self._update_stable()

        return self._result(self._stable_gesture, hand_found, landmarks)

    def release(self):
        logger.info("GestureDetector released.")

    def close(self):
        self.release()

    def _detect(self, frame: np.ndarray) -> Tuple[str, bool, Optional[List]]:
        mask = self._skin_mask(frame)

        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=3)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return "none", False, None

        hand_contour = max(contours, key=cv2.contourArea)

        frame_area = frame.shape[0] * frame.shape[1]
        contour_area = cv2.contourArea(hand_contour)
        if not (frame_area * self._contour_min_ratio < contour_area < frame_area * self._contour_max_ratio):
            return "none", False, None

        fingers = self._count_fingers(hand_contour)

        hull = cv2.convexHull(hand_contour)
        h, w = frame.shape[:2]
        landmarks = [(float(p[0][0]) / w, float(p[0][1]) / h) for p in hull]

        if fingers >= 4:
            return "open_palm", True, landmarks
        if fingers == 1:
            return self._verify_pointing_up(hand_contour, frame.shape), True, landmarks

        return "none", True, landmarks

    def _skin_mask(self, frame: np.ndarray) -> np.ndarray:
        try:
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            ycrcb = cv2.cvtColor(frame, cv2.COLOR_BGR2YCrCb)
        except cv2.error as e:
            logger.error(f"[GESTURE] Color conversion failed: {e}")
            return np.zeros(frame.shape[:2], dtype=np.uint8)

        mask_hsv = cv2.inRange(hsv, self._skin_hsv_lower, self._skin_hsv_upper)
        mask_ycr = cv2.inRange(ycrcb, self._skin_ycrcb_lower, self._skin_ycrcb_upper)

        return cv2.bitwise_and(mask_hsv, mask_ycr)

    def _count_fingers(self, contour: np.ndarray) -> int:
        hull_indices = cv2.convexHull(contour, returnPoints=False)

        if hull_indices is None or len(hull_indices) < 3:
            return 0

        try:
            defects = cv2.convexityDefects(contour, hull_indices)
        except cv2.error:
            return 0

        if defects is None:
            return 0

        finger_count = 0
        for i in range(defects.shape[0]):
            s, e, f, d = defects[i, 0]
            depth = d / 256.0

            if depth < self._finger_depth_threshold:
                continue

            start = contour[s][0]
            end = contour[e][0]
            far = contour[f][0]

            a = np.linalg.norm(end - far)
            b = np.linalg.norm(start - far)
            c = np.linalg.norm(start - end)

            if a == 0 or b == 0:
                continue

            cos_angle = (a**2 + b**2 - c**2) / (2 * a * b)
            cos_angle = np.clip(cos_angle, -1.0, 1.0)
            angle = np.degrees(np.arccos(cos_angle))

            if angle < self._finger_angle_threshold:
                finger_count += 1

        return min(finger_count + 1, 5)

    def _verify_pointing_up(self, contour: np.ndarray, shape: tuple) -> str:
        x, y, w, h = cv2.boundingRect(contour)
        aspect = h / (w + 1e-6)

        if aspect < self._pointing_aspect_ratio:
            return "none"

        top_point = contour[contour[:, :, 1].argmin()][0]
        rel_y = (top_point[1] - y) / (h + 1e-6)
        if rel_y > self._pointing_top_ratio:
            return "none"

        return "pointing_up"

    def _update_stable(self):
        for candidate in ("open_palm", "pointing_up", "none"):
            if self._buffer.count(candidate) >= self._stability_frames:
                self._stable_gesture = candidate
                return

    def _result(self, gesture, hand_found, landmarks) -> dict:
        return {
            "gesture": gesture,
            "hand_found": hand_found,
            "landmarks": landmarks,
            "command": GESTURE_TO_COMMAND.get(gesture, "none"),
        }
