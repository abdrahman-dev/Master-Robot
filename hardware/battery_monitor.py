"""
Battery monitor — reads voltage from ESP32 via serial, triggers Pi shutdown at low voltage.
ESP32 sends lines like: BAT:8.12
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Optional, Callable

logger = logging.getLogger(__name__)

LOW_VOLTAGE_THRESHOLD = 7.2   # volts — warn and start countdown
CRITICAL_VOLTAGE_THRESHOLD = 6.8  # volts — immediate shutdown
WARN_COUNTDOWN_SECONDS = 30
CHECK_INTERVAL = 0.5  # seconds between read attempts


class BatteryMonitor:
    def __init__(
        self,
        motor_controller,
        on_low_battery: Optional[Callable[[float], None]] = None,
        on_shutdown: Optional[Callable[[], None]] = None,
        on_update: Optional[Callable[[float], None]] = None,
    ):
        self._motor = motor_controller
        self._on_low_battery = on_low_battery
        self._on_shutdown = on_shutdown
        self._on_update = on_update
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._voltage: float = 99.0  # unknown initially
        self._warning_started: Optional[float] = None
        self._lock = threading.Lock()

    def get_voltage(self) -> float:
        with self._lock:
            return self._voltage

    def start(self) -> None:
        if not self._motor.is_available():
            logger.warning("[battery] Motor controller not available — battery monitor disabled")
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("[battery] Monitor started")

    def stop(self) -> None:
        self._running = False

    def _run(self) -> None:
        while self._running:
            line = self._motor.read_line()
            if line and line.startswith("BAT:"):
                try:
                    voltage = float(line[4:])
                    with self._lock:
                        self._voltage = voltage
                    logger.debug("[battery] Voltage: %.2fV", voltage)
                    if self._on_update:
                        self._on_update(voltage)
                    self._check_voltage(voltage)
                except ValueError:
                    pass
            time.sleep(CHECK_INTERVAL)

    def _check_voltage(self, voltage: float) -> None:
        if voltage <= CRITICAL_VOLTAGE_THRESHOLD:
            logger.critical("[battery] CRITICAL voltage %.2fV — shutting down NOW", voltage)
            if self._on_shutdown:
                self._on_shutdown()
            self._do_shutdown()
            return

        if voltage <= LOW_VOLTAGE_THRESHOLD:
            if self._warning_started is None:
                self._warning_started = time.monotonic()
                logger.warning("[battery] Low voltage %.2fV — shutdown in %ds", voltage, WARN_COUNTDOWN_SECONDS)
                if self._on_low_battery:
                    self._on_low_battery(voltage)
            else:
                elapsed = time.monotonic() - self._warning_started
                remaining = WARN_COUNTDOWN_SECONDS - elapsed
                if remaining <= 0:
                    logger.critical("[battery] Countdown expired — shutting down")
                    if self._on_shutdown:
                        self._on_shutdown()
                    self._do_shutdown()
        else:
            if self._warning_started is not None:
                logger.info("[battery] Voltage recovered to %.2fV", voltage)
            self._warning_started = None

    def _do_shutdown(self) -> None:
        logger.critical("[battery] Sending stop/center to motors...")
        self._motor.stop()
        self._motor.center_servos()
        time.sleep(0.15)
        logger.critical("[battery] Executing: sudo shutdown -h now")
        os.system("sudo shutdown -h now")
