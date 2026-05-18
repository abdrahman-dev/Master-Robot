from __future__ import annotations

import logging
import sys
from collections import deque
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from config.settings import get_settings

logger = logging.getLogger(__name__)

_EMOTION_LABELS = ["angry", "disgust", "fear", "happy", "sad", "surprise", "neutral"]

_MODEL_PATH = Path(__file__).parent.parent.parent / "models" / "emotion_cnn_pytorch.pt"


def _import_torch():
    try:
        import torch
        import torch.nn as nn
        return torch, nn
    except ImportError:
        raise RuntimeError(
            "[EMOTION] PyTorch not installed. Run: pip install torch torchvision"
        )


def _create_model(num_classes=7):
    torch, nn = _import_torch()

    class EmotionCNN(nn.Module):
        def __init__(self, n_classes=7):
            super().__init__()
            self.features = nn.Sequential(
                nn.Conv2d(1, 32, 3, padding=1),
                nn.BatchNorm2d(32),
                nn.ReLU(inplace=True),
                nn.Conv2d(32, 32, 3, padding=1),
                nn.BatchNorm2d(32),
                nn.ReLU(inplace=True),
                nn.MaxPool2d(2, 2),
                nn.Dropout2d(0.25),
                nn.Conv2d(32, 64, 3, padding=1),
                nn.BatchNorm2d(64),
                nn.ReLU(inplace=True),
                nn.Conv2d(64, 64, 3, padding=1),
                nn.BatchNorm2d(64),
                nn.ReLU(inplace=True),
                nn.MaxPool2d(2, 2),
                nn.Dropout2d(0.25),
                nn.Conv2d(64, 128, 3, padding=1),
                nn.BatchNorm2d(128),
                nn.ReLU(inplace=True),
                nn.MaxPool2d(2, 2),
                nn.Dropout2d(0.25),
            )
            self.classifier = nn.Sequential(
                nn.Linear(128 * 6 * 6, 256),
                nn.BatchNorm1d(256),
                nn.ReLU(inplace=True),
                nn.Dropout(0.5),
                nn.Linear(256, n_classes),
            )

        def forward(self, x):
            x = self.features(x)
            x = x.view(x.size(0), -1)
            x = self.classifier(x)
            return x

    return EmotionCNN(n_classes=num_classes)


class EmotionDetector:
    SUPPORTED_EMOTIONS = set(_EMOTION_LABELS)

    def __init__(
        self,
        window_size: int = 5,
        frame_skip: int = 3,
        min_confidence: float = 0.40,
    ):
        self._window_size = window_size
        self._frame_skip = frame_skip
        self._min_confidence = min_confidence
        self._frame_counter = 0
        self._emotion_buffer: deque[str] = deque(maxlen=window_size)
        self._last_result = self._empty_result()
        self._model = None
        self._device = None
        self._face_cascade = None
        self._enabled = True

        self._init_detector()

    def _init_detector(self):
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        self._face_cascade = cv2.CascadeClassifier(cascade_path)
        if self._face_cascade.empty():
            raise RuntimeError("[EMOTION] Failed to load Haar cascade")

        try:
            torch, nn = _import_torch()
            self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            self._model = _create_model(num_classes=7)
            self._model.to(self._device)
            self._model.eval()
            self._load_weights()
            logger.info(f"[EMOTION] PyTorch emotion detector ready (device: {self._device})")
        except Exception as e:
            logger.warning(f"[EMOTION] Failed to initialize PyTorch model: {e}. Disabling emotion detection.")
            self._enabled = False

    def _load_weights(self):
        torch, _ = _import_torch()

        if _MODEL_PATH.exists():
            try:
                state = torch.load(str(_MODEL_PATH), map_location=self._device, weights_only=True)
                self._model.load_state_dict(state)
                logger.info(f"[EMOTION] Loaded weights from {_MODEL_PATH}")
                return
            except Exception as e:
                logger.warning(f"[EMOTION] Failed to load local weights: {e}")

        logger.warning(
            "[EMOTION] No pre-trained weights found at %s. "
            "Place trained emotion_cnn_pytorch.pt in models/ directory. "
            "Using random weights - accuracy will be limited.", _MODEL_PATH
        )

    def process_frame(self, frame: np.ndarray) -> dict:
        if not self._enabled:
            return self._empty_result()

        if frame is None or frame.ndim != 3:
            return self._empty_result()

        self._frame_counter += 1
        if self._frame_counter % self._frame_skip != 0:
            return self._last_result

        raw_emotion, confidence, face_found = self._detect(frame)

        if face_found and confidence >= self._min_confidence:
            self._emotion_buffer.append(raw_emotion)

        smoothed = self._get_smoothed_emotion()

        self._last_result = {
            "emotion": smoothed,
            "confidence": round(confidence, 3),
            "face_found": face_found,
        }
        return self._last_result

    def reset(self):
        self._emotion_buffer.clear()
        self._frame_counter = 0
        self._last_result = self._empty_result()
        logger.info("[EMOTION] Reset.")

    def close(self):
        self._model = None
        self._face_cascade = None
        logger.info("[EMOTION] Closed.")

    def release(self):
        self.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _detect(self, frame: np.ndarray) -> tuple[str, float, bool]:
        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            faces = self._face_cascade.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=5, minSize=(48, 48)
            )

            if len(faces) == 0:
                return "neutral", 0.0, False

            (x, y, w, h) = max(faces, key=lambda f: f[2] * f[3])
            face_crop = gray[y:y + h, x:x + w]
            face_crop = cv2.resize(face_crop, (48, 48))
            face_crop = face_crop.astype(np.float32) / 255.0
            face_crop = (face_crop - 0.5) * 2.0

            torch, _ = _import_torch()
            tensor = (
                torch.from_numpy(face_crop)
                .unsqueeze(0)
                .unsqueeze(0)
                .to(self._device)
            )

            with torch.no_grad():
                output = self._model(tensor)
                probs = torch.softmax(output, dim=1).cpu().numpy()[0]

            top_idx = int(np.argmax(probs))
            confidence = float(probs[top_idx])
            emotion = _EMOTION_LABELS[top_idx]

            return emotion, confidence, True

        except Exception as e:
            logger.error(f"[EMOTION] Detection error: {e}")
            return "neutral", 0.0, False

    def _get_smoothed_emotion(self) -> str:
        if not self._emotion_buffer:
            return "neutral"
        return max(set(self._emotion_buffer), key=self._emotion_buffer.count)

    @staticmethod
    def _empty_result() -> dict:
        return {"emotion": "neutral", "confidence": 0.0, "face_found": False}
