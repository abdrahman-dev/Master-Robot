from __future__ import annotations

import logging
import os
import sys
import threading
import time
from typing import Optional

from flask import Flask, jsonify, request
from flask_cors import CORS

logger = logging.getLogger(__name__)


def battery_status(battery_monitor) -> dict:
    try:
        voltage = battery_monitor.get_voltage()
        if voltage >= 99.0:
            return {"level": -1, "voltage": -1, "status": "unavailable"}
        pct = max(0, min(100, int((voltage - 6.8) / (8.4 - 6.8) * 100)))
        if voltage <= 6.8:
            status = "critical"
        elif voltage <= 7.2:
            status = "low"
        else:
            status = "ok"
        return {"level": pct, "voltage": round(voltage, 2), "status": status}
    except Exception:
        return {"level": -1, "voltage": -1, "status": "unavailable"}


def robot_status(battery_monitor, motor, academic_context, mic_enabled: bool = True) -> dict:
    bat = battery_status(battery_monitor)
    motor_avail = motor.is_available() if motor else False
    acad_active = academic_context.is_active() if academic_context else False
    acad_title = academic_context.get_title() if academic_context and acad_active else ""
    return {
        "battery": bat,
        "motor": {"available": motor_avail},
        "academic_mode": {"active": acad_active, "title": acad_title or ""},
        "mic_enabled": mic_enabled,
        "success": True,
    }


def create_mobile_server(
    motor,
    battery_monitor,
    tts,
    llm,
    session_id: str,
    academic_context,
    settings,
    mic_enabled: bool = True,
):
    app = Flask(__name__)
    CORS(app)

    @app.route("/battery", methods=["GET"])
    def get_battery():
        try:
            return jsonify(battery_status(battery_monitor))
        except Exception as e:
            logger.error("[mobile] /battery error: %s", e)
            return jsonify({"level": -1, "voltage": -1, "status": "unavailable"})

    @app.route("/status", methods=["GET"])
    def get_status():
        try:
            return jsonify(robot_status(battery_monitor, motor, academic_context, mic_enabled))
        except Exception as e:
            logger.error("[mobile] /status error: %s", e)
            return jsonify({"success": False, "error": str(e)})

    @app.route("/command", methods=["POST"])
    def handle_command():
        try:
            try:
                data = request.get_json(force=True)
            except Exception:
                return jsonify({"message": "طلب غير صالح", "success": False}), 400

            action = data.get("action", "")
            params = data.get("params", {})

            logger.info("[mobile] Command received: %s %s", action, params)

            if action == "move":
                direction = params.get("direction", "forward")
                duration_ms = params.get("duration_ms", 2000)
                if motor and motor.is_available():
                    method_map = {
                        "forward": motor.forward,
                        "backward": motor.backward,
                        "left": motor.turn_left,
                        "right": motor.turn_right,
                        "stop": motor.stop,
                    }
                    method = method_map.get(direction)
                    if method:
                        if direction == "stop":
                            method()
                        else:
                            method(duration_ms)
                        return jsonify({"message": "تم تحريك الروبوت", "success": True})
                return jsonify({"message": "المحركات غير متصلة", "success": False})

            elif action == "speak":
                text = params.get("text", "")
                language = params.get("language", "ar")
                if tts and text:
                    tts.speak(text, language)
                    return jsonify({"message": "تم نطق النص بنجاح", "success": True})
                return jsonify({"message": "النص فارغ", "success": False})

            elif action == "volume":
                state = params.get("state", "")
                logger.info("[mobile] Volume command: %s", state)
                return jsonify({"message": "تم تعديل الصوت", "success": True})

            elif action == "power":
                if params.get("state") == "off":
                    def _do_shutdown():
                        time.sleep(2)
                        if sys.platform == "linux":
                            os.system("sudo shutdown -h now")
                        else:
                            logger.warning("[mobile] Shutdown skipped — not on Linux")
                    threading.Thread(target=_do_shutdown, daemon=True).start()
                    return jsonify({"message": "جاري إغلاق الراسبري باي", "success": True})
                elif params.get("state") == "restart":
                    def _do_restart():
                        time.sleep(2)
                        if sys.platform == "linux":
                            os.system("sudo reboot")
                        else:
                            logger.warning("[mobile] Restart skipped — not on Linux")
                    threading.Thread(target=_do_restart, daemon=True).start()
                    return jsonify({"message": "جاري إعادة التشغيل", "success": True})
                return jsonify({"message": "حالة طاقة غير معروفة", "success": False})

            elif action == "academic":
                mode = params.get("mode", "")
                if mode == "set":
                    context_text = params.get("context", "")
                    title = params.get("title", "الدرس")
                    if academic_context and context_text:
                        academic_context.set(title=title, content=context_text)
                        return jsonify({"message": "تم تفعيل الوضع الأكاديمي", "success": True})
                    return jsonify({"message": "النص فارغ", "success": False})
                elif mode == "clear":
                    if academic_context:
                        academic_context.clear()
                    return jsonify({"message": "تم إيقاف الوضع الأكاديمي", "success": True})
                elif mode == "ask":
                    question = params.get("question", "")
                    language = params.get("language", "ar")
                    if llm and academic_context and academic_context.is_active():
                        ctx_str = academic_context.get_formatted(language)
                        response = llm.chat(
                            session_id=session_id,
                            user_message=question,
                            academic_context=ctx_str,
                        )
                        return jsonify({"answer": response, "success": True})
                    return jsonify({"message": "الوضع الأكاديمي غير نشط", "success": False})
                return jsonify({"message": "وضع أكاديمي غير معروف", "success": False})

            elif action == "status":
                return jsonify(robot_status(battery_monitor, motor, academic_context, mic_enabled))

            return jsonify({"message": "أمر غير معروف", "success": False})

        except Exception as e:
            logger.error("[mobile] Command error: %s", e, exc_info=True)
            return jsonify({"success": False, "error": str(e)})

    return app


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Rope Mobile API Server (standalone)")
    parser.add_argument("--port", type=int, default=5000, help="Port to listen on")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host to bind to")
    args = parser.parse_args()

    # Standalone mode — all components are None (no hardware connected)
    # Useful for testing endpoints without running the full robot
    logger.warning("[mobile] Running in standalone mode — no hardware components connected")

    logging.basicConfig(level=logging.INFO)

    standalone_app = create_mobile_server(
        motor=None,
        battery_monitor=None,
        tts=None,
        llm=None,
        session_id="standalone_test",
        academic_context=None,
        settings=None,
    )

    print(f"[mobile] Standalone server running on http://{args.host}:{args.port}")
    print("[mobile] All hardware endpoints will return unavailable/error responses")
    print("[mobile] Useful for testing mobile app connectivity only")

    standalone_app.run(host=args.host, port=args.port, debug=True, use_reloader=False)
