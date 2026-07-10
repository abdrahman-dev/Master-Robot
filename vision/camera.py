import cv2
import numpy as np
import logging
import os
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
        self._logged_channel_strip = False

        self._auto_detect = os.environ.get("CAMERA_AUTO_DETECT", "").lower() in ("true", "1", "yes")
        self._configured_device = os.environ.get("CAMERA_DEVICE", "") or None
        self._selected_device = None

        if IS_RASPBERRY_PI and PICAMERA2_AVAILABLE:
            self._backend = "picamera2"
            logger.info("CameraManager: picamera2 backend available")
        else:
            self._backend = "opencv"
            if IS_RASPBERRY_PI and not PICAMERA2_AVAILABLE:
                logger.warning("CameraManager: picamera2 not available, falling back to OpenCV")

        if self._auto_detect:
            logger.info("[CAMERA] Auto-detect enabled")
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
            if self._selected_device is None and (self._configured_device or self._auto_detect):
                self._selected_device = self._discover_camera()

            if self._selected_device is not None:
                if self._selected_device == "picamera2":
                    self._backend = "picamera2"
                    self._open_picamera()
                else:
                    self._backend = "opencv"
                    self._open_opencv(self._selected_device)
            else:
                if self._backend == "picamera2":
                    self._open_picamera()
                else:
                    self._open_opencv()

            self._is_open = True
            backend_name = self._backend.capitalize()
            if self._selected_device == "picamera2":
                device_str = "picamera2"
            elif isinstance(self._selected_device, int):
                device_str = f"index {self._selected_device}"
            else:
                device_str = str(self._selected_device)
            logger.info("[CAMERA] Backend   : %s", backend_name)
            logger.info("[CAMERA] Device    : %s", device_str)
            logger.info("[CAMERA] Resolution: %dx%d", CAMERA_WIDTH, CAMERA_HEIGHT)
            logger.info("[CAMERA] FPS       : %d", CAMERA_FPS)
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
            main={"size": (CAMERA_WIDTH, CAMERA_HEIGHT), "format": "XBGR8888"},
            buffer_count=STREAM_BUFFER_SIZE,
        )
        self._camera.configure(config)
        self._camera.start()
        self._selected_device = "picamera2"

    def _capture_picamera(self) -> np.ndarray:
        frame = self._camera.capture_array("main")
        if frame is not None and frame.ndim == 3 and frame.shape[2] == 4:
            frame = cv2.cvtColor(frame[:, :, :3], cv2.COLOR_RGB2BGR)
            if not self._logged_channel_strip:
                logger.debug("[camera] Converted picamera2 XBGR8888 -> BGR")
                self._logged_channel_strip = True
        frame = cv2.flip(frame, 0)
        return frame

    def _open_opencv(self, device=None):
        cap = None

        if device is None:
            for idx in FALLBACK_INDICES:
                cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
                cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 2000)
                ret = cap.grab()
                if ret:
                    logger.info(f"Opened camera at index {idx}")
                    self._selected_device = idx
                    break
                cap.release()
                cap = None
            else:
                raise RuntimeError(f"OpenCV could not open camera. Tried indices: {FALLBACK_INDICES}")
        else:
            if isinstance(device, int) and not IS_RASPBERRY_PI:
                cap = cv2.VideoCapture(device, cv2.CAP_DSHOW)
            else:
                cap = cv2.VideoCapture(device)
            cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 2000)
            ret = cap.grab()
            if not ret:
                cap.release()
                raise RuntimeError(f"Failed to open camera at {device}")

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
        return cv2.flip(frame, 0)

    def _probe_picamera(self) -> bool:
        try:
            cam = Picamera2()
            config = cam.create_preview_configuration(
                main={"size": (CAMERA_WIDTH, CAMERA_HEIGHT), "format": "XBGR8888"},
                buffer_count=1,
            )
            cam.configure(config)
            cam.start()
            frame = cam.capture_array("main")
            if frame is not None and frame.size > 0:
                h, w = frame.shape[:2]
                logger.info("[CAMERA] Camera verified (%dx%d)", w, h)
                cam.stop()
                cam.close()
                return True
            cam.stop()
            cam.close()
            return False
        except Exception as e:
            logger.warning("[CAMERA] Picamera2 probe failed: %s", e)
            return False

    def _probe_opencv(self, device) -> bool:
        try:
            if isinstance(device, int) and not IS_RASPBERRY_PI:
                cap = cv2.VideoCapture(device, cv2.CAP_DSHOW)
            else:
                cap = cv2.VideoCapture(device)
            cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 2000)
            ret, frame = cap.read()
            if ret and frame is not None and frame.size > 0:
                h, w = frame.shape[:2]
                logger.info("[CAMERA] Camera verified (%dx%d)", w, h)
                cap.release()
                return True
            cap.release()
            return False
        except Exception as e:
            logger.warning("[CAMERA] OpenCV probe for %s failed: %s", device, e)
            return False

    def _discover_camera(self):
        configured = self._configured_device

        if configured:
            device = int(configured) if configured.isdigit() else configured
            logger.info("[CAMERA] Trying configured device: %s", configured)
            if self._probe_opencv(device):
                logger.info("[CAMERA] Using configured device: %s", configured)
                return device
            if not self._auto_detect:
                raise RuntimeError(
                    f"Configured camera device {configured} not found and auto-detect is disabled"
                )
            logger.warning("[CAMERA] Configured device %s failed, falling back to auto-detect", configured)

        candidates = []
        if IS_RASPBERRY_PI:
            if PICAMERA2_AVAILABLE:
                logger.info("[CAMERA] Trying Picamera2...")
                if self._probe_picamera():
                    logger.info("[CAMERA] Using: Picamera2")
                    return "picamera2"
            candidates = [f"/dev/video{i}" for i in range(6)]
        else:
            candidates = list(range(6))

        for dev in candidates:
            logger.info("[CAMERA] Trying %s...", dev)
            if self._probe_opencv(dev):
                logger.info("[CAMERA] Using: %s", dev)
                return dev

        raise RuntimeError("No working camera found")
