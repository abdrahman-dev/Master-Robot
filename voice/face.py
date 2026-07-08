from __future__ import annotations

import logging
import math
import os
import random
import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, Callable, List

import pygame

from voice.text_utils import contains_arabic, reshape_text, wrap_text

logger = logging.getLogger(__name__)


@dataclass
class BatteryData:
    percentage: Optional[int] = None
    voltage: Optional[float] = None
    charging: bool = False

_PI = math.pi


# ── Easing ────────────────────────────────────────────────────────

def ease_out_quad(t: float) -> float:
    return t * (2.0 - t)


def ease_in_out_cubic(t: float) -> float:
    return 4.0 * t * t * t if t < 0.5 else 1.0 - pow(-2.0 * t + 2.0, 3.0) / 2.0


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * max(0.0, min(1.0, t))


def damp(a: float, b: float, lam: float, dt: float) -> float:
    return lerp(a, b, 1.0 - math.exp(-lam * dt))


# ── UI Config ─────────────────────────────────────────────────────

@dataclass
class UISettings:
    ENABLE_SCANLINES: bool = False
    ENABLE_PARTICLES: bool = False
    ENABLE_GLOW: bool = True
    ENABLE_IDLE_DRIFT: bool = True
    ENABLE_SMOOTHING: bool = True


# ── Settings state ────────────────────────────────────────────────

@dataclass
class SettingsState:
    language: str = "ar"
    tts_speed: int = 1
    volume: int = 3
    vision_mode: str = "OFF"
    mic_muted: bool = False

    SPEED_LABELS = ["Slow", "Normal", "Fast"]
    VOLUME_LABELS = ["25%", "50%", "75%", "100%"]
    VISION_LABELS = ["OFF", "MINIMAL", "BALANCED", "FULL"]
    MIC_LABELS = ["ON", "OFF"]


# ── Default params schema ─────────────────────────────────────────

DEFAULT_FACE_PARAMS = {
    "eye_open": 1.0,
    "blink": 0.0,
    "pupil_x": 0.0,
    "pupil_y": 0.0,
    "mouth_open": 0.06,
    "happy": False,
    "curious_l": False,
    "thinking_eyes": 0.0,
    "listening_bars": 0.0,
    "cheeks": 0.0,
    "glow_pulse": 0.0,
    "eyebrow_raise": 0.0,
    "eye_target_h": 55.0,
    "iris_bright": 0.0,
}


def merge_params(state_params: dict) -> dict:
    merged = {**DEFAULT_FACE_PARAMS, **state_params}
    for key in state_params:
        if key not in DEFAULT_FACE_PARAMS:
            logger.warning("[face] Unknown param '%s'", key)
    return merged


# ── Themes ────────────────────────────────────────────────────────

@dataclass
class Theme:
    name: str
    bg: tuple
    eye_socket: tuple
    iris: tuple
    iris_highlight: tuple
    pupil: tuple
    glow: tuple
    glow_alpha: int
    mouth: tuple
    mouth_fill: tuple
    sep_line: tuple
    status_bg: tuple
    status_text: tuple
    panel_bg: tuple
    panel_border: tuple
    panel_highlight: tuple
    panel_label: tuple
    panel_value: tuple
    panel_close: tuple


THEMES = {
    "dark_blue": Theme(
        name="dark_blue",
        bg=(6, 8, 16), eye_socket=(18, 22, 40),
        iris=(0, 120, 255), iris_highlight=(60, 180, 255),
        pupil=(255, 255, 255),
        glow=(0, 60, 180), glow_alpha=40,
        mouth=(0, 100, 220), mouth_fill=(0, 60, 140),
        sep_line=(30, 40, 70), status_bg=(12, 15, 28),
        status_text=(60, 80, 120),
        panel_bg=(10, 14, 30), panel_border=(30, 40, 80),
        panel_highlight=(0, 60, 180, 80),
        panel_label=(180, 200, 255), panel_value=(0, 120, 255),
        panel_close=(100, 120, 180),
    ),
    "cyber_green": Theme(
        name="cyber_green",
        bg=(6, 16, 8), eye_socket=(18, 40, 22),
        iris=(0, 220, 100), iris_highlight=(60, 255, 150),
        pupil=(255, 255, 255),
        glow=(0, 160, 60), glow_alpha=35,
        mouth=(0, 180, 80), mouth_fill=(0, 100, 50),
        sep_line=(30, 70, 40), status_bg=(12, 28, 15),
        status_text=(60, 120, 80),
        panel_bg=(10, 30, 14), panel_border=(30, 80, 40),
        panel_highlight=(0, 180, 60, 80),
        panel_label=(180, 255, 200), panel_value=(0, 220, 100),
        panel_close=(100, 180, 120),
    ),
    "monochrome": Theme(
        name="monochrome",
        bg=(10, 10, 10), eye_socket=(28, 28, 28),
        iris=(160, 160, 160), iris_highlight=(220, 220, 220),
        pupil=(255, 255, 255),
        glow=(120, 120, 120), glow_alpha=30,
        mouth=(140, 140, 140), mouth_fill=(100, 100, 100),
        sep_line=(40, 40, 40), status_bg=(18, 18, 18),
        status_text=(80, 80, 80),
        panel_bg=(18, 18, 18), panel_border=(50, 50, 50),
        panel_highlight=(100, 100, 100, 80),
        panel_label=(200, 200, 200), panel_value=(160, 160, 160),
        panel_close=(120, 120, 120),
    ),
}


