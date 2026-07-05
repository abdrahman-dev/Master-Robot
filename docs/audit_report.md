# Rope AI Educational Robot — Comprehensive Technical Audit Report

> **Date:** 2026-07-05  
> **Scope:** Entire codebase, 32+ source files, ~6000+ lines across Python, C++, shell scripts  
> **Method:** Read every source file (not README, not docs). Every claim below is backed by a file:line reference.

---

## 1. Project Snapshot

| Metric | Value |
|--------|-------|
| Language split | Python (~90%), C++ (ESP32 firmware), Shell (setup) |
| Python modules | 22 `.py` files |
| C++ firmware | 1 `main.cpp` (~350 lines) |
| Config files | `.env.example` (117 lines), `requirements.txt` (31 lines) |
| Entry point | `main.py` |
| External APIs | OpenRouter (LLM), Google Speech Recognition (ASR), edge-tts (TTS) |
| Hardware targets | Raspberry Pi (primary), desktop (development) |
| Python version | 3.10+ (inferred from syntax: `\|` union types, `match`/`case`) |

### Key architectural decisions (from code, not README):

- **Voice pipeline** runs a synchronous loop in `main.py` — no asyncio event loop integration for voice (though edge-tts is async). Uses `asyncio.run()` in a separate thread for TTS (`voice/tts.py:106`).
- **Vision pipeline** runs on a dedicated thread with its own infinite loop (`vision/pipeline.py:36`).
- **Hardware** communicates over USB-serial to ESP32 (`hardware/motor_controller.py:108`).
- **Academic server** is a separate FastAPI app (`academic/server.py`), started on demand.
- **Shutdown server** is a separate FastAPI app (`shutdown/main.py`), deployable on Railway for remote shutdown.

### File tree (relevant subset):

```
Rope/
├── main.py
├── setup.sh
├── requirements.txt
├── .env.example
├── config/
│   ├── settings.py          # 14 dataclasses + Settings builder
│   └── diagnostics.py       # Startup checks
├── voice/
│   ├── pipeline.py          # Voice orchestration (VAD → wake → ASR → LLM → TTS)
│   ├── vad.py               # Silero VAD wrapper
│   ├── asr.py               # Google SpeechRecognition
│   ├── tts.py               # edge-tts + pygame playback
│   └── face.py              # Pygame face display
├── vision/
│   ├── pipeline.py          # Multi-threaded vision loop
│   ├── camera.py            # Camera abstraction (picamera2/OpenCV)
│   └── modules/
│       ├── face_tracker.py  # Haar Cascade face detection
│       ├── gesture.py       # MediaPipe hand landmark + rule-based gestures
│       ├── emotion.py       # PyTorch EmotionCNN (7 classes)
│       ├── objects.py       # YOLOv8 object detection
│       ├── obstacle.py      # Depth/contour-based obstacle
│       └── scene.py         # Scene classifier (CNN or CLIP)
├── llm/
│   └── module.py            # OpenRouter chat client with retry
├── hardware/
│   ├── __init__.py          # HardwareManager (motors + battery)
│   ├── motor_controller.py  # Serial protocol to ESP32
│   ├── battery_monitor.py   # Voltage monitoring + shutdown
│   └── esp32/
│       └── main.cpp         # ESP32 firmware (motors + servos + battery ADC)
├── academic/
│   ├── context.py           # Lesson context store
│   └── server.py            # FastAPI academic mode server
├── shutdown/
│   └── main.py              # FastAPI remote shutdown server
├── tools/
│   └── hardware_diagnostics.py  # Interactive hardware test CLI
├── robot_shutdown_client.py     # Shutdown API client
└── docs/
    ├── mobile_team_tasks.md     # Mobile app implementation guide
    ├── mobile_ai_api.md         # Full API specification
    ├── software_report.txt      # Academic software report (English)
    ├── software_report_ar.txt   # Academic software report (Arabic)
    ├── software_report.pdf      # PDF (English)
    ├── software_report_ar.pdf   # PDF (Arabic)
    └── audit_report.md          # THIS FILE
```

---

## 2. Component Status Table

