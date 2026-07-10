#!/usr/bin/env python3
"""Rope Health Check — enhanced standalone diagnostic script."""

from dotenv import load_dotenv
load_dotenv()

import importlib
import importlib.metadata
import os
import platform
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# ── ANSI codes ────────────────────────────────────────────────────
OK = "\033[92mOK\033[0m"
WN = "\033[93mWARN\033[0m"
ER = "\033[91mERROR\033[0m"
GR = "\033[90mINFO\033[0m"
SK = "\033[90mSKIP\033[0m"

RESULTS = []
REPORT_LINES = []

PIP_TO_MODULE = {
    "python-dotenv": "dotenv",
    "speechrecognition": "speech_recognition",
    "edge-tts": "edge_tts",
    "opencv-python": "cv2",
    "arabic-reshaper": "arabic_reshaper",
    "python-bidi": "bidi",
}

# ── Helpers ───────────────────────────────────────────────────────

def check(name, status, detail=""):
    RESULTS.append((name, status, detail))
    print(f"  [{status}] {name:45s} {detail}")
    REPORT_LINES.append(f"[{status}] {name:45s} {detail}")


def ansi(s, code):
    return f"\033[{code}m{s}\033[0m"


def section(title):
    print()
    print(ansi(f"── {title} {'─' * (50 - len(title))}", "4"))
    REPORT_LINES.append("")
    REPORT_LINES.append(f"── {title} {'─' * (50 - len(title))}")


def is_pi():
    return os.path.exists("/proc/device-tree/model")


def pi_model():
    if is_pi():
        try:
            with open("/proc/device-tree/model") as f:
                return f.read().strip().replace("\x00", "")
        except Exception:
            return "unknown"
    return None


# ── Main ──────────────────────────────────────────────────────────

