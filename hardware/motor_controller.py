import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)


class MotorController:
    def __init__(self, port: str = "/dev/ttyS0", baudrate: int = 115200, timeout: float = 1.0):
        self._port = port
        self._baudrate = baudrate
        self._timeout = timeout
        self._serial: Optional[object] = None
        self._available = False

        try:
            import serial as pyserial
            self._serial = pyserial.Serial(port=port, baudrate=baudrate, timeout=timeout)
            self._available = True
            logger.info("[motor] Connected on %s at %d baud", port, baudrate)
        except ImportError:
            logger.warning("[motor] pyserial not installed — motor controller disabled")
        except Exception as e:
            logger.warning("[motor] Could not open %s: %s — motor controller disabled", port, e)

    def is_available(self) -> bool:
        return self._available

    def _send(self, command: str) -> bool:
        if not self._available or self._serial is None:
            return False
        try:
            payload = (command + "\n").encode("utf-8")
            self._serial.write(payload)
            logger.debug("[motor] Sent: %s", command)
            time.sleep(0.05)
            return True
        except Exception as e:
            logger.warning("[motor] Send failed: %s", e)
            return False

    def forward(self, duration_ms: int = 0) -> bool:
        if duration_ms > 0:
            return self._send(f"F{duration_ms}")
        return self._send("F")

    def backward(self, duration_ms: int = 0) -> bool:
        if duration_ms > 0:
            return self._send(f"B{duration_ms}")
        return self._send("B")

    def turn_left(self, duration_ms: int = 0) -> bool:
        if duration_ms > 0:
            return self._send(f"L{duration_ms}")
        return self._send("L")

    def turn_right(self, duration_ms: int = 0) -> bool:
        if duration_ms > 0:
            return self._send(f"R{duration_ms}")
        return self._send("R")

    def stop(self) -> bool:
        return self._send("S")

    def set_speed(self, speed: int) -> bool:
        speed = max(0, min(255, int(speed)))
        return self._send(f"SPD:{speed}")

    def close(self):
        if self._serial is not None and self._serial.is_open:
            try:
                self._serial.close()
                logger.info("[motor] Serial port closed")
            except Exception as e:
                logger.warning("[motor] Error closing serial: %s", e)
        self._available = False
