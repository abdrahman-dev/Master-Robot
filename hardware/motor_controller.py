import glob
import logging
import os
import sys
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
        self._requested_port = port
        self._port = port
        self._baudrate = baudrate
        self._timeout = timeout
        self._serial: Optional[object] = None
        self._available = False
        self._auto_detected = False

        self._current_speed: int = 180
        self._head_angle: int = 90
        self._right_arm_angle: int = 90
        self._left_arm_angle: int = 90

        auto_detect = os.getenv("ROBOT_MOTOR_AUTO_DETECT", "true").lower() in ("1", "true", "yes")
        verify_timeout = float(os.getenv("ROBOT_MOTOR_VERIFY_TIMEOUT_SEC", "2.0"))

        try:
            import serial as pyserial
        except ImportError:
            logger.warning("[motor] pyserial not installed — motor controller disabled")
            return

        # Step 1: Try the configured (requested) port
        ser = self._try_open_port(pyserial, port)
        if ser is not None:
            self._serial = ser
            self._available = True
            logger.info("[motor] Connected on configured port %s at %d baud", port, baudrate)
            return

        if not auto_detect:
            logger.warning(
                "[motor] Configured port %s unavailable and auto-detection disabled — "
                "motor controller disabled", port
            )
            return

        # Step 2: Auto-detection
        logger.info("[motor] Configured port %s unavailable — starting auto-detection", port)
        detected = self._auto_detect(pyserial, verify_timeout)
        if detected is not None:
            self._serial = detected
            self._auto_detected = True
            self._available = True
            logger.info("[motor] Auto-detected ESP32 on %s at %d baud", self._port, baudrate)
        else:
            logger.warning("[motor] No valid serial device found — motor controller disabled")

    # ── public API: properties ────────────────────────────────

    def is_available(self) -> bool:
        return self._available

    @property
    def port(self) -> str:
        """The port currently connected to (may differ from requested_port if auto-detected)."""
        return self._port

    @property
    def requested_port(self) -> str:
        """The port that was originally requested / configured via .env."""
        return self._requested_port

    @property
    def auto_detected(self) -> bool:
        """True if the port was found via auto-detection rather than the configured value."""
        return self._auto_detected

    # ── internal helpers ──────────────────────────────────────

    def _try_open_port(self, pyserial_module, port: str) -> Optional[object]:
        """Attempt to open *port* and return the Serial object, or None on failure."""
        try:
            ser = pyserial_module.Serial(
                port=port, baudrate=self._baudrate, timeout=self._timeout
            )
            logger.debug("[motor] Opened %s", port)
            return ser
        except Exception as e:
            logger.debug("[motor] Could not open %s: %s", port, e)
            return None

    def _get_candidate_ports(self) -> list[str]:
        """Return a list of serial-port paths to try during auto-detection."""
        candidates: list[str] = []

        if sys.platform == "win32":
            try:
                import serial.tools.list_ports as lp
                candidates = [p.device for p in lp.comports()]
            except Exception:
                logger.debug("[motor] serial.tools.list_ports not available")
        else:
            patterns = [
                "/dev/serial0",
                "/dev/serial1",
                "/dev/ttyAMA*",
                "/dev/ttyS*",
                "/dev/ttyUSB*",
                "/dev/ttyACM*",
            ]
            for pattern in patterns:
                candidates.extend(glob.glob(pattern))
            # Deduplicate while preserving insertion order
            seen: set[str] = set()
            candidates = [p for p in candidates if not (p in seen or seen.add(p))]

        # Remove the already-tried configured port so we don't retry it
        return [p for p in candidates if p != self._requested_port]

    def _verify_esp32(self, ser, timeout_sec: float) -> bool:
        """
        Wait up to *timeout_sec* seconds for a valid ESP32 response.
        Returns True if either the startup banner or a battery packet is seen.
        """
        start = time.monotonic()
        buf = ""
        while time.monotonic() - start < timeout_sec:
            try:
                if ser.in_waiting > 0:
                    raw = ser.read(ser.in_waiting)
                    buf += raw.decode("utf-8", errors="replace")
                    lines = buf.split("\n")
                    for line in lines[:-1]:
                        line = line.strip()
                        if "ROPE Motor Controller Ready" in line or line.startswith("BAT:"):
                            logger.debug("[motor] Verified ESP32 on %s", ser.port)
                            return True
                    buf = lines[-1]
            except Exception:
                pass
            time.sleep(0.05)
        return False

    def _auto_detect(self, pyserial_module, verify_timeout: float) -> Optional[object]:
        """Scan candidate serial ports and return an open, verified Serial object, or None."""
        for port in self._get_candidate_ports():
            ser = self._try_open_port(pyserial_module, port)
            if ser is None:
                continue
            if self._verify_esp32(ser, verify_timeout):
                self._port = port
                return ser
            # Verification failed — close and try the next one
            try:
                ser.close()
            except Exception:
                pass
        return None

    # ── internal helpers: commands ────────────────────────────

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
