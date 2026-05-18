# Rope — AI Educational Robot

## Project Overview

Rope is an interactive AI-powered educational robot designed to run on Raspberry Pi 4/5 or any Linux/Windows desktop. It combines real-time voice interaction (VAD + ASR + TTS), computer vision (face detection, object recognition, gesture control, obstacle detection), and an expressive animated robot face — all coordinated through a modular pipeline architecture.

---

## Project Structure — Final

```
Rope/
├── main.py                          # Entry point, system state machine
├── health_check.py                  # Standalone diagnostic script
├── test_vision_debug.py             # Standalone vision pipeline test
├── requirements.txt                 # Python dependencies
├── .env                             # Environment variables (API key, etc.)
├── .gitignore
├── README.md
├── PROJECT_REPORT.md                # This file
│
├── config/
│   ├── __init__.py
│   ├── settings.py                  # All config dataclasses, env-var driven
│   └── diagnostics.py               # Watchdog, SystemMonitor, temperature, GC
│
├── llm/
│   ├── __init__.py
│   └── module.py                    # OpenRouter client, session management, memory
│
├── voice/
│   ├── __init__.py
│   ├── vad.py                       # Silero VAD (Voice Activity Detection)
│   ├── asr.py                       # Google Speech Recognition (ASR)
│   ├── tts.py                       # edge-tts text-to-speech
│   ├── face.py                      # Animated robot face (pygame)
│   └── pipeline.py                  # Voice pipeline coordinator
│
├── vision/
│   ├── __init__.py
│   ├── camera.py                    # Cross-platform camera manager
│   ├── pipeline.py                  # Vision pipeline coordinator
│   └── modules/
│       ├── __init__.py
│       ├── face_tracker.py          # OpenCV DNN face detection + identity
│       ├── gesture.py               # Skin-color gesture recognition
│       ├── emotion.py               # PyTorch CNN emotion classifier
│       ├── objects.py               # YOLOv8 object detection (lazy load)
│       ├── scene.py                 # YOLOv8 scene segmentation (lazy load)
│       └── obstacle.py              # Lucas-Kanade optical flow obstacle detection
│
├── models/                          # ML model files (auto-downloaded or manual)
├── piper_models/                    # (Legacy — not currently used)
├── data/                            # SQLite database, log files
└── vision_debug_output/             # Test output (created by test_vision_debug.py)
```

---

## Architecture

### Threading Model

The system runs on 3 threads:

1. **Main thread** — `face.run_main_thread()` — pygame display loop (60 FPS). Handles touch/swipe input, settings panel overlay, face rendering.
2. **Voice thread** — `run_forever()` — `sd.InputStream` callback for microphone capture. Separately, a **worker thread** processes speech segments sequentially from a bounded queue (maxsize=3).
3. **Vision thread** — `run_loop()` — captures camera frames and runs all vision modules in a loop. Updates a shared context dict protected by a lock.

### State Machine

```
DEFAULT ──swipe left──> SETTINGS_PANEL ──swipe left──> VISION_MODE
   ^                                                        │
   │                                                        │ swipe left
   │                                                        v
   └─────────────────── swipe left <──── VOICE_ONLY <───────┘
   │
   └── swipe right (any state) → triggers settings, returns after 2s
```

- **DEFAULT**: Voice pipeline active, vision off, face idle.
- **SETTINGS_PANEL**: Overlay drawn on face. Tap rows to cycle: Language, TTS Speed, Volume, Vision Mode.
- **VISION_MODE**: Voice + Vision active. Touch swipe cycles profiles (Minimal/Balanced/Full).
- **VOICE_ONLY**: Voice active, vision off.

### Voice Pipeline Flow

```
Microphone → VAD (Silero) → ASR (Google) → LLM (OpenRouter) → TTS (edge-tts) → Speaker
                │                                                    │
                └── interrupt: stops current TTS playback ───────────┘
```

- VAD detects speech → starts recording segment
- Silence timeout → segment queued to bounded worker queue (maxsize=3)
- Worker: ASR transcribes (Arabic first, then English fallback)
- If vision active: reads best vision context from rolling buffer (last 10 frames)
- LLM generates response (Arabic system prompt)
- TTS plays response via pygame.mixer.music (edge-tts generates MP3)
- Interruption: new VAD segment stops current TTS immediately

### Vision Pipeline Flow

```
Camera → Face Tracker → Gesture Detector → Emotion Detector → Object Detection → Scene Segmentation → Obstacle Detection
          │                 │
          └── only runs if face detected ──┘
```

- **Always-on**: Face tracker, Obstacle detector
- **On face detected**: Gesture, Emotion
- **Per profile**: Objects (YOLOv8), Scene segmentation (YOLOv8n-seg)
- Context buffer: stores last 10 frames' results, picks the one with the most faces/objects for LLM consumption

---

## Key Features Implemented (Latest)

### 1. Rolling Vision Context Buffer (`vision/pipeline.py`)

