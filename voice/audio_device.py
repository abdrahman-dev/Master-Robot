import logging
import os
import re
import subprocess
import sys
from typing import Optional

logger = logging.getLogger(__name__)

AUDIO_DEVICE_OVERRIDE = os.getenv("ROBOT_AUDIO_DEVICE", "").strip()


def get_alsa_card_number() -> Optional[int]:
    """Parse `arecord -l` and return the ALSA card number of the first USB microphone.

    Returns None if no USB microphone is found or ``arecord`` is unavailable.
    """
    if AUDIO_DEVICE_OVERRIDE:
        m = re.match(r"(?:plughw:)?(\d+)", AUDIO_DEVICE_OVERRIDE)
        if m:
            card = int(m.group(1))
            logger.info("Using ROBOT_AUDIO_DEVICE override: card %d", card)
            return card

    try:
        result = subprocess.run(
            ["arecord", "-l"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        logger.warning("arecord not available — cannot auto-detect audio device")
        return None

    candidates = []
    for line in result.stdout.splitlines():
        lower = line.lower()
        if "usb" in lower or "microphone" in lower or "mic" in lower:
            m = re.search(r"card\s+(\d+):", line)
            if m:
                candidates.append(int(m.group(1)))

    if candidates:
        card = candidates[0]
        logger.info("Detected USB microphone on card %d", card)
        return card

    logger.warning("No USB microphone found in arecord -l output")
    return None


def get_sounddevice_index(alsa_card: Optional[int] = None) -> Optional[int]:
    """Return the *sounddevice* device index matching the given ALSA card.

    Parameters
    ----------
    alsa_card
        ALSA card number.  If *None* it is auto-detected via
        :func:`get_alsa_card_number`.

    Returns
    -------
    int or None
        The device index to pass to ``sd.InputStream(device=...)``,
        or *None* when no suitable device could be found.
    """
    import sounddevice as sd

    if alsa_card is None:
        alsa_card = get_alsa_card_number()

    if alsa_card is not None:
        devices = sd.query_devices()
        for i, device_info in enumerate(devices):
            name = device_info.get("name", "")
            if f"(hw:{alsa_card}," in name:
                logger.info("Audio device %d: %s", i, name)
                return i

    # Fallback for Windows / non-ALSA platforms
    if AUDIO_DEVICE_OVERRIDE:
        devices = sd.query_devices()
        try:
            idx = int(AUDIO_DEVICE_OVERRIDE)
            if 0 <= idx < len(devices):
                logger.info("Using device %d via ROBOT_AUDIO_DEVICE override", idx)
                return idx
        except ValueError:
            pass
        for i, dev in enumerate(devices):
            if AUDIO_DEVICE_OVERRIDE.lower() in dev["name"].lower():
                logger.info("Matched device %d '%s' via ROBOT_AUDIO_DEVICE='%s'",
                            i, dev["name"], AUDIO_DEVICE_OVERRIDE)
                return i

    default = sd.default.device
    if default is None:
        pass
    elif isinstance(default, (int, float)):
        pass
    else:
        try:
            default = default[0]
        except (TypeError, IndexError, KeyError):
            default = None
    if default is not None and default >= 0:
        logger.info("Using system default input device index %d", default)
        return int(default)

    # Generic USB microphone name scan (cross-platform fallback)
    for i, dev in enumerate(sd.query_devices()):
        name_lower = dev["name"].lower()
        if dev["max_input_channels"] > 0 and any(kw in name_lower for kw in ("usb", "microphone", "mic", "input")):
            logger.info("Matched device %d '%s' (generic mic name scan)", i, dev["name"])
            return i

    for i, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0:
            logger.info("Fallback to device %d '%s' (has input channels)", i, dev["name"])
            return i

    logger.warning("No matching audio device found — caller should handle gracefully")
    return None


def get_device_sample_rate(device_index: int) -> Optional[int]:
    """Return the native sample rate of the given *sounddevice* device index."""
    import sounddevice as sd

    try:
        info = sd.query_devices(device_index)
        return int(info["default_samplerate"])
    except Exception as exc:
        logger.warning("Could not query sample rate for device %d: %s", device_index, exc)
        return None


def get_alsa_playback_device() -> Optional[str]:
    """Detect the best ALSA playback device for TTS audio output.

    Uses ``aplay -l`` to enumerate playback devices, preferring USB
    devices over HDMI or headphone jack.  On non-Linux platforms or
    when ``aplay`` is unavailable it returns *None*, letting callers
    fall back to the ALSA default.

    Returns
    -------
    str or None
        An ALSA device identifier (e.g. ``plughw:3,0``) or *None*.
    """
    override = AUDIO_DEVICE_OVERRIDE
    if override:
        logger.info("Using ROBOT_AUDIO_DEVICE override for playback: %s", override)
        return override

    if sys.platform != "linux":
        return None

    try:
        result = subprocess.run(
            ["aplay", "-l"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        logger.warning("aplay not available — cannot auto-detect playback device")
        return None

    candidates: list[tuple[int, str]] = []
    for line in result.stdout.splitlines():
        lower = line.lower()
        if "usb" in lower:
            m = re.search(r"card\s+(\d+):", line)
            if m:
                card = int(m.group(1))
                candidates.append((card, line.strip()))

    if candidates:
        card, desc = candidates[0]
        device = f"plughw:{card},0"
        logger.info("Selected USB playback device card %d — %s", card, desc)
        return device

    logger.info("No USB playback device found — will use ALSA default")
    return None
