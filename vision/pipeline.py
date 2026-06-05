import copy
import logging
import threading
import time
from collections import deque, Counter
from contextlib import contextmanager
from typing import Callable, Dict, Optional

from config.settings import get_settings, IS_RASPBERRY_PI, VisionProfile, detect_preset, profile_module_config
from config.diagnostics import get_cpu_temperature, THERMAL_THROTTLE_C, THERMAL_RESTORE_C
from vision.camera import CameraManager
from vision.modules.face_tracker import FaceIdentityTracker
from vision.modules.gesture import GestureDetector
from vision.modules.emotion import EmotionDetector
from vision.modules.objects import ObjectRecognitionModule
from vision.modules.scene import SceneSegmentationModule
from vision.modules.obstacle import ObstacleDetector

logger = logging.getLogger(__name__)

_SETTINGS = get_settings()
_VISION = _SETTINGS.vision
_PRESET = detect_preset()


class VisionPipeline:
    def __init__(self):
        self._camera: Optional[CameraManager] = None
        self._face_tracker: Optional[FaceIdentityTracker] = None
        self._gesture_detector: Optional[GestureDetector] = None
        self._emotion_detector: Optional[EmotionDetector] = None
        self._object_recognition: Optional[ObjectRecognitionModule] = None
        self._scene_segmentation: Optional[SceneSegmentationModule] = None
        self._obstacle_detector: Optional[ObstacleDetector] = None
        self._is_open = False
        self._running = False
        self._thread: Optional[threading.Thread] = None

        self._context: Dict = self._default_context()
        self._context_lock = threading.Lock()
        self._context_buffer: deque = deque(maxlen=10)
        self._shutdown_event = threading.Event()

        self._current_profile = _VISION.profile

        base_fs = 2 if IS_RASPBERRY_PI else 2
        if IS_RASPBERRY_PI:
            base_fs = 3
        self._base_frame_skip = base_fs
        self._current_frame_skip = base_fs
        self._max_frame_skip = _VISION.max_frame_skip

        self._frame_times: deque = deque(maxlen=30)
        self._thermal_throttle = False
        self._load_shed_active = False
        self._profile_downgraded = False

        self._watchdog_ping: Optional[Callable] = None

        logger.info("VisionPipeline initialized. profile=%s preset=%s",
                     self._current_profile.value, _PRESET.value)

    def set_watchdog_ping(self, fn: Callable) -> None:
        self._watchdog_ping = fn

    def open(self) -> bool:
        if self._is_open:
            logger.warning("VisionPipeline is already open.")
            return True

        self._shutdown_event.clear()
        self._camera = CameraManager()
        if not self._camera.is_available():
            logger.error("Cannot open VisionPipeline: camera not available")
            self._camera = None
            return False
        try:
            if not self._camera.open():
                raise RuntimeError("Failed to open camera")

            self._face_tracker = FaceIdentityTracker(frame_skip=self._current_frame_skip)
            self._gesture_detector = GestureDetector()
            self._emotion_detector = EmotionDetector()
            self._object_recognition = ObjectRecognitionModule(frame_skip=max(6, self._current_frame_skip * 2))
            self._scene_segmentation = SceneSegmentationModule(frame_skip=max(10, self._current_frame_skip * 3))
            self._obstacle_detector = ObstacleDetector()

            self._apply_profile(self._current_profile)

            self._is_open = True
            logger.info("VisionPipeline opened successfully.")
            return True

        except Exception as e:
            logger.error(f"Failed to open VisionPipeline: {e}")
            self.close()
            return False

    def _apply_profile(self, profile: VisionProfile) -> None:
        config = profile_module_config(profile, _PRESET)
        if self._object_recognition:
            self._object_recognition.enabled = config["enable_objects"]
        if self._scene_segmentation:
            self._scene_segmentation.enabled = config["enable_scene"]
        if self._obstacle_detector:
            self._obstacle_detector.enabled = config["enable_obstacle"]
        if self._emotion_detector:
            self._emotion_detector.enabled = False 
        logger.info("[vision] Profile %s applied: objects=%s scene=%s obstacle=%s emotion=%s",
                     profile.value, config["enable_objects"], config["enable_scene"],
                     config["enable_obstacle"], config["enable_emotion"])

    def set_profile(self, profile: VisionProfile) -> None:
        self._current_profile = profile
        self._apply_profile(profile)
        logger.info("[vision] Profile changed to %s", profile.value)

    def close(self):
        self._shutdown_event.set()
        if self._camera is not None:
            try:
                self._camera.close()
            except Exception as e:
                logger.warning(f"Error closing camera: {e}")
            finally:
                self._camera = None

        for mod, name in [
            (self._face_tracker, "face tracker"),
            (self._gesture_detector, "gesture detector"),
            (self._emotion_detector, "emotion detector"),
            (self._object_recognition, "object recognition"),
            (self._scene_segmentation, "scene segmentation"),
            (self._obstacle_detector, "obstacle detector"),
        ]:
            if mod is not None:
                try:
                    if hasattr(mod, "release"):
                        mod.release()
                    elif hasattr(mod, "close"):
                        mod.close()
                except Exception as e:
                    logger.warning(f"Error closing {name}: {e}")

        self._face_tracker = None
        self._gesture_detector = None
        self._emotion_detector = None
        self._object_recognition = None
        self._scene_segmentation = None
        self._obstacle_detector = None
        self._is_open = False
        logger.info("VisionPipeline closed.")

    def get_all_context(self) -> Dict:
        if not self._is_open:
            return self._default_context({"error": "pipeline_not_open"})

        try:
            frame = self._camera.get_frame()
            if self._shutdown_event.is_set():
                return self._default_context({"error": "shutdown"})
            if frame is None:
                return self._default_context({"error": "no_frame"})

            h, w = frame.shape[:2]
            if w > 640 and IS_RASPBERRY_PI:
                scale = 640.0 / w
                new_w, new_h = int(w * scale), int(h * scale)
                frame = frame[::2, ::2] if new_w < w else frame

            t0 = time.monotonic()
            context = self._default_context()
            context["frame"] = frame
            context["timestamp"] = t0

            if self._face_tracker is not None:
                face_results = self._face_tracker.process_frame(frame)
                context["faces"] = face_results if face_results is not None else []

            has_face = len(context["faces"]) > 0 if context.get("faces") else False

            if has_face:
                if self._gesture_detector is not None:
                    context["gesture"] = self._gesture_detector.process_frame(frame)
                if self._emotion_detector is not None:
                    context["emotion"] = self._emotion_detector.process_frame(frame)

            if self._object_recognition is not None and self._object_recognition.enabled:
                context["objects"] = self._object_recognition.process_frame(frame)

            if self._scene_segmentation is not None and self._scene_segmentation.enabled:
                context["scene"] = self._scene_segmentation.process_frame(frame)

            if self._obstacle_detector is not None and self._obstacle_detector.enabled:
                context["obstacle"] = self._obstacle_detector.process_frame(frame)

            elapsed = time.monotonic() - t0
            self._frame_times.append(elapsed)

            entry = {
                "faces": copy.deepcopy(context.get("faces", [])),
                "gesture": copy.deepcopy(context.get("gesture", {})),
                "emotion": copy.deepcopy(context.get("emotion", {})),
                "objects": copy.deepcopy(context.get("objects", {})),
                "scene": copy.deepcopy(context.get("scene", {})),
                "obstacle": copy.deepcopy(context.get("obstacle", {})),
            }

            self._context_buffer.append(entry)

            best = entry
            for e in self._context_buffer:
                e_faces = len(e["faces"])
                b_faces = len(best["faces"])
                e_objs = e["objects"].get("count", 0) if isinstance(e["objects"], dict) else 0
                b_objs = best["objects"].get("count", 0) if isinstance(best["objects"], dict) else 0
                if e_faces > b_faces or (e_faces == b_faces and e_objs > b_objs):
                    best = e

            with self._context_lock:
                self._context = best

            self._adaptive_throttle(elapsed)

            return context

        except Exception as e:
            logger.error(f"Error getting vision context: {e}")
            return self._default_context({"error": str(e)})

    def _adaptive_throttle(self, last_frame_time: float) -> None:
        if not _VISION.adaptive_shedding:
            return

        temp = get_cpu_temperature()
        if temp is not None:
            if temp >= THERMAL_THROTTLE_C and not self._thermal_throttle:
                self._thermal_throttle = True
                self._current_frame_skip = min(self._max_frame_skip, self._base_frame_skip + 3)
                if self._current_profile == VisionProfile.FULL:
                    self.set_profile(VisionProfile.BALANCED)
                logger.warning("[thermal] %0.fC throttling frame_skip=%d", temp, self._current_frame_skip)
            elif temp <= THERMAL_RESTORE_C and self._thermal_throttle:
                self._thermal_throttle = False
                self._current_frame_skip = self._base_frame_skip
                self._apply_profile(self._current_profile)
                logger.info("[thermal] %0.fC restored frame_skip=%d", temp, self._current_frame_skip)

        if len(self._frame_times) < 10:
            return

        avg_time = sum(self._frame_times) / len(self._frame_times)
        target = _VISION.target_frame_interval

        if avg_time > target * 1.5 and not self._load_shed_active:
            self._load_shed_active = True
            self._current_frame_skip = min(self._max_frame_skip, self._current_frame_skip + 1)
            if self._current_profile == VisionProfile.FULL and not self._profile_downgraded:
                self._profile_downgraded = True
                self.set_profile(VisionProfile.BALANCED)
            logger.info("[shed] Avg frame %.0fms > %.0fms target, skip=%d",
                         avg_time * 1000, target * 1000, self._current_frame_skip)

        elif avg_time < target * 0.5 and self._load_shed_active:
            self._current_frame_skip = max(self._base_frame_skip, self._current_frame_skip - 1)
            if self._current_frame_skip <= self._base_frame_skip:
                self._load_shed_active = False
                if self._profile_downgraded:
                    self._profile_downgraded = False
                    self._apply_profile(self._current_profile)
                logger.info("[shed] Load normalized, restore skip=%d", self._current_frame_skip)

    def get_frame_skip(self) -> int:
        return self._current_frame_skip

    def get_shared_context(self) -> Dict:
        with self._context_lock:
            return copy.deepcopy(self._context)

    def is_open(self) -> bool:
        return self._is_open

    def get_profile(self) -> VisionProfile:
        return self._current_profile

    def warmup(self, frames: int = 3) -> bool:
        if not self._is_open:
            logger.error("Cannot warmup: pipeline is not open")
            return False

        logger.info(f"Warming up camera ({frames} frames)...")
        try:
            for i in range(frames):
                if self._shutdown_event.is_set():
                    return False
                frame = self._camera.get_frame()
                if frame is None:
                    logger.warning(f"Warmup frame {i+1} failed")
                    return False
            logger.info("Camera warmup complete")
            return True
        except Exception as e:
            logger.error(f"Warmup error: {e}")
            return False

    def enable_object_recognition(self):
        if self._object_recognition is not None:
            self._object_recognition.enabled = True
            logger.info("[VISION] Object recognition enabled")

    def disable_object_recognition(self):
        if self._object_recognition is not None:
            self._object_recognition.enabled = False
            logger.info("[VISION] Object recognition disabled")

    def enable_scene_segmentation(self):
        if self._scene_segmentation is not None:
            self._scene_segmentation.enabled = True
            logger.info("[VISION] Scene segmentation enabled")

    def disable_scene_segmentation(self):
        if self._scene_segmentation is not None:
            self._scene_segmentation.enabled = False
            logger.info("[VISION] Scene segmentation disabled")

    def enable_obstacle_detection(self):
        if self._obstacle_detector is not None:
            self._obstacle_detector.enabled = True
            logger.info("[VISION] Obstacle detection enabled")

    def disable_obstacle_detection(self):
        if self._obstacle_detector is not None:
            self._obstacle_detector.enabled = False
            logger.info("[VISION] Obstacle detection disabled")

    def run_loop(self) -> None:
        if not self._is_open:
            logger.error("[vision] Cannot run loop: pipeline not open")
            return
        if self._camera is not None and not self._camera.is_available():
            logger.warning("[vision] Camera unavailable, vision loop disabled")
            return

        logger.info("[vision] Loop started")
        frame_count = 0

        try:
            while self._running and not self._shutdown_event.is_set():
                if self._watchdog_ping:
                    self._watchdog_ping()
                self.get_all_context()
                frame_count += 1
                if frame_count % 100 == 0:
                    logger.info("[vision] %d frames processed", frame_count)
                time.sleep(0.01)
        except Exception as e:
            logger.error(f"[vision] Loop error: {e}")
        finally:
            logger.info(f"[vision] Loop stopped ({frame_count} frames processed)")

    def start(self) -> None:
        if not self._is_open:
            logger.error("Cannot start: pipeline not open")
            return

        self._running = True
        self._shutdown_event.clear()
        self._thread = threading.Thread(target=self.run_loop, daemon=True)
        self._thread.start()
        logger.info("[vision] Thread started")

    def stop(self) -> None:
        logger.info("[vision] Stopping...")
        self._running = False
        self._shutdown_event.set()
        if self._thread:
            self._thread.join(timeout=2)
            if self._thread.is_alive():
                logger.warning("[vision] Thread did not exit in time, releasing camera")
                if self._camera:
                    try:
                        self._camera.close()
                    except Exception:
                        pass
            self._thread = None
        logger.info("[vision] Stopped")

    @contextmanager
    def managed(self):
        self.open()
        try:
            yield self
        finally:
            self.close()

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *args):
        self.close()

    @staticmethod
    def _default_context(overrides: Optional[Dict] = None) -> Dict:
        base = {
            "frame": None,
            "timestamp": 0.0,
            "faces": [],
            "gesture": {"gesture": "none", "command": "none", "hand_found": False, "landmarks": None},
            "emotion": {"emotion": "neutral", "confidence": 0.0, "face_found": False},
            "objects": {"objects": [], "count": 0, "prompt": ""},
            "scene": {"segments": [], "scene_description": "", "dominant_segment": ""},
            "obstacle": {"obstacle_detected": False, "direction": "clear", "confidence": 0.0},
            "error": None,
        }
        if overrides:
            base.update(overrides)
        return base
