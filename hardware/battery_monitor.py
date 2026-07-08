"""
Battery monitor — reads voltage from ESP32 via TCP, triggers Pi shutdown at low voltage.
ESP32 sends lines like: BAT:8.12
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class BatteryMonitor:
    def __init__(
        self,
        motor_controller,
        on_low_battery: Optional[Callable[[float], None]] = None,
        on_shutdown: Optional[Callable[[], None]] = None,
        on_update: Optional[Callable[[float], None]] = None,
        settings=None,
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

        if settings is not None:
            self._low_voltage = settings.low_voltage_threshold
            self._critical_voltage = settings.critical_voltage_threshold
            self._countdown = settings.shutdown_countdown_sec
            self._check_interval = settings.poll_interval_sec
        else:
            self._low_voltage = float(os.getenv("ROBOT_BATTERY_LOW_VOLTAGE", "7.1"))
            self._critical_voltage = float(os.getenv("ROBOT_BATTERY_CRITICAL_VOLTAGE", "6.5"))
            self._countdown = int(os.getenv("ROBOT_BATTERY_WARN_COUNTDOWN_SEC", "30"))
            self._check_interval = float(os.getenv("ROBOT_BATTERY_CHECK_INTERVAL_SEC", "0.5"))

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
            time.sleep(self._check_interval)

    def _check_voltage(self, voltage: float) -> None:
        if voltage <= self._critical_voltage:
            logger.critical("[battery] CRITICAL voltage %.2fV — shutting down NOW", voltage)
            if self._on_shutdown:
                self._on_shutdown()
            self._do_shutdown()
            return

        if voltage <= self._low_voltage:
            if self._warning_started is None:
                self._warning_started = time.monotonic()
                logger.warning("[battery] Low voltage %.2fV — shutdown in %ds", voltage, self._countdown)
                if self._on_low_battery:
                    self._on_low_battery(voltage)
            else:
                elapsed = time.monotonic() - self._warning_started
                remaining = self._countdown - elapsed
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