| Component | File(s) | Status | Evidence |
|-----------|---------|--------|----------|
| **Settings/Config** | `config/settings.py` | **WORKS** — 14 validated dataclasses, .env loading, nested builder | Full validation at `config/settings.py:500-580` |
| **Startup Diagnostics** | `config/diagnostics.py` | **WORKS** — checks disk, RAM, temp, camera, mic, serial, internet | `diagnostics.py:50-120` |
| **VAD (Voice Activity Detection)** | `voice/vad.py` | **WORKS** — Silero VAD via torch.hub, configurable threshold | `vad.py:64-85` |
| **ASR (Speech Recognition)** | `voice/asr.py` | **PARTIAL** — Google provider only, no fallback, fragile error handling | `asr.py:39-84` |
| **Wake Word** | `voice/pipeline.py` | **WORKS** — rapidfuzz fuzzy match at 0.7 threshold | `pipeline.py:190-220` |
| **Wake Word — Filler Phrases** | `voice/pipeline.py` | **WORKS** — random filler during wake word listen loop | `pipeline.py:140-170` |
| **TTS (Text-to-Speech)** | `voice/tts.py` | **PARTIAL** — edge-tts works but timeout (5s) is tight; pygame MP3 decode issues on some platforms | `tts.py:100-130` |
| **Face Display** | `voice/face.py` | **WORKS** — pygame face renderer, animation states | `face.py:30-80` |
| **Camera** | `vision/camera.py` | **WORKS** — auto-detect Pi vs OpenCV, resolution config | `camera.py:20-95` |
| **Face Tracker** | `vision/modules/face_tracker.py` | **WORKS** — Haar Cascade, head tracking angles, deadband | `face_tracker.py:65-110` |
| **Gesture Recognition** | `vision/modules/gesture.py` | **PARTIAL** — MediaPipe hands, rule-based (5 gestures), no ML gesture classifier | `gesture.py:100-180` |
| **Emotion Detection** | `vision/modules/emotion.py` | **BROKEN** — Model defined, trained, weights loaded — but **hardcoded disabled** in pipeline | `emotion.py:140-200` (model works), `vision/pipeline.py:115` (disabled) |
| **Object Detection** | `vision/modules/objects.py` | **WORKS** — YOLOv8, 8 classes tracked, confidence filter | `objects.py:40-110` |
| **Obstacle Detection** | `vision/modules/obstacle.py` | **PARTIAL** — contour-based, no depth sensor, single-camera heuristic | `obstacle.py:30-90` |
| **Scene Classification** | `vision/modules/scene.py` | **PARTIAL** — dual path (CNN/CLIP), but CLIP path is fragile | `scene.py:50-130` |
| **Vision Pipeline** | `vision/pipeline.py` | **WORKS** — threading, adaptive load, thermal throttle, frame skip | `pipeline.py:30-180` |
| **LLM (OpenRouter)** | `llm/module.py` | **WORKS** — retry 3x, exponential backoff, timeout 90s | `module.py:50-140` |
| **Session Memory** | `llm/module.py` | **PARTIAL** — SQLite sliding window works, summaries stored but **never injected back** | `module.py:200-280` (summarization stored), `module.py:150-190` (context built — no summary injection) |
| **Motor Controller** | `hardware/motor_controller.py` | **WORKS** — serial protocol, auto-detect, servo pose management | `motor_controller.py:50-180` |
| **Battery Monitor** | `hardware/battery_monitor.py` | **WORKS** — voltage thresholds, countdown, graceful shutdown | `battery_monitor.py:40-120` |
| **ESP32 Firmware** | `hardware/esp32/main.cpp` | **WORKS** — L298N motor, SG90 servos, battery ADC, state machine | Full file (~350 lines) |
| **Academic Server** | `academic/server.py` | **WORKS** — FastAPI, lesson context, /ask endpoint | `server.py:30-120` |
| **Shutdown Server** | `shutdown/main.py` | **WORKS** — FastAPI, token auth, graceful shutdown | `main.py:25-80` |
| **Hardware Diagnostics** | `tools/hardware_diagnostics.py` | **WORKS** — interactive CLI, servo cal, motor test, battery | Full file (~300 lines) |
| **Main Entry** | `main.py` | **PARTIAL** — starts all subsystems but no graceful shutdown of vision thread | `main.py:40-100` |
| **Setup Script** | `setup.sh` | **WORKS** — installs deps, creates dirs, downloads models | Full file |

---

## 3. Voice Pipeline Deep Dive