**Problem**: Voice pipeline read only the latest single frame's vision data. If that frame missed the face (26% miss rate with OpenCV DNN), the LLM received empty context and replied "nothing visible".

**Solution**: Added `_context_buffer: deque(maxlen=10)`. Every vision frame stores its results in the buffer. When `get_shared_context()` is called, the pipeline picks the entry with the **most faces** (ties broken by most objects). This ensures the LLM always gets the best available detection from the last ~0.5-2 seconds.

### 2. Bounded Segment Queue (`voice/pipeline.py`)

Replaced unbounded daemon thread-per-segment with `queue.Queue(maxsize=3)` + single worker thread. If queue is full, oldest segment is discarded. Prevents thread explosion during rapid speech.

### 3. Safe Console Logging (`main.py`)

Custom `AsciiHandler(logging.StreamHandler)` that encodes all log output as ASCII with `errors="replace"` before writing to stdout. Prevents `UnicodeEncodeError` crashes when Arabic text appears in logs on Windows (cp1252 console).

### 4. Adaptive Load Shedding (`vision/pipeline.py`)

Tracks rolling average of frame processing time (30-frame window). If avg exceeds target interval, automatically increases `frame_skip` and optionally downgrades vision profile from FULL to BALANCED. Restores when load normalizes.

### 5. Lazy YOLO Loading (`vision/modules/objects.py`, `scene.py`)

YOLO models load on first `process_frame()` call in the vision thread, not in `__init__`. Main thread never blocks on YOLO loading. First inference includes model load time (~5s on CPU), subsequent frames run at ~100-200ms.

### 6. Watchdog System (`config/diagnostics.py`)

Timestamp-based liveness tracking. Registered components (`voice_queue_worker`, `vision_loop`) log warnings if they haven't pinged within their timeout. Helps detect stuck threads without crashing.

### 7. Settings Panel UI (`voice/face.py`)

In-pygame overlay with touch-input rows: Language (Arabic/English), TTS Speed (Slow/Normal/Fast), Volume (25/50/75/100%), Vision Mode (OFF/Minimal/Balanced/Full). Tap to cycle, selection flash animation, close via X button.

### 8. Thread-safe Shared Context (`vision/pipeline.py`)

`get_shared_context()` returns `copy.deepcopy()` under lock. No numpy arrays exposed — only lightweight semantic dicts (faces, gesture, emotion, objects, scene, obstacle). Prevents race conditions between vision writer and voice reader.

### 9. Raspberry Pi Optimizations (`config/settings.py`, `vision/pipeline.py`)

- Auto-detects Pi 4 vs Pi 5 vs Desktop via `/proc/device-tree/model`
- Default camera: 640x480@15fps on Pi, 1280x720@30fps on Desktop
- Frame skips: face=3, objects=6, scene=10 on Pi
- `cv2.setNumThreads(1)`, `torch.set_num_threads(1)` on Pi
- YOLO forced to `device="cpu"`, `half=False` on Pi
- Adaptive load shedding more aggressive on Pi

### 10. Camera Unavailable Fallback (`vision/camera.py`, `vision/pipeline.py`)

- Tries `picamera2` first on Pi, falls back to OpenCV
- `is_available()` method
- `run_loop()` exits immediately if camera unavailable
- Pipeline does not spin or crash

### 11. Offline Fallback (`llm/module.py`, `voice/pipeline.py`)

- `OpenRouterConnection.__init__()` does NOT crash on empty API key — logs warning
- `chat()` raises `LLMModuleError` on failure
- `voice/pipeline.py` catches it and returns: "I am having trouble connecting right now"
- Robot continues running (VAD + ASR + TTS + face) without LLM

### 12. OpenRouter Retry with Backoff (`llm/module.py`)

- 3 retries with exponential backoff (1s, 2s, 4s) on HTTP 429 or 5xx
- 30s per-attempt timeout
- On repeated failure: returns offline fallback

---

## Technical Details

### Audio System

- **Input**: `sounddevice.InputStream` at 16kHz, 1ch, float32, 32ms blocks
- **VAD**: Silero VAD (PyTorch), loaded once via `torch.hub.load()` or local `.jit` fallback
- **ASR**: Google Speech Recognition via `speech_recognition` library. Arabic first, English fallback
- **TTS**: edge-tts (Microsoft Edge cloud). Voices: `ar-EG-ShakirNeural` (male), `en-US-GuyNeural` (male). MP3 generated to temp file, played via `pygame.mixer.music`
- **Interruption**: When new VAD speech detected during TTS playback, `TTSModule.stop()` sets stop event → `pygame.mixer.music.stop()`

### Vision System

