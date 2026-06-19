import cv2
import numpy as np
import logging
import threading
from pathlib import Path
from typing import Optional

from config.settings import IS_RASPBERRY_PI, get_settings

try:
    from picamera2 import Picamera2
    PICAMERA2_AVAILABLE = True
except ImportError:
    PICAMERA2_AVAILABLE = False

_CAM = get_settings().camera

CAMERA_WIDTH = _CAM.width
CAMERA_HEIGHT = _CAM.height
CAMERA_FPS = _CAM.fps
CAMERA_INDEX = _CAM.index
STREAM_BUFFER_SIZE = _CAM.buffer_size
FALLBACK_INDICES = _CAM.camera_fallback_indices

logger = logging.getLogger(__name__)


class CameraManager:
    def __init__(self):
        self._camera = None
        self._is_open = False
        self._backend = None
        self._available = True
        self._shutdown_event = threading.Event()

        if IS_RASPBERRY_PI and PICAMERA2_AVAILABLE:
            self._backend = "picamera2"
            logger.info("CameraManager: picamera2 backend available")
        else:
            self._backend = "opencv"
            if IS_RASPBERRY_PI and not PICAMERA2_AVAILABLE:
                logger.warning("CameraManager: picamera2 not available, falling back to OpenCV")

        logger.info(f"CameraManager initialized - backend: {self._backend}")

    def get_backend_name(self) -> str:
        return self._backend

    def is_available(self) -> bool:
        return self._available

    def open(self) -> bool:
        if not self._available:
            logger.warning("Camera is not available.")
            return False

        if self._is_open:
            logger.warning("Camera is already open.")
            return True

        self._shutdown_event.clear()
        try:
            if self._backend == "picamera2":
                self._open_picamera()
            else:
                self._open_opencv()

            self._is_open = True
            logger.info(f"Camera opened - {CAMERA_WIDTH}x{CAMERA_HEIGHT} @ {CAMERA_FPS}fps")
            return True

        except Exception as e:
            logger.error(f"Failed to open camera: {e}")
            self._available = False
            return False

    def close(self):
        if not self._is_open:
            return
        self._shutdown_event.set()
        try:
            if self._backend == "picamera2":
                if self._camera is not None:
                    self._camera.stop()
                    self._camera.close()
            else:
                if self._camera is not None:
                    self._camera.release()

            self._camera = None
            self._is_open = False
            logger.info("Camera closed.")

        except Exception as e:
            logger.error(f"Error closing camera: {e}")

    def get_frame(self) -> Optional[np.ndarray]:
        if not self._is_open:
            return None

        if self._shutdown_event.is_set():
            return None

        try:
            if self._backend == "picamera2":
                return self._capture_picamera()
            else:
                return self._capture_opencv()
        except Exception as e:
            logger.error(f"Failed to capture frame: {e}")
            return None

    def start_stream(self):
        if not self._is_open:
            return
        try:
            while not self._shutdown_event.is_set():
                frame = self._read_raw()
                if frame is not None:
                    yield frame
        except (GeneratorExit, KeyboardInterrupt):
            pass

    def _read_raw(self) -> Optional[np.ndarray]:
        try:
            if self._backend == "picamera2":
                return self._capture_picamera()
            else:
                return self._capture_opencv()
        except Exception as e:
            logger.error(f"Raw read failed: {e}")
            return None

    def is_open(self) -> bool:
        return self._is_open

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *args):
        self.close()

    def _open_picamera(self):
        self._camera = Picamera2()
        config = self._camera.create_preview_configuration(
            main={"size": (CAMERA_WIDTH, CAMERA_HEIGHT), "format": "BGR888"},
            buffer_count=STREAM_BUFFER_SIZE,
        )
        self._camera.configure(config)
        self._camera.start()

    def _capture_picamera(self) -> np.ndarray:
        return self._camera.capture_array("main")

    def _open_opencv(self):
        cap = None
        for idx in FALLBACK_INDICES:
            cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
            cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 2000)
            ret = cap.grab()
            if ret:
                logger.info(f"Opened camera at index {idx}")
                break
            cap.release()
            cap = None
        else:
            raise RuntimeError(f"OpenCV could not open camera. Tried indices: {FALLBACK_INDICES}")

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
        cap.set(cv2.CAP_PROP_FPS, CAMERA_FPS)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, STREAM_BUFFER_SIZE)
        self._camera = cap

    def _capture_opencv(self) -> Optional[np.ndarray]:
        if self._shutdown_event.is_set():
            return None
        ret, frame = self._camera.read()
        if not ret or frame is None or frame.size == 0:
            logger.warning("Invalid frame received")
            return None
        return cv2.flip(frame, 1)