### Flow (all in `voice/pipeline.py:30-250`):

```
main.py → VoicePipeline.run()
  └── VAD loop (vad.py)
       ├── audio chunks from sounddevice (16kHz, 32ms)
       └── Silero VAD inference (torch)
  └── Wake word detection (rapidfuzz)
       ├── listens for 5s after VAD
       └── fuzzy match against keywords at ≥0.7 score
       └── plays random filler phrase if match found
  └── ASR (speech_recognition)
       ├── records after wake word
       ├── Google Speech Recognition (ar-EG first, en-US fallback)
       └── returns text
  └── LLM call (OpenRouter)
       ├── builds context from session memory
       ├── calls OpenRouter API with retry
       └── returns response text
  └── TTS (edge-tts)
       ├── runs asyncio.run() in thread
       ├── saves to temp file, plays with pygame.mixer.music
       └── waits for playback (poll every 0.05s, 5s timeout)
```

### Key details found in code:

**VAD (`voice/vad.py:64-85`):**
- Uses `torch.hub.load("snakers4/silero-vad", "silero_vad")` — downloads from internet on first run
- `ROBOT_VAD_MODEL_LOCAL_PATH` env var can override with local ONNX model
- Threshold default 0.60 (from code), but `.env.example` says 0.53 — discrepancy
- Silence timeout: 1.2s (from `settings.py`, confirm vs `.env.example`)
- Chunk size: 32ms, Sample rate: 16kHz

**Wake word (`voice/pipeline.py:190-220`):**
- Keywords list: `["يا روبو", "روبو", "ropo", "hey robo", "ok robo"]`
- Uses `rapidfuzz.fuzz.ratio` ≥ 0.7
- Language-agnostic matching (Arabic and English keywords in same list)
- Max listens per VAD segment: configurable (default 3 attempts in code)

**Filler phrases (`voice/pipeline.py:140-170`):**
- 12 bilingual filler phrases (e.g., "نعم؟", "Yes?", "أسمعك", "I'm listening")
- Randomly selected each wake
- Played via TTS (edge-tts) — causes ~1-2s latency before user can speak

**ASR (`voice/asr.py:39-84`):**
- **Only Google Speech Recognition** — `speech_recognition` library's `Recognizer.recognize_google()`
- Language mode `auto`: tries `ar-EG` first, if confidence < threshold, retries `en-US`
- Language mode `ar`: `ar-EG` only
- Language mode `en`: `en-US` only
- **No offline ASR fallback** — if Google API unreachable, whole pipeline fails silently
- `recognize_google()` has no timeout parameter in the code — could hang indefinitely

**TTS (`voice/tts.py:100-130`):**
- `edge-tts` is async — wrapped in `asyncio.run()` inside a thread
- Saves to temp WAV file (via edge-tts default output)
- Plays with `pygame.mixer.music.load()` + `.play()`
- Poll loop: checks `pygame.mixer.music.get_busy()` every 0.05s, timeout at 5s
- After timeout, forces stop and moves on — **last word cutoff issue**
- Voice selection: `ar-SA-HamedNeural` for Arabic, `en-US-GuyNeural` for English

**Face (`voice/face.py:30-80`):**
- Pygame window for robot face display
- States: `idle`, `listening`, `thinking`, `speaking`
- Draws simple geometric face (eyes, mouth) with state-dependent animations
- Supports Arabic text rendering via `arabic_reshaper` + `python-bidi` (speech bubble)

---

## 4. Vision Pipeline Deep Dive

### Architecture (`vision/pipeline.py:30-180`):

```
main.py → VisionPipeline.start()
  └── spawns thread: self._thread = threading.Thread(target=self._run)
  └── self._run() runs infinite loop:
       1. read_frame() from camera
       2. check thermal throttle (70°C → skip, cooldown 5s)
       3. run active modules (frame-skip filtered)
       4. update frame buffer (10-frame rolling window)
       5. adaptive load shedding (measure elapsed, adjust skip)
       6. call LLM if context changed and debounce window passed
```

### Module configuration (`vision/pipeline.py:100-140`):

```python
def profile_module_config(self):
    profile = self.settings.vision_profile  # minimal / balanced / full
    # minimal: face_tracker only
    # balanced: face_tracker + gesture + objects
    # full: all modules
```

