# Rope — AI Educational Robot

![Status](https://img.shields.io/badge/status-in%20development-yellow)
![Platform](https://img.shields.io/badge/platform-Raspberry%20Pi%205%20%7C%20Windows-blue)
![Python](https://img.shields.io/badge/python-3.10%2B-green)
![License](https://img.shields.io/badge/license-MIT-brightgreen)

An interactive educational robot with a conversational voice pipeline and an animated robot face, designed to run on a Raspberry Pi 4/5 or desktop.

## Features

- **Voice Pipeline** — VAD (Silero) → ASR (Google) → LLM (OpenRouter) → TTS (edge-tts)
- **Vision Pipeline** — Face tracking, gesture recognition, emotion detection, object detection (YOLOv8), obstacle detection, scene understanding
- **Animated Robot Face** — Pygame-based animated face with state transitions (IDLE, LISTENING, THINKING, SPEAKING, CURIOUS)
- **Hardware Control** — ESP32-based motor driver (TB6612FNG) with differential drive, three servos for head and arms, battery voltage monitoring with automatic Pi shutdown
- **Settings Panel** — Swipe-based UI to toggle vision profiles and modes
- **Session Memory** — SQLite-backed conversation history with sliding window and summarization
- **Filler Phrases** — Natural-sounding filler phrases in Arabic and English while the LLM processes
- **Offline Fallback** — Graceful degradation when OpenRouter is unreachable
- **Remote Shutdown** — FastAPI-based remote shutdown system with web dashboard and Raspberry Pi polling client

## Current Status

> المشروع شغال بالكامل على Desktop (Windows). الخطوة الجاية هي نقله على Raspberry Pi 5.

| المكون | الحالة |
|--------|--------|
| Voice Pipeline (VAD → ASR → LLM → TTS) | ✅ شغال |
| Animated Face UI | ✅ شغال |
| Settings Panel (swipe gesture) | ✅ شغال |
| Mic Mute Toggle | ✅ شغال |
| Vision Pipeline (YOLO + Face + Gesture) | ✅ شغال على Desktop |
| Wake Word Detection | ✅ شغال (كلمات: "روبو" / "ropo" / "يا روبو") |
| Voice Motor Commands | ✅ شغال (أوامر بالعربية والإنجليزية) |
| Head Tracking (Servo Follows Face) | ✅ شغال |
| Camera Vertical Flip (Fix for upside-down mount) | ✅ شغال |
| Face Identity Tracking (LBP Embeddings) | ✅ شغال |
| ESP32 Motor + Servo + Battery Firmware | ✅ شغال |
| Battery Monitor (Auto Shutdown on Low) | ✅ شغال |
| Raspberry Pi Deployment | 🔄 الخطوة الجاية |
| Remote Shutdown System | ✅ شغال |
| Mobile App Integration | 📋 مخطط |
| YOLO Fine-tuning (Electronics) | 📋 مخطط |

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                          main.py (Entry Point)                       │
│                                                                       │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────────────┐    │
│  │  FaceModule │  │  TTSModule   │  │      LLMModule            │    │
│  │  (pygame)   │  │  (edge-tts)  │  │  ┌────────────────────┐   │    │
│  │             │  │              │  │  │  SessionManager    │   │    │
│  │  IDLE       │  │  speak()     │  │  │  (SQLite DB)       │   │    │
│  │  LISTENING  │  │  speak_and_  │  │  │                    │   │    │
│  │  THINKING   │  │  wait()      │  │  │  MemoryManager     │   │    │
│  │  SPEAKING   │  │  stop()      │  │  │  (sliding window + │   │    │
│  │  CURIOUS    │  │              │  │  │   summarization)   │   │    │
│  └──────┬──────┘  └──────┬───────┘  │  └────────────────────┘   │    │
│         │                │          │  ┌────────────────────┐   │    │
│         │ callbacks      │ speak()  │  │  OpenRouterConn    │   │    │
│         │                │          │  │  (API → LLM)       │   │    │
│         │                │          │  └────────────────────┘   │    │
│         │                │          └──────────┬───────────────┘    │
│         │                │                     │                    │
│  ┌──────▼────────────────▼─────────────────────▼───────────────┐    │
│  │                    VoicePipeline                             │    │
│  │                                                               │    │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐  │    │
│  │  │   VAD    │─▶│   ASR    │─▶│  Filler  │─▶│    LLM     │  │    │
│  │  │ (Silero) │  │ (Google) │  │  Phrase  │  │  (chat)    │  │    │
│  │  │          │  │          │  │(fire &   │  │            │  │    │
│  │  │  mic ────┤  │  audio──▶│  │ forget)  │  │  response  │  │    │
│  │  │  input   │  │  → text  │  │          │  │            │  │    │
│  │  └──────────┘  └────┬─────┘  └──────────┘  └─────┬──────┘  │    │
│  │                     │                             │          │    │
│  │                     │         ┌──────────────┐    │          │    │
│  │                     │         │   TTS stop() │◀───┘          │    │
│  │                     │         │   + speak_   │               │    │
│  │                     │         │   and_wait() │               │    │
│  │                     │         └──────┬───────┘               │    │
│  │                     └────────────────┘                       │    │
│  └──────────────────────────┬───────────────────────────────────┘    │
│                             │                                         │
│  ┌──────────────────────────▼───────────────────────────────────┐    │
│  │                    VisionPipeline                              │    │
│  │  (activated by swipe gesture, controlled by set_vision_active) │    │
│  │                                                               │    │
│  │  ┌────────┐                                                   │    │
│  │  │Camera  │                                                   │    │
│  │  │(cv2)   │                                                   │    │
│  │  └───┬────┘                                                   │    │
│  │      │ frames                                                  │    │
│  │  ┌───▼──────────────────────────────────────────────────┐     │    │
│  │  │                  Module Router                        │     │    │
│  │  │                                                       │     │    │
│  │  │  ┌────────────┐  ┌──────────┐  ┌──────────────────┐  │     │    │
│  │  │  │FaceTracker │  │ Gesture  │  │    Emotion       │  │     │    │
│  │  │  │(OpenCV DNN)│  │(MediaPipe│  │   (CNN PyTorch)  │  │     │    │
│  │  │  └────────────┘  └──────────┘  └──────────────────┘  │     │    │
│  │  │  ┌────────────┐  ┌──────────┐  ┌──────────────────┐  │     │    │
│  │  │  │  Objects   │  │ Obstacle │  │     Scene        │  │     │    │
│  │  │  │ (YOLOv8n)  │  │ Detect   │  │  (YOLOv8n-seg)   │  │     │    │
│  │  │  └────────────┘  └──────────┘  └──────────────────┘  │     │    │
│  │  └──────────────────────────┬────────────────────────────┘     │    │
│  │                             │                                   │    │
│  │                     shared_context                              │    │
│  └─────────────────────────────┼───────────────────────────────────┘    │
│                                │                                        │
│                                ▼                                        │
│                    ┌───────────────────────┐                            │
│                    │  LLM with Vision      │                            │
│                    │  [VISION] prompt      │                            │
│                    └───────────────────────┘                            │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                    Settings Panel                                │   │
│  │  Swipe left → Settings → Vision Mode → Voice Only → Default     │   │
│  │  Rows: vision_mode, log_level, language, ...                    │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                    Watchdog & Diagnostics                        │   │
│  │  - Component health pings                                       │   │
│  │  - CPU temperature monitoring                                   │   │
│  │  - Periodic garbage collection                                  │   │
│  │  - System monitor (FPS, temp overlay)                           │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### Data Flow

```
User speaks ─▶ VAD detects speech ─▶ ASR transcribes ─▶ Filler phrase plays
                                                               │
                                                               ▼
Face: THINKING ◀────────────────────────────────── LLM processes (with vision context)
                                                               │
                                                               ▼
Face: SPEAKING ◀─────────────────────────────────── TTS speaks response
                                                               │
                                                               ▼
                                                         Face: IDLE
```

## Project Structure

```
Rope/
├── main.py                         # Entry point
├── health_check.py                 # Startup diagnostics
├── record_wake_word.py             # Wake word data collection tool
├── requirements.txt                # Python dependencies
├── .env                            # Environment variables (not committed)
├── .env.example                    # Template for .env
├── .gitignore
├── setup.sh                        # Raspberry Pi setup script
├── setup.ps1                       # Windows setup script
│
├── config/
│   ├── __init__.py
│   ├── settings.py                 # All configuration dataclasses
│   └── diagnostics.py              # Startup diagnostics & watchdog
│
├── voice/
│   ├── __init__.py
│   ├── vad.py                      # Voice Activity Detection (Silero)
│   ├── asr.py                      # Automatic Speech Recognition (Google)
│   ├── tts.py                      # Text-to-Speech (edge-tts)
│   ├── face.py                     # Animated robot face (pygame)
│   └── pipeline.py                 # Voice pipeline orchestrator
│
├── vision/
│   ├── __init__.py
│   ├── camera.py                   # Camera capture
│   ├── pipeline.py                 # Vision pipeline orchestrator
│   └── modules/
│       ├── __init__.py
│       ├── face_tracker.py         # Face detection & tracking
│       ├── gesture.py              # Hand gesture recognition
│       ├── emotion.py              # Emotion detection (CNN)
│       ├── objects.py              # Object detection (YOLOv8)
│       ├── obstacle.py             # Obstacle detection
│       └── scene.py                # Scene understanding (YOLOv8-seg)
│
├── llm/
│   ├── __init__.py
│   └── module.py                   # LLM module (OpenRouter + session memory)
│
├── hardware/
│   ├── __init__.py
│   ├── motor_controller.py         # Serial communication with ESP32
│   ├── battery_monitor.py          # Voltage monitoring & auto-shutdown
│   └── esp32/
│       └── main.cpp                # ESP32 firmware (motors, servos, battery ADC)
│
├── models/                         # Pre-trained ML models
│   ├── deploy.prototxt
│   ├── res10_300x300_ssd_iter_140000.caffemodel
│   ├── yolov8s.pt
│   ├── yolov8s-seg.pt
│   └── emotion_cnn_pytorch.pt
│
├── wake_word_data/                 # Wake word training recordings
│   ├── positive/
│   └── negative/
│
├── data/                           # Runtime data (SQLite DB, logs)
├── shutdown/
│   ├── __init__.py
│   ├── main.py                     # FastAPI remote shutdown server
│   ├── README.md                   # Deployment instructions
│   └── requirements.txt            # Isolated deps for Railway
├── robot_shutdown_client.py        # Raspberry Pi polling client
├── ropo-shutdown.service           # systemd service for polling client
├── piper_models/                   # Legacy TTS models (no longer used)
├── tests/                          # Unit tests
└── vision_debug_output/            # Debug frames from testing
```

## Requirements

### Hardware

- Raspberry Pi 4/5 (4GB+ RAM recommended)
- USB microphone
- Speaker (3.5mm or USB)
- USB or CSI camera
- Touchscreen (for gesture/swipe interaction)
- ESP32 development board (for motor/servo/battery control)
- TB6612FNG dual motor driver module
- 2x DC motors with wheels (differential drive)
- 3x Servo motors (head, left arm, right arm)
- 7.4V LiPo battery (or equivalent)
- Voltage divider resistors for battery ADC (GPIO 34 max 3.3V)

### Software

- Python 3.10+
- Dependencies listed in `requirements.txt`

## Installation

### Desktop (Windows / Linux)

```bash
git clone https://github.com/abdrahman-dev/Master-Robot.git
cd Rope
python -m venv venv
venv\Scripts\activate    # Windows
# or: source venv/bin/activate  # Linux
pip install -r requirements.txt
```

### Raspberry Pi

```bash
git clone https://github.com/abdrahman-dev/Master-Robot.git
cd Master-Robot
chmod +x setup.sh
./setup.sh
```

## Configuration

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

### Environment Variables

| Variable                         | Description                                         | Default                       |
| -------------------------------- | --------------------------------------------------- | ----------------------------- |
| `ROBOT_OPENROUTER_API_KEY`       | OpenRouter API key for LLM access                   | _(required)_                  |
| `ROBOT_OPENROUTER_MODEL`         | LLM model to use                                    | `openrouter/free`             |
| `ROBOT_VAD_THRESHOLD`            | Voice activity detection sensitivity                | `0.60`                        |
| `ROBOT_VAD_SILENCE_TIMEOUT_SEC`  | Silence duration before ending speech segment       | `0.80`                        |
| `ROBOT_VAD_MIN_SPEECH_SEC`       | Minimum speech duration to trigger ASR              | `0.50`                        |
| `ROBOT_VAD_PRE_ROLL_SEC`         | Pre-speech buffer to capture start of utterance     | `0.30`                        |
| `ROBOT_DEFAULT_SESSION_LANGUAGE` | Default session language (`ar` or `en`)             | `ar`                          |
| `ROBOT_VISION_PROFILE`           | Vision profile (`minimal`, `balanced`, `full`)      | `balanced`                    |
| `ROBOT_CAM_WIDTH`                | Camera capture width                                | `1280` (desktop) / `640` (Pi) |
| `ROBOT_CAM_HEIGHT`               | Camera capture height                               | `720` (desktop) / `480` (Pi)  |
| `ROBOT_CAM_FPS`                  | Camera frames per second                            | `30` (desktop) / `15` (Pi)    |
| `ROBOT_LOG_LEVEL`                | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) | `INFO`                        |
| `ROBOT_STUDENT_NAME`             | Student name displayed in UI                        | `Student`                     |
| `ROBOT_ASR_PROVIDER`             | ASR engine (`google`)                               | `google`                      |
| `ROBOT_ASR_LANGUAGE_MODE`        | Language detection (`auto`, `ar`, `en`)              | `auto`                        |
| `ROBOT_ASR_SAMPLE_RATE`          | ASR sample rate in Hz                                | `16000`                       |
| `ROBOT_ASR_DEFAULT_DURATION_SEC` | Default recording duration (non-streaming)           | `5.0`                         |
| `ROBOT_LLM_PROVIDER`             | LLM provider (`openrouter`)                          | `openrouter`                  |
| `ROBOT_LLM_REQUEST_TIMEOUT_SEC`  | LLM request timeout                                  | `90`                          |
| `ROBOT_LLM_SUMMARIZE_TIMEOUT_SEC`| Summarization timeout                                | `60`                          |
| `ROBOT_LLM_WINDOW_SIZE`          | Conversation sliding window size (messages)          | `50`                          |
| `ROBOT_FACE_THRESHOLD`           | Face detection confidence threshold                  | `0.35`                        |
| `ROBOT_FACE_FRAME_SKIP`          | Process every Nth face frame                         | `2`                           |
| `ROBOT_FACE_SCALE_FACTOR`        | Scale factor for face detection image                | `0.5`                         |
| `ROBOT_TTS_ENGINE`               | TTS engine (`edge_tts`)                              | `edge_tts`                    |
| `ROBOT_TTS_POLL_SEC`             | Pygame playback poll interval                        | `0.05`                        |
| `ROBOT_MOTOR_PORT`               | Serial port for ESP32                                | `COM3` (Win) / `/dev/ttyS0` (Pi) |
| `ROBOT_MOTOR_BAUDRATE`           | Serial baud rate                                     | `115200`                      |
| `ROBOT_METRICS_OVERLAY`          | Show FPS/temperature overlay on face (`0`/`1`)       | `0`                           |
| `ROBOT_ADAPTIVE_SHEDDING`        | Enable adaptive load shedding (`0`/`1`)              | `1`                           |
| `ROBOT_TARGET_FRAME_MS`          | Target milliseconds per frame for throttling         | `100`                         |
| `ROBOT_MAX_FRAME_SKIP`           | Maximum frame skip during throttling                 | `10`                          |
| `SHUTDOWN_API_URL`               | Backend API URL for remote shutdown (Railway)       | _(required for shutdown)_     |
| `SHUTDOWN_TOKEN`                 | Shared secret token for shutdown auth               | _(required for shutdown)_     |
| `SHUTDOWN_POLL_INTERVAL`         | Polling interval in seconds (RPi client)            | `15`                          |

## Usage

```bash
python health_check.py   # verify everything works
python main.py           # run the robot
```

### Controls

| Gesture                  | Action               |
| ------------------------ | -------------------- |
| Swipe left (once)        | Open settings panel  |
| Swipe left (in settings) | Activate vision mode |
| Swipe left (in vision)   | Voice only mode      |
| Tap settings row         | Cycle value          |
| Tap X                    | Close panel          |

## Voice Pipeline

The voice pipeline processes audio in real-time through four stages:

1. **Wake Word Detection** — Continuously listens for the robot name ("روبو" / "ropo" / "يا روبو" / "hey robo") using fuzzy string matching (rapidfuzz, threshold 70%). All regular conversation is gated behind wake word activation. First wake word triggers an introduction greeting.
2. **VAD (Silero)** — Continuously monitors microphone input using Silero VAD to detect speech segments with configurable sensitivity and silence timeout.
3. **ASR (Google)** — Transcribes captured speech segments using Google's Speech Recognition API with automatic language detection (Arabic/English).
4. **LLM (OpenRouter)** — Sends transcribed text to the LLM with conversation history and optional vision context. While the LLM processes, a natural filler phrase plays (e.g., "Let me think..." / "لحظة بفكر...") to maintain engagement.
5. **TTS (edge-tts)** — Speaks the LLM response aloud using edge-tts, with animated face state transitions. If new speech is detected while speaking, TTS is interrupted immediately.

### Voice Motor Commands

The pipeline also recognises movement commands directly from speech (before sending to LLM):

| Phrase | Action |
|--------|--------|
| "تعالي" / "اقترب" / "come here" | Move forward (2s) |
| "ارجع" / "go back" | Move backward (2s) |
| "يمين" / "turn right" | Turn right (1s) |
| "شمال" / "turn left" | Turn left (1s) |
| "دور" | Turn right (3s) |
| "وقف" / "استنى" / "stop" | Stop motors |

**Offline fallback:** If OpenRouter is unreachable, the robot responds with a friendly error message. The pipeline continues running and will retry on the next turn.

## Vision Pipeline

The vision pipeline runs camera frames through multiple optional modules:

- **Camera** — OpenCV backend with automatic picamera2 detection on Raspberry Pi for CSI cameras. Frames are vertically flipped (`cv2.flip(frame, 0)`) to compensate for physically upside-down camera mounting. The OpenCV backend tries multiple camera indices as fallback.
- **Face Tracker** — Detects and tracks faces using OpenCV DNN (Caffe SSD) with identity tracking via LBP embeddings and cosine distance matching. Returns `"same_student"` or `"new_student"` status with per-session UUID. Results include `center_x`/`center_y`, `normalized_x`/`normalized_y` (0.0–1.0), and `frame_width`/`frame_height`. Faces are sorted by bounding box area (largest first).
- **Head Tracking** — The pipeline maps the largest face's `normalized_x` to the head servo angle (0–180°) with a 5° deadband to avoid serial flooding. Call `set_motor_controller(motor)` to attach a MotorController instance.
- **Gesture Recognition** — Recognizes hand gestures using MediaPipe hand landmarks
- **Emotion Detection** — Classifies facial expressions using a custom CNN
- **Object Detection** — Identifies objects using YOLOv8n
- **Obstacle Detection** — Detects obstacles and their direction
- **Scene Understanding** — Segments scenes using YOLOv8n-seg

### Vision Profiles

| Profile    | Enabled Modules                                 | Description                         |
| ---------- | ----------------------------------------------- | ----------------------------------- |
| `MINIMAL`  | Obstacle detection only                         | Lightweight, fastest performance    |
| `BALANCED` | Obstacle + Emotion                              | Good balance of features and speed  |
| `FULL`     | All modules (objects, scene, obstacle, emotion) | Maximum capability, slowest on Pi 4 |

### Performance Management

The pipeline includes two automatic mechanisms to maintain stable frame rates:

- **Thermal Throttling** — When CPU temperature reaches 75°C, frame skip is increased and the profile is downgraded from FULL to BALANCED. Normal operation resumes at 65°C.
- **Adaptive Load Shedding** — If average frame processing time exceeds the target by 50%, frame skip is incremented. When time drops below 50% of the target, it is restored. Configurable via `ROBOT_ADAPTIVE_SHEDDING` and `ROBOT_TARGET_FRAME_MS`.

### Context Buffer

A 10-frame rolling buffer stores recent vision results. The frame with the most faces (then most objects) is selected as the shared context returned to the LLM, ensuring the best observation is used for responses.

## Hardware Layer

The robot includes a physical motor and servo control system managed by an ESP32 microcontroller communicating over serial UART with the Raspberry Pi.

### Architecture

```
                    Raspberry Pi 5
                  ┌──────────────────────┐
                  │   MotorController    │
                  │  (PySerial UART)     │
                  │                      │
                  │   BatteryMonitor     │
                  │  (read_line thread)  │
                  └──────┬───────────────┘
                         │  UART (115200 baud)
                         │  RX=GPIO16, TX=GPIO17
                  ┌──────▼───────────────┐
                  │      ESP32           │
                  │  (main.cpp)          │
                  └──┬───────┬──────┬────┘
                     │       │      │
            ┌────────▼─┐ ┌───▼──┐ ┌─▼──────────┐
            │TB6612FNG │ │Servos│ │Battery ADC  │
            │Motor Drvr│ │x3    │ │GPIO 34      │
            └──────────┘ └──────┘ └─────────────┘
```

### ESP32 Pin Mapping

| Component | Pin | Description |
|-----------|-----|-------------|
| PWMA      | 25  | Motor A PWM speed |
| AIN1/AIN2 | 26/27 | Motor A direction |
| PWMB      | 14  | Motor B PWM speed |
| BIN1/BIN2 | 12/13 | Motor B direction |
| STBY      | 33  | Standby (active HIGH) |
| SERVO_HEAD | 18 | Head servo PWM (500–2400µs) |
| SERVO_ARM_R | 19 | Right arm servo PWM |
| SERVO_ARM_L | 21 | Left arm servo PWM |
| BATTERY   | 34  | Battery voltage ADC (max 3.3V via divider) |
| UART RX   | 16  | Receive from Pi |
| UART TX   | 17  | Transmit to Pi |

### Motor Commands (ESP32)

| Command | Description |
|---------|-------------|
| `F`, `B`, `L`, `R` | Forward, backward, turn left, turn right (continuous) |
| `F2000`, `B1000`, etc. | Movement with auto-stop after ms |
| `S` | Stop motors |
| `SPD:150` | Set motor speed (0–255) |
| `HEAD:90` | Move head servo to angle (0–180) |
| `ARM_R:90` / `ARM_L:90` | Move arm servos to angle (0–180) |
| `HAPPY` | Animate both arms (150°/30° → 90°, non-blocking) |
| `CENTER` | Return all 3 servos to 90° |

The ESP32 also sends battery voltage data every 2 seconds as `BAT:7.45` lines over serial.

### Battery Monitor

The `BatteryMonitor` runs as a background daemon thread that reads `BAT:` lines from the serial connection and triggers warnings or shutdown based on voltage thresholds:

| Threshold | Voltage | Action |
|-----------|---------|--------|
| Critical | ≤ 6.8V | Immediate `sudo shutdown -h now` |
| Low | ≤ 7.2V | Warning + 30-second countdown |
| Recovery | > 7.2V | Cancels countdown, logs recovery |

## Remote Shutdown System

A standalone system to remotely shut down the robot via a web dashboard or mobile app.

### Architecture

```
Mobile App / Browser
        │  POST /shutdown { "token": "…" }
        ▼
Railway (FastAPI — shutdown/main.py)
        │  GET /shutdown-status (polled every 15s)
        ▼
Raspberry Pi (robot_shutdown_client.py)
        │  sudo shutdown -h now
        ▼
     Ropo Robot
```

### Start the Server (Local Development)

```bash
# Install deps
pip install fastapi uvicorn

# Set token (optional — defaults to "ropo-shutdown-default-token")
export SHUTDOWN_TOKEN=my-secret-token

# Run from project root
uvicorn shutdown.main:app --host 0.0.0.0 --port 8000
```

Then open **http://localhost:8000** in a browser to access the Ropo Control Panel.

### API Endpoints

| Method | Path               | Description                    |
|--------|--------------------|--------------------------------|
| GET    | `/`                | Web dashboard (Ropo Control Panel) |
| GET    | `/shutdown-status` | Check shutdown flag            |
| POST   | `/shutdown`        | Request robot shutdown         |
| POST   | `/shutdown-reset`  | Reset shutdown flag            |

All `POST` endpoints require `{ "token": "SECRET_TOKEN" }` in the request body.

### Deploy to Railway

See `shutdown/README.md` for full Railway deployment instructions.

### Raspberry Pi Client

The polling client (`robot_shutdown_client.py`) runs as a systemd service (`ropo-shutdown.service`) and continuously polls the backend every 15 seconds. When it detects a shutdown signal, it resets the flag and executes `sudo shutdown -h now`.

## Roadmap

### Phase 1 — Desktop Complete ✅
- [x] Voice pipeline (VAD + ASR + LLM + TTS)
- [x] Animated robot face (pygame)
- [x] Vision pipeline (YOLO + face tracking + gesture)
- [x] Settings panel with touch gestures
- [x] Mic mute toggle
- [x] Health check diagnostic tool
- [x] Adaptive load shedding
- [x] Wake word detection (fuzzy matching — "روبو" / "ropo")
- [x] Camera vertical flip (fix for upside-down mount)
- [x] Face identity tracking (LBP embeddings + session management)

### Phase 2 — Hardware Control ✅
- [x] ESP32 firmware (TB6612FNG motors + servos + battery ADC)
- [x] Motor controller Python driver (forward, backward, turn, speed)
- [x] Servo control (head, left arm, right arm — 0–180°)
- [x] Head tracking (servo follows largest face)
- [x] Voice motor commands (Arabic + English)
- [x] Battery monitor with automatic Pi shutdown
- [x] HAPPY arm animation (non-blocking state machine)

### Phase 3 — Raspberry Pi Deployment 🔄
- [ ] Run setup.sh on Pi 5
- [ ] Test all pipelines on Pi hardware
- [ ] Tune performance (frame skips, vision profiles, thermal throttle)
- [ ] Connect touchscreen display
- [ ] Test CSI camera with picamera2
- [ ] Wire ESP32 for motor + servo + battery
- [ ] Calibrate battery voltage divider ratio

### Phase 4 — Mobile App 📋
- [ ] Design mobile app wireframes
- [ ] Build app (Flutter or React Native)
- [ ] WebSocket connection to robot
- [ ] Live camera feed on mobile
- [ ] Remote settings control

### Phase 5 — Specialized Vision 📋
- [ ] Collect electronics/circuit dataset
- [ ] Fine-tune YOLOv8s on classroom objects
- [ ] Integrate specialized model
- [ ] Test with real circuit diagrams

## Team Contribution

**Wake Word Recording (needed now):**
كل عضو في التيم يسجّل samples عشان نبني dataset للـ wake word.

```bash
python record_wake_word.py
```

الهدف لكل شخص:
- 50+ positive sample — قول "روبو" بأشكال مختلفة
- 100+ negative sample — كلام عادي من غير "روبو"

بعد التسجيل ابعت فولدر `wake_word_data/` للـ team lead.

**Recommended: 500+ positive, 1000+ negative total across all team members.**

## Known Limitations

- **edge-tts requires internet** — TTS will not work without an active connection
- **Emotion detector needs manually placed weights** — The `emotion_cnn_pytorch.pt` model must be placed in `models/` manually; it is not included by default
- **Google ASR requires internet** — Speech recognition will fail without connectivity
- **YOLO is slow on Pi 4 CPU** — Object detection runs at ~200-500ms per frame on Pi 4 without GPU acceleration; consider using `MINIMAL` profile on Pi 4

## License

MIT
