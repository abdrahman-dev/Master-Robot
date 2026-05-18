from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()

import logging
import logging.handlers
import os
import sys
import threading
import time
from enum import Enum
from pathlib import Path

import pygame

from config.settings import get_settings, configure_platform, VisionProfile, detect_preset
from config.diagnostics import (
    run_startup_diagnostics, print_diagnostics,
    Watchdog, SystemMonitor,
    get_cpu_temperature,
)
from voice.pipeline import VoicePipeline
from voice.tts import TTSModule
from voice.face import FaceModule, FaceState, SettingsState
from vision.pipeline import VisionPipeline
from llm.module import LLMModule

_SETTINGS = get_settings()
_PRESET = detect_preset()


class SystemMode(Enum):
    DEFAULT = "default"
    SETTINGS_PANEL = "settings_panel"
    VISION_MODE = "vision_mode"
    VOICE_ONLY = "voice_only"
    SETTINGS = "settings"


def setup_logging() -> None:
    log_dir = _SETTINGS.paths.project_root / "data"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = str(log_dir / "robot.log")

    root = logging.getLogger()
    root.setLevel(getattr(logging, _SETTINGS.general.log_level.upper(), logging.INFO))

    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8",
    )

    class AsciiHandler(logging.StreamHandler):
        def emit(self, record):
            try:
                msg = self.format(record)
                self.stream.write(msg.encode("ascii", errors="replace").decode("ascii") + self.terminator)
                self.flush()
            except Exception:
                self.handleError(record)

    console = AsciiHandler(sys.stdout)

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    file_handler.setFormatter(formatter)
    console.setFormatter(formatter)

    root.addHandler(file_handler)
    root.addHandler(console)

    logging.getLogger("ultralytics").setLevel(logging.WARNING)


def configure_module_defaults(vision: VisionPipeline) -> None:
    from config.settings import profile_module_config
    cfg = profile_module_config(VisionProfile(_SETTINGS.vision.profile.value), _PRESET)
    if cfg["enable_objects"]:
        vision.enable_object_recognition()
    if cfg["enable_scene"]:
        vision.enable_scene_segmentation()
    if cfg["enable_obstacle"]:
        vision.enable_obstacle_detection()