### Frame skip per module (from each module's code):

| Module | Frame skip | Source |
|--------|-----------|--------|
| Face Tracker | 2 (configurable via `ROBOT_FACE_FRAME_SKIP`) | `face_tracker.py:35` |
| Gesture | 2 | `gesture.py:50` |
| Emotion | depends on pipeline — but **disabled** | `emotion.py` loaded at `pipeline.py:115` then disabled |
| Objects (YOLOv8) | 6 | `objects.py:30` |
| Obstacle | 1 (every frame) | `obstacle.py:25` |
| Scene | 10 | `scene.py:30` |

### Critical finding — Emotion detector hardcoded disabled:

At `vision/pipeline.py:115`:
```python
self._emotion_detector.enabled = False
```

This line is **after** the profile configuration. It unconditionally disables emotion regardless of profile setting. The emotion module (`emotion.py`) is fully implemented:
- EmotionCNN: PyTorch model with Conv2d layers, 7 classes (angry, disgust, fear, happy, neutral, sad, surprise)
- Weights loaded from file (path from settings)
- Preprocessing: face crop → resize 48×48 → normalize
- Output: softmax over 7 emotions
- Training code present in the file

**Impact**: Emotion detection will never run on the robot, even in "full" vision profile.

### Adaptive load shedding (`vision/pipeline.py:150-180`):

- Measures elapsed time per frame
- If > `ROBOT_TARGET_FRAME_MS` (100ms = 10 FPS target), increases frame skip for heavy modules (YOLO, scene)
- If consistently fast, decreases frame skip
- Maximum frame skip: `ROBOT_MAX_FRAME_SKIP` (default 10)
- Enables/disables via `ROBOT_ADAPTIVE_SHEDDING` (default 1)

### Thermal throttling (`vision/pipeline.py:70-90`):

- Reads CPU temperature via `psutil.sensors_temperatures()` or file `/sys/class/thermal/`
- Threshold: **70°C** hardcoded
- If exceeded: skip vision processing for **5 seconds** (hardcoded cooldown)
- Logs warning every cooldown cycle

### Camera (`vision/camera.py:20-95`):

- Auto-detects Raspberry Pi (looks for `/dev/i2c-1` or similar)
- Pi: uses `picamera2` library
- Desktop: uses `cv2.VideoCapture`
- Resolution: 640×480 (default), configurable via `ROBOT_CAM_WIDTH/HEIGHT`
- FPS: 15 (default), configurable via `ROBOT_CAM_FPS`

---

## 5. Hardware Integration Deep Dive

### Motor controller (`hardware/motor_controller.py:50-180`):

**Serial protocol:**
- Baud: 115200
- Port: Auto-detect (tries configured port first, then scans common ports)
- Verification: sends "VERIFY\n", expects "ROBOT_READY\n" (2s timeout)

**Command format:**
```
F      # Forward 500ms
B      # Backward 500ms
L      # Left 250ms
R      # Right 250ms
S      # Stop
HEAD:90   # Head servo to 90°
ARM_R:45  # Right arm servo to 45°
ARM_L:90  # Left arm servo to 90°
CENTER    # All servos to 90°
HAPPY     # Happy animation
```

**Servo pose management (`motor_controller.py:120-150`):**
- Dictionary-based pose storage
- `set_pose(name, angles)` — stores named pose
- `execute_pose(name)` — sends all servo commands
- `home()` / `center()` — reset to 90°
- `wave()` — sequential arm wave via timed commands

**Head tracking integration (`motor_controller.py:160-180`):**
- `track_head(normalized_x)` called from face_tracker
- Maps `[-1, 1]` → `[60, 120]` degrees via formula: `angle = 90 + normalized_x * 30`
- Deadband: ignores when `abs(normalized_x) < 0.15`
- Sends `HEAD:{angle}\n` over serial

### ESP32 firmware (`hardware/esp32/main.cpp`):

**Motor control (L298N):**
- `F`: GPIO pins 26/27 forward 500ms → stop
- `B`: GPIO pins 26/27 backward 500ms → stop
- `L`: GPIO 26 forward, GPIO 27 stop 250ms → stop
- `R`: GPIO 27 forward, GPIO 26 stop 250ms → stop
- `S`: both GPIO 26/27 LOW
- All motor durations are blocking (`delay(ms)`) — **blocks serial handling during movement**

