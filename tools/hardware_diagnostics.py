#!/usr/bin/env python3
"""
ROPE hardware diagnostics and calibration utility.

Standalone — depends only on the ``hardware`` package (MotorController,
BatteryMonitor) and the Python standard library.  No Voice / Vision / LLM /
TTS modules are imported.

Usage
-----
    python tools/hardware_diagnostics.py

When no ESP32 is connected the menu still works; every command shows
"[motor] Send failed" warnings and no hardware is harmed.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hardware import MotorController, BatteryMonitor

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CALIBRATION_PATH = Path(__file__).resolve().parent.parent / "calibration.json"

# ---------------------------------------------------------------------------
# Safe BatteryMonitor  (overrides the OS-shutdown to just log)
# ---------------------------------------------------------------------------

class SafeBatteryMonitor(BatteryMonitor):
    """Identical to BatteryMonitor but *never* calls ``shutdown -h now``."""

    def _do_shutdown(self) -> None:
        logger.critical("[battery] SHUTDOWN REQUESTED — suppressed in diagnostics mode")
        if self._on_shutdown:
            self._on_shutdown()

# ---------------------------------------------------------------------------
# Calibration state
# ---------------------------------------------------------------------------

@dataclass
class Calibration:
    head_center: int = 90
    head_left: int = 35
    head_right: int = 145
    right_arm_up: int = 135
    right_arm_down: int = 55
    right_arm_center: int = 90
    left_arm_up: int = 45
    left_arm_down: int = 140
    left_arm_center: int = 90


def load_calibration(path: Path = CALIBRATION_PATH) -> Calibration:
    try:
        with open(path) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return Calibration()
    valid_keys = {f.name for f in dataclasses.fields(Calibration)}
    kwargs = {k: v for k, v in data.items() if k in valid_keys}
    return Calibration(**kwargs)


def save_calibration(cal: Calibration, path: Path = CALIBRATION_PATH) -> None:
    with open(path, "w") as f:
        json.dump(dataclasses.asdict(cal), f, indent=2)
    print(f"  Calibration saved to {path}")


def print_calibration(cal: Calibration) -> None:
    print("  ── Calibration state ──")
    for f in dataclasses.fields(cal):
        print(f"    {f.name:<20} = {getattr(cal, f.name):>3}")
    print()

# ---------------------------------------------------------------------------
# Interactive servo calibration helpers
# ---------------------------------------------------------------------------

_SLOT_HELP = {
    "center": "center",
    "left": "left-most position",
    "right": "right-most position",
    "up": "up position",
    "down": "down position",
}


def _prompt_slot(name: str, angle: int) -> Optional[str]:
    """Ask user which calibration slot to save *angle* into.

    Returns the slot key (e.g. ``"head_left"``) or ``None`` to cancel.
    """
    print(f"\n  Save current angle ({angle}) to which slot?")
    print(f"    This servo's slots: {_available_slots(name)}")
    slot = input("  Slot name (or Enter to cancel): ").strip().lower()
    if not slot:
        return None
    full_key = f"{name}_{slot}"
    if full_key in {f.name for f in dataclasses.fields(Calibration)}:
        return full_key
    print(f"  Invalid slot '{slot}' for {name}. Available: {_available_slots(name)}")
    return None


def _available_slots(name: str) -> list[str]:
    prefix = f"{name}_"
    return [
        f.name[len(prefix):]
        for f in dataclasses.fields(Calibration)
        if f.name.startswith(prefix)
    ]


def calibrate_servo(
    mc: MotorController,
    label: str,
    move_fn: Callable[[int], Any],
    get_current: Callable[[], int],
    cal: Calibration,
    cal_prefix: str,
) -> None:
    """Interactive calibration loop for a single servo.

    Keys
    ~~~~
    ``A`` / ``D``  — coarse -5 / +5 degrees
    ``Z`` / ``C``  — fine   -1 / +1 degrees
    ``Space``      — re-send current angle
    ``S``          — save current angle to a calibration slot
    ``P``          — print all saved calibration values
    ``Q`` / Escape — exit calibration
    """
    angle = get_current()
    move_fn(angle)
    print(f"\n  ═════ {label} Calibration ═════")
    print(f"     A/D = ±5°,  Z/C = ±1°,  Space = resend,  S = save slot,  P = print cal,  Q = exit")

    while True:
        print(f"  \r  Current angle: {angle:>3}°  (head={mc.head_angle}, left={mc.left_arm_angle}, right={mc.right_arm_angle})", end="")
        key = _get_key()
        if key == "q":
            print("\n  Exiting calibration.")
            break
        elif key == "a":
            angle = max(0, min(180, angle - 5))
            move_fn(angle)
        elif key == "d":
            angle = max(0, min(180, angle + 5))
            move_fn(angle)
        elif key == "z":
            angle = max(0, min(180, angle - 1))
            move_fn(angle)
        elif key == "c":
            angle = max(0, min(180, angle + 1))
            move_fn(angle)
        elif key == " ":
            move_fn(angle)
            print(f"  \n  Re-sent {angle}")
        elif key == "s":
            full_key = _prompt_slot(cal_prefix, angle)
            if full_key:
                setattr(cal, full_key, angle)
                print(f"  Saved {full_key} = {angle}")
        elif key == "p":
            print()
            print_calibration(cal)


def _get_key() -> str:
    """Read a single keypress from stdin (cross-platform)."""
    try:
        import msvcrt  # Windows

        while True:
            ch = msvcrt.getwch()
            if ch == "\x00" or ch == "\xe0":
                msvcrt.getwch()
                continue
            if ch == "\r":
                return "\n"
            if ch == "\x1b":
                return "q"
            return ch.lower()
    except ImportError:
        import sys
        import termios
        import tty

        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            if ch == "\x1b":
                return "q"
            return ch.lower()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)


# ---------------------------------------------------------------------------
# Calibration edit sub-menu
# ---------------------------------------------------------------------------

def edit_calibration_values(cal: Calibration) -> None:
    """Let the user type new values for every calibration field."""
    print("\n  ═════ Edit Calibration Values ═════")
    print("  Press Enter to keep the current value.\n")
    for f in dataclasses.fields(cal):
        current = getattr(cal, f.name)
        try:
            raw = input(f"    {f.name:<20} [{current:>3}]: ").strip()
            if raw:
                setattr(cal, f.name, int(raw))
        except (ValueError, EOFError):
            pass
    print()
    print_calibration(cal)


# ---------------------------------------------------------------------------
# Test / command helpers
# ---------------------------------------------------------------------------

def test_motion(mc: MotorController, label: str, move_fn: Callable, duration: int = 0) -> None:
    print(f"  Executing: {label}  (duration={duration}ms)")
    move_fn(duration)


def test_speed_menu(mc: MotorController) -> None:
    print(f"  Current speed: {mc.speed}")
    try:
        val = int(input("  Enter new speed (0–255): ").strip())
        mc.set_speed(val)
        print(f"  Speed set to {mc.speed}")
    except (ValueError, EOFError):
        print("  Invalid.")


# ---------------------------------------------------------------------------
# Battery read helpers
# ---------------------------------------------------------------------------

def read_battery_once(mc: MotorController) -> Optional[float]:
    """Poll the serial line for a BAT: message.  Returns the voltage or None."""
    print("  Reading battery (up to 3 seconds)...")
    for _ in range(60):  # 60 * 0.05s = 3s
        line = mc.read_line()
        if line and line.startswith("BAT:"):
            try:
                v = float(line[4:])
                print(f"  Battery voltage: {v:.2f} V")
                return v
            except ValueError:
                pass
        time.sleep(0.05)
    print("  No battery data received — is the ESP32 connected?")
    return None


def live_battery_monitor(mc: MotorController) -> None:
    """Live battery monitor — press Q to quit."""
    print("\n  ═════ Live Battery Monitor ═════")
    print("  Press Q to return to menu.\n")

    def on_update(v: float) -> None:
        print(f"  Battery: {v:.2f} V  (Q=quit)", end="\r")

    monitor = SafeBatteryMonitor(
        motor_controller=mc,
        on_update=on_update,
        on_low_battery=lambda v: print(f"\n  ⚠ LOW BATTERY: {v:.2f} V"),
        on_shutdown=lambda: print("\n  ⚠ SHUTDOWN TRIGGERED (suppressed)"),
    )
    monitor.start()

    try:
        while True:
            if _get_key_blocking(timeout=0.2) == "q":
                break
    finally:
        monitor.stop()
    print("\n  Monitor stopped.")


def _get_key_blocking(timeout: float = 0.0) -> Optional[str]:
    """Like _get_key but with a timeout.  Returns None on timeout."""
    import select
    import sys

    try:
        import msvcrt  # Windows
        if msvcrt.kbhit():
            return msvcrt.getwch().lower()
        return None
    except ImportError:
        # Unix
        import termios
        import tty
        fd = sys.stdin.fileno()
        r, _, _ = select.select([fd], [], [], timeout)
        if not r:
            return None
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            return ch.lower()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)


# ---------------------------------------------------------------------------
# Full hardware test
# ---------------------------------------------------------------------------

def full_hardware_test(mc: MotorController) -> None:
    """Run through every motion and servo command once."""
    print("\n  ═════ Full Hardware Test ═════\n")

    tests = [
        ("Forward (500ms)", lambda: mc.forward(500)),
        ("Backward (500ms)", lambda: mc.backward(500)),
        ("Turn Left (500ms)", lambda: mc.turn_left(500)),
        ("Turn Right (500ms)", lambda: mc.turn_right(500)),
        ("Stop", lambda: mc.stop()),
        ("Set Speed 180", lambda: mc.set_speed(180)),
        ("Set Speed 255", lambda: mc.set_speed(255)),
        ("Set Speed 150", lambda: mc.set_speed(150)),
        ("Head → 0°", lambda: mc.move_head(0)),
        ("Head → 90°", lambda: mc.move_head(90)),
        ("Head → 180°", lambda: mc.move_head(180)),
        ("Head → 90°", lambda: mc.move_head(90)),
        ("Right Arm → 0°", lambda: mc.move_arm_right(0)),
        ("Right Arm → 90°", lambda: mc.move_arm_right(90)),
        ("Right Arm → 180°", lambda: mc.move_arm_right(180)),
        ("Right Arm → 90°", lambda: mc.move_arm_right(90)),
        ("Left Arm → 0°", lambda: mc.move_arm_left(0)),
        ("Left Arm → 90°", lambda: mc.move_arm_left(90)),
        ("Left Arm → 180°", lambda: mc.move_arm_left(180)),
        ("Left Arm → 90°", lambda: mc.move_arm_left(90)),
        ("Happy Animation", lambda: mc.happy()),
        ("Center All", lambda: mc.center_servos()),
    ]

    failed = []
    for label, fn in tests:
        print(f"  [{label}] ", end="", flush=True)
        ok = fn()
        print("✓" if ok else "✗")
        if not ok:
            failed.append(label)
        time.sleep(0.15)

    # Battery read attempt
    print("\n  [Battery] ", end="", flush=True)
    v = read_battery_once(mc)
    if v is None:
        print("  ✗ (not available)")
        failed.append("Battery")
    else:
        print(f"  ✓  ({v:.2f} V)")

    print(f"\n  ── Results ──")
    print(f"  Passed: {len(tests) - len(failed) + (0 if v is None else 1)}")
    if failed:
        print(f"  Failed: {', '.join(failed)}")
    else:
        print("  All tests passed!")
    print()


# ---------------------------------------------------------------------------
# TCP connection report
# ---------------------------------------------------------------------------

def print_serial_report(mc: MotorController) -> None:
    """Display a summary of the ESP32 TCP connection state."""
    print("  ═════ Motor Controller ═════")
    print(f"  ESP32 IP        : {mc._esp32_ip}")
    print(f"  ESP32 Port      : {mc._esp32_port}")
    print(f"  Connection      : {mc.requested_port if mc.is_available() else '—'}")
    print(f"  ESP32 Status    : {'Connected' if mc.is_available() else 'Disconnected'}")
    print()


# ---------------------------------------------------------------------------
# Startup self-test
# ---------------------------------------------------------------------------

def run_self_test(mc: MotorController) -> None:
    """Run a quick self-test and print results for each subsystem."""
    print("  ═════ Startup Self-Test ═════")

    ok = mc.is_available()
    print(f"  {'[PASS]' if ok else '[FAIL]'} ESP32 Connection")

    if ok:
        for _ in range(20):
            line = mc.read_line()
            if line and line.startswith("BAT:"):
                print(f"  [PASS] Battery Stream")
                break
            time.sleep(0.05)
        else:
            print("  [WARN] Battery Stream (no packet yet)")
    else:
        print("  [SKIP] Battery Stream")

    for item in [
        "Camera", "Microphone", "Speaker",
        "Face Detection", "Gesture Detection", "Shutdown API",
    ]:
        print(f"  [SKIP] {item} (not in diagnostics mode)")
    print()


# ---------------------------------------------------------------------------
# Menu
# ---------------------------------------------------------------------------

def show_menu() -> None:
    print()
    print("  ╔══════════════════════════════════════════╗")
    print("  ║    ROPE Hardware Diagnostics Tool        ║")
    print("  ╠══════════════════════════════════════════╣")
    print("  ║  1  Forward     8  Happy Animation       ║")
    print("  ║  2  Backward    9  Battery (one-shot)    ║")
    print("  ║  3  Turn Left  10  Battery (live)        ║")
    print("  ║  4  Turn Right 11  Full Hardware Test    ║")
    print("  ║  5  Stop       12  Speed (set)           ║")
    print("  ║  6  Head Cal.  13  Centre Servos         ║")
    print("  ║  7  R.Arm Cal. 14  L.Arm Cal.            ║")
    print("  ║                  15  Edit Calibration     ║")
    print("  ║                  16  Save Calibration     ║")
    print("  ║                   Q  Quit                 ║")
    print("  ╚══════════════════════════════════════════╝")


def main() -> None:
    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s [%(name)s] %(message)s",
    )

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    # ── calibration state ──
    cal = load_calibration()
    print_calibration(cal)

    # ── MotorController ──
    mc = MotorController()
    if not mc.is_available():
        print("  ⚠ Motor controller not available — commands will be simulated.\n")

    print_serial_report(mc)
    run_self_test(mc)

    # ── main loop ──
    try:
        while True:
            show_menu()
            try:
                choice = input("  Choice: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\n  Bye!")
                break

            if choice == "q":
                print("  Bye!")
                break
            elif choice == "1":
                test_motion(mc, "Forward", mc.forward, 500)
            elif choice == "2":
                test_motion(mc, "Backward", mc.backward, 500)
            elif choice == "3":
                test_motion(mc, "Turn Left", mc.turn_left, 500)
            elif choice == "4":
                test_motion(mc, "Turn Right", mc.turn_right, 500)
            elif choice == "5":
                mc.stop()
                print("  Stop sent.")
            elif choice == "6":
                calibrate_servo(
                    mc, "Head", mc.move_head, lambda: mc.head_angle, cal, "head"
                )
            elif choice == "7":
                calibrate_servo(
                    mc, "Right Arm", mc.move_arm_right, lambda: mc.right_arm_angle, cal, "right_arm"
                )
            elif choice == "8":
                mc.happy()
                print("  Happy animation sent.")
            elif choice == "9":
                read_battery_once(mc)
            elif choice == "10":
                live_battery_monitor(mc)
            elif choice == "11":
                full_hardware_test(mc)
            elif choice == "12":
                test_speed_menu(mc)
            elif choice == "13":
                mc.center_servos()
                print("  Centre servos sent.")
            elif choice == "14":
                calibrate_servo(
                    mc, "Left Arm", mc.move_arm_left, lambda: mc.left_arm_angle, cal, "left_arm"
                )
            elif choice == "15":
                edit_calibration_values(cal)
            elif choice == "16":
                save_calibration(cal)
            else:
                print("  Unknown option.  Enter 1–16 or Q.")
    finally:
        mc.close()
        print("  Motor controller closed.")


if __name__ == "__main__":
    logger = logging.getLogger(__name__)
    main()