def main() -> None:
    import sys, io
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

    setup_logging()
    configure_platform()
    logger = logging.getLogger("main")

    logger.info("Starting Rope (preset=%s)", _PRESET.value)

    diag = run_startup_diagnostics()
    print_diagnostics(diag)
    llm_is_available = diag.get("internet") == "ok"

    face = FaceModule(fullscreen=False)
    face.start()

    if _SETTINGS.vision.enable_metrics_overlay:
        face.set_show_overlay(True)

    tts_module = TTSModule(_SETTINGS.tts)
    llm = LLMModule()

    session_id = llm.create_session(
        student_name=_SETTINGS.general.student_name,
        language=_SETTINGS.general.default_session_language,
    )
    logger.info(f"Session created: {session_id}")

    vision_pipeline = VisionPipeline()

    watch = Watchdog()
    system_monitor = SystemMonitor()

    def get_vision_context():
        return vision_pipeline.get_shared_context()

    def set_face_state(state_str: str) -> None:
        try:
            face.set_state(FaceState(state_str))
        except ValueError:
            pass

    voice_pipeline = VoicePipeline(
        llm=llm,
        tts_module=tts_module,
        session_id=session_id,
        face_set_state=set_face_state,
        vision_context_getter=get_vision_context if llm_is_available else None,
    )

    voice_pipeline.set_watchdog_ping(lambda: watch.ping("voice_queue_worker"))
    vision_pipeline.set_watchdog_ping(lambda: watch.ping("vision_loop"))

    system_mode = SystemMode.DEFAULT
    mode_lock = threading.Lock()
    settings_timer_active = False

    def on_settings_change(key: str, value: str) -> None:
        nonlocal system_mode
        with mode_lock:
            logger.info("[settings] %s = %s", key, value)
            if key == "vision_mode":
                if value == "OFF":
                    if system_mode == SystemMode.VISION_MODE:
                        vision_pipeline.stop()
                        vision_pipeline.close()
                        system_mode = SystemMode.DEFAULT
                elif value == "MINIMAL":
                    if system_mode != SystemMode.VISION_MODE:
                        if vision_pipeline.open():
                            vision_pipeline.start()
                            voice_pipeline.set_vision_active(True)
                            system_mode = SystemMode.VISION_MODE
                    vision_pipeline.set_profile(VisionProfile.MINIMAL)
                elif value == "BALANCED":
                    if system_mode != SystemMode.VISION_MODE:
                        if vision_pipeline.open():
                            vision_pipeline.start()
                            voice_pipeline.set_vision_active(True)
                            system_mode = SystemMode.VISION_MODE
                    vision_pipeline.set_profile(VisionProfile.BALANCED)
                elif value == "FULL":
                    if system_mode != SystemMode.VISION_MODE:
                        if vision_pipeline.open():
                            vision_pipeline.start()
                            voice_pipeline.set_vision_active(True)
                            system_mode = SystemMode.VISION_MODE
                    vision_pipeline.set_profile(VisionProfile.FULL)

    face.set_settings_callback(on_settings_change)

    def on_swipe(direction: str) -> None:
        nonlocal system_mode
        with mode_lock:
            if direction == "close_settings":
                face.close_settings()
                system_mode = SystemMode.DEFAULT
                logger.info("[mode] SETTINGS_PANEL -> DEFAULT")
                return

            if direction == "left":
                if system_mode == SystemMode.DEFAULT:
                    logger.info("[mode] DEFAULT -> SETTINGS_PANEL")
                    face.open_settings()
                    system_mode = SystemMode.SETTINGS_PANEL
                elif system_mode == SystemMode.SETTINGS_PANEL:
                    face.close_settings()
                    logger.info("[mode] SETTINGS_PANEL -> VISION_MODE")
                    system_mode = SystemMode.VISION_MODE
                    face.set_state(FaceState.CURIOUS)
                    if vision_pipeline.open():
                        vision_pipeline.warmup(frames=3)
                        configure_module_defaults(vision_pipeline)
                        vision_pipeline.set_profile(VisionProfile.BALANCED)
                        vision_pipeline.start()
                        voice_pipeline.set_vision_active(True)
                elif system_mode == SystemMode.VISION_MODE:
                    logger.info("[mode] VISION_MODE -> VOICE_ONLY")
                    system_mode = SystemMode.VOICE_ONLY
                    vision_pipeline.stop()
                    vision_pipeline.close()
                    voice_pipeline.set_vision_active(False)
                    face.set_state(FaceState.IDLE)
                elif system_mode == SystemMode.VOICE_ONLY:
                    logger.info("[mode] VOICE_ONLY -> DEFAULT")
                    system_mode = SystemMode.DEFAULT
                    face.set_state(FaceState.IDLE)

    def on_event(event: pygame.event.Event) -> None:
        pass

    face.set_swipe_callback(on_swipe)
    face.set_event_handler(on_event)

    watch.register("voice_queue_worker", timeout_sec=60.0)
    watch.register("vision_loop", timeout_sec=30.0)
    watch.start()

    voice_pipeline.start()
    voice_pipeline.set_vision_active(False)
    logger.info("[startup] All modules initialized, entering pygame main loop")

    frame_count = 0

    try:
        face.run_main_thread()
    except KeyboardInterrupt:
        logger.info("[shutdown] KeyboardInterrupt")
    except Exception as e:
        logger.error(f"[shutdown] Error: {e}", exc_info=True)
    finally:
        logger.info("[shutdown] Starting shutdown sequence...")
        watch.stop()
        voice_pipeline.stop()
        vision_pipeline.stop()
        vision_pipeline.close()
        llm.close()
        face.stop()
        logger.info("[shutdown] Complete")


if __name__ == "__main__":
    main()