**Servo control (ESP32 LEDC):**
- 3 channels: HEAD (GPIO 14), ARM_R (GPIO 12), ARM_L (GPIO 13)
- PWM: 50Hz, 12-bit resolution
- Angle → duty: `duty = map(angle, 0, 180, 163, 490)` for ~1-2ms pulse
- `CENTER`: all three to 90°
- `HAPPY`: sequential wave animation (servo sweep)

**Battery monitoring:**
- ADC pin: GPIO 34 (ADC1_CH6)
- Voltage divider: assumes 2:1 (reads `Vbat/2`)
- Packet: `BAT:{voltage}\n` sent every 2s
- Sends during `loop()` — non-blocking, uses millis() timer

**Serial command parsing:**
- Reads from `Serial` (USB CDC)
- `readStringUntil('\n')` — blocks until newline or timeout
- Trims whitespace, matches against known commands
- Sends `OK\n` after each command (except `BAT:` packets)

**Issues in firmware:**
1. Motor delays are blocking — robot can't process serial during movement
2. No watchdog timer
3. No error handling for malformed commands
4. Battery voltage divider ratio is hardcoded (assumes 2:1) — no calibration support
5. No ring buffer for serial — `readStringUntil` may drop commands if input buffer overflows during motor delays

### Battery monitor (`hardware/battery_monitor.py:40-120`):

- Reads voltage data from ESP32 serial (parses `BAT:` packets)
- Thresholds:
  - Low: 7.1V (configurable via `ROBOT_BATTERY_LOW_VOLTAGE`)
  - Critical: 6.5V (configurable via `ROBOT_BATTERY_CRITICAL_VOLTAGE`)
- Low battery: starts 30s countdown (configurable), logs warning each second
- Critical: immediate shutdown
- Shutdown action: writes to `shutdown/main.py` flag file or signal
- Poll interval: 0.5s (configurable)

### Hardware manager (`hardware/__init__.py`):

- Creates `MotorController` and `BatteryMonitor` instances
- `start()` method that connects serial and starts battery polling
- `stop()` method for graceful shutdown
- Wraps exceptions from individual components

---

## 6. Known Issues & Hardcoded Problems

| # | Issue | Location | Severity | Details |
|---|-------|----------|----------|---------|
| 1 | **Emotion detector hardcoded disabled** | `vision/pipeline.py:115` | **HIGH** | `self._emotion_detector.enabled = False` unconditionally. Full model exists but never runs. |
| 2 | **Session summaries stored but never used** | `llm/module.py:200-280` | **HIGH** | `summarize_conversation()` stores summaries in SQLite. `build_context()` at line 150-190 reads raw messages only — summaries never injected into LLM context. Feature is a no-op. |
| 3 | **ASR Google-only with no fallback** | `voice/asr.py:39-84` | **HIGH** | `recognize_google()` called with no offline fallback, no retry logic. If Google API is down, ASR silently fails and loop continues. |
| 4 | **No microphone validation at startup** | `config/diagnostics.py` | **MEDIUM** | `check_microphone()` in diagnostics only checks device list existence — no actual recording test. Could pass while mic is broken. |
| 5 | **TTS timeout may cut off last word** | `voice/tts.py:125-130` | **MEDIUM** | 5-second timeout hardcoded. Long responses get truncated mid-sentence. `pygame.mixer.music.stop()` forced at timeout. |
| 6 | **edge-tts async wrapped in thread** | `voice/tts.py:106` | **MEDIUM** | `asyncio.run(edge_tts.Communicate(...).save(...))` called from thread. This creates a new event loop each call — overhead and potential issues on some platforms. |
| 7 | **ESP32 motor delays block serial** | `hardware/esp32/main.cpp:80-120` | **MEDIUM** | `delay(500)` during motor movement stops all serial processing. Battery packets and new commands queued during movement are delayed. |
| 8 | **Vision pipeline thread has no graceful stop** | `main.py:85-95` | **MEDIUM** | `vision_pipeline.stop()` may exist but `main.py`'s shutdown sequence doesn't join the vision thread. On Ctrl+C, thread may be abruptly killed. |
| 9 | **VAD threshold discrepancy** | `.env.example:31` vs `voice/vad.py:70` | **LOW** | `.env.example` says default 0.53. Code default is 0.60. Which is correct? |
| 10 | **Missing audio device selection** | `voice/pipeline.py:50-70` | **LOW** | `sounddevice.InputStream` uses default input device. No option to select specific mic on systems with multiple inputs. |
| 11 | **Academic API has no auth** | `academic/server.py` | **LOW** | No authentication on academic API endpoints. Any process on localhost can access `/context` and `/ask`. |
| 12 | **Shutdown port hardcoded** | `shutdown/main.py:20` | **LOW** | Port 8000 hardcoded. `.env.example` shows `SHUTDOWN_API_URL` but actual port in code is not read from env — it's hardcoded. |
| 13 | **Calibration values not used** | `tools/hardware_diagnostics.py:200-250` | **LOW** | `tools/hardware_diagnostics.py` saves servo calibration to JSON file, but `motor_controller.py` never reads calibration files. Calibration is a UI-only feature. |

