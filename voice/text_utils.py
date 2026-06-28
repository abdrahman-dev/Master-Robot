from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from arabic_reshaper import ArabicReshaper  # type: ignore[import-untyped]
    from bidi.algorithm import get_display  # type: ignore[import-untyped]
    _SHAPER = ArabicReshaper({
        "delete_harakat": False,
        "support_ligatures": True,
        "use_unshaped_instead_of_isolated": False,
    })
    _HAS_SHAPING = True
except ImportError:
    _SHAPER = None  # type: ignore[assignment]
    _HAS_SHAPING = False

_ARABIC_BLOCKS = (
    (0x0600, 0x06FF),
    (0x0750, 0x077F),
    (0x08A0, 0x08FF),
    (0xFB50, 0xFDFF),
    (0xFE70, 0xFEFF),
)


def contains_arabic(text: str) -> bool:
    if not text:
        return False
    for c in text:
        cp = ord(c)
        for lo, hi in _ARABIC_BLOCKS:
            if lo <= cp <= hi:
                return True
    return False


def reshape_text(text: str) -> str:
    if not _HAS_SHAPING or not contains_arabic(text):
        return text
    try:
        return get_display(_SHAPER.reshape(text))
    except Exception as exc:
        logger.warning("[text] Reshaping failed: %s", exc)
        return text


def wrap_text(text: str, font, max_width: int) -> list[str]:
    if not text:
        return []
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = current + " " + word if current else word
        w, _ = font.size(candidate)
        if w > max_width and current:
            lines.append(current)
            current = word
            ww, _ = font.size(word)
            if ww > max_width:
                break_part = ""
                for ch in word:
                    test_part = break_part + ch
                    tw, _ = font.size(test_part)
                    if tw > max_width and break_part:
                        lines.append(break_part)
                        break_part = ch
                    else:
                        break_part = test_part
                current = break_part
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines
