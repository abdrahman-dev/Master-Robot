from __future__ import annotations

import logging
import os
import socket
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
        # TCP configuration read from environment
        self._esp32_ip = os.getenv("ROBOT_ESP32_IP", "192.168.149.254")
        self._esp32_port = int(os.getenv("ROBOT_ESP32_PORT", "3333"))
        self._timeout = timeout

        # Backward-compat attributes (used by diagnostics tool)
        self._requested_port = f"{self._esp32_ip}:{self._esp32_port}"
        self._port = self._requested_port
        self._baudrate = 0
        self._auto_detected = False

        self._sock: Optional[socket.socket] = None
        self._available = False
        self._recv_buffer = ""

        self._current_speed: int = 180
        self._head_angle: int = 90
        self._right_arm_angle: int = 90
        self._left_arm_angle: int = 90

        self._connect()

    # ── public API: properties ────────────────────────────────

    def is_available(self) -> bool:
        return self._available

    @property
    def port(self) -> str:
        return self._port

    @property
    def requested_port(self) -> str:
        return self._requested_port

    @property
    def auto_detected(self) -> bool:
        return self._auto_detected

    # ── internal helpers: TCP transport ───────────────────────

    def _connect(self) -> bool:
        try:
            sock = socket.create_connection(
                (self._esp32_ip, self._esp32_port),
                timeout=self._timeout,
            )
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.settimeout(0.0)
            self._sock = sock
            self._available = True
            logger.info(
                "[motor] Connected to ESP32 at %s:%d",
                self._esp32_ip, self._esp32_port,
            )
            return True
        except (OSError, socket.gaierror) as e:
            logger.warning("[motor] Could not connect to %s:%d — %s", self._esp32_ip, self._esp32_port, e)
            self._sock = None
            self._available = False
            return False

    def _handle_disconnect(self):
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        self._available = False
        self._recv_buffer = ""

    # ── internal helpers: commands ────────────────────────────

    def _send(self, command: str) -> bool:
        if not self._available:
            self._connect()
        if not self._available or self._sock is None:
            return False
        try:
            payload = (command + "\n").encode("utf-8")
            self._sock.sendall(payload)
            logger.debug("[motor] Sent: %s", command)
            time.sleep(0.05)
            return True
        except (OSError, socket.timeout) as e:
            logger.warning("[motor] Send failed: %s", e)
            self._handle_disconnect()
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

    # ── TCP I/O ────────────────────────────────────────────────

    def read_line(self) -> Optional[str]:
        if not self._available or self._sock is None:
            return None
        try:
            data = self._sock.recv(4096)
            if not data:
                self._handle_disconnect()
                return None
            self._recv_buffer += data.decode("utf-8", errors="replace")
            if "\n" in self._recv_buffer:
                line, self._recv_buffer = self._recv_buffer.split("\n", 1)
                line = line.strip()
                return line if line else None
        except (BlockingIOError, socket.timeout):
            pass
        except (OSError, ConnectionError) as e:
            logger.warning("[motor] Read failed: %s", e)
            self._handle_disconnect()
        return None

    # ── lifecycle ─────────────────────────────────────────────

    def close(self):
        self.stop()
        self.center_servos()
        time.sleep(0.15)
        if self._sock is not None:
            try:
                self._sock.close()
                logger.info("[motor] TCP socket closed")
            except Exception as e:
                logger.warning("[motor] Error closing socket: %s", e)
            self._sock = None
        self._available = False