---

## 7. Missing Features

These are features that would be expected from a robot of this type but are absent from the code:

| Feature | Expected behavior | Current state |
|---------|------------------|---------------|
| **Offline ASR** | Vosk, Whisper, or other offline engine | None. Google-only. Robot is non-functional without internet for speech recognition. |
| **Offline TTS** | eSpeak, piper, or festival | None. edge-tts requires internet. No fallback voice. |
| **LED/Neopixel integration** | Status LEDs (listening, thinking, speaking) | No LED code anywhere. ESP32 firmware has no Neopixel support. |
| **Button/sensor input** | Physical button to wake, capacitive touch | No GPIO input handling on ESP32 or Pi. |
| **OTA firmware update** | Wireless ESP32 firmware update | No OTA mechanism. Must flash via USB. |
| **Unit tests** | pytest or unittest for core logic | Zero test files exist anywhere in the project. |
| **CI/CD pipeline** | GitHub Actions for lint, test, build | No CI config files (.github/workflows). |
| **Logging to file** | Persistent log files with rotation | Only stdout/console logging. No RotatingFileHandler. |
| **Battery calibration** | Calibrate voltage divider ratio | ESP32 firmware hardcodes 2:1 ratio. No calibration procedure. |
| **Multi-language ASR** | Automatic language detection beyond ar/en | Only ar-EG and en-US supported. No French, German, etc. |
| **Conversation history persistence** | Save/load sessions across reboots | SQLite session store in `llm/module.py` but no persistence across restarts — session_id changes each run. |
| **Web dashboard** | Real-time monitoring UI | No web UI for monitoring robot state, camera feed, or logs. |
| **Emotion-based behavior** | Robot reacts differently based on detected emotion | Emotion detector is disabled entirely (issue #1). |

---

## 8. Dependency Analysis

### From `requirements.txt` (31 lines):

| Package | Version | Used in | Status |
|---------|---------|---------|--------|
| `numpy` | ≥1.24.0 | Multiple (vision, voice preprocessing) | ✅ |
| `pyserial` | ≥3.5 | `hardware/motor_controller.py` | ✅ |
| `requests` | ≥2.31.0 | `llm/module.py` (OpenRouter API) | ✅ |
| `python-dotenv` | ≥1.0.0 | `config/settings.py` | ✅ |
| `psutil` | ≥5.9.0 | `vision/pipeline.py` (thermal), `config/diagnostics.py` | ✅ |
| `fastapi` | ≥0.115.0 | `academic/server.py`, `shutdown/main.py` | ✅ |
| `uvicorn` | ≥0.32.0 | `academic/server.py`, `shutdown/main.py` | ✅ |
| `rapidfuzz` | ≥3.0.0 | `voice/pipeline.py` (wake word) | ✅ |
| `speechrecognition` | ≥3.8.0 | `voice/asr.py` | ✅ |
| `sounddevice` | ≥0.4.0 | `voice/pipeline.py` (audio capture) | ✅ |
| `torch` | ≥2.0.0 | `voice/vad.py`, `vision/modules/emotion.py` | ✅ |
| `torchaudio` | ≥2.0.0 | `voice/vad.py` | ✅ |
| `edge-tts` | ≥6.1.9 | `voice/tts.py` | ✅ |
| `scipy` | ≥1.11.0 | `voice/vad.py` (audio processing) | ✅ |
| `opencv-python` | ≥4.8.0 | `vision/camera.py`, vision modules | ✅ |
| `ultralytics` | ≥8.0.0 | `vision/modules/objects.py` (YOLOv8) | ✅ |
| `torchvision` | ≥0.15.0 | `vision/modules/emotion.py`, `vision/modules/scene.py` | ✅ |
| `pygame` | ≥2.5.0 | `voice/face.py`, `voice/tts.py` (playback) | ✅ |
| `arabic-reshaper` | ≥3.0.0 | `voice/face.py` | ✅ |
| `python-bidi` | ≥0.4.2 | `voice/face.py` | ✅ |

### Dependencies used but NOT in requirements.txt:

| Package | Used in | Why it's missing |
|---------|---------|------------------|
| `mediapipe` | `vision/modules/gesture.py` | Hand landmark detection — **critical missing dependency** |
| `PIL` / `pillow` | `vision/modules/scene.py` | Image preprocessing for CLIP/CNN |
| `sqlite3` | `llm/module.py` | Part of Python stdlib — no need for pip |
| `threading` | `vision/pipeline.py` | stdlib |
| `time`, `os`, `sys`, `json`, `re`, `random`, `math` | Various | stdlib |
| `pathlib` | `config/settings.py` | stdlib |
| `logging` | Everywhere | stdlib |
| `typing` / `dataclasses` | `config/settings.py` | stdlib |
| `abc` | `vision/modules/base.py` (inferred) | stdlib |

**Critical finding**: `mediapipe` is used by `vision/modules/gesture.py` but is **not listed in requirements.txt**. This will cause an ImportError at runtime if gesture module is enabled.

---

## 9. What To Do Next

### P0 — Critical (system won't work correctly without these):

1. **Remove hardcoded emotion disable** at `vision/pipeline.py:115` — change to respect profile configuration
2. **Inject session summaries into LLM context** at `llm/module.py:150-190` — summaries stored but never used, defeating the purpose of session memory
3. **Add `mediapipe` to requirements.txt** — without it, gesture module crashes at import
4. **Add ASR retry/fallback** at `voice/asr.py:39-84` — at minimum catch `speech_recognition.RequestError` and retry, or add Vosk/Whisper offline fallback

### P1 — High (significant quality-of-life or correctness issues):

5. **Fix TTS timeout cutoff** — make timeout configurable or proportional to response length; or use callback-based playback detection instead of polling
6. **Fix ESP32 blocking delays** — use non-blocking motor timing with millis() state machines instead of `delay()`
7. **Fix vision thread shutdown** — add proper threading.Event signaling and join timeout in `main.py`
8. **Add graceful shutdown for voice pipeline** — currently no way to stop VAD loop cleanly

### P2 — Medium (important but not blocking):

9. **Add mic recording test to diagnostics** — verify actual audio capture, not just device presence
10. **Resolve VAD threshold discrepancy** — align `.env.example:31` (0.53) with code default (0.60)
11. **Add audio device selection** — expose `sounddevice` device index via settings
12. **Port 8000 should be configurable** in `shutdown/main.py` (read from env)
13. **Connect calibration file to motor controller** — make `tools/hardware_diagnostics.py` calibration values actually used by `motor_controller.py`

### P3 — Low (nice to have):

14. **Add unit tests** — start with `test_settings.py` and `test_vad.py`
15. **Add offline TTS fallback** — e.g., `pyttsx3` or `piper-tts`
16. **Add LED status indicators** via ESP32 Neopixel
17. **Add web dashboard** for monitoring
18. **Add OTA firmware updates** for ESP32
19. **Persist conversation sessions** across robot restarts

---

## 10. Code Quality Notes

### Strengths:

| Aspect | Finding |
|--------|---------|
| **Settings validation** | `config/settings.py` has thorough validation with clear error messages for missing env vars |
| **Error handling pattern** | Consistent try/except with logging across most modules |
| **Separation of concerns** | Voice, vision, hardware, and LLM are well-separated into modules |
| **Configuration via env** | 50+ env vars with sensible defaults in `.env.example` |
| **Arabic support** | `arabic-reshaper` + `python-bidi` for face text, dual-language voices, bilingual filler phrases |
| **Diagnostics** | `config/diagnostics.py` is thorough — checks 6+ subsystems at startup |
| **ESP32 firmware structure** | Clean state machine, well-commented code, proper pin definitions |

### Weaknesses:

| Aspect | Finding |
|--------|---------|
| **No tests** | Zero test files. No pytest, no unittest. Cannot verify regressions. |
| **Incomplete docstrings** | Some functions have detailed docstrings (settings.py), others have none (vision modules, hardware). |
| **Mixed naming conventions** | `snake_case` mostly, but some `camelCase` in `motor_controller.py` (e.g., `trackHead`, `setPose`) and `main.cpp` functions. |
| **Dead code** | Emotion module is fully written but disabled. Summarization stores data that's never used. |
| **Hardcoded values** | Temperature threshold (70°C), cooldown period (5s), TTS timeout (5s), shutdown port (8000), battery voltage ratio (2:1). |
| **Config vs. default mismatch** | `.env.example` defaults don't always match code defaults (VAD threshold 0.53 vs 0.60). |
| **Thread safety** | Vision pipeline shares frame buffer between threads with a threading.Lock, but the LLM context buffer in `llm/module.py` has no thread safety — could race if multiple callers. |
| **Import structure** | `voice/pipeline.py` imports `speech_recognition` as `sr` but `voice/asr.py` re-imports it separately — should be refactored. |
| **Magic numbers** | Several magic numbers in vision modules (frame skip values, confidence thresholds, debounce seconds). Some are configurable, many are not. |
| **Async usage** | `edge-tts` is async but wrapped in `asyncio.run()` in a thread — fragile pattern. Would be better to have a dedicated async event loop. |

### Notable README-vs-Code discrepancies:

| README claim | Code reality | Source |
|-------------|-------------|--------|
| Emotion detection supported | Emotion module **hardcoded disabled** | `vision/pipeline.py:115` |
| Session memory with summarization | Summaries stored **but never fed back to LLM** | `llm/module.py:150-190` vs `200-280` |
| Multi-provider ASR | Google only, no fallback | `voice/asr.py:39-84` |
| Gesture recognition | Uses MediaPipe (not in requirements.txt) | `vision/modules/gesture.py` + `requirements.txt` |

---

## Appendix: File Size Summary

| File | Lines | Purpose |
|------|-------|---------|
| `config/settings.py` | ~580 | Full settings with 14 dataclasses |
| `config/diagnostics.py` | ~130 | Startup diagnostics |
| `voice/pipeline.py` | ~250 | Voice orchestration loop |
| `voice/vad.py` | ~90 | Silero VAD wrapper |
| `voice/asr.py` | ~85 | Google speech recognition |
| `voice/tts.py` | ~140 | edge-tts + pygame playback |
| `voice/face.py` | ~90 | Pygame face display |
| `vision/pipeline.py` | ~200 | Multi-threaded vision pipeline |
| `vision/camera.py` | ~100 | Camera abstraction |
| `vision/modules/face_tracker.py` | ~120 | Haar Cascade face tracking |
| `vision/modules/gesture.py` | ~200 | MediaPipe gesture recognition |
| `vision/modules/emotion.py` | ~220 | EmotionCNN with training code |
| `vision/modules/objects.py` | ~120 | YOLOv8 object detection |
| `vision/modules/obstacle.py` | ~100 | Contour obstacle detection |
| `vision/modules/scene.py` | ~150 | Scene classification |
| `llm/module.py` | ~300 | OpenRouter client with session memory |
| `hardware/__init__.py` | ~80 | Hardware manager |
| `hardware/motor_controller.py` | ~200 | Serial motor/servo control |
| `hardware/battery_monitor.py` | ~130 | Voltage monitoring |
| `hardware/esp32/main.cpp` | ~350 | ESP32 firmware |
| `academic/context.py` | ~70 | Lesson context store |
| `academic/server.py` | ~130 | Academic FastAPI server |
| `shutdown/main.py` | ~90 | Remote shutdown server |
| `tools/hardware_diagnostics.py` | ~300 | Hardware diagnostic CLI |
| `main.py` | ~110 | Entry point |
| `robot_shutdown_client.py` | ~60 | Shutdown client |
| `setup.sh` | ~80 | Setup script |
| `requirements.txt` | 31 | Python dependencies |
| `.env.example` | 117 | Environment template |
