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
- **Settings Panel** — Swipe-based UI to toggle vision profiles and modes
- **Session Memory** — SQLite-backed conversation history with sliding window and summarization
- **Filler Phrases** — Natural-sounding filler phrases in Arabic and English while the LLM processes
- **Offline Fallback** — Graceful degradation when OpenRouter is unreachable

## Current Status

> المشروع شغال بالكامل على Desktop (Windows). الخطوة الجاية هي نقله على Raspberry Pi 5.

| المكون | الحالة |
|--------|--------|
| Voice Pipeline (VAD → ASR → LLM → TTS) | ✅ شغال |
| Animated Face UI | ✅ شغال |
| Settings Panel (swipe gesture) | ✅ شغال |
| Mic Mute Toggle | ✅ شغال |
| Vision Pipeline (YOLO + Face + Gesture) | ✅ شغال على Desktop |
| Wake Word Detection | 🔄 قيد التطوير |
| Raspberry Pi Deployment | 🔄 الخطوة الجاية |
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

1. **VAD (Silero)** — Continuously monitors microphone input using Silero VAD to detect speech segments with configurable sensitivity and silence timeout.
2. **ASR (Google)** — Transcribes captured speech segments using Google's Speech Recognition API with automatic language detection (Arabic/English).
3. **LLM (OpenRouter)** — Sends transcribed text to the LLM with conversation history and optional vision context. While the LLM processes, a natural filler phrase plays (e.g., "Let me think..." / "لحظة بفكر...") to maintain engagement.
4. **TTS (edge-tts)** — Speaks the LLM response aloud using edge-tts, with animated face state transitions.

**Offline fallback:** If OpenRouter is unreachable, the robot responds with a friendly error message. The pipeline continues running and will retry on the next turn.

## Vision Pipeline

The vision pipeline runs camera frames through multiple optional modules:

- **Face Tracker** — Detects and tracks faces using OpenCV DNN (Caffe SSD)
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

## Roadmap

### Phase 1 — Desktop Complete ✅
- [x] Voice pipeline (VAD + ASR + LLM + TTS)
- [x] Animated robot face (pygame)
- [x] Vision pipeline (YOLO + face tracking + gesture)
- [x] Settings panel with touch gestures
- [x] Mic mute toggle
- [x] Health check diagnostic tool
- [x] Adaptive load shedding

### Phase 2 — Wake Word (In Progress) 🔄
- [ ] Record wake word dataset ("روبو" / "ropo") — team contribution via record_wake_word.py
- [ ] Train openwakeword model
- [ ] Integrate wake word detector before VAD
- [ ] Test accuracy in classroom environment

### Phase 3 — Raspberry Pi Deployment 🔄
- [ ] Run setup.sh on Pi 5
- [ ] Test all pipelines on Pi hardware
- [ ] Tune performance (frame skips, vision profiles)
- [ ] Connect touchscreen display
- [ ] Test CSI camera with picamera2
- [ ] GPIO integration (LED status indicators)

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
