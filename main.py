from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()

import logging
import logging.handlers
import os
import sys
from pathlib import Path

from config.settings import get_settings, configure_platform, detect_preset
from config.diagnostics import run_startup_diagnostics, print_diagnostics
from voice.pipeline import VoicePipeline
from voice.tts import TTSModule
from voice.face import FaceModule, FaceState
from vision.pipeline import VisionPipeline
from llm.module import LLMModule
from hardware import MotorController

_SETTINGS = get_settings()
_PRESET = detect_preset()


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
    logger.info("Session created: %s", session_id)

    vision_pipeline = VisionPipeline()

    motor_port = os.getenv("ROBOT_MOTOR_PORT", "COM3" if sys.platform == "win32" else "/dev/ttyS0")
    motor = MotorController(port=motor_port)
    if motor.is_available():
        logger.info("[main] Motor controller connected on %s", motor_port)
    else:
        logger.warning("[main] Motor controller not available — running without motors")

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
        motor_controller=motor,
        vision_context_getter=vision_pipeline.get_shared_context,
    )

    if vision_pipeline.open():
        vision_pipeline.start()

    voice_pipeline.start()
    logger.info("[startup] All modules initialized, entering pygame main loop")

    try:
        face.run_main_thread()
    except KeyboardInterrupt:
        logger.info("[shutdown] KeyboardInterrupt")
    except Exception as e:
        logger.error("[shutdown] Error: %s", e, exc_info=True)
    finally:
        logger.info("[shutdown] Starting shutdown sequence...")
        voice_pipeline.stop()
        vision_pipeline.stop()
        vision_pipeline.close()
        motor.close()
        llm.close()
        face.stop()
        logger.info("[shutdown] Complete")


if __name__ == "__main__":
    main()
