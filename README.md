# Rope — AI Educational Robot

![Status](https://img.shields.io/badge/status-in%20development-yellow)
![Platform](https://img.shields.io/badge/platform-Raspberry%20Pi%205%20%7C%20Windows-blue)
![Python](https://img.shields.io/badge/python-3.10%2B-green)
![License](https://img.shields.io/badge/license-MIT-brightgreen)

An interactive educational robot with a conversational voice pipeline, vision system, animated face, and physical hardware control. Designed for Raspberry Pi 4/5 and Windows desktop.

## Features

- **Voice Pipeline** — VAD (Silero) → ASR (Google) → LLM (OpenRouter) → TTS (edge-tts)
- **Wake Word Activation** — "روبو", "يا روبو", "ropo", "hey robo", "ok robo" with fuzzy matching (rapidfuzz, 70% threshold)
- **Vision Pipeline** — Face tracking (OpenCV DNN), gesture recognition (OpenCV contour analysis), object detection (YOLOv8s), obstacle detection (Lucas-Kanade optical flow), scene understanding (YOLOv8s-seg)
- **Animated Robot Face** — Pygame-based with state transitions (IDLE, LISTENING, THINKING, SPEAKING, HAPPY, CURIOUS, SLEEP)
- **Settings Panel** — Tap/click-to-cycle settings for language, TTS speed, volume, vision mode, microphone mute; theme support (dark_blue, cyber_green, monochrome)
- **Hardware Control** — ESP32-based L298N motor driver with differential drive, three servos (head, left arm, right arm), battery voltage monitoring with automatic Pi shutdown
- **Academic Mode** — FastAPI server for lesson context injection; mobile app sends lesson content, robot answers follow-up questions via LLM + TTS
- **Session Memory** — SQLite-backed conversation history with sliding window and summarization
- **Filler Phrases** — Natural-sounding filler phrases in Arabic and English while the LLM processes
- **Offline Fallback** — Graceful degradation when OpenRouter is unreachable
- **Remote Shutdown** — FastAPI-based remote shutdown system with web dashboard and Raspberry Pi polling client (systemd service)
- **Hardware Diagnostics** — Standalone interactive tool for motor/servo calibration, battery monitoring, and full hardware test
- **Health Check** — Comprehensive startup and standalone diagnostics with report generation

## Current Status

| Component | Status |
|-----------|--------|
| Voice Pipeline (VAD → ASR → LLM → TTS) | Working |
| Animated Face UI | Working |
| Settings Panel (tap/click) | Working |
| Mic Mute Toggle | Working |
| Vision Pipeline (YOLO + Face + Gesture) | Working on Desktop |
| Wake Word Detection | Working ("روبو" / "ropo" / "يا روبو" / "hey robo" / "ok robo") |
| Voice Motor Commands | Working (Arabic and English) |
| Head Tracking (Servo Follows Face) | Working |
| Camera Vertical Flip | Working |
| Face Identity Tracking (LBP Embeddings) | Working |
| ESP32 L298N Motor + Servo + Battery Firmware | Working |
| Battery Monitor (Auto Shutdown on Low) | Working |
| Academic Mode (FastAPI + Context Injection) | Working |
| Hardware Diagnostics Tool | Working |
| Remote Shutdown System | Working |
| Raspberry Pi Deployment | Next step |
| YOLO Fine-tuning (Electronics) | Planned |

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          main.py (Entry Point)                           │
│                                                                           │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────────────────┐    │
│  │  FaceModule │  │  TTSModule   │  │      LLMModule                │    │
│  │  (pygame)   │  │  (edge-tts)  │  │  ┌────────────────────────┐   │    │
│  │             │  │              │  │  │  SessionManager        │   │    │
│  │  IDLE       │  │  speak()     │  │  │  (SQLite DB)           │   │    │
│  │  LISTENING  │  │  speak_and_  │  │  │                        │   │    │
│  │  THINKING   │  │  wait()      │  │  │  MemoryManager         │   │    │
│  │  SPEAKING   │  │  stop()      │  │  │  (sliding window +     │   │    │
│  │  CURIOUS    │  │              │  │  │   summarization)       │   │    │
│  │  HAPPY      │  │              │  │  │                        │   │    │
│  │  SLEEP      │  │              │  │  │  OpenRouterConn        │   │    │
│  └──────┬──────┘  └──────┬───────┘  │  │  (API → LLM)           │   │    │
│         │                │          │  └────────────────────────┘   │    │
│         │ callbacks      │ speak()  └──────────┬───────────────────┘    │
│         │                │                     │                        │
│  ┌──────▼────────────────▼─────────────────────▼───────────────────┐    │
│  │                    VoicePipeline                                  │    │
│  │                                                                   │    │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────────┐  │    │
│  │  │   VAD    │─▶│   ASR    │─▶│  Filler  │─▶│    LLM          │  │    │
│  │  │ (Silero) │  │ (Google) │  │  Phrase  │  │  (chat)         │  │    │
│  │  │          │  │          │  │(fire &   │  │                 │  │    │
│  │  │  mic ────┤  │  audio──▶│  │ forget)  │  │  response       │  │    │
│  │  │  input   │  │  → text  │  │          │  │                 │  │    │
│  │  └──────────┘  └────┬─────┘  └──────────┘  └─────┬───────────┘  │    │
│  │                     │                             │              │    │
│  │                     │         ┌──────────────┐    │              │    │
│  │                     │         │   TTS stop() │◀───┘              │    │
│  │                     │         │   + speak_   │                   │    │
│  │                     │         │   and_wait() │                   │    │
│  │                     │         └──────┬───────┘                   │    │
│  │                     └────────────────┘                           │    │
│  └──────────────────────────┬───────────────────────────────────────┘    │
│                             │                                            │
│  ┌──────────────────────────▼───────────────────────────────────────┐    │
│  │                    VisionPipeline                                  │    │
│  │                                                                   │    │
│  │  ┌────────┐                                                       │    │
│  │  │Camera  │                                                       │    │
│  │  │(cv2/   │                                                       │    │
│  │  │picam2) │                                                       │    │
│  │  └───┬────┘                                                       │    │
│  │      │ frames                                                      │    │
│  │  ┌───▼──────────────────────────────────────────────────┐         │    │
│  │  │                  Module Router                        │         │    │
│  │  │                                                       │         │    │
│  │  │  ┌────────────┐  ┌──────────┐  ┌──────────────────┐  │         │    │
│  │  │  │FaceTracker │  │ Gesture  │  │    Emotion        │  │         │    │
│  │  │  │(OpenCV DNN)│  │(OpenCV   │  │   (CNN PyTorch)   │  │         │    │
│  │  │  │            │  │ contour) │  │   [disabled]      │  │         │    │
│  │  │  └────────────┘  └──────────┘  └──────────────────┘  │         │    │
│  │  │  ┌────────────┐  ┌──────────┐  ┌──────────────────┐  │         │    │
│  │  │  │  Objects   │  │ Obstacle │  │     Scene         │  │         │    │
│  │  │  │ (YOLOv8s)  │  │ (LK Flow)│  │  (YOLOv8s-seg)    │  │         │    │
│  │  │  └────────────┘  └──────────┘  └──────────────────┘  │         │    │
│  │  └──────────────────────────┬────────────────────────────┘         │    │
│  │                             │                                       │    │
│  │                     shared_context                                  │    │
│  └─────────────────────────────┼───────────────────────────────────────┘    │
│                                │                                            │
│                                ▼                                            │
│                    ┌───────────────────────┐                                │
│                    │  LLM with Vision      │                                │
│                    │  [VISION] prompt      │                                │
│                    └───────────────────────┘                                │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    Academic Mode (FastAPI)                            │   │
│  │  /status /context (POST/DELETE) /ask                                 │   │
│  │  Mobile app sends lesson content, robot answers via LLM + TTS        │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    Settings Panel                                     │   │
│  │  Tap → Settings → Cycle rows: Language, TTS Speed, Volume,           │   │
│  │  Vision Mode, Microphone                                              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    Watchdog & Diagnostics                             │   │
│  │  - Component health pings (Watchdog)                                 │   │
│  │  - CPU temperature monitoring                                        │   │
│  │  - Periodic garbage collection                                       │   │
│  │  - System monitor (FPS, temp overlay)                                 │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
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
├── health_check.py                 # Standalone enhanced diagnostics with report
├── test_vision_debug.py            # Standalone vision debug tool (annotated frames)
├── requirements.txt                # Python dependencies
├── .env                            # Environment variables (not committed)
├── .env.example                    # Template for .env
├── .gitignore
├── setup.sh                        # Raspberry Pi / Linux setup script
├── setup.ps1                       # Windows setup script (PowerShell)
├── calibration.json                # Servo calibration state (generated by diag tool)
├── documentation.html              # HTML system documentation (static)
│
├── config/
│   ├── __init__.py
│   ├── settings.py                 # All configuration dataclasses
│   └── diagnostics.py              # Startup diagnostics, Watchdog, SystemMonitor
│
├── voice/
│   ├── __init__.py
│   ├── vad.py                      # Voice Activity Detection (Silero VAD)
│   ├── asr.py                      # Automatic Speech Recognition (Google)
│   ├── tts.py                      # Text-to-Speech (edge-tts via pygame)
│   ├── face.py                     # Animated robot face (pygame)
│   ├── text_utils.py               # Arabic reshaping (arabic-reshaper + python-bidi)
│   └── pipeline.py                 # Voice pipeline orchestrator
│
├── vision/
│   ├── __init__.py
│   ├── camera.py                   # Camera capture (OpenCV / picamera2)
│   ├── pipeline.py                 # Vision pipeline orchestrator
│   ├── documentation.html          # Vision-specific docs
│   └── modules/
│       ├── __init__.py
│       ├── face_tracker.py         # Face detection & tracking (OpenCV DNN)
│       ├── gesture.py              # Hand gesture recognition (OpenCV contour)
│       ├── emotion.py              # Emotion detection (PyTorch CNN)
│       ├── objects.py              # Object detection (YOLOv8s)
│       ├── obstacle.py             # Obstacle detection (Lucas-Kanade optical flow)
│       └── scene.py                # Scene understanding (YOLOv8s-seg)
│
├── llm/
│   ├── __init__.py
│   └── module.py                   # LLM module (OpenRouter + session memory + summarization)
│
├── hardware/
│   ├── __init__.py                 # Exports MotorController, BatteryMonitor
│   ├── motor_controller.py         # Serial communication with ESP32
│   ├── battery_monitor.py          # Voltage monitoring & auto-shutdown
│   ├── HARDWARE_DOCS.html          # Hardware documentation (static)
│   └── esp32/
│       └── main.cpp                # ESP32 firmware (L298N motors, servos, battery ADC)
│
├── tools/
│   ├── __init__.py
│   └── hardware_diagnostics.py     # Interactive motor/servo/battery calibration tool
│
├── academic/
│   ├── __init__.py
│   ├── context.py                  # Thread-safe lesson context holder
│   └── server.py                   # FastAPI academic API server
│
├── shutdown/
│   ├── __init__.py
│   ├── main.py                     # FastAPI remote shutdown server + web dashboard
│   ├── README.md                   # Railway deployment instructions
│   └── requirements.txt            # Isolated deps for Railway
├── robot_shutdown_client.py        # Raspberry Pi polling client
├── ropo-shutdown.service           # systemd service for polling client
│
├── models/                         # Pre-trained ML models
│   ├── deploy.prototxt
│   ├── res10_300x300_ssd_iter_140000.caffemodel
│   ├── yolov8s.pt
│   ├── yolov8s-seg.pt
│   ├── yolov8n.pt
│   ├── yolov8n-seg.pt
│   ├── hand_landmarker.task
│   └── face_landmarker.task
│
├── data/                           # Runtime data (SQLite DB, logs)
├── fonts/
│   └── Cairo-Regular.ttf           # Arabic-capable font for speech bubbles
├── doc/                            # Documentation artifacts
├── piper_models/                   # Legacy TTS models (no longer used)
├── tests/                          # Unit tests (empty)
└── vision_debug_output/            # Debug frames from test_vision_debug.py
```

## Requirements

### Hardware

- Raspberry Pi 4/5 (4GB+ RAM recommended) or Windows/Linux desktop
- USB microphone
- Speaker (3.5mm or USB)
- USB or CSI camera
- Touchscreen (for settings panel interaction)
- ESP32 development board (for motor/servo/battery control)
- L298N dual motor driver module (or compatible H-bridge)
- 2x DC motors with wheels (differential drive)
- 3x Servo motors (head, left arm, right arm)
- 7.4V LiPo battery (or equivalent)
- Voltage divider resistors for battery ADC (GPIO 34 max 3.3V)

### Software

- Python 3.10+
- Dependencies listed in `requirements.txt`
- ESP32 Arduino Core v3.x for firmware compilation

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

### Windows (PowerShell)

```powershell
.\setup.ps1
```

### Raspberry Pi / Linux

```bash
git clone https://github.com/abdrahman-dev/Master-Robot.git
cd Rope
chmod +x setup.sh
./setup.sh
```

The setup script:
- Checks Python version (3.10+)
- Installs system dependencies (apt-get)
- Creates a virtual environment (`--system-site-packages` on Pi for picamera2)
- Installs Python packages with resilient retry logic
- Downloads OpenCV face detection models
- Downloads YOLOv8s and YOLOv8s-seg models (resumable)
- Configures camera, UART, and GPU memory on Raspberry Pi
- Runs the final pre-flight check (audio resampling, camera backend, YOLO models, imports, mic)
- Run with `--resume` to skip apt-get (re-run after partial failure)

## Configuration

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

### Environment Variables

| Variable | Description | Default |
| -------- | ----------- | ------- |
| `ROBOT_OPENROUTER_API_KEY` | OpenRouter API key for LLM access | _(required)_ |
| `ROBOT_OPENROUTER_MODEL` | LLM model to use | `openrouter/free` |
| `ROBOT_OPENROUTER_AVAILABILITY_TIMEOUT_SEC` | Timeout for API availability check | `5` |
| `ROBOT_LLM_PROVIDER` | LLM provider | `openrouter` |
| `ROBOT_LLM_REQUEST_TIMEOUT_SEC` | LLM request timeout | `90` |
| `ROBOT_LLM_SUMMARIZE_TIMEOUT_SEC` | Summarization timeout | `60` |
| `ROBOT_LLM_WINDOW_SIZE` | Conversation sliding window size (messages) | `50` |
| `ROBOT_LOG_LEVEL` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) | `INFO` |
| `ROBOT_STUDENT_NAME` | Student name displayed in UI | `Student` |
| `ROBOT_DEFAULT_SESSION_LANGUAGE` | Default session language (`ar` or `en`) | `ar` |
| `ROBOT_FULLSCREEN` | Start in fullscreen mode | `false` |
| `ROBOT_ACADEMIC_MODE` | Enable academic API server | `false` |
| `ROBOT_ACADEMIC_API_PORT` | Academic API server port | `8001` |
| `ROBOT_VAD_THRESHOLD` | Voice activity detection sensitivity (0.0–1.0) | `0.60` |
| `ROBOT_VAD_SILENCE_TIMEOUT_SEC` | Silence duration before ending speech segment | `0.80` |
| `ROBOT_VAD_MIN_SPEECH_SEC` | Minimum speech duration to trigger ASR | `0.50` |
| `ROBOT_VAD_PRE_ROLL_SEC` | Pre-speech buffer to capture start of utterance | `0.30` |
| `ROBOT_VAD_SAMPLE_RATE` | VAD sample rate in Hz | `16000` |
| `ROBOT_VAD_CHUNK_MS` | VAD chunk duration in ms | `32` |
| `ROBOT_VAD_TORCH_THREADS` | Torch thread count for VAD inference | `1` |
| `ROBOT_VAD_MAX_ABS_AMP` | Maximum absolute amplitude for audio clipping | `1.0` |
| `ROBOT_VAD_HUB_REPO` | Silero VAD hub repository | `snakers4/silero-vad` |
| `ROBOT_VAD_HUB_NAME` | Silero VAD model name | `silero_vad` |
| `ROBOT_VAD_TRUST_REPO` | Trust hub repo | `true` |
| `ROBOT_VAD_MODEL_LOCAL_PATH` | Local path for VAD model (optional) | _(empty)_ |
| `ROBOT_ASR_PROVIDER` | ASR engine | `google` |
| `ROBOT_ASR_LANGUAGE_MODE` | Language detection (`auto`, `ar`, `en`) | `auto` |
| `ROBOT_ASR_SAMPLE_RATE` | ASR sample rate in Hz | `16000` |
| `ROBOT_ASR_DEFAULT_DURATION_SEC` | Default recording duration (non-streaming) | `5.0` |
| `ROBOT_CAM_WIDTH` | Camera capture width | `1280` (desktop) / `640` (Pi) |
| `ROBOT_CAM_HEIGHT` | Camera capture height | `720` (desktop) / `480` (Pi) |
| `ROBOT_CAM_FPS` | Camera frames per second | `30` (desktop) / `15` (Pi) |
| `ROBOT_CAM_INDEX` | Camera index | `0` |
| `ROBOT_CAM_FORMAT` | Frame format | `BGR` |
| `ROBOT_CAM_BUFFER` | Camera buffer size | `1` |
| `ROBOT_FACE_THRESHOLD` | Face detection confidence threshold (max 0.6) | `0.35` |
| `ROBOT_FACE_FRAME_SKIP` | Process every Nth face frame | `2` |
| `ROBOT_FACE_SCALE_FACTOR` | Scale factor for face detection image | `0.5` |
| `ROBOT_VISION_PROFILE` | Vision profile (`minimal`, `balanced`, `full`) | `balanced` |
| `ROBOT_METRICS_OVERLAY` | Show FPS/temperature overlay on face (`0`/`1`) | `0` |
| `ROBOT_ADAPTIVE_SHEDDING` | Enable adaptive load shedding (`0`/`1`) | `1` |
| `ROBOT_TARGET_FRAME_MS` | Target milliseconds per frame for throttling | `100` |
| `ROBOT_MAX_FRAME_SKIP` | Maximum frame skip during throttling | `10` |
| `ROBOT_TTS_ENGINE` | TTS engine | `edge_tts` |
| `ROBOT_TTS_POLL_SEC` | Pygame playback poll interval | `0.05` |
| `ROBOT_TTS_AR_VOICE` | Arabic TTS voice | `ar-SA-HamedNeural` |
| `ROBOT_TTS_EN_VOICE` | English TTS voice | `en-US-GuyNeural` |
| `ROBOT_TTS_TEMP_DIR` | TTS audio temp directory | (system temp) |
| `ROBOT_TTS_AUDIO_TEMPLATE` | TTS audio filename template | `tts_{turn_id}.wav` |
| `ROBOT_MOTOR_PORT` | Serial port for ESP32 | `COM3` (Win) / `/dev/ttyS0` (Pi) |
| `ROBOT_MOTOR_BAUDRATE` | Serial baud rate | `115200` |
| `SHUTDOWN_API_URL` | Backend API URL for remote shutdown | _(required for shutdown)_ |
| `SHUTDOWN_TOKEN` | Shared secret token for shutdown auth | _(required for shutdown)_ |
| `SHUTDOWN_POLL_INTERVAL` | Polling interval in seconds (RPi client) | `15` |

## Usage

```bash
python health_check.py   # comprehensive system diagnostics
python main.py           # run the robot
python tools/hardware_diagnostics.py   # hardware calibration and testing
python test_vision_debug.py            # vision pipeline debug + annotated frames
```

### Controls

| Action | Method |
|--------|--------|
| Open settings panel | Drag horizontally across face (80+ px) |
| Cycle setting value | Tap a settings row |
| Close settings panel | Tap Close row or press Escape |
| Toggle fullscreen | Press F |
| Quit | Close window or Ctrl+C in terminal |

## Voice Pipeline

The voice pipeline processes audio in real-time through four stages:

1. **Wake Word Detection** — Continuously listens for robot name ("روبو" / "يا روبو" / "ropo" / "hey robo" / "ok robo") using fuzzy string matching (rapidfuzz, threshold 70%). All regular conversation is gated behind wake word activation. First wake word triggers introduction greeting: "أنا روبو، مساعدك الذكي! كيف أقدر أساعدك?" Subsequent activations get "نعم".
2. **VAD (Silero)** — Continuously monitors microphone input using Silero VAD to detect speech segments with configurable sensitivity and silence timeout. Audio is resampled to 16kHz if needed.
3. **ASR (Google)** — Transcribes captured speech segments using Google Speech Recognition API with automatic language detection (Arabic/English).
4. **LLM (OpenRouter)** — Sends transcribed text to the LLM with conversation history, optional vision context, and optional academic context. While the LLM processes, a natural filler phrase plays (e.g., "Let me think..." / "لحظة بفكر..."). New speech interrupts TTS immediately.
5. **TTS (edge-tts)** — Speaks the LLM response using edge-tts via pygame mixer, with animated face state transitions. Language is auto-detected from text (Arabic/English).

### Voice Motor Commands

The pipeline intercepts movement commands before sending to the LLM:

| Phrase | Action |
|--------|--------|
| "تعالي" / "اقترب" / "come here" | Move forward (2s) |
| "ارجع" / "go back" | Move backward (2s) |
| "يمين" / "turn right" | Turn right (1s) |
| "شمال" / "turn left" | Turn left (1s) |
| "دور" | Turn right (3s) |
| "وقف" / "استنى" / "stop" | Stop motors |

**Offline fallback:** If OpenRouter is unreachable (after 3 retries), the robot responds with a random fallback message in the detected language. The pipeline continues running and retries on next turn.

## Vision Pipeline

The vision pipeline runs camera frames through multiple optional modules:

- **Camera** — OpenCV backend with automatic picamera2 detection on Raspberry Pi for CSI cameras. Falls back through multiple camera indices (0, 1, 2). Frames are vertically flipped (`cv2.flip(frame, 0)`) to compensate for upside-down camera mounting.
- **Face Tracker** — Detects and tracks faces using OpenCV DNN (Caffe SSD) with identity tracking via LBP embeddings and cosine distance matching. Returns `"same_student"` or `"new_student"` with per-session UUID. Results include `center_x`/`center_y`, `normalized_x`/`normalized_y` (0.0–1.0), and `frame_width`/`frame_height`. Faces sorted by bounding box area (largest first). Face detection models auto-download if missing.
- **Head Tracking** — Maps the largest face's `normalized_x` to the head servo angle (0–180°) with 5° deadband to avoid serial flooding. Attach via `set_motor_controller(motor)`.
- **Gesture Recognition** — OpenCV-based skin detection (HSV + YCrCb masks) with contour analysis and convexity defect finger counting. Recognizes `open_palm` (stop) and `pointing_up` (continue).
- **Emotion Detection** — PyTorch CNN (7-class: angry, disgust, fear, happy, sad, surprise, neutral). **Note: Emotion is currently hardcoded disabled** in the pipeline regardless of profile setting. Place trained `emotion_cnn_pytorch.pt` in `models/`.
- **Object Detection** — YOLOv8s (lazy-loaded). Configurable confidence threshold (default 0.5). Disabled by default; enabled in FULL profile.
- **Obstacle Detection** — Lucas-Kanade optical flow-based. Tracks feature points across frames, computes flow divergence to detect approaching obstacles. Returns direction (left/right/stop/clear).
- **Scene Understanding** — YOLOv8s-seg (lazy-loaded). Classifies visible objects into scene descriptions (e.g., "classroom: person, desk, and laptop"). Disabled by default; enabled in FULL profile on desktop.

### Vision Profiles

| Profile | Enabled Modules | Description |
|---------|----------------|-------------|
| `MINIMAL` | Obstacle only | Lightweight, fastest performance |
| `BALANCED` | Obstacle + Emotion (currently disabled) | Good balance of features and speed |
| `FULL` | Objects + Scene (desktop only) + Obstacle | Maximum capability, slowest on Pi |

### Performance Management

- **Thermal Throttling** — When CPU temperature reaches 75°C, frame skip increases and profile downgrades from FULL to BALANCED. Normal operation restores at 65°C.
- **Adaptive Load Shedding** — If average frame processing exceeds 150% of target, frame skip increments. When below 50% of target, it restores. Configurable via `ROBOT_ADAPTIVE_SHEDDING` and `ROBOT_TARGET_FRAME_MS`.

### Context Buffer

A 10-frame rolling buffer stores recent vision results. The frame with the most faces (then most objects) is selected as shared context returned to the LLM, ensuring the best observation is used.

## Hardware Layer

The robot includes a physical motor and servo control system managed by an ESP32 microcontroller communicating over serial UART.

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
            │  L298N   │ │Servos│ │Battery ADC  │
            │Motor Drvr│ │x3    │ │GPIO 34      │
            └──────────┘ └──────┘ └─────────────┘
```

### ESP32 Pin Mapping

| Component | Pin | Description |
|-----------|-----|-------------|
| ENA (Motor A PWM) | 25 | Motor A speed (PWM 0–255 @ 1kHz) |
| IN1 | 26 | Motor A direction 1 |
| IN2 | 27 | Motor A direction 2 |
| ENB (Motor B PWM) | 14 | Motor B speed (PWM 0–255 @ 1kHz) |
| IN3 | 12 | Motor B direction 1 |
| IN4 | 13 | Motor B direction 2 |
| SERVO_HEAD | 18 | Head servo PWM (500–2400µs pulse) |
| SERVO_ARM_R | 19 | Right arm servo PWM |
| SERVO_ARM_L | 21 | Left arm servo PWM |
| BATTERY | 34 | Battery voltage ADC (max 3.3V via divider) |
| UART RX | 16 | Receive from Pi (Serial2) |
| UART TX | 17 | Transmit to Pi (Serial2) |

### Motor Commands (ESP32)

| Command | Description |
|---------|-------------|
| `F`, `B`, `L`, `R` | Forward, backward, turn left, turn right (continuous) |
| `F2000`, `B1000`, etc. | Movement with auto-stop after ms |
| `S` | Stop motors |
| `SPD:150` | Set motor speed (0–255) |
| `HEAD:90` | Move head servo to angle (0–180) |
| `ARM_R:90` / `ARM_L:90` | Move arm servos to angle (0–180) |
| `HAPPY` | Animate both arms (150°/30° → 90°, non-blocking state machine) |
| `CENTER` | Return all 3 servos to 90° |

The ESP32 sends battery voltage data every 2 seconds as `BAT:7.45` lines over serial. It also echoes acknowledgements (e.g., `OK:F`, `OK:HEAD:90`, `STOPPED`).

### Battery Monitor

The `BatteryMonitor` runs as a background daemon thread that reads `BAT:` lines from serial and triggers warnings or shutdown:

| Threshold | Voltage | Action |
|-----------|---------|--------|
| Critical | ≤ 6.8V | Immediate `sudo shutdown -h now` |
| Low | ≤ 7.2V | Warning + 30-second countdown |
| Recovery | > 7.2V | Cancels countdown, logs recovery |

## Academic Mode

A FastAPI server that integrates with the voice pipeline to answer lesson-specific follow-up questions. Controlled by `ROBOT_ACADEMIC_MODE=true` and `ROBOT_ACADEMIC_API_PORT=8001`.

### Architecture

```
Mobile App (lesson context)
        │ POST /context { "context": "...", "lesson_title": "..." }
        │ POST /ask { "context": "...", "question": "...", "language": "..." }
        ▼
Academic API Server (FastAPI on port 8001)
        │
        ├── AcademicContext (thread-safe, holds lesson title + excerpt)
        ├── LLMModule.chat() (injects academic context into LLM system prompt)
        └── TTSModule.speak() (speaks answer through robot speaker)
```

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/status` | Check if academic context is active |
| POST | `/context` | Set lesson context (title + content) |
| DELETE | `/context` | Clear academic context |
| POST | `/ask` | Ask a question within lesson context (returns TTS answer) |

The context is stored in a thread-safe `AcademicContext` holder — no persistence or RAG. The voice pipeline checks `academic_context.is_active()` on each turn and injects the lesson content into the LLM system prompt.

## Hardware Diagnostics Tool

A standalone interactive tool for testing and calibrating hardware:

```bash
python tools/hardware_diagnostics.py
```

Features:
- Interactive menu: forward, backward, turn, stop, speed control
- Servo calibration (head, left arm, right arm) with keyboard controls (A/D ±5°, Z/C ±1°)
- Calibration save/load to `calibration.json`
- Battery monitoring (one-shot and live)
- Full hardware test (runs every command once)
- Safe mode (suppresses actual OS shutdown)

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
pip install fastapi uvicorn
export SHUTDOWN_TOKEN=my-secret-token
uvicorn shutdown.main:app --host 0.0.0.0 --port 8000
```

Open **http://localhost:8000** for the Ropo Control Panel dashboard.

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Web dashboard (Ropo Control Panel) |
| GET | `/shutdown-status` | Check shutdown flag |
| POST | `/shutdown` | Request robot shutdown |
| POST | `/shutdown-reset` | Reset shutdown flag |

All POST endpoints require `{ "token": "SECRET_TOKEN" }` in the request body.

### Raspberry Pi Client

The polling client (`robot_shutdown_client.py`) runs as a systemd service (`ropo-shutdown.service`) and polls the backend every 15 seconds. When it detects a shutdown signal, it resets the flag and executes `sudo shutdown -h now`.

## Animated Face

The pygame-based face module renders a robot face with:

- **7 states**: IDLE, LISTENING, THINKING, SPEAKING, HAPPY, CURIOUS, SLEEP
- **Eye animations**: Smooth blinking, asymmetric blink, pupil drift, state-dependent eye height
- **Mouth animation**: Speaking mouth sync, happy smile
- **Glow pulse**: State-dependent glow intensity
- **Speech bubble**: Academic mode caption with Arabic text reshaping (Cairo font)
- **Battery indicator**: Top-right battery icon with pulsing low-battery warning
- **3 themes**: dark_blue, cyber_green, monochrome
- **Settings panel**: Language, TTS speed, Volume, Vision mode, Microphone mute
- **Overlay**: FPS and temperature display (when `ROBOT_METRICS_OVERLAY=1`)

## Health Check

Two diagnostic tools:

1. **Startup diagnostics** (`config/diagnostics.py`) — Automatically runs in `main.py`. Checks: microphone, speaker, camera, model files, disk space, RAM, internet connectivity.

2. **Standalone health check** (`python health_check.py`) — Comprehensive 462-line diagnostic script: platform info, package versions, model file presence, VAD settings, network connectivity, module imports, live VAD/TTS/LLM/camera tests, hardware test (MotorController + BatteryMonitor lifecycle), integration tests. Saves report to `health_report.txt`.

## Configuration System

All configuration is defined in `config/settings.py` as frozen dataclasses:

| Dataclass | Purpose |
|-----------|---------|
| `GeneralSettings` | Log level, student name, language, fullscreen |
| `PathSettings` | Project paths, model names/URLs, DB path |
| `CameraSettings` | Camera resolution/FPS, face detection params |
| `GestureSettings` | Skin color ranges, finger detection thresholds |
| `VisionSettings` | Profile, overlay, throttling, thermal limits |
| `ASRSettings` | Provider, sample rate, language mode |
| `VADSettings` | Threshold, chunk size, silence timeout, model source |
| `LLMSettings` | API key, model, timeouts, system prompts (AR/EN) |
| `TTSSettings` | Engine, voices, temp directory |
| `AcademicSettings` | Enable flag, API port |
| `ServoSettings` | Angle limits, happy/rest poses |
| `MotorSettings` | Serial port, baudrate, default speed |
| `BatterySettings` | Voltage thresholds, shutdown countdown |
| `HeadTrackingSettings` | Deadband, smoothing, invert flag |

Platform auto-detection via `detect_preset()` returns `RASPBERRY_PI_4`, `RASPBERRY_PI_5`, or `DESKTOP_DEBUG`. Camera resolution/FPS defaults differ by platform.

## Graceful Fallback Behavior

| Component | Failure Mode | Behavior |
|-----------|-------------|----------|
| Microphone | Not available / PortAudioError | Audio pipeline disabled, robot runs without voice input |
| Camera | Not available / cannot open | Vision pipeline disabled, voice-only mode |
| Motor Controller | Serial port not found | Runs without motors/servos/battery monitoring |
| OpenRouter API | Unreachable / timeout (3 retries) | Random fallback message in detected language |
| Emotion Model | Missing `emotion_cnn_pytorch.pt` | Model initializes with random weights (limited accuracy) |
| YOLO Model | Missing `yolov8s.pt` / `yolov8s-seg.pt` | Module disabled with log warning |
| Silero VAD | Hub download fails | Tries local fallback in `config/snakers4-silero-vad/` |
| FastAPI / Uvicorn | Not installed | Academic API server disabled |

## Roadmap

### Phase 1 — Desktop Complete
- [x] Voice pipeline (VAD + ASR + LLM + TTS)
- [x] Animated robot face (pygame)
- [x] Vision pipeline (YOLO + face tracking + gesture)
- [x] Settings panel with touch/drag gestures
- [x] Mic mute toggle
- [x] Health check diagnostic tool
- [x] Adaptive load shedding + thermal throttling
- [x] Wake word detection (fuzzy matching — "روبو" / "ropo" / "يا روبو")
- [x] Camera vertical flip
- [x] Face identity tracking (LBP embeddings + session management)
- [x] Arabic text reshaping (arabic-reshaper + python-bidi)

### Phase 2 — Hardware Control
- [x] ESP32 firmware (L298N motors + servos + battery ADC)
- [x] Motor controller Python driver
- [x] Servo control (head, left arm, right arm — 0–180°)
- [x] Head tracking (servo follows largest face)
- [x] Voice motor commands (Arabic + English)
- [x] Battery monitor with automatic Pi shutdown
- [x] HAPPY arm animation (non-blocking state machine)
- [x] Hardware diagnostics and calibration tool

### Phase 3 — Academic & Shutdown Systems
- [x] Academic mode (FastAPI + context injection)
- [x] Remote shutdown system (FastAPI + web dashboard)
- [x] Raspberry Pi polling client (systemd service)
- [x] Hardware diagnostics tool

### Phase 4 — Raspberry Pi Deployment
- [ ] Run setup.sh on Pi 5
- [ ] Test all pipelines on Pi hardware
- [ ] Tune performance (frame skips, vision profiles, thermal throttle)
- [ ] Connect touchscreen display
- [ ] Test CSI camera with picamera2
- [ ] Wire ESP32 for motor + servo + battery
- [ ] Calibrate battery voltage divider ratio

### Phase 5 — Mobile App
- [ ] Design mobile app wireframes
- [ ] Build app (Flutter or React Native)
- [ ] WebSocket connection to robot
- [ ] Live camera feed on mobile
- [ ] Remote settings control

### Phase 6 — Specialized Vision
- [ ] Collect electronics/circuit dataset
- [ ] Fine-tune YOLOv8s on classroom objects
- [ ] Integrate specialized model
- [ ] Test with real circuit diagrams

## Known Limitations

- **edge-tts requires internet** — TTS will not work without an active connection
- **Emotion detector is hardcoded disabled** — The `_apply_profile` method forces `emotion_detector.enabled = False` regardless of profile. Enable by removing that line in `vision/pipeline.py:115`
- **Google ASR requires internet** — Speech recognition will fail without connectivity
- **YOLO is slow on Pi 4 CPU** — Object detection runs at ~200-500ms per frame on Pi 4 CPU; use MINIMAL profile
- **Gesture uses OpenCV contour analysis**, not MediaPipe — may be less accurate than ML-based approaches
- **ESP32 firmware targets L298N** — STBY pin control not implemented (TB6612FNG users need modifications)

## License

MIT
