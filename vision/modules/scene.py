from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np

from config.settings import IS_RASPBERRY_PI

logger = logging.getLogger(__name__)

_MODEL_PATH = Path(__file__).parent.parent.parent / "models" / "yolov8s-seg.pt"

_SCENE_TEMPLATES: dict[str, list[str]] = {
    "classroom": ["classroom", "educational setting", "learning space"],
    "desk": ["desk or table", "study area"],
    "book": ["books present", "reading materials"],
    "laptop": ["laptop or computer", "digital setup"],
    "chair": ["seating area", "chair visible"],
    "person": ["student visible", "person present"],
    "cell phone": ["mobile device", "phone present"],
    "bottle": ["drink bottle", "hydration available"],
    "default": ["learning environment", "indoor space"],
}


class SceneSegmentationModule:
    def __init__(
        self,
        confidence_threshold: float = 0.5,
        frame_skip: int = 10,
    ):
        self._conf_threshold = confidence_threshold
        self._frame_skip = frame_skip
        self._frame_counter = 0
        self._enabled = False
        self._model = None
        self._model_loaded = False
        logger.info("[SCENE] SceneSegmentationModule initialized (lazy load)")

    def _ensure_model(self):
        if self._model_loaded:
            return
        try:
            from ultralytics import YOLO
            path = str(_MODEL_PATH)
            logger.info("[SCENE] Loading YOLO model from %s ...", path)
            self._model = YOLO(path)
            self._model_loaded = True
            logger.info("[SCENE] YOLO model loaded")
        except Exception as e:
            logger.error(f"[SCENE] Failed to load YOLO model: {e}")
            self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled and self._model_loaded

    @enabled.setter
    def enabled(self, value: bool):
        self._enabled = bool(value)
        self._frame_counter = 0
        if self._enabled and not self._model_loaded:
            logger.info("[SCENE] Enabled - model will load on first inference")

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
        return self._segment(frame)

    def _segment(self, frame: np.ndarray) -> dict:
        try:
            predict_kwargs = {"verbose": False, "conf": self._conf_threshold}
            if IS_RASPBERRY_PI:
                predict_kwargs["device"] = "cpu"
                predict_kwargs["half"] = False
            results = self._model(frame, **predict_kwargs)
            frame_area = frame.shape[0] * frame.shape[1]
            segments = []
            if results and len(results) > 0:
                boxes = results[0].boxes
                if boxes is not None and len(boxes) > 0:
                    for box in boxes:
                        x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                        label = results[0].names[int(box.cls[0])]
                        conf = float(box.conf[0])
                        area = (x2 - x1) * (y2 - y1)
                        segments.append({
                            "label": label, "confidence": round(conf, 3),
                            "area_ratio": round(area / frame_area, 4),
                        })
            segments.sort(key=lambda s: s["area_ratio"], reverse=True)
            dominant = segments[0]["label"] if segments else ""
            description = self._build_scene_description(segments, dominant)
            result = {"segments": segments, "scene_description": description, "dominant_segment": dominant}
            self._last_result = result
            return result
        except Exception as e:
            logger.error(f"[SCENE] Segmentation error: {e}")
            return self._empty_result()

    def close(self):
        self._model = None
        self._model_loaded = False
        logger.info("[SCENE] Closed.")

    def release(self):
        self.close()

    @staticmethod
    def _build_scene_description(segments: list, dominant: str) -> str:
        if not segments:
            return ""
        label = dominant.lower()
        templates = _SCENE_TEMPLATES.get(label, _SCENE_TEMPLATES["default"])
        seen = list(dict.fromkeys(s["label"] for s in segments))
        if len(seen) <= 2:
            items = " and ".join(seen)
        else:
            *rest, last = seen
            items = ", ".join(rest) + f", and {last}"
        return f"{templates[0]}: {items}"

    @staticmethod
    def _empty_result() -> dict:
        return {"segments": [], "scene_description": "", "dominant_segment": ""}
