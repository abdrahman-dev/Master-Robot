#!/usr/bin/env python3
"""
Standalone audio pipeline test for Rope.
Tests: device detection -> raw capture -> resampling -> VAD -> ASR -> TTS
Run: python test_audio_pipeline.py

No imports from voice/ or config/ modules.
"""

import asyncio
import math
import os
import sys
import time
import wave
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

load_dotenv()

if sys.platform == "win32":
    import io
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

PASS = "PASS"
FAIL = "FAIL"
results = {}


def _ok(msg):
    print(f"  {GREEN}* {msg}{RESET}")


def _fail(msg):
    print(f"  {RED}* {msg}{RESET}")


def _warn(msg):
    print(f"  {YELLOW}* {msg}{RESET}")


def _info(msg):
    print(f"  {CYAN}* {msg}{RESET}")


def _heading(label, en_label):
    print(f"\n{BOLD}--- {en_label} ---{RESET}")


def _step_result(name, status, detail=""):
    results[name] = (status, detail)
    tag = PASS if status == PASS else FAIL
    if status == PASS:
        _ok(f"{name}: {detail}" if detail else name)
    else:
        _fail(f"{name}: {detail}" if detail else name)


def _save_wav(path, data, samplerate):
    with wave.open(path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(samplerate)
        i16 = np.clip(data * 32767, -32768, 32767).astype(np.int16)
        wf.writeframes(i16.tobytes())


# ============================================================
# Step 1: Device detection
# ============================================================
_heading("\u0627\u0644\u062e\u0637\u0648\u0629 1", "Step 1: Device detection")
print("Enumerating audio devices...\n")

try:
    import sounddevice as sd

    devices = sd.query_devices()
    if not devices:
        _fail("No audio devices found")
        _step_result("Device detection", FAIL, "No audio devices")
        sys.exit(1)

    input_devices = []
    for i, dev in enumerate(devices):
        ch = dev.get("max_input_channels", 0)
        sr = dev.get("default_samplerate", 0)
        name = dev.get("name", "Unknown")
        print(f"  [{i}] {name} \u2014 {ch} input ch, {sr:.0f} Hz")
        if ch > 0:
            input_devices.append((i, name, ch, sr))

    if not input_devices:
        _fail("No input devices found")
        _step_result("Device detection", FAIL, "No input devices")
        sys.exit(1)

    # Prefer USB mic (keyword in name), otherwise first input device
    usb = [(i, n, c, s) for i, n, c, s in input_devices
           if "usb" in n.lower()]
    if not usb:
        # Broader search: "microphone" in name, exclude "microsoft sound mapper"
        usb = [(i, n, c, s) for i, n, c, s in input_devices
               if "microphone" in n.lower()
               and "microsoft" not in n.lower()]
    if usb:
        dev_idx, dev_name, dev_ch, dev_sr = usb[0]
        print(f"\n  Selected USB mic: {dev_name}")
    else:
        # Pick first input device that isn't "Microsoft Sound Mapper"
        filtered = [(i, n, c, s) for i, n, c, s in input_devices
                    if "microsoft" not in n.lower()]
        if not filtered:
            filtered = input_devices
        dev_idx, dev_name, dev_ch, dev_sr = filtered[0]
        print(f"\n  Selected first input device: {dev_name}")

    print(f"  Device {dev_idx} \u2014 {dev_ch} ch at {dev_sr:.0f} Hz")
    _step_result("Device detection", PASS, f"Device {dev_idx}: {dev_name}")

except Exception as e:
    _fail(f"Error: {e}")
    _step_result("Device detection", FAIL, str(e))
    sys.exit(1)

# ============================================================
# Step 2: Raw audio capture
# ============================================================
_heading("\u0627\u0644\u062e\u0637\u0648\u0629 2", "Step 2: Raw audio capture")
print("Recording 3 seconds of audio...\n")

try:
    duration_s = 3.0
    native_sr = int(dev_sr)

    _info(f"Recording {duration_s}s at {native_sr} Hz (device {dev_idx})...")
    sys.stdout.flush()
    frames = int(duration_s * native_sr)
    recording = sd.rec(
        frames,
        samplerate=native_sr,
        channels=1,
        dtype="float32",
        device=dev_idx,
    )
    # Wait with timeout in a separate thread
    import threading as _t
    _done = _t.Event()

    def _poll():
        sd.wait()
        _done.set()

    _t.Thread(target=_poll, daemon=True).start()
    if not _done.wait(timeout=duration_s + 4.0):
        sd.stop()
        _warn("Recording timed out")
    recording = recording.flatten()

    peak = float(np.max(np.abs(recording)))
    print(f"  Peak amplitude: {peak:.4f}")

    if peak < 0.01:
        _warn("Mic too quiet \u2014 check connection")
        _step_result("Raw audio capture", FAIL, f"peak={peak:.4f}")
    else:
        _ok("Mic capturing audio OK")
        _step_result("Raw audio capture", PASS, f"peak={peak:.4f}")

    raw_path = "test_raw.wav"
    _save_wav(raw_path, recording, native_sr)
    print(f"  Saved: {raw_path} ({os.path.getsize(raw_path)} bytes)")

except Exception as e:
    _fail(f"Error: {e}")
    _step_result("Raw audio capture", FAIL, str(e))
    _warn("Continuing with synthetic 440 Hz tone for remaining tests")
    native_sr = int(dev_sr)
    t = np.linspace(0, 3, int(3 * native_sr), endpoint=False)
    recording = (0.1 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    peak = 0.1
    raw_path = "test_raw.wav"
    _save_wav(raw_path, recording, native_sr)
    print(f"  Synthetic audio saved: {raw_path}")

# ============================================================
# Step 3: Resampling
# ============================================================
_heading("\u0627\u0644\u062e\u0637\u0648\u0629 3", "Step 3: Resampling")
print("Resampling audio to 16000 Hz...\n")

try:
    target_sr = 16000
    resampled = None

    try:
        from scipy.signal import resample_poly

        gcd = math.gcd(native_sr, target_sr)
        up = target_sr // gcd
        down = native_sr // gcd
        resampled = resample_poly(recording, up, down).astype(np.float32)
        _info(f"Using scipy.signal.resample_poly (ratio={up}/{down})")
    except ImportError:
        duration = recording.shape[0] / float(native_sr)
        target_len = max(1, int(round(duration * target_sr)))
        src_x = np.linspace(0.0, duration, num=recording.shape[0],
                            endpoint=False, dtype=np.float64)
        dst_x = np.linspace(0.0, duration, num=target_len,
                            endpoint=False, dtype=np.float64)
        resampled = np.interp(dst_x, src_x, recording).astype(np.float32)
        _info("Using numpy.interp (scipy not available)")

    print(f"  Resampled: {native_sr} Hz -> {target_sr} Hz")
    print(f"  Samples: {len(recording)} -> {len(resampled)}")

    resampled_path = "test_resampled_16k.wav"
    _save_wav(resampled_path, resampled, target_sr)
    rsize = os.path.getsize(resampled_path)
    print(f"  Saved: {resampled_path} ({rsize} bytes)")
    _step_result("Resampling", PASS, f"{native_sr}->{target_sr} Hz")

except Exception as e:
    _fail(f"Error: {e}")
    _step_result("Resampling", FAIL, str(e))
    resampled = None

# ============================================================
# Step 4: VAD test
# ============================================================
_heading("\u0627\u0644\u062e\u0637\u0648\u0629 4", "Step 4: VAD test")
print("Silero Voice Activity Detection...\n")

vad_speech = 0
vad_total = 0

try:
    import torch

    model_path_str = os.getenv("ROBOT_VAD_MODEL_LOCAL_PATH", "").strip()
    model = None

    _info("Loading Silero VAD model...")

    if model_path_str:
        p = Path(model_path_str)
        if p.exists():
            _info(f"Loading local model from: {p}")
            model = torch.jit.load(str(p), map_location="cpu")

    if model is None:
        try:
            model, _ = torch.hub.load(
                "snakers4/silero-vad",
                "silero_vad",
                trust_repo=os.getenv("ROBOT_VAD_TRUST_REPO", "true").lower()
                in ("1", "true", "yes"),
            )
            _info("Model loaded from torch hub")
        except Exception as hub_err:
            _warn(f"Hub load failed: {hub_err}")
            fallback_dir = Path(__file__).parent / "config" / "snakers4-silero-vad"
            if fallback_dir.exists():
                jit_files = list(fallback_dir.glob("*.jit"))
                if jit_files:
                    model = torch.jit.load(str(jit_files[0]), map_location="cpu")
                    _info(f"Loaded from local fallback: {jit_files[0]}")
            if model is None:
                raise RuntimeError(
                    "Silero VAD unavailable. No internet and no local model."
                )

    model.eval()

    if resampled is None:
        raise RuntimeError("No resampled audio for VAD")

    threshold = float(os.getenv("ROBOT_VAD_THRESHOLD", "0.40"))
    print(f"  Threshold: {threshold}")

    chunk_size = 512
    vad_total = 0
    vad_speech = 0

    for start in range(0, len(resampled) - chunk_size + 1, chunk_size):
        chunk = resampled[start:start + chunk_size]
        vad_total += 1
        if chunk.dtype != np.float32:
            chunk = chunk.astype(np.float32)
        if not chunk.flags["C_CONTIGUOUS"]:
            chunk = np.ascontiguousarray(chunk, dtype=np.float32)
        t = torch.from_numpy(chunk)
        prob = float(model(t.unsqueeze(0), target_sr)
                     .detach().cpu().numpy().flatten()[0])
        if prob >= threshold:
            vad_speech += 1

    print(f"  VAD: {vad_speech}/{vad_total} speech chunks (threshold={threshold})")

    if vad_speech == 0:
        _warn("VAD detected no speech \u2014 speak louder")
        _step_result("VAD", FAIL, f"0/{vad_total} speech chunks")
    else:
        _step_result("VAD", PASS, f"{vad_speech}/{vad_total} speech chunks")

except Exception as e:
    _fail(f"Error: {e}")
    _step_result("VAD", FAIL, str(e))

# ============================================================
# Step 5: ASR test
# ============================================================
_heading("\u0627\u0644\u062e\u0637\u0648\u0629 5", "Step 5: ASR test")
print("Automatic Speech Recognition...\n")

try:
    provider = os.getenv("ROBOT_ASR_PROVIDER", "whisper")
    print(f"  Provider: {provider}")

    if resampled is None:
        raise RuntimeError("No resampled audio for ASR")

    i16 = np.clip(resampled * 32767, -32768, 32767).astype(np.int16)
    audio_bytes = i16.tobytes()
    t0 = time.monotonic()
    result_text = None
    result_lang = None

    if provider == "whisper":
        try:
            from faster_whisper import WhisperModel

            model_size = os.getenv("ROBOT_ASR_WHISPER_MODEL", "tiny")
            _info(f"Loading faster-whisper model: {model_size}")
            wm = WhisperModel(model_size, device="cpu",
                              compute_type="int8",
                              cpu_threads=1, num_workers=1)

            audio_np = i16.astype(np.float32) / 32768.0
            peak_asr = float(np.max(np.abs(audio_np)))
            if 0 < peak_asr < 0.3:
                audio_np = audio_np * (0.3 / peak_asr)
                audio_np = np.clip(audio_np, -1.0, 1.0)

            segments, info = wm.transcribe(
                audio_np, language="ar",
                beam_size=5, vad_filter=False,
            )
            result_text = " ".join(s.text for s in segments).strip()
            result_lang = info.language if info.language else "ar"

        except ImportError:
            _warn("faster-whisper not installed, trying Google ASR")
            provider = "google"

    if provider == "google":
        import speech_recognition as sr
        recognizer = sr.Recognizer()
        audio_data = sr.AudioData(audio_bytes, target_sr, sample_width=2)
        try:
            result_text = recognizer.recognize_google(audio_data, language="ar-EG")
            result_lang = "ar"
        except sr.UnknownValueError:
            pass
        except sr.RequestError as e:
            raise RuntimeError(f"Google ASR request failed: {e}")

    elapsed = time.monotonic() - t0

    if result_text:
        _ok(f"ASR result: '{result_text}'")
        print(f"  Language: {result_lang}  Time: {elapsed:.2f}s")
        _step_result("ASR", PASS, f"result='{result_text[:60]}'")
    else:
        _fail(f"ASR failed (time={elapsed:.2f}s)")
        _step_result("ASR", FAIL, "No transcription")

except Exception as e:
    _fail(f"Error: {e}")
    _step_result("ASR", FAIL, str(e))

# ============================================================
# Step 6: TTS test
# ============================================================
_heading("\u0627\u0644\u062e\u0637\u0648\u0629 6", "Step 6: TTS test")
print("Text-to-Speech...\n")

try:
    import edge_tts
    import pygame

    tts_text = "\u0627\u062e\u062a\u0628\u0627\u0631 \u0646\u0627\u062c\u062d\u060c \u0623\u0646\u0627 \u0623\u0633\u0645\u0639\u0643 \u0628\u0648\u0636\u0648\u062d"
    tts_path = "test_tts.mp3"

    try:
        print(f"  Text: '{tts_text}'")
    except UnicodeEncodeError:
        print(f"  Text: (Arabic: successful test, I can hear you clearly)")
    _info("Voice: ar-SA-HamedNeural (edge-tts)")

    async def _gen():
        c = edge_tts.Communicate(text=tts_text, voice="ar-SA-HamedNeural")
        await c.save(tts_path)

    asyncio.run(_gen())
    print(f"  Saved: {tts_path} ({os.path.getsize(tts_path)} bytes)")

    pygame.mixer.init()
    pygame.mixer.music.load(tts_path)
    pygame.mixer.music.play()
    _ok("Playing TTS \u2014 listen for audio")

    while pygame.mixer.music.get_busy():
        time.sleep(0.1)

    print("  Playback finished")
    _step_result("TTS", PASS, "Audio played")

except Exception as e:
    _fail(f"Error: {e}")
    _step_result("TTS", FAIL, str(e))

# ============================================================
# Step 7: Summary
# ============================================================
print()
print("=" * 52)
print("  AUDIO PIPELINE TEST RESULTS")
print("=" * 52)

all_pass = True
for name in ["Device detection", "Raw audio capture", "Resampling",
             "VAD", "ASR", "TTS"]:
    if name in results:
        status, detail = results[name]
        if status == PASS:
            print(f"  {name:25s}  {GREEN}PASS{RESET}  {detail}")
        else:
            print(f"  {name:25s}  {RED}FAIL{RESET}  {detail}")
            all_pass = False
    else:
        print(f"  {name:25s}  {YELLOW}SKIP{RESET}")
        all_pass = False

print("=" * 52)
if all_pass:
    print(f"  {BOLD}Overall: {GREEN}READY{RESET}")
else:
    print(f"  {BOLD}Overall: {RED}NOT READY{RESET}")
print("=" * 52)