# ── States ────────────────────────────────────────────────────────

class FaceState(Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    HAPPY = "happy"
    CURIOUS = "curious"
    SLEEP = "sleep"


# ── Settings panel rows ───────────────────────────────────────────

PANEL_ROWS = [
    {"key": "language",    "icon": "LANG", "label": "Language"},
    {"key": "tts_speed",   "icon": "SPD",  "label": "TTS Speed"},
    {"key": "volume",      "icon": "VOL",  "label": "Volume"},
    {"key": "vision_mode", "icon": "VIS",  "label": "Vision Mode"},
    {"key": "mic_muted",   "icon": "MIC",  "label": "Microphone"},
    {"key": "_close",      "icon": "X",    "label": "Close"},
]


def _settings_value(set_s: SettingsState, key: str) -> str:
    if key == "language":
        return "Arabic" if set_s.language == "ar" else "English"
    if key == "tts_speed":
        return SettingsState.SPEED_LABELS[set_s.tts_speed]
    if key == "volume":
        return SettingsState.VOLUME_LABELS[set_s.volume]
    if key == "vision_mode":
        return set_s.vision_mode
    if key == "mic_muted":
        return "OFF" if set_s.mic_muted else "ON"
    return ""


def _settings_cycle(set_s: SettingsState, key: str):
    if key == "language":
        set_s.language = "en" if set_s.language == "ar" else "ar"
    elif key == "tts_speed":
        set_s.tts_speed = (set_s.tts_speed + 1) % 3
    elif key == "volume":
        set_s.volume = (set_s.volume + 1) % 4
    elif key == "vision_mode":
        labels = SettingsState.VISION_LABELS
        idx = (labels.index(set_s.vision_mode) + 1) % len(labels)
        set_s.vision_mode = labels[idx]
    elif key == "mic_muted":
        set_s.mic_muted = not set_s.mic_muted


# ── Battery indicator constants ───────────────────────────────────

BATTERY_PAD_RIGHT = 10
BATTERY_PAD_TOP = 8
BATTERY_W = 20
BATTERY_H = 12
BATTERY_BORDER = 2
BATTERY_TERM_W = 4
BATTERY_TERM_H = 6
BATTERY_COLOR_GREEN = (0, 200, 80)
BATTERY_COLOR_YELLOW = (220, 200, 0)
BATTERY_COLOR_RED = (220, 60, 40)
BATTERY_OUTLINE = (80, 100, 140)
BATTERY_LOW_THRESHOLD = 20

# ── Face Module ───────────────────────────────────────────────────

PANEL_W = int(480 * 0.85)
PANEL_H = 6 * 52 + 20
PANEL_X = (480 - PANEL_W) // 2
PANEL_Y = (320 - PANEL_H) // 2
ROW_H = 52
CLOSE_BTN_R = 16


class FaceModule:
    W, H = 480, 320
    FPS = 60

    def __init__(self, fullscreen: bool = False, ui: Optional[UISettings] = None):
        self._target_state = FaceState.IDLE
        self._current_state = FaceState.IDLE
        self._lock = threading.Lock()
        self._running = False
        self._fullscreen = fullscreen
        self._ui = ui or UISettings()

        self._dt = 0.016
        self._t = 0.0

        self._transition_t = 1.0
        self._transition_duration = 0.25
        self._prev_params: dict = {}
        self._raw_params: dict = {}
        self._merged_params: dict = dict(DEFAULT_FACE_PARAMS)

        self._eye_h_left = 55.0
        self._eye_h_right = 55.0
        self._eye_target_h = 55.0
        self._eye_osc_t = 0.0
        self._mouth_h = 8.0
        self._mouth_target_h = 8.0
        self._mouth_osc_t = 0.0

        self._blink_t = 0.0
        self._blink_timer = random.uniform(2.5, 5.0)
        self._blink_asym = 0.0
        self._asymmetric_blink = False

        self._mouth_t = 0.0
        self._eye_angle = 0.0
        self._breath_t = 0.0

        self._pupil_target_x = 0.0
        self._pupil_target_y = 0.0
        self._pupil_drift_x = 0.0
        self._pupil_drift_y = 0.0
        self._drift_timer = 0.0

        self._startup_t = 0.0
        self._startup_done = False
        self._startup_eye_h = 0.0

        self._idle_timer = 0.0
        self._idle_dim = 0.0
        self._wakelock = False

        self._state_change_flash = 0.0
        self._battery_pulse_t = 0.0

        self._swipe_callback: Optional[Callable[[str], None]] = None
        self._event_handler: Optional[Callable[[pygame.event.Event], None]] = None
        self._finger_start_x: Optional[int] = None
        self._finger_start_y: Optional[int] = None
        self._overlay_text: Optional[str] = None
        self._show_overlay = False
        self._theme_name = "dark_blue"
        self._cache: dict = {}

        self._particles: Optional[list] = None

        # status indicators
        self._battery = BatteryData()

        # academic caption
        self._spoken_text: Optional[str] = None

        # speech bubble font (loaded lazily on first use)
        self._bubble_font: Optional[pygame.font.Font] = None
        self._bubble_font_path = str(Path(__file__).resolve().parent.parent / "fonts" / "Cairo-Regular.ttf")

        # settings panel
        self._settings_open = False
        self._settings = SettingsState()
        self._settings_callback: Optional[Callable] = None
        self._selected_row = -1
        self._selection_flash = 0.0

    def set_settings_callback(self, cb: Callable) -> None:
        self._settings_callback = cb

    @property
    def settings_state(self) -> SettingsState:
        return self._settings

    @property
    def panel_open(self) -> bool:
        return self._settings_open

    def open_settings(self) -> None:
        self._settings_open = True
        self._selected_row = -1

    def close_settings(self) -> None:
        self._settings_open = False
        self._selected_row = -1

    # ── theme ─────────────────────────────────────────────────

    def set_theme(self, name: str) -> None:
        if name in THEMES:
            self._theme_name = name
            self._cache.clear()

    @property
    def theme(self) -> Theme:
        return THEMES.get(self._theme_name, THEMES["dark_blue"])

    # ── public API ────────────────────────────────────────────

    def set_state(self, state: FaceState | str) -> None:
        if isinstance(state, str):
            try:
                state = FaceState(state)
            except ValueError:
                return
        with self._lock:
            if state != self._target_state:
                if self._startup_done:
                    self._prev_params = dict(self._raw_params)
                    self._transition_t = 0.0
                    self._state_change_flash = 1.0
                self._target_state = state
                self._wakelock = True
                self._idle_timer = 0.0

    def get_state(self) -> FaceState:
        with self._lock:
            return self._current_state

    def set_swipe_callback(self, cb: Callable[[str], None]) -> None:
        self._swipe_callback = cb

    def set_event_handler(self, handler: Callable[[pygame.event.Event], None]) -> None:
        self._event_handler = handler

    def set_overlay_text(self, text: Optional[str]) -> None:
        self._overlay_text = text

    def set_show_overlay(self, show: bool) -> None:
        self._show_overlay = show

    def set_battery_status(self, percentage: Optional[int] = None, voltage: Optional[float] = None, charging: bool = False) -> None:
        self._battery.percentage = percentage
        self._battery.voltage = voltage
        self._battery.charging = charging

    def set_spoken_text(self, text: Optional[str]) -> None:
        self._spoken_text = text

    def get_spoken_text(self) -> Optional[str]:
        return self._spoken_text

    def _get_bubble_font(self) -> pygame.font.Font:
        if self._bubble_font is not None:
            return self._bubble_font
        if Path(self._bubble_font_path).is_file():
            try:
                self._bubble_font = pygame.font.Font(self._bubble_font_path, self._BUBBLE_FONT_SIZE)
                logger.info("[face] Loaded bubble font: %s", self._bubble_font_path)
                return self._bubble_font
            except Exception as exc:
                logger.warning("[face] Failed to load bubble font: %s", exc)
        else:
            logger.warning("[face] Bubble font not found at %s; using pygame default", self._bubble_font_path)
        return pygame.font.Font(None, self._BUBBLE_FONT_SIZE)

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False

    def _handle_mouse_event(self, event) -> None:
        self._wakelock = True
        self._idle_timer = 0.0

        if event.type == pygame.MOUSEBUTTONDOWN:
            if self._settings_open:
                mx, my = event.pos
                if mx >= PANEL_X + PANEL_W - CLOSE_BTN_R * 3 and my <= PANEL_Y + CLOSE_BTN_R * 3:
                    self._settings_open = False
                    if self._swipe_callback:
                        self._swipe_callback("close_settings")
                    return
                rel_y = my - PANEL_Y - 10
                if 0 <= rel_y < len(PANEL_ROWS) * ROW_H:
                    idx = int(rel_y // ROW_H)
                    if 0 <= idx < len(PANEL_ROWS):
                        row = PANEL_ROWS[idx]
                        if row["key"] == "_close":
                            self._settings_open = False
                            if self._swipe_callback:
                                self._swipe_callback("close_settings")
                        else:
                            _settings_cycle(self._settings, row["key"])
                            self._selected_row = idx
                            self._selection_flash = 0.2
                            if self._settings_callback:
                                self._settings_callback(row["key"], _settings_value(self._settings, row["key"]))
                return
            self._finger_start_x, self._finger_start_y = event.pos
        elif event.type == pygame.MOUSEBUTTONUP:
            if self._finger_start_x is not None and not self._settings_open:
                end_x, end_y = event.pos
                dx = end_x - self._finger_start_x
                dy = end_y - self._finger_start_y
                if abs(dx) > 80 and abs(dx) > abs(dy) * 1.5:
                    if self._swipe_callback:
                        self._swipe_callback("left" if dx < 0 else "right")
                self._finger_start_x = None
                self._finger_start_y = None

    def get_panel_swipe_direction(self) -> Optional[str]:
        """Call from swipe callback to decide behavior based on panel state."""
        if self._settings_open:
            return "panel"
        return None

    # ── main loop ─────────────────────────────────────────────

    def run_main_thread(self) -> None:
        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        import pygame

        # Initialize mixer first — works without display
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.pre_init(frequency=44100, size=-16, channels=2, buffer=2048)
                pygame.mixer.init()
        except pygame.error as e:
            logger.warning("[face] Audio device unavailable: %s", e)

        # Then try display init separately
        try:
            pygame.display.init()
        except Exception as e:
            logger.warning("[face] Display init failed (headless?): %s", e)

        # Rest of pygame init
        pygame.font.init()
        flags = pygame.FULLSCREEN if self._fullscreen else 0
        screen = pygame.display.set_mode((self.W, self.H), flags)
        pygame.display.set_caption("Ropo")
        clock = pygame.time.Clock()
        surf = pygame.Surface((self.W, self.H))

        self._init_particles()

        while self._running:
            raw_dt = clock.tick(self.FPS) / 1000.0
            dt = min(raw_dt, 0.05)

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self._running = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    self._settings_open = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_f:
                    self._fullscreen = not self._fullscreen
                    flags = pygame.FULLSCREEN if self._fullscreen else 0
                    screen = pygame.display.set_mode((self.W, self.H), flags)
                    pygame.display.set_caption("Ropo")
                    logger.info("[face] Fullscreen toggled: %s", self._fullscreen)
                elif event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
                    self._handle_mouse_event(event)
                elif self._event_handler:
                    self._event_handler(event)

            with self._lock:
                target_state = self._target_state

            self._update(dt, target_state)

            try:
                surf.fill(self.theme.bg)
                self._draw_separators(surf)
                self._draw_eye_pair(surf, self.theme)
                self._draw_mouth(surf, self.theme)
                if self._ui.ENABLE_GLOW:
                    self._draw_glow(surf, self.theme)
                self._draw_status_bar(surf)
                self._draw_battery_indicator(surf)
                self._draw_speech_bubble(surf)
                if self._settings_open:
                    self._draw_settings_panel(surf)
                if self._show_overlay and self._overlay_text:
                    font = pygame.font.Font(None, 14)
                    o = font.render(self._overlay_text, True, (60, 80, 120))
                    surf.blit(o, (4, self.H - 18))
            except Exception as exc:
                logger.error("[face] Render error: %s", exc, exc_info=True)
                surf.fill((6, 8, 16))
                font = pygame.font.Font(None, 22)
                fb = font.render("Ropo", True, (0, 120, 255))
                surf.blit(fb, (self.W // 2 - 24, self.H // 2 - 12))

            if self._fullscreen:
                info = pygame.display.Info()
                scale = min(info.current_w / self.W, info.current_h / self.H)
                sw, sh = int(self.W * scale), int(self.H * scale)
                scaled = pygame.transform.scale(surf, (sw, sh))
                screen.fill((0, 0, 0))
                screen.blit(scaled, ((info.current_w - sw) // 2, (info.current_h - sh) // 2))
            else:
                screen.blit(surf, (0, 0))
            pygame.display.flip()

        pygame.display.quit()

    # ── particles ─────────────────────────────────────────────

    def _init_particles(self) -> None:
        if not self._ui.ENABLE_PARTICLES:
            return
        self._particles = [
            {"x": random.uniform(0, self.W), "y": random.uniform(0, self.H),
             "vx": random.uniform(-4, 4), "vy": random.uniform(-2, 2),
             "r": random.uniform(1.0, 2.5), "s": random.uniform(1.0, 3.0)}
            for _ in range(6)
        ]

    # ── update ────────────────────────────────────────────────

    def _update(self, dt: float, target: FaceState) -> None:
        self._t += dt
        self._dt = dt

        if not self._startup_done:
            self._startup_t += dt
            if self._startup_t < 0.6:
                self._startup_eye_h = ease_in_out_cubic(self._startup_t / 0.6) * 55.0
            else:
                self._startup_done = True
                self._startup_eye_h = 55.0
            self._eye_h_left = self._startup_eye_h
            self._eye_h_right = self._startup_eye_h
            self._build_params(FaceState.IDLE)
            self._merged_params = merge_params(self._raw_params)
            return

        with self._lock:
            self._current_state = target

        self._breath_t += dt * 2.0

        if self._transition_t < 1.0:
            self._transition_t = min(self._transition_t + dt / self._transition_duration, 1.0)
            s = ease_in_out_cubic(self._transition_t)
        else:
            s = 1.0

        self._state_change_flash = max(0.0, self._state_change_flash - dt * 12.0)
        self._selection_flash = max(0.0, self._selection_flash - dt)
        self._battery_pulse_t += dt

        self._idle_timer += dt
        if self._idle_timer > 30.0 and target == FaceState.IDLE and self._wakelock:
            self._idle_dim = min(0.5, self._idle_dim + dt * 0.02)
        else:
            self._idle_dim = max(0.0, self._idle_dim - dt * 0.1)

        self._blink_timer -= dt
        if self._blink_timer <= 0:
            self._blink_t = 1.0
            self._blink_timer = random.uniform(3.0, 6.0)
            self._asymmetric_blink = random.random() < 0.3
            self._blink_asym = random.uniform(0.0, 0.4) if self._asymmetric_blink else 0.0
        if self._blink_t > 0:
            self._blink_t -= dt * 12.0
            if self._blink_t < 0:
                self._blink_t = 0.0

        blink_phase = max(0.0, self._blink_t)
        blink_l = 1.0 - ease_out_quad(blink_phase + (self._blink_asym if self._asymmetric_blink else 0))
        blink_r = 1.0 - ease_out_quad(blink_phase)
        blink_l = max(0.0, min(1.0, blink_l))
        blink_r = max(0.0, min(1.0, blink_r))

        self._eye_target_h = 55.0
        self._mouth_target_h = 8.0

        if target == FaceState.LISTENING:
            self._eye_target_h = 63.0
            self._mouth_target_h = 14.0
        elif target == FaceState.THINKING:
            self._eye_target_h = 45.0
            self._mouth_target_h = 8.0
        elif target == FaceState.SPEAKING:
            self._eye_osc_t += dt * 4.0 * _PI * 2
            self._eye_target_h = 55.0 + math.sin(self._eye_osc_t) * 4.0
            self._mouth_osc_t += dt * 4.0 * _PI * 2
            self._mouth_target_h = 8.0 + abs(math.sin(self._mouth_osc_t)) * 16.0
        elif target == FaceState.HAPPY:
            self._eye_target_h = 42.0
            self._mouth_target_h = 8.0
        elif target == FaceState.CURIOUS:
            self._eye_target_h = 50.0
            self._mouth_target_h = 8.0
        elif target == FaceState.SLEEP:
            self._eye_target_h = 4.0
            self._mouth_target_h = 4.0

        if self._ui.ENABLE_SMOOTHING:
            self._eye_h_left = damp(self._eye_h_left, self._eye_target_h * blink_l, 12.0, dt)
            self._eye_h_right = damp(self._eye_h_right, self._eye_target_h * blink_r, 12.0, dt)
            self._mouth_h = damp(self._mouth_h, self._mouth_target_h, 12.0, dt)
        else:
            self._eye_h_left = self._eye_target_h * blink_l
            self._eye_h_right = self._eye_target_h * blink_r
            self._mouth_h = self._mouth_target_h

        self._eye_h_left = max(2.0, self._eye_h_left)
        self._eye_h_right = max(2.0, self._eye_h_right)

        if self._ui.ENABLE_IDLE_DRIFT and target == FaceState.IDLE:
            self._drift_timer += dt
            if self._drift_timer > random.uniform(2.0, 4.0):
                self._pupil_target_x = random.uniform(-8.0, 8.0)
                self._pupil_target_y = random.uniform(-5.0, 5.0)
                self._drift_timer = 0.0
        elif target == FaceState.SLEEP:
            self._pupil_target_x = 0.0
            self._pupil_target_y = 5.0
        elif target == FaceState.LISTENING:
            self._pupil_target_x = math.sin(self._t * 2.0) * 6.0
            self._pupil_target_y = -3.0
        elif target == FaceState.THINKING:
            self._eye_angle += dt * 2.0
            self._pupil_target_x = math.cos(self._eye_angle) * 10.0
            self._pupil_target_y = math.sin(self._eye_angle) * 8.0
        elif target == FaceState.CURIOUS:
            self._pupil_target_x = 8.0
            self._pupil_target_y = -6.0
        elif target == FaceState.SPEAKING:
            self._pupil_target_x = math.sin(self._t * 3.0) * 4.0
            self._pupil_target_y = 0.0
        else:
            self._pupil_target_x = 0.0
            self._pupil_target_y = 0.0

        self._pupil_drift_x = damp(self._pupil_drift_x, self._pupil_target_x, 8.0, dt)
        self._pupil_drift_y = damp(self._pupil_drift_y, self._pupil_target_y, 8.0, dt)

        self._build_params(target)
        raw = dict(self._raw_params)
        raw["eye_open"] = 1.0 - max(0.0, self._blink_t)
        raw["pupil_x"] = self._pupil_drift_x / 10.0
        raw["pupil_y"] = self._pupil_drift_y / 10.0
        raw["mouth_open"] = self._mouth_h / 24.0
        raw["eyebrow_raise"] = 0.0
        if target == FaceState.HAPPY:
            raw["eyebrow_raise"] = -0.3
        if target == FaceState.CURIOUS:
            raw["eyebrow_raise"] = -0.4

        if s < 1.0 and isinstance(raw, dict):
            all_keys = set(DEFAULT_FACE_PARAMS.keys()) | set(raw.keys())
            for k in all_keys:
                if k in raw and k in self._prev_params:
                    v = raw[k]
                    if isinstance(v, (int, float)):
                        raw[k] = lerp(float(self._prev_params.get(k, v)), float(v), s)

        self._raw_params = raw
        self._merged_params = merge_params(raw)

    def _build_params(self, state: FaceState) -> None:
        t = self._t
        base = {}
        if state == FaceState.IDLE:
            base["glow_pulse"] = (math.sin(t * 0.8) + 1) * 0.25
        elif state == FaceState.LISTENING:
            base["listening_bars"] = 1.0
            base["glow_pulse"] = 0.6
            base["iris_bright"] = 0.5
        elif state == FaceState.THINKING:
            base["thinking_eyes"] = 1.0
            base["glow_pulse"] = 0.5
        elif state == FaceState.SPEAKING:
            base["glow_pulse"] = 0.6
        elif state == FaceState.HAPPY:
            base["happy"] = True
            base["cheeks"] = 1.0
            base["glow_pulse"] = 0.8
        elif state == FaceState.CURIOUS:
            base["curious_l"] = True
            base["glow_pulse"] = 0.4
        elif state == FaceState.SLEEP:
            base["glow_pulse"] = 0.0
        self._raw_params = base

    # ── drawing ───────────────────────────────────────────────

    def _draw_separators(self, surf: pygame.Surface) -> None:
        t = self.theme
        c = t.sep_line
        pygame.draw.line(surf, c, (0, 118), (self.W, 118), 1)
        pygame.draw.line(surf, c, (0, 172), (self.W, 172), 1)

    def _draw_eye_pair(self, surf: pygame.Surface, theme: Theme) -> None:
        self._draw_eye(surf, 160, 145, theme)
        self._draw_eye(surf, 320, 145, theme)

    def _draw_eye(self, surf: pygame.Surface, cx: int, cy: int, theme: Theme) -> None:
        rel = "left" if cx == 160 else "right"
        eo = 1.0 - max(0.0, self._blink_t)
        tw = 90
        th = self._eye_h_left if rel == "left" else self._eye_h_right
        th = max(2.0, th * eo)

        flash = self._state_change_flash

        # socket
        pygame.draw.rect(surf, theme.eye_socket,
                         (cx - tw // 2, cy - int(th) // 2, tw, int(th)),
                         border_radius=12)

        # iris
        iris_w = 50
        iris_h = max(4, int(30 * (th / 55.0)))
        ix = cx + int(self._pupil_drift_x * 0.5) - iris_w // 2
        iy = cy + int(self._pupil_drift_y * 0.5) - iris_h // 2
        ir_color = theme.iris
        if flash > 0:
            ir_color = tuple(min(255, c + int(60 * flash)) for c in ir_color)
        pygame.draw.rect(surf, ir_color,
                         (ix, iy, iris_w, iris_h),
                         border_radius=8)

        # iris highlight
        hi_h = max(2, iris_h // 3)
        pygame.draw.rect(surf, theme.iris_highlight,
                         (ix, iy, iris_w, hi_h),
                         border_radius=8)

        # pupil
        px = cx + int(self._pupil_drift_x) - 6
        py = cy + int(self._pupil_drift_y) - 6
        pygame.draw.circle(surf, theme.pupil, (px, py), 12)

        # reflection
        pygame.draw.circle(surf, (255, 255, 255, 200),
                           (px - 3, py - 4), 4)

    def _draw_mouth(self, surf: pygame.Surface, theme: Theme) -> None:
        mh = int(self._mouth_h)
        mw = 120
        cx, cy = 240, 240

        if self._current_state == FaceState.HAPPY:
            for yy in range(mh):
                spread = max(2, int((1.0 - yy / max(mh, 1)) * mw // 2))
                pygame.draw.line(surf, theme.mouth,
                                 (cx - spread, cy + yy),
                                 (cx + spread, cy + yy), 1)
        else:
            rect = pygame.Rect(cx - mw // 2, cy - mh // 2, mw, max(mh, 2))
            pygame.draw.rect(surf, theme.mouth, rect, border_radius=max(mh // 2, 1))
            if mh > 6:
                inner = pygame.Rect(cx - mw // 2 + 4, cy - mh // 2 + 2,
                                    mw - 8, max(mh - 4, 2))
                pygame.draw.rect(surf, theme.mouth_fill, inner, border_radius=2)

    def _draw_glow(self, surf: pygame.Surface, theme: Theme) -> None:
        pulse = self._merged_params.get("glow_pulse", 0.3)
        if pulse < 0.05:
            return
        ga = theme.glow_alpha
        a = int(ga * pulse)
        gs = pygame.Surface((180, 120), pygame.SRCALPHA)
        pygame.draw.ellipse(gs, (*theme.glow, a), (0, 0, 180, 120))
        surf.blit(gs, (150, 85), special_flags=pygame.BLEND_ALPHA_SDL2)

    def _draw_status_bar(self, surf: pygame.Surface) -> None:
        t = self.theme
        bar_y = self.H - 16
        pygame.draw.rect(surf, t.status_bg, (0, bar_y, self.W, 16))
        state_name = self._current_state.value.capitalize()
        font = pygame.font.Font(None, 14)
        label = font.render(state_name, True, t.status_text)
        surf.blit(label, (8, bar_y + 2))

        if self._settings.mic_muted:
            pygame.draw.circle(surf, (255, 60, 60), (465, 10), 5)

    # ── settings panel ────────────────────────────────────────

    def _draw_settings_panel(self, surf: pygame.Surface) -> None:
        t = self.theme
        ps = pygame.Surface((PANEL_W, PANEL_H), pygame.SRCALPHA)
        ps.fill((*t.panel_bg, 220))
        pygame.draw.rect(ps, (*t.panel_border, 255),
                         (0, 0, PANEL_W, PANEL_H), 2, border_radius=20)
        surf.blit(ps, (PANEL_X, PANEL_Y))

        font_lbl = pygame.font.Font(None, 22)
        font_val = pygame.font.Font(None, 22)

        for i, row in enumerate(PANEL_ROWS):
            y = PANEL_Y + 10 + i * ROW_H

            if i == self._selected_row and self._selection_flash > 0:
                hl = pygame.Surface((PANEL_W - 20, ROW_H - 4), pygame.SRCALPHA)
                highlight = t.panel_highlight
                hl.fill((*highlight[:3], int(highlight[3] * (self._selection_flash / 0.2))))
                surf.blit(hl, (PANEL_X + 10, y + 2))

            if row["key"] == "_close":
                txt = font_lbl.render("  Close", True, t.panel_close)
                surf.blit(txt, (PANEL_X + 20, y + 14))
            else:
                icon_txt = f"{row['icon']}  {row['label']}"
                lbl = font_lbl.render(icon_txt, True, t.panel_label)
                surf.blit(lbl, (PANEL_X + 20, y + 14))

                val = _settings_value(self._settings, row["key"])
                if row["key"] == "mic_muted":
                    mic_color = (255, 80, 80) if self._settings.mic_muted else (80, 255, 120)
                    v = font_val.render(val, True, mic_color)
                else:
                    v = font_val.render(val, True, t.panel_value)
                surf.blit(v, (PANEL_X + PANEL_W - 30 - v.get_width(), y + 14))

    # ── battery indicator ────────────────────────────────────

    def _draw_battery_indicator(self, surf: pygame.Surface) -> None:
        pct = self._battery.percentage
        if pct is None:
            return

        if pct >= 60:
            fill_color = BATTERY_COLOR_GREEN
        elif pct >= 30:
            fill_color = BATTERY_COLOR_YELLOW
        else:
            fill_color = BATTERY_COLOR_RED

        fill_w = max(0, int((BATTERY_W - BATTERY_BORDER * 2) * pct / 100.0))
        fill_h = BATTERY_H - BATTERY_BORDER * 2

        if pct < BATTERY_LOW_THRESHOLD:
            phase = self._battery_pulse_t * (2.0 * _PI / 1.5)
            visibility = 0.45 + 0.55 * (0.5 + 0.5 * math.sin(phase))
            alpha = int(visibility * 255)
        else:
            alpha = 255

        x = self.W - BATTERY_PAD_RIGHT - BATTERY_W
        y = BATTERY_PAD_TOP

        if alpha < 255:
            temp = pygame.Surface((BATTERY_W + BATTERY_TERM_W, BATTERY_H), pygame.SRCALPHA)
            draw = temp
            ox = 0
            oy = 0
        else:
            draw = surf
            ox = x
            oy = y

        if fill_w > 0:
            pygame.draw.rect(draw, fill_color,
                             (ox + BATTERY_BORDER, oy + BATTERY_BORDER, fill_w, fill_h))

        pygame.draw.rect(draw, BATTERY_OUTLINE,
                         (ox, oy, BATTERY_W, BATTERY_H), BATTERY_BORDER)

        pygame.draw.rect(draw, BATTERY_OUTLINE,
                         (ox + BATTERY_W, oy + (BATTERY_H - BATTERY_TERM_H) // 2,
                          BATTERY_TERM_W, BATTERY_TERM_H))

        if self._battery.charging and fill_w > 4:
            cx = ox + BATTERY_W // 2
            cy = oy + BATTERY_H // 2
            bolt_color = (255, 255, 255)
            pygame.draw.line(draw, bolt_color, (cx - 2, cy - 3), (cx + 1, cy - 3), 2)
            pygame.draw.line(draw, bolt_color, (cx + 1, cy - 3), (cx + 1, cy), 2)
            pygame.draw.line(draw, bolt_color, (cx + 1, cy), (cx - 2, cy + 2), 2)
            pygame.draw.line(draw, bolt_color, (cx - 2, cy + 2), (cx - 2, cy), 2)
            pygame.draw.line(draw, bolt_color, (cx - 2, cy), (cx - 3, cy), 2)

        if alpha < 255:
            temp.set_alpha(alpha)
            surf.blit(temp, (x, y))

    # ── speech bubble (academic caption) ─────────────────────

    _BUBBLE_MAX_WIDTH = 440
    _BUBBLE_PAD_X = 16
    _BUBBLE_PAD_Y = 10
    _BUBBLE_BOTTOM_MARGIN = 20
    _BUBBLE_FONT_SIZE = 16
    _BUBBLE_MAX_LINES = 3
    _BUBBLE_BG = (18, 22, 40, 210)
    _BUBBLE_TEXT_COLOR = (220, 230, 255)

    def _draw_speech_bubble(self, surf: pygame.Surface) -> None:
        raw = self._spoken_text
        if not raw:
            return

        font = self._get_bubble_font()
        is_rtl = contains_arabic(raw)

        display_text = reshape_text(raw)

        max_text_w = min(self._BUBBLE_MAX_WIDTH, self.W - self._BUBBLE_PAD_X * 2) - self._BUBBLE_PAD_X * 2
        lines = wrap_text(display_text, font, max_text_w)
        lines = lines[:self._BUBBLE_MAX_LINES]

        line_h = font.get_height() + 4
        bubble_h = len(lines) * line_h + self._BUBBLE_PAD_Y * 2
        bubble_w = min(self._BUBBLE_MAX_WIDTH, self.W - self._BUBBLE_PAD_X * 2)
        bx = (self.W - bubble_w) // 2
        by = self.H - self._BUBBLE_BOTTOM_MARGIN - bubble_h - 16

        bsurf = pygame.Surface((bubble_w, bubble_h), pygame.SRCALPHA)
        bsurf.fill(self._BUBBLE_BG)
        pygame.draw.rect(bsurf, (*self._BUBBLE_BG[:3], 220),
                         (0, 0, bubble_w, bubble_h), border_radius=8)
        surf.blit(bsurf, (bx, by))

        for i, line in enumerate(lines):
            rendered = font.render(line, True, self._BUBBLE_TEXT_COLOR)
            if is_rtl:
                lw, _ = rendered.get_size()
                x = bx + bubble_w - self._BUBBLE_PAD_X - lw
            else:
                x = bx + self._BUBBLE_PAD_X
            surf.blit(rendered, (x, by + self._BUBBLE_PAD_Y + i * line_h))

    # ── optional extras ───────────────────────────────────────

    def _draw_thinking(self, surf, cx, cy, dim):
        t = self._t
        theme = self.theme
        for i in range(3):
            phase = (t * 3.0 + i * 0.38) % 1.0
            dy = -math.sin(phase * _PI) * 8
            alpha = int(60 + math.sin(phase * _PI) * 195 * dim)
            ds = pygame.Surface((10, 10), pygame.SRCALPHA)
            c = theme.iris
            pygame.draw.circle(ds, (c[0], c[1], c[2], alpha), (5, 5), 4)
            surf.blit(ds, (cx - 20 + i * 20 - 5, int(cy + dy - 5)))

    def _draw_listening(self, surf, cx, cy, dim):
        t = self._t
        theme = self.theme
        for i in range(7):
            phase = (t * 5.0 + i * 0.45) % (_PI * 2)
            h = int(4 + abs(math.sin(phase)) * 18)
            alpha = int(60 + abs(math.sin(phase)) * 195 * dim)
            bx = cx - 42 + i * 12
            bs = pygame.Surface((6, 28), pygame.SRCALPHA)
            c = theme.iris
            pygame.draw.rect(bs, (c[0], c[1], c[2], alpha),
                             (0, 14 - h // 2, 6, h), border_radius=3)
            surf.blit(bs, (bx - 3, cy - 14))

    def _draw_pulse(self, surf, cx, cy, dim):
        t = self._t
        theme = self.theme
        pulse = (math.sin(t * 4.0) + 1) / 2
        r = 80 + int(pulse * 16)
        alpha = int(6 + pulse * 20 * dim)
        ps = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
        c = theme.iris
        pygame.draw.circle(ps, (c[0], c[1], c[2], alpha), (r, r), r, 2)
        surf.blit(ps, (cx - r, cy - r))

    def _draw_cheeks(self, surf, cx, EY, dim, intensity):
        theme = self.theme
        for x in [cx - 50, cx + 50]:
            cs = pygame.Surface((40, 20), pygame.SRCALPHA)
            c = theme.iris
            a = int(30 * intensity * dim)
            pygame.draw.ellipse(cs, (c[0], c[1], c[2], a), (0, 0, 40, 20))
            surf.blit(cs, (x - 20, EY + 42))
