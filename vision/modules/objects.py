from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np

from config.settings import IS_RASPBERRY_PI

logger = logging.getLogger(__name__)

_MODEL_PATH = Path(__file__).parent.parent.parent / "models" / "yolov8s.pt"


class ObjectRecognitionModule:
    def __init__(
        self,
        confidence_threshold: float = 0.5,
        frame_skip: int = 6,
    ):
        self._conf_threshold = confidence_threshold
        self._frame_skip = frame_skip
        self._frame_counter = 0
        self._enabled = False
        self._model = None
        self._model_loaded = False
        logger.info("[OBJECT] ObjectRecognitionModule initialized (lazy load)")

    def _ensure_model(self):
        if self._model_loaded:
            return
        try:
            from ultralytics import YOLO

            path = str(_MODEL_PATH)
            logger.info("[OBJECT] Loading YOLO model from %s ...", path)
            self._model = YOLO(path)
            self._model_loaded = True
            logger.info("[OBJECT] YOLO model loaded")
        except Exception as e:
            logger.error(f"[OBJECT] Failed to load YOLO model: {e}")
            self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled and self._model_loaded

    @enabled.setter
    def enabled(self, value: bool):
        self._enabled = bool(value)
        self._frame_counter = 0
        if self._enabled and not self._model_loaded:
            logger.info("[OBJECT] Enabled - model will load on first inference")

    def process_frame(self, frame: np.ndarray) -> dict:
        if not self._enabled:
            return self._empty_result()
        if frame is None or frame.ndim != 3:
            return self._empty_result()
        if not self._model_loaded:
            self._ensure_model()
            if not self._model_loaded:
                return self._empty_result()
        self._frame_counter += 1
        if self._frame_counter % self._frame_skip != 0:
            return self._last_result if hasattr(self, '_last_result') else self._empty_result()
        return self._detect(frame)

    def _detect(self, frame: np.ndarray) -> dict:
        try:
            predict_kwargs = {"verbose": False, "conf": self._conf_threshold}
            if IS_RASPBERRY_PI:
                predict_kwargs["device"] = "cpu"
                predict_kwargs["half"] = False
            results = self._model(frame, **predict_kwargs)
            objects = []
            if results and len(results) > 0:
                boxes = results[0].boxes
                if boxes is not None and len(boxes) > 0:
                    for box in boxes:
                        x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                        label = results[0].names[int(box.cls[0])]
                        conf = float(box.conf[0])
                        objects.append({"label": label, "confidence": round(conf, 3), "bbox": [x1, y1, x2, y2]})
            count = len(objects)
            prompt = self._build_prompt(objects, count)
            result = {"objects": objects, "count": count, "prompt": prompt}
            self._last_result = result
            return result
        except Exception as e:
            logger.error(f"[OBJECT] Detection error: {e}")
            return self._empty_result()

    def close(self):
        self._model = None
        self._model_loaded = False
        logger.info("[OBJECT] Closed.")

    def release(self):
        self.close()

    @staticmethod
    def _build_prompt(objects: list, count: int) -> str:
        if count == 0:
            return ""
        labels = [o["label"] for o in objects]
        if count == 1:
            return f"a {labels[0]}"
        if count == 2:
            return f"a {labels[0]} and a {labels[1]}"
        *rest, last = labels
        return f"{', '.join(rest)}, and a {last}"

    @staticmethod
    def _empty_result() -> dict:
        return {"objects": [], "count": 0, "prompt": ""}