- **Camera**: OpenCV `VideoCapture` (Windows/Linux) or `picamera2` (RPi). Resolution configurable via env vars.
- **Face Detection**: OpenCV DNN (`res10_300x300_ssd_iter_140000.caffemodel`), confidence threshold 0.35, frame_skip 2-3. Identity via LBP histogram + cosine distance.
- **Gesture Detection**: Rule-based skin-color segmentation (HSV + YCrCb) + convex hull defects. Gestures: open_palm (stop), pointing_up (continue). Smoothing via 7-frame buffer.
- **Emotion Detection**: PyTorch CNN (3 conv blocks + 2 FC), 48x48 input, 7 emotions. Weights must be placed manually at `models/emotion_cnn_pytorch.pt` (random init otherwise).
- **Object Detection**: YOLOv8n via Ultralytics. Lazy-loaded on first inference. Frame_skip 3-6. Filtered by vision profile.
- **Scene Segmentation**: YOLOv8n-seg. Same lazy-load pattern. Heuristic scene description templates.
- **Obstacle Detection**: Lucas-Kanade sparse optical flow. Detects approaching obstacles by motion divergence analysis.

### LLM System

- **Provider**: OpenRouter API (OpenAI-compatible)
- **Default Model**: `liquid/lfm-2.5-1.2b-instruct:free`
- **Session Management**: SQLite with WAL mode, per-thread connections
- **Sliding Window**: Last 50 messages (configurable)
- **Auto-Summarization**: Triggered at window size threshold
- **Arabic System Prompt**: "انت روبوت تعليمي ذكي اسمك روبي. تتحدث مع طلاب في مرحلة التعليم الأساسي..."
- **Vision Integration**: `[VISION]` prefix injected into user message with detected faces/objects/gestures/emotions/obstacles

### Configuration

All settings via environment variables in `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `ROBOT_OPENROUTER_API_KEY` | — | OpenRouter API key |
| `ROBOT_LOG_LEVEL` | INFO | Logging verbosity |
| `ROBOT_VAD_THRESHOLD` | 0.60 | VAD sensitivity |
| `ROBOT_DEFAULT_SESSION_LANGUAGE` | ar | Default language (ar/en) |
| `ROBOT_CAM_WIDTH/HEIGHT/FPS` | 1280x720@30 | Camera resolution (640x480@15 on Pi) |
| `ROBOT_VISION_PROFILE` | balanced | Default vision profile |
| `ROBOT_TTS_ENGINE` | piper | (legacy, now edge-tts) |
| `ROBOT_ADAPTIVE_SHEDDING` | 1 | Enable adaptive load shedding |

---

## Known Limitations

1. **Face detection reliability**: OpenCV DNN at 0.35 threshold detects ~74% of frames. The rolling buffer (last 10 frames) mitigates this significantly.
2. **No wake word**: Microphone is always listening — no push-to-talk or wake-word detection.
3. **Emotion weights**: `emotion_cnn_pytorch.pt` must be manually placed in `models/`. Without it, random weights produce unreliable results.
4. **YOLO on Pi**: ~200-500ms per inference on Pi 4 CPU. Scene segmentation disabled by default on Pi.
5. **Unicode console**: Arabic text appears as `??` on Windows cp1252 console. Full Arabic visible in log file (`data/robot.log`).
6. **edge-tts dependency**: Requires internet for TTS synthesis (cloud-based). No offline TTS fallback.
7. **Single camera**: Only one camera index supported. No hot-swap.

---

## Building and Running

```bash
# Setup
python -m venv venv
source venv/bin/activate   # or venv\Scripts\activate on Windows
pip install -r requirements.txt

# Configure
echo "ROBOT_OPENROUTER_API_KEY=sk-or-v1-..." >> .env

# Health check
python health_check.py

# Vision test
python test_vision_debug.py

# Run
python main.py
```

**Controls during runtime:**
- Swipe left: Open settings panel → Cycle vision modes
- Swipe right: Quick settings (2s)
- Tap settings row: Toggle value
- Tap X/Close: Close panel
- Escape: Close panel / Exit
- Speak: Robot listens and responds

---

## Test Results (Desktop, 1280x720)

From `test_vision_debug.py` — 50 frames with all modules active:

| Module | Detection Rate | Avg Time/Frame |
|--------|---------------|----------------|
| Face tracker | 37/50 (74%) | 125ms |
| Object detection (YOLO) | 50/50 (100%) | 120ms (after first load) |
| Gesture detection | 50/50 (100%) | 26ms |
| Scene segmentation (YOLO) | 50/50 | 150ms |
| Obstacle detection | — | 7ms |
| Emotion detection | — | 200ms (sporadic) |

**Total per frame (all modules): ~500-800ms → ~1.5-2 FPS**
**Face-only mode: ~150ms → ~6-7 FPS**
**With rolling buffer: LLM always gets best detection from last 10 frames**

---

## Debugging

- **Vision pipeline test**: `python test_vision_debug.py` — saves annotated frames to `vision_debug_output/`
- **Log file**: `data/robot.log` — contains full Arabic text (file is UTF-8)
- **Console**: Arabic appears as `??` on Windows — log file has the real text
- **LLM debugging**: Set `ROBOT_LOG_LEVEL=DEBUG` to see `final_message` and `vision_context` in logs
- **Watchdog warnings**: `vision_loop stale` means camera is not running (normal in DEFAULT/VOICE_ONLY modes)
