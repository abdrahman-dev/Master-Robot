import cv2
import uuid
import logging
import urllib.request
import numpy as np
from pathlib import Path
from typing import List, Dict, Tuple, Optional

from config.settings import get_settings

logger = logging.getLogger(__name__)


def _ensure_models() -> Tuple[str, str]:
    settings = get_settings()
    paths = settings.paths

    paths.models_dir.mkdir(parents=True, exist_ok=True)
    proto_path = paths.models_dir / paths.face_proto_name
    weights_path = paths.models_dir / paths.face_weights_name

    try:
        if not proto_path.exists():
            logger.info(f"Downloading {paths.face_proto_name} ...")
            urllib.request.urlretrieve(paths.face_proto_url, proto_path)
            logger.info("Downloaded deploy.prototxt")
    except Exception as e:
        raise RuntimeError(f"Failed to download face proto file: {e}") from e

    try:
        if not weights_path.exists():
            logger.info(f"Downloading {paths.face_weights_name} (~10MB) ...")
            urllib.request.urlretrieve(paths.face_weights_url, weights_path)
            logger.info("Downloaded caffemodel")
    except Exception as e:
        raise RuntimeError(f"Failed to download face weights file: {e}") from e

    return str(proto_path), str(weights_path)


def _face_embedding(gray_crop: np.ndarray, size: int = 64) -> np.ndarray:
    face = cv2.resize(gray_crop, (size, size))

    lbp = np.zeros_like(face, dtype=np.uint8)
    for i in range(1, size - 1):
        for j in range(1, size - 1):
            center = int(face[i, j])
            code = 0
            code |= (int(face[i-1, j-1]) >= center) << 7
            code |= (int(face[i-1, j  ]) >= center) << 6
            code |= (int(face[i-1, j+1]) >= center) << 5
            code |= (int(face[i,   j+1]) >= center) << 4
            code |= (int(face[i+1, j+1]) >= center) << 3
            code |= (int(face[i+1, j  ]) >= center) << 2
            code |= (int(face[i+1, j-1]) >= center) << 1
            code |= (int(face[i,   j-1]) >= center) << 0
            lbp[i, j] = code

    hist, _ = np.histogram(lbp.ravel(), bins=256, range=(0, 256))
    hist = hist.astype(np.float32)
    norm = np.linalg.norm(hist)
    return hist / (norm + 1e-6)


class FaceIdentityTracker:
    def __init__(
        self,
        threshold: float = None,
        frame_skip: int = None,
        scale_factor: float = None,
    ):
        settings = get_settings()
        camera_settings = settings.camera

        raw_threshold = threshold if threshold is not None else camera_settings.face_threshold
        self.threshold = min(float(raw_threshold), 0.6)
        self.frame_skip = frame_skip if frame_skip is not None else camera_settings.face_frame_skip
        self.scale_factor = scale_factor if scale_factor is not None else camera_settings.face_scale_factor
        self._frame_counter = 0

        self._conf_threshold = 0.35

        proto, weights = _ensure_models()
        self._net = cv2.dnn.readNetFromCaffe(proto, weights)
        logger.info("FaceIdentityTracker (OpenCV DNN) ready.")

        self._known_embeddings: List[np.ndarray] = []
        self._known_ids: List[str] = []

    def process_frame(self, frame: np.ndarray) -> List[Dict]:
        if frame is None:
            return []

        self._frame_counter += 1
        if self._frame_counter % self.frame_skip != 0:
            return []

        h, w = frame.shape[:2]

        effective_scale = self.scale_factor if 0.1 <= self.scale_factor < 1.0 else 1.0
        if effective_scale < 1.0:
            proc = cv2.resize(frame, (int(w * effective_scale), int(h * effective_scale)))
        else:
            proc = frame
        scale_inv = 1.0 / effective_scale if effective_scale < 1.0 else 1.0

        blob = cv2.dnn.blobFromImage(
            cv2.resize(proc, (300, 300)),
            scalefactor=1.0,
            size=(300, 300),
            mean=(104.0, 177.0, 123.0),
        )
        self._net.setInput(blob)
        detections = self._net.forward()

        results = []
        ph, pw = proc.shape[:2]

        for i in range(detections.shape[2]):
            confidence = float(detections[0, 0, i, 2])
            if confidence < self._conf_threshold:
                continue

            x1 = int(detections[0, 0, i, 3] * pw)
            y1 = int(detections[0, 0, i, 4] * ph)
            x2 = int(detections[0, 0, i, 5] * pw)
            y2 = int(detections[0, 0, i, 6] * ph)

            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(pw - 1, x2), min(ph - 1, y2)

            if x2 <= x1 or y2 <= y1:
                continue

            ox1 = int(x1 * scale_inv)
            oy1 = int(y1 * scale_inv)
            ox2 = int(x2 * scale_inv)
            oy2 = int(y2 * scale_inv)

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            face_crop = gray[oy1:oy2, ox1:ox2]

            if face_crop.size == 0:
                continue

            embedding = _face_embedding(face_crop)
            face_id, status = self._identify_face(embedding)

            results.append({
                "face_id": face_id,
                "status": status,
                "bbox": (oy1, ox2, oy2, ox1),
                "landmarks": None,
            })

        return results

    def reset_session(self) -> None:
        self._known_embeddings.clear()
        self._known_ids.clear()
        self._frame_counter = 0
        logger.info("Session reset.")

    def get_known_count(self) -> int:
        return len(self._known_ids)

    def close(self):
        self._net = None
        logger.info("FaceIdentityTracker closed.")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __del__(self):
        self.close()

    def _identify_face(self, embedding: np.ndarray) -> Tuple[str, str]:
        if not self._known_embeddings:
            return self._register_new(embedding)

        known = np.array(self._known_embeddings)
        dots = known @ embedding
        norms = np.linalg.norm(known, axis=1) * np.linalg.norm(embedding)
        cosine_dist = 1.0 - dots / (norms + 1e-6)

        min_idx = int(np.argmin(cosine_dist))
        min_dist = float(cosine_dist[min_idx])

        if min_dist <= self.threshold:
            return self._known_ids[min_idx], "same_student"
        return self._register_new(embedding)

    def _register_new(self, embedding: np.ndarray) -> Tuple[str, str]:
        new_id = str(uuid.uuid4())
        self._known_embeddings.append(embedding)
        self._known_ids.append(new_id)
        return new_id, "new_student"
