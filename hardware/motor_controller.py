import logging
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Pose:
    head: int = 90
    right_arm: int = 90
    left_arm: int = 90


class MotorController:
    POSE_CENTER = Pose()
    POSE_IDLE = Pose()

    def __init__(self, port: str = "/dev/serial0", baudrate: int = 115200, timeout: float = 1.0):
        self._port = port
        self._baudrate = baudrate
        self._timeout = timeout
        self._serial: Optional[object] = None
        self._available = False

        self._current_speed: int = 180
        self._head_angle: int = 90
        self._right_arm_angle: int = 90
        self._left_arm_angle: int = 90

        try:
            import serial as pyserial
            self._serial = pyserial.Serial(port=port, baudrate=baudrate, timeout=timeout)
            self._available = True
            logger.info("[motor] Connected on %s at %d baud", port, baudrate)
        except ImportError:
            logger.warning("[motor] pyserial not installed — motor controller disabled")
        except Exception as e:
            logger.warning("[motor] Could not open %s: %s — motor controller disabled", port, e)

    # ── public helpers ────────────────────────────────────────

    def is_available(self) -> bool:
        return self._available

    # ── internal helpers ──────────────────────────────────────

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

    def _send_motion(self, command: str, duration_ms: int = 0) -> bool:
        if duration_ms > 0:
            return self._send(f"{command}{duration_ms}")
        return self._send(command)

    def _send_servo(self, name: str, angle: int) -> bool:
        return self._send(f"{name}:{angle}")

    # ── motion commands ───────────────────────────────────────

    def forward(self, duration_ms: int = 0) -> bool:
        return self._send_motion("F", duration_ms)

    def backward(self, duration_ms: int = 0) -> bool:
        return self._send_motion("B", duration_ms)

    def turn_left(self, duration_ms: int = 0) -> bool:
        return self._send_motion("L", duration_ms)

    def turn_right(self, duration_ms: int = 0) -> bool:
        return self._send_motion("R", duration_ms)

    def stop(self) -> bool:
        return self._send("S")

    def set_speed(self, speed: int) -> bool:
        speed = max(0, min(255, int(speed)))
        result = self._send(f"SPD:{speed}")
        if result:
            self._current_speed = speed
        return result

    # ── servo commands ────────────────────────────────────────

    def move_head(self, angle: int) -> bool:
        angle = max(0, min(180, int(angle)))
        result = self._send_servo("HEAD", angle)
        if result:
            self._head_angle = angle
        return result

    def move_arm_right(self, angle: int) -> bool:
        angle = max(0, min(180, int(angle)))
        result = self._send_servo("ARM_R", angle)
        if result:
            self._right_arm_angle = angle
        return result

    def move_arm_left(self, angle: int) -> bool:
        angle = max(0, min(180, int(angle)))
        result = self._send_servo("ARM_L", angle)
        if result:
            self._left_arm_angle = angle
        return result

    def happy(self) -> bool:
        return self._send("HAPPY")

    def center_servos(self) -> bool:
        pose = self.POSE_CENTER
        self._head_angle = pose.head
        self._right_arm_angle = pose.right_arm
        self._left_arm_angle = pose.left_arm
        return self._send("CENTER")

    # ── cached state properties ───────────────────────────────

    @property
    def speed(self) -> int:
        return self._current_speed

    @property
    def head_angle(self) -> int:
        return self._head_angle

    @property
    def left_arm_angle(self) -> int:
        return self._left_arm_angle

    @property
    def right_arm_angle(self) -> int:
        return self._right_arm_angle

    # ── pose API ──────────────────────────────────────────────

    def apply_pose(self, head: Optional[int] = None, right_arm: Optional[int] = None, left_arm: Optional[int] = None) -> None:
        if head is not None:
            self.move_head(head)
        if right_arm is not None:
            self.move_arm_right(right_arm)
        if left_arm is not None:
            self.move_arm_left(left_arm)

    # ── serial I/O ────────────────────────────────────────────

    def read_line(self) -> Optional[str]:
        """Read one line from ESP32 if available. Returns None if nothing available."""
        if not self._available or self._serial is None:
            return None
        try:
            if self._serial.in_waiting > 0:
                line = self._serial.readline().decode("utf-8", errors="replace").strip()
                return line if line else None
        except Exception as e:
            logger.warning("[motor] Read failed: %s", e)
        return None

    # ── lifecycle ─────────────────────────────────────────────

    def close(self):
        self.stop()
        self.center_servos()
        time.sleep(0.15)
        if self._serial is not None and self._serial.is_open:
            try:
                self._serial.close()
                logger.info("[motor] Serial port closed")
            except Exception as e:
                logger.warning("[motor] Error closing serial: %s", e)
        self._available = False
