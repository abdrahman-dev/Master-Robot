#!/usr/bin/env python3
"""Rope Health Check — standalone diagnostic script."""

import importlib
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

OK = "\033[92mOK\033[0m"
WN = "\033[93mWARN\033[0m"
ER = "\033[91mERROR\033[0m"
GR = "\033[90mINFO\033[0m"

RESULTS = []

PIP_TO_MODULE = {
    "python-dotenv": "dotenv",
    "speechrecognition": "speech_recognition",
    "edge-tts": "edge_tts",
    "opencv-python": "cv2",
}


def check(name, status, detail=""):
    RESULTS.append((name, status, detail))
    print(f"  [{status}] {name:40s} {detail}")


def ansi(s, code):
    return f"\033[{code}m{s}\033[0m"


def main():
    print()
    print(ansi("=" * 56, "1"))
    print(ansi("  ROPE HEALTH CHECK", "1"))
    print(ansi("=" * 56, "1"))
    print()

    # ── 1. Environment ─────────────────────────────────────────
    print(ansi("-- Environment ---------------------------------", "4"))

    pyv = sys.version_info
    if pyv >= (3, 10):
        check("Python version", OK, f"{pyv.major}.{pyv.minor}")
    else:
        check("Python version", ER, f"{pyv.major}.{pyv.minor} (need >=3.10)")

    req_path = ROOT / "requirements.txt"
    if req_path.exists():
        with open(req_path) as f:
            pkgs = [line.split("#")[0].strip() for line in f if line.strip() and not line.startswith("#")]
        for pkg_line in pkgs:
            pkg_name = pkg_line.split(">=")[0].split("==")[0].strip()
            mod_name = PIP_TO_MODULE.get(pkg_name, pkg_name.replace("-", "_"))
            try:
                importlib.import_module(mod_name)
                check(f"  dep: {pkg_name}", OK)
            except ImportError as e:
                check(f"  dep: {pkg_name}", ER, str(e).split(":")[-1].strip())
    else:
        check("requirements.txt", ER, "not found")

    env_path = ROOT / ".env"
    if env_path.exists():
        check(".env file", OK)
    else:
        check(".env file", WN, "not found, env vars may be missing")

    required_env = ["ROBOT_OPENROUTER_API_KEY"]
    for key in required_env:
        val = os.getenv(key, "")
        if val:
            check(f"  {key}", OK, "set")
        else:
            check(f"  {key}", GR, "optional — will use offline mode")

    try:
        import edge_tts
        check("edge_tts", OK, edge_tts.__version__ if hasattr(edge_tts, "__version__") else "installed")
    except ImportError as e:
        check("edge_tts", ER, str(e).split(":")[-1].strip())

    models_dir = ROOT / "models"
    check("models/", OK if models_dir.exists() else ER)

    data_dir = ROOT / "data"
    writable = os.access(str(data_dir), os.W_OK) if data_dir.exists() else False
    check("data/ writable", OK if writable else WN)

    try:
        import shutil
        total, used, free = shutil.disk_usage(str(ROOT))
        free_gb = free // (2 ** 30)
        check("Disk free", OK if free_gb >= 1 else WN, f"{free_gb}GB")
    except Exception:
        check("Disk free", WN, "unable to check")

    try:
        import psutil
        mem = psutil.virtual_memory()
        free_mb = mem.available / (1024 * 1024)
        check("RAM available", OK if free_mb >= 2000 else WN, f"{free_mb:.0f}MB")
    except ImportError:
        check("RAM available", GR, "install psutil for detail")

    # ── 2. Hardware (non-fatal) ────────────────────────────────
    print()
    print(ansi("-- Hardware -----------------------------------", "4"))

    try:
        import sounddevice as sd
        devices = sd.query_devices()
        has_input = any(d["max_input_channels"] > 0 for d in devices)
        has_output = any(d["max_output_channels"] > 0 for d in devices)
        input_name = ""
        output_name = ""
        for d in devices:
            if d["max_input_channels"] > 0 and not input_name:
                input_name = d["name"]
            if d["max_output_channels"] > 0 and not output_name:
                output_name = d["name"]
        check("Microphone", OK if has_input else WN, input_name or "none found")
        if has_input:
            try:
                with sd.InputStream(samplerate=16000, channels=1, blocksize=480):
                    check("  sd.InputStream opens", OK)
            except Exception as e:
                check("  sd.InputStream opens", WN, str(e)[:60])
        check("Speaker", OK if has_output else WN, output_name or "none found")
    except Exception as e:
        check("sounddevice", ER, str(e)[:60])

    try:
        import cv2
        cap = cv2.VideoCapture(0)
        if cap.isOpened():
            ret, frame = cap.read()
            if ret and frame is not None:
                h, w = frame.shape[:2]
                check("Camera", OK, f"{w}x{h}")
            else:
                check("Camera", WN, "opened but no frame")
            cap.release()
        else:
            check("Camera", WN, "could not open index 0")
    except Exception as e:
        check("Camera", WN, str(e)[:60])

    if sys.platform == "linux":
        try:
            import multiprocessing
            cpu_count = multiprocessing.cpu_count()
            freq = ""
            try:
                with open("/proc/cpuinfo") as f:
                    for line in f:
                        if "model name" in line:
                            freq = line.split(":")[-1].strip()[:60]
                            break
            except Exception:
                pass
            check("Platform", GR, f"{cpu_count} cores | {freq}")
        except Exception:
            check("Platform", GR, "linux")

    # ── 3. Network ─────────────────────────────────────────────
    print()
    print(ansi("-- Network ------------------------------------", "4"))

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

    api_key = os.getenv("ROBOT_OPENROUTER_API_KEY", "")
    if api_key:
        try:
            import requests
            t0 = time.time()
            r = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                json={
                    "model": "liquid/lfm-2.5-1.2b-instruct:free",
                    "messages": [{"role": "user", "content": "hello"}],
                    "max_tokens": 1,
                },
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                timeout=10,
            )
            latency = time.time() - t0
            status = r.status_code
            if status == 200:
                check("OpenRouter API call", OK, f"{latency:.1f}s")
            elif status == 401:
                check("OpenRouter API call", WN, "HTTP 401 — invalid key")
            else:
                check("OpenRouter API call", WN, f"HTTP {status}")
        except Exception as e:
            check("OpenRouter API call", WN, str(e)[:50])

    # ── 4. Module imports ─────────────────────────────────────
    print()
    print(ansi("-- Module Imports -----------------------------", "4"))

    modules = [
        "voice.vad", "voice.asr", "voice.tts", "voice.face",
        "voice.pipeline", "vision.camera", "vision.pipeline",
        "vision.modules.face_tracker", "vision.modules.gesture",
        "vision.modules.emotion", "vision.modules.objects",
        "vision.modules.scene", "vision.modules.obstacle",
        "llm.module", "config.settings", "config.diagnostics",
    ]
    for mod_name in modules:
        try:
            importlib.import_module(mod_name)
            check(f"  {mod_name}", OK)
        except Exception as e:
            check(f"  {mod_name}", ER, str(e).split("\n")[0][:70])

    # ── 5. Integration ─────────────────────────────────────────
    print()
    print(ansi("-- Integration --------------------------------", "4"))

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

    # ── Summary ────────────────────────────────────────────────
    print()
    print(ansi("=" * 56, "1"))
    passed = sum(1 for _, s, _ in RESULTS if s == OK)
    warned = sum(1 for _, s, _ in RESULTS if s == WN)
    errors = sum(1 for _, s, _ in RESULTS if s == ER)
    total = len(RESULTS)
    score = f"{passed}/{total} passed ({warned} warnings, {errors} errors)"
    if errors:
        print(ansi(f"  SCORE: {score}", "91"))
    elif warned:
        print(ansi(f"  SCORE: {score}", "93"))
    else:
        print(ansi(f"  SCORE: {score}", "92"))
    print(ansi("=" * 56, "1"))
    print()

    report_path = ROOT / "health_report.txt"
    with open(report_path, "w") as f:
        f.write("ROPE HEALTH CHECK REPORT\n")
        f.write("=" * 50 + "\n\n")
        for name, status, detail in RESULTS:
            f.write(f"[{status}] {name} {detail}\n".strip() + "\n")
        f.write(f"\nSCORE: {score}\n")
    print(f"Full report saved to {report_path}")


if __name__ == "__main__":
    main()
