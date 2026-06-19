from __future__ import annotations

import gc
import logging
import os
import shutil
import socket
import threading
import time
from pathlib import Path
from typing import Optional, Dict, Callable

from config.settings import get_settings, IS_RASPBERRY_PI

logger = logging.getLogger(__name__)

_SETTINGS = get_settings()


# ── Temperature ────────────────────────────────────────────────────

def get_cpu_temperature() -> Optional[float]:
    if not IS_RASPBERRY_PI:
        return None
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return int(f.read().strip()) / 1000.0
    except (FileNotFoundError, IOError, ValueError):
        return None


THERMAL_THROTTLE_C = 75.0
THERMAL_RESTORE_C = 65.0


# ── Startup diagnostics ───────────────────────────────────────────

def run_startup_diagnostics() -> Dict[str, str]:
    results = {}

    try:
        import sounddevice as sd
        devices = sd.query_devices()
        has_input = any(d["max_input_channels"] > 0 for d in devices)
        results["microphone"] = "ok" if has_input else "no input device"
    except Exception as e:
        results["microphone"] = f"error: {e}"

    try:
        import sounddevice as sd
        devices = sd.query_devices()
        has_output = any(d["max_output_channels"] > 0 for d in devices)
        results["speaker"] = "ok" if has_output else "no output device"
    except Exception as e:
        results["speaker"] = f"error: {e}"

    try:
        import cv2
        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        ret = cap.grab()
        cap.release()
        results["camera"] = "ok" if ret else "not accessible"
    except Exception as e:
        results["camera"] = f"error: {e}"

    settings = get_settings()
    for model_name, path in [
        ("face_proto", settings.paths.models_dir / settings.paths.face_proto_name),
        ("face_weights", settings.paths.models_dir / settings.paths.face_weights_name),
        ("yolov8s", settings.paths.models_dir / "yolov8s.pt"),
        ("yolov8s-seg", settings.paths.models_dir / "yolov8s-seg.pt"),
        ("emotion", settings.paths.models_dir / "emotion_cnn_pytorch.pt"),
    ]:
        if not path.exists():
            results[f"model_{model_name}"] = "missing"
        elif path.stat().st_size < 1_000_000:
            results[f"model_{model_name}"] = "corrupted (too small)"
        else:
            results[f"model_{model_name}"] = "ok"

    try:
        total, used, free = shutil.disk_usage(settings.paths.project_root)
        free_gb = free // (2**30)
        results["disk_free_gb"] = str(free_gb)
        results["disk"] = "ok" if free_gb > 1 else "low space"
    except Exception as e:
        results["disk"] = f"error: {e}"

    try:
        import psutil
        mem = psutil.virtual_memory()
        results["ram_total_gb"] = f"{mem.total / (1024**3):.1f}"
        results["ram_available_gb"] = f"{mem.available / (1024**3):.1f}"
        results["ram"] = "ok" if mem.available > 512 * 1024 * 1024 else "low"
    except ImportError:
        results["ram"] = "unknown (install psutil)"

    try:
        socket.setdefaulttimeout(3)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(
            ("8.8.8.8", 53)
        )
        results["internet"] = "ok"
    except Exception:
        results["internet"] = "not reachable"

    return results


def print_diagnostics(results: Dict[str, str]) -> None:
    print("=" * 50)
    print("STARTUP DIAGNOSTICS")
    print("=" * 50)
    for key, value in results.items():
        icon = "OK" if value == "ok" else "!!"
        print(f"  [{icon}] {key}: {value}")
    print("=" * 50)


# ── Memory cleanup ────────────────────────────────────────────────

_last_gc = 0.0
_GC_INTERVAL = 60.0

def periodic_gc(force: bool = False) -> None:
    global _last_gc
    now = time.monotonic()
    if force or (now - _last_gc > _GC_INTERVAL):
        collected = gc.collect()
        _last_gc = now
        if collected > 0:
            logger.debug("[gc] Collected %d objects", collected)


# ── Watchdog ──────────────────────────────────────────────────────

class Watchdog:
    def __init__(self):
        self._components: Dict[str, float] = {}
        self._lock = threading.Lock()
        self._timeout: Dict[str, float] = {}
        self._callbacks: Dict[str, Callable] = {}
        self._running = False

    def register(self, name: str, timeout_sec: float = 30.0,
                 on_stale: Optional[Callable] = None) -> None:
        with self._lock:
            self._components[name] = time.monotonic()
            self._timeout[name] = timeout_sec
            if on_stale:
                self._callbacks[name] = on_stale

    def ping(self, name: str) -> None:
        with self._lock:
            self._components[name] = time.monotonic()

    def start(self) -> threading.Thread:
        self._running = True
        t = threading.Thread(target=self._run, daemon=True)
        t.start()
        return t

    def stop(self) -> None:
        self._running = False

    def _run(self) -> None:
        while self._running:
            now = time.monotonic()
            with self._lock:
                for name, last in list(self._components.items()):
                    elapsed = now - last
                    if elapsed > self._timeout.get(name, 30.0):
                        logger.warning("[watchdog] %s stale for %.0fs", name, elapsed)
                        cb = self._callbacks.get(name)
                        if cb:
                            try:
                                cb()
                            except Exception as e:
                                logger.error("[watchdog] callback %s failed: %s", name, e)
            time.sleep(10.0)


# ── System monitor metrics ────────────────────────────────────────

class SystemMonitor:
    def __init__(self):
        self._fps_history = []
        self._lock = threading.Lock()

    def record_fps(self, fps: float) -> None:
        with self._lock:
            self._fps_history.append(fps)
            if len(self._fps_history) > 100:
                self._fps_history.pop(0)

    def get_average_fps(self) -> float:
        with self._lock:
            if not self._fps_history:
                return 0.0
            return sum(self._fps_history) / len(self._fps_history)

    def get_overlay_text(self) -> str:
        avg_fps = self.get_average_fps()
        temp = get_cpu_temperature()
        parts = [f"FPS: {avg_fps:.1f}"]
        if temp is not None:
            parts.append(f"Temp: {temp:.0f}C")
        return " | ".join(parts)
