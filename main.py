from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()

import logging
import logging.handlers
import os
import sys
import threading
from pathlib import Path

from config.settings import get_settings, configure_platform, detect_preset
from config.diagnostics import run_startup_diagnostics, print_diagnostics
from voice.pipeline import VoicePipeline
from voice.tts import TTSModule
from voice.face import FaceModule, FaceState
from vision.pipeline import VisionPipeline
from llm.module import LLMModule
from hardware import MotorController, BatteryMonitor
from academic.context import AcademicContext
from academic.server import create_academic_app, run_academic_server
from mobile.server import create_mobile_server

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

    face = FaceModule(fullscreen=_SETTINGS.general.fullscreen)
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

    motor = MotorController()
    if motor.is_available():
        logger.info("[main] Motor controller connected to %s", motor.requested_port)
    else:
        logger.warning("[main] Motor controller not available — running without motors")

    vision_pipeline.set_motor_controller(motor)

    def on_low_battery(voltage: float):
        logger.warning("[main] Low battery: %.2fV", voltage)

    def on_battery_update(voltage: float):
        pct = max(0, min(100, int((voltage - 6.8) / (8.4 - 6.8) * 100)))
        face.set_battery_status(percentage=pct, voltage=voltage, charging=False)

    battery_monitor = BatteryMonitor(
        motor_controller=motor,
        on_low_battery=on_low_battery,
        on_shutdown=lambda: logger.critical("[main] Battery shutdown triggered"),
        on_update=on_battery_update,
        settings=_SETTINGS.battery,
    )
    battery_monitor.start()

    def set_face_state(state_str: str) -> None:
        try:
            face.set_state(FaceState(state_str))
        except ValueError:
            pass

    if _SETTINGS.academic.mode:
        academic_context = AcademicContext()

        def on_tts_text(text: str) -> None:
            face.set_spoken_text(text)
        tts_module.set_text_callback(on_tts_text)

        app = create_academic_app(academic_context, llm, tts_module, face)
        run_academic_server(app, port=_SETTINGS.academic.api_port)
    else:
        academic_context = None

    voice_pipeline = VoicePipeline(
        llm=llm,
        tts_module=tts_module,
        session_id=session_id,
        face_set_state=set_face_state,
        motor_controller=motor,
        vision_context_getter=vision_pipeline.get_shared_context,
        academic_context=academic_context,
    )

    if vision_pipeline.open():
        vision_pipeline.start()

    voice_pipeline.start()
    logger.info("[startup] All modules initialized, entering pygame main loop")

    mobile_app = create_mobile_server(
        motor=motor,
        battery_monitor=battery_monitor,
        tts=tts_module,
        llm=llm,
        session_id=session_id,
        academic_context=academic_context,
        settings=_SETTINGS,
        mic_enabled=_SETTINGS.general.mic_enabled,
    )
    _mobile_thread = threading.Thread(
        target=lambda: mobile_app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False),
        daemon=True,
        name="mobile-api",
    )
    _mobile_thread.start()
    logger.info("[mobile] API server started on port 5000")

    if _SETTINGS.general.dev_text_input:
        logger.info("[dev] Text input mode enabled — type text and press Enter")

        def dev_input_loop():
            while True:
                try:
                    text = input("[dev] > ").strip()
                except (EOFError, KeyboardInterrupt):
                    break
                if not text:
                    continue
                if text.lower() in ("quit", "exit"):
                    break
                voice_pipeline.process_text(text, "ar")

        dev_thread = threading.Thread(target=dev_input_loop, daemon=True)
        dev_thread.start()
        logger.info("[dev] Text input ready — session language: ar")
        print("\n[DEV MODE] Text input active. Type Arabic or English, press Enter.")
        print("[DEV MODE] Robot will always respond in Arabic.")
        print("[DEV MODE] Type 'quit' to exit.\n")

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
        battery_monitor.stop()
        motor.stop()
        motor.center_servos()
        motor.close()
        llm.close()
        face.stop()
        logger.info("[shutdown] Complete")


if __name__ == "__main__":
    main()