def main():
    report_path = ROOT / "health_report.txt"

    print()
    print(ansi("=" * 56, "1"))
    print(ansi("  ROPE HEALTH CHECK — Enhanced", "1"))
    print(ansi("=" * 56, "1"))
    print()

    # ── Platform Info ─────────────────────────────────────────────
    section("Platform Info")

    os_name = platform.system()
    os_release = platform.release()
    check("OS", OK, f"{os_name} {os_release}")

    check("Python", OK, sys.version.split("\n")[0])

    cpu_count = os.cpu_count() or "unknown"
    check("CPU cores", OK, str(cpu_count))

    try:
        import psutil
        mem = psutil.virtual_memory()
        total_gb = mem.total / (1024 ** 3)
        avail_gb = mem.available / (1024 ** 3)
        check("RAM", OK, f"{total_gb:.1f}GB total, {avail_gb:.1f}GB available")
    except ImportError:
        check("RAM", GR, "install psutil for detail")

    if is_pi():
        check("Raspberry Pi", OK, pi_model())
    else:
        check("Raspberry Pi", GR, "no — running on desktop/server")

    check("Working directory", OK, str(ROOT))

    # ── Package Versions ──────────────────────────────────────────
    section("Package Versions")

    packages = [
        ("numpy", "numpy"),
        ("requests", "requests"),
        ("python-dotenv", "dotenv"),
        ("speechrecognition", "speech_recognition"),
        ("sounddevice", "sounddevice"),
        ("torch", "torch"),
        ("edge-tts", "edge_tts"),
        ("opencv-python", "cv2"),
        ("ultralytics", "ultralytics"),
        ("torchvision", "torchvision"),
        ("pygame", "pygame"),
        ("psutil", "psutil"),
        ("arabic-reshaper", "arabic_reshaper"),
        ("python-bidi", "bidi"),
    ]

    for pip_name, import_name in packages:
        try:
            ver = importlib.metadata.version(pip_name)
            check(f"  {pip_name}", OK, f"=={ver}")
        except importlib.metadata.PackageNotFoundError:
            check(f"  {pip_name}", ER, "not installed")
        except Exception as e:
            check(f"  {pip_name}", WN, str(e)[:50])

    # ── Model Files ───────────────────────────────────────────────
    section("Model Files")

    model_files = [
        "models/deploy.prototxt",
        "models/res10_300x300_ssd_iter_140000.caffemodel",
        "models/yolov8s.pt",
        "models/yolov8s-seg.pt",
    ]

    for mf in model_files:
        fp = ROOT / mf
        if fp.exists():
            size_mb = fp.stat().st_size / (1024 * 1024)
            check(f"  {mf}", OK, f"{size_mb:.1f} MB")
        else:
            check(f"  {mf}", WN, "missing")

    # ── VAD Settings ──────────────────────────────────────────────
    section("VAD Settings (from env)")

    vad_keys = [
        ("ROBOT_VAD_THRESHOLD", "0.45"),
        ("ROBOT_VAD_SILENCE_TIMEOUT_SEC", "1.20"),
        ("ROBOT_VAD_MIN_SPEECH_SEC", "0.40"),
        ("ROBOT_VAD_PRE_ROLL_SEC", "0.40"),
    ]

    for key, default in vad_keys:
        val = os.getenv(key)
        if val is not None:
            check(f"  {key}", OK, f"{val}  [ENV]")
        else:
            check(f"  {key}", GR, f"{default}  [DEFAULT]")

    # ── Network ───────────────────────────────────────────────────
    section("Network")

    for host, label in [("api.openrouter.ai", "OpenRouter API"),
                         ("www.google.com", "Google (ASR)")]:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(5)
            s.connect((host, 443))
            s.close()
            check(f"  {label}", OK)
        except Exception as e:
            check(f"  {label}", WN, str(e)[:50])

    # ── Module Imports ────────────────────────────────────────────
    section("Module Imports")

    modules = [
        "voice.vad", "voice.asr", "voice.tts", "voice.face",
        "voice.pipeline", "vision.camera", "vision.pipeline",
        "vision.modules.face_tracker", "vision.modules.gesture",
        "vision.modules.objects",
        "vision.modules.scene", "vision.modules.obstacle",
        "llm.module", "config.settings", "config.diagnostics",
        "hardware.motor_controller",
        "hardware.battery_monitor",
    ]
    for mod_name in modules:
        try:
            importlib.import_module(mod_name)
            check(f"  {mod_name}", OK)
        except Exception as e:
            check(f"  {mod_name}", ER, str(e).split("\n")[0][:70])

    # ── Live Module Tests ─────────────────────────────────────────
    section("Live Module Tests")

    # 1. VAD live test
    try:
        from voice import vad as vad_mod
        import numpy as np
        import torch

        t0 = time.monotonic()
        vad_mod._load_model_once()
        load_time = (time.monotonic() - t0) * 1000
        check("  VAD model load", OK, f"{load_time:.0f}ms")

        # Silero VAD requires exactly 512 samples at 16kHz (32ms)
        audio_chunk = np.zeros(512, dtype=np.float32)
        t0 = time.monotonic()
        result = vad_mod.is_speech(audio_chunk)
        infer_ms = (time.monotonic() - t0) * 1000
        if not result:
            check("  VAD silence test", OK, f"correctly silent ({infer_ms:.1f}ms)")
        else:
            check("  VAD silence test", WN, f"false positive on silence ({infer_ms:.1f}ms)")
    except Exception as e:
        check("  VAD live test", ER, str(e)[:70])

    # 2. TTS live test
    try:
        import edge_tts
        tts_tmp = os.path.join(tempfile.gettempdir(), "rope_health_tts_test.mp3")
        phrase = "مرحبا"
        t0 = time.monotonic()
        communicate = edge_tts.Communicate(text=phrase, voice="ar-EG-ShakirNeural")
        # edge_tts.Communicate.save is async
        import asyncio
        asyncio.run(communicate.save(tts_tmp))
        gen_ms = (time.monotonic() - t0) * 1000

        if os.path.exists(tts_tmp):
            fsize = os.path.getsize(tts_tmp)
            check("  TTS generation", OK, f"{gen_ms:.0f}ms, {fsize} bytes")
            os.remove(tts_tmp)
        else:
            check("  TTS generation", ER, "no output file")
    except Exception as e:
        check("  TTS live test", ER, str(e)[:70])

    # 3. LLM live test
    api_key = os.getenv("ROBOT_OPENROUTER_API_KEY", "").strip()
    if api_key:
        try:
            import requests
            t0 = time.monotonic()
            r = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                json={
                    "model": os.getenv("ROBOT_OPENROUTER_MODEL", "openrouter/free"),
                    "messages": [{"role": "user", "content": "say hi"}],
                    "max_tokens": 5,
                },
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                timeout=15,
            )
            resp_ms = (time.monotonic() - t0) * 1000
            if r.status_code == 200:
                body = r.json()
                model_used = body.get("model", "unknown")
                check("  LLM API call", OK, f"HTTP {r.status_code}, {resp_ms:.0f}ms, model={model_used}")
            elif r.status_code == 401:
                check("  LLM API call", WN, f"HTTP 401 — invalid key ({resp_ms:.0f}ms)")
            else:
                check("  LLM API call", WN, f"HTTP {r.status_code} ({resp_ms:.0f}ms)")
        except Exception as e:
            check("  LLM live test", WN, str(e)[:60])
    else:
        check("  LLM API call", GR, "No API key — skipping LLM test")

    # 4. Camera live test
    try:
        import cv2
        cap = cv2.VideoCapture(0)
        if cap.isOpened():
            ret, frame = cap.read()
            if ret and frame is not None:
                h, w = frame.shape[:2]
                fps_set = cap.get(cv2.CAP_PROP_FPS)
                check("  Camera live", OK, f"{w}x{h}, fps={fps_set:.0f}")
            else:
                check("  Camera live", WN, "opened but no frame")
            cap.release()
        else:
            check("  Camera live", WN, "could not open index 0")
    except Exception as e:
        check("  Camera live test", WN, str(e)[:60])

    # ── Hardware ────────────────────────────────────────────
    section("Hardware")

    try:
        from hardware import MotorController, BatteryMonitor

        mc = MotorController()
        if mc.is_available():
            check("MotorController available", OK, f"port={mc._port}, baud={mc._baudrate}")

            ok = mc.center_servos()
            check("Center servos", OK if ok else WN, "sent" if ok else "send failed")

            ok = mc.stop()
            check("Stop motors", OK if ok else WN, "sent" if ok else "send failed")

            t0 = time.monotonic()
            battery_found = False
            while time.monotonic() - t0 < 2.0:
                line = mc.read_line()
                if line and line.startswith("BAT:"):
                    try:
                        v = float(line[4:])
                        check("Battery voltage", OK, f"{v:.2f}V")
                        battery_found = True
                        break
                    except ValueError:
                        pass
            if not battery_found:
                check("Battery voltage", GR, "no BAT: packet (expected if ESP32 not connected)")
        else:
            check("MotorController available", WN, "serial port not available — skipping hardware tests")

        bm = BatteryMonitor(motor_controller=mc)
        bm.start()
        bm.stop()
        check("BatteryMonitor lifecycle", OK, "construct → start → stop")
    except Exception as e:
        check("Hardware section", ER, str(e)[:70])

    # ── Integration ───────────────────────────────────────────────
    section("Integration")

    try:
        os.environ["SDL_VIDEODRIVER"] = "dummy"
        from voice.face import FaceModule
        f = FaceModule()
        f.start()
        f.stop()
        check("FaceModule instantiate", OK)
    except Exception as e:
        check("FaceModule instantiate", ER, str(e)[:60])

    try:
        from config.settings import get_settings
        s = get_settings()
        from voice.tts import TTSModule
        tts = TTSModule(s.tts)
        check("TTSModule instantiate", OK)
        del tts
    except Exception as e:
        check("TTSModule instantiate", WN, str(e)[:60])

    try:
        from llm.module import LLMModule
        llm = LLMModule()
        check("LLMModule instantiate (DB)", OK)
    except Exception as e:
        check("LLMModule instantiate (DB)", ER, str(e)[:60])

    try:
        from vision.pipeline import VisionPipeline
        vp = VisionPipeline()
        check("VisionPipeline instantiate", OK, "camera not opened")
    except Exception as e:
        check("VisionPipeline instantiate", ER, str(e)[:60])

    try:
        from voice.pipeline import VoicePipeline
        from llm.module import LLMModule
        from voice.tts import TTSModule
        s = get_settings()
        llm = LLMModule()
        tts = TTSModule(s.tts)
        sid = llm.create_session("health", "en")
        vpipeline = VoicePipeline(llm=llm, tts_module=tts, session_id=sid)
        check("VoicePipeline instantiate", OK, "not opened")
    except Exception as e:
        check("VoicePipeline instantiate", ER, str(e)[:60])

    try:
        from hardware import MotorController, BatteryMonitor
        i_mc = MotorController()
        i_bm = BatteryMonitor(motor_controller=i_mc)
        i_mc.close()
        check("Hardware integration", OK, "MotorController + BatteryMonitor lifecycle")
    except Exception as e:
        check("Hardware integration", ER, str(e)[:60])

    # ── Summary ───────────────────────────────────────────────────
    print()
    print(ansi("=" * 56, "1"))

    passed = sum(1 for _, s, _ in RESULTS if s == OK)
    warned = sum(1 for _, s, _ in RESULTS if s == WN)
    errors = sum(1 for _, s, _ in RESULTS if s == ER)
    skipped = sum(1 for _, s, _ in RESULTS if s in (GR, SK))
    total = len(RESULTS)
    score = f"{passed}/{total} passed ({warned} warnings, {errors} errors, {skipped} skipped)"

    if errors:
        print(ansi(f"  SCORE: {score}", "91"))
    elif warned:
        print(ansi(f"  SCORE: {score}", "93"))
    else:
        print(ansi(f"  SCORE: {score}", "92"))

    pct = (passed / total * 100) if total > 0 else 0
    if pct >= 90:
        readiness = "READY — run python main.py"
    elif pct >= 70:
        readiness = "MOSTLY READY — check warnings above"
    else:
        readiness = "NOT READY — fix errors above"

    print(ansi(f"  Readiness: {readiness}", "1"))
    print(ansi("=" * 56, "1"))
    print()

    # ── Save report ───────────────────────────────────────────────
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("ROPE HEALTH CHECK REPORT\n")
        f.write(f"Timestamp: {datetime.now().isoformat()}\n")
        f.write(f"Platform: {platform.system()} {platform.release()}\n")
        f.write(f"Python: {sys.version.split(chr(10))[0]}\n")
        f.write(f"CPU cores: {os.cpu_count()}\n")
        if is_pi():
            f.write(f"Raspberry Pi: {pi_model()}\n")
        f.write(f"Working directory: {ROOT}\n")
        f.write("=" * 56 + "\n\n")
        for line in REPORT_LINES:
            f.write(line + "\n")
        f.write("\n" + "=" * 56 + "\n")
        f.write(f"SCORE: {score}\n")
        f.write(f"Readiness: {readiness}\n")

    print(f"Full report saved to {report_path}")


if __name__ == "__main__":
    main()
