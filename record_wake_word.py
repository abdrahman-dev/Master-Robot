#!/usr/bin/env python3
"""
ROPE — أداة تسجيل بيانات كلمة التنبيه
تسجيل بيانات التدريب لكلمة التنبيه للروبوت "روبو"
"""

import os
import sys
import time
import datetime
import glob
from pathlib import Path

# ── Dependency checks ─────────────────────────────────────────────

try:
    import sounddevice as sd
except ImportError:
    print("خطأ: مكتبة sounddevice غير مثبتة.")
    print("شغّل: pip install sounddevice")
    sys.exit(1)

try:
    import soundfile as sf
except ImportError:
    print("خطأ: مكتبة soundfile غير مثبتة.")
    print("شغّل: pip install soundfile")
    sys.exit(1)

try:
    import numpy as np
except ImportError:
    print("خطأ: مكتبة numpy غير مثبتة.")
    print("شغّل: pip install numpy")
    sys.exit(1)

# ── ANSI colors ───────────────────────────────────────────────────

if sys.platform == "win32":
    os.system("")

RESET = "\033[0m"
BOLD = "\033[1m"
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
CYAN = "\033[96m"
MAGENTA = "\033[95m"
BG_BLUE = "\033[44m"
BG_GREEN = "\033[42m"
BG_YELLOW = "\033[43m"
BG_RED = "\033[41m"

# ── Constants ─────────────────────────────────────────────────────

SAMPLE_RATE = 16000
CHANNELS = 1
DURATION = 1.5
DTYPE = "int16"

DATA_DIR = Path("wake_word_data")
POS_DIR = DATA_DIR / "positive"
NEG_DIR = DATA_DIR / "negative"
LOG_FILE = DATA_DIR / "session_log.txt"

POSITIVE_PROMPTS_AR = [
    "يا روبو",
    "روبو انت سامعني؟",
    "روبو يلا بينا",
    "روبو ساعدني",
    "هي روبو",
    "روبو احنا هنبدأ",
    "روبو في حاجة عايز أسألك",
]

POSITIVE_PROMPTS_EN = [
    "hey ropo",
    "ropo are you there?",
    "ropo let's go",
    "ropo help me",
    "yo ropo",
    "ropo can you hear me?",
    "ok ropo",
]

NEGATIVE_PROMPTS = [
    ("الجو حلو النهارده", "ar"),
    ("واحد اتنين تلاتة أربعة خمسة", "ar"),
    ("one two three four five six", "en"),
    ("ازيك عامل إيه", "ar"),
    ("the weather is nice today", "en"),
    ("مرحبا كيف حالك", "ar"),
    ("hello how are you doing", "en"),
    ("أنا بحب الشوكولاتة", "ar"),
    ("I like to drink coffee", "en"),
    ("تمام خلاص يلا", "ar"),
    ("كن صامتاً", "silence"),
    ("صمت تام", "silence"),
    ("بدون كلام", "silence"),
]

# ── Helpers ───────────────────────────────────────────────────────

def clear_screen():
    os.system("cls" if sys.platform == "win32" else "clear")


def print_banner():
    print()
    print(f"{CYAN}{'=' * 48}{RESET}")
    print(f"{CYAN}  ROPE — أداة تسجيل كلمة التنبيه{RESET}")
    print(f"{CYAN}{'=' * 48}{RESET}")
    print()


def print_prompt_box(prompt_text, color=BG_BLUE):
    width = 50
    print()
    print(f"{color}╔{'═' * width}╗{RESET}")
    mid = f"  {prompt_text}  "
    padded = mid + " " * max(0, width - len(mid))
    print(f"{color}║{RESET}{BOLD} {padded[:width]} {RESET}{color}║{RESET}")
    print(f"{color}╚{'═' * width}╝{RESET}")
    print()


def volume_bar(peak_pct):
    bars = int(peak_pct / 6.25)
    empty = 16 - bars
    bar_str = f"{GREEN}{'█' * bars}{RESET}{RED}{'░' * empty}{RESET}"
    return bar_str


def count_files(directory):
    return len(glob.glob(str(directory / "*.wav")))


def get_next_index(directory, prefix):
    existing = glob.glob(str(directory / f"{prefix}_*.wav"))
    if not existing:
        return 1
    indices = []
    for f in existing:
        try:
            name = Path(f).stem
            idx = int(name.split("_")[1])
            indices.append(idx)
        except (ValueError, IndexError):
            pass
    return max(indices) + 1 if indices else 1


def log_recording(recorder_name, rec_type, filename, prompt_text, peak_amp):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{timestamp}, {recorder_name}, {rec_type}, {filename}, {prompt_text}, {peak_amp:.4f}\n"
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line)


def check_microphone():
    try:
        devices = sd.query_devices()
        has_input = any(d.get("max_input_channels", 0) > 0 for d in devices)
        if not has_input:
            return False
        return True
    except Exception:
        return False


# ── Recording ─────────────────────────────────────────────────────

def record_sample():
    frames = int(SAMPLE_RATE * DURATION)
    recording = sd.rec(frames, samplerate=SAMPLE_RATE, channels=CHANNELS, dtype=DTYPE)
    sd.wait()
    return recording


def play_sample(recording):
    sd.play(recording, samplerate=SAMPLE_RATE)
    sd.wait()


def get_peak_amplitude(recording):
    audio_float = recording.astype(np.float64)
    peak = np.max(np.abs(audio_float)) / 32767.0
    return float(peak)


def save_wav(filepath, recording):
    sf.write(str(filepath), recording, SAMPLE_RATE, subtype="PCM_16")
    if not filepath.exists():
        raise RuntimeError("لم يتم حفظ الملف على القرص")


# ── Main flow ─────────────────────────────────────────────────────

def main():
    clear_screen()
    print_banner()

    if not check_microphone():
        print(f"{RED}{'=' * 48}{RESET}")
        print(f"{RED}  خطأ: لم يتم العثور على ميكروفون!{RESET}")
        print(f"{RED}{'=' * 48}{RESET}")
        print()
        print("من فضلك وصّل ميكروفون وحاول تاني.")
        print()
        sys.exit(1)

    recorder_name = input(f"{CYAN}اكتب اسمك: {RESET}").strip()
    if not recorder_name:
        recorder_name = "مجهول"

    DATA_DIR.mkdir(exist_ok=True)
    POS_DIR.mkdir(exist_ok=True)
    NEG_DIR.mkdir(exist_ok=True)

    while True:
        clear_screen()
        print_banner()
        print(f"{GREEN}المسجّل: {BOLD}{recorder_name}{RESET}")
        print()
        print(f"{YELLOW}[P]{RESET} عينات إيجابية — قول {GREEN}\"روبو\"{RESET}")
        print(f"{YELLOW}[N]{RESET} عينات سلبية — كلام عشوائي بدون {RED}\"روبو\"{RESET}")
        print(f"{YELLOW}[Q]{RESET} خروج")
        print()
        choice = input(f"{CYAN}اختار [P/N/Q]: {RESET}").strip().lower()

        if choice == "q":
            print(f"\n{GREEN}مع السلامة!{RESET}\n")
            break
        elif choice == "p":
            run_session(recorder_name, "positive")
        elif choice == "n":
            run_session(recorder_name, "negative")

    total_pos = count_files(POS_DIR)
    total_neg = count_files(NEG_DIR)
    clear_screen()
    print_banner()
    print(f"{CYAN}{'─' * 48}{RESET}")
    print(f"{BOLD}ملخص الجلسة{RESET}")
    print(f"{CYAN}{'─' * 48}{RESET}")
    print()
    print(f"  ملفات إيجابية:  {GREEN}{total_pos}{RESET}")
    print(f"  ملفات سلبية:    {GREEN}{total_neg}{RESET}")
    print()
    print(f"  {YELLOW}مُقترح:{RESET}")
    print(f"    ١٠٠+ إيجابي، ٢٠٠+ سلبي لدقة جيدة")
    print()
    print(f"  {CYAN}ابعت فولدر wake_word_data/ لقائد الفريق{RESET}")
    print()


def run_session(recorder_name, session_type):
    is_positive = session_type == "positive"
    prefix = "positive" if is_positive else "negative"
    directory = POS_DIR if is_positive else NEG_DIR

    if is_positive:
        prompts = []
        ar_list = list(POSITIVE_PROMPTS_AR)
        en_list = list(POSITIVE_PROMPTS_EN)
        while ar_list or en_list:
            if ar_list:
                prompts.append((ar_list.pop(0), "ar"))
            if en_list:
                prompts.append((en_list.pop(0), "en"))
    else:
        prompts = NEGATIVE_PROMPTS

    idx = get_next_index(directory, prefix)
    session_count = 0

    for prompt_text, lang in prompts:
        clear_screen()
        print_banner()
        print(f"{GREEN}المسجّل: {recorder_name}  |  النوع: {prefix}  |  ملف رقم #{idx:03d}{RESET}")
        print()

        if lang == "silence":
            print_prompt_box(f"  {prompt_text}  ", BG_YELLOW)
        else:
            print_prompt_box(f"  {prompt_text}  ")

        input(f"{YELLOW}جاهز؟ اضغط ENTER للبداية{RESET}")
        print()

        for i in [3, 2, 1]:
            sys.stdout.write(f"\r{BOLD}{RED}{i}...{RESET} ")
            sys.stdout.flush()
            time.sleep(1)
        sys.stdout.write(f"\r{BOLD}{BG_RED} REC {RESET} ")
        sys.stdout.flush()
        print()

        try:
            recording = record_sample()
        except Exception as e:
            print(f"\n{RED}فشل التسجيل: {e}{RESET}")
            input(f"\n{YELLOW}اضغط ENTER للاستمرار{RESET}")
            continue

        peak = get_peak_amplitude(recording)
        peak_pct = peak * 100
        print(f"\n  مستوى الصوت: {volume_bar(peak_pct)} {peak_pct:.0f}%")

        if peak_pct < 10:
            print(f"  {RED}⚠ صوتك خافت جداً!{RESET}")
        elif peak_pct > 95:
            print(f"  {RED}⚠ صوتك عالي جداً!{RESET}")
        else:
            print(f"  {GREEN}✓ مستوى جيد{RESET}")

        print(f"\n{CYAN}جاري التشغيل...{RESET}")
        try:
            play_sample(recording)
        except Exception as e:
            print(f"  {YELLOW}فشل التشغيل: {e}{RESET}")

        while True:
            print()
            print(f"  {GREEN}[K]{RESET} احتفظ")
            print(f"  {YELLOW}[R]{RESET} أعد التسجيل")
            print(f"  {BLUE}[S]{RESET} تخطّى")
            print(f"  {RED}[Q]{RESET} خروج")
            print()
            decision = input(f"{CYAN}اختار [K/R/S/Q]: {RESET}").strip().lower()

            if decision == "k":
                filename = f"{prefix}_{idx:03d}.wav"
                filepath = directory / filename
                try:
                    save_wav(filepath, recording)
                    log_recording(recorder_name, session_type, filename, prompt_text, peak)
                    print(f"\n{GREEN}✓ تم الحفظ: {filename}{RESET}")
                    idx += 1
                    session_count += 1
                except Exception as e:
                    print(f"\n{RED}فشل الحفظ: {e}{RESET}")
                break

            elif decision == "r":
                print(f"\n{YELLOW}إعادة التسجيل...{RESET}")
                time.sleep(0.5)
                for i in [3, 2, 1]:
                    sys.stdout.write(f"\r{BOLD}{RED}{i}...{RESET} ")
                    sys.stdout.flush()
                    time.sleep(1)
                sys.stdout.write(f"\r{BOLD}{BG_RED} REC {RESET} ")
                sys.stdout.flush()
                print()
                try:
                    recording = record_sample()
                    peak = get_peak_amplitude(recording)
                    peak_pct = peak * 100
                    print(f"\n  مستوى الصوت: {volume_bar(peak_pct)} {peak_pct:.0f}%")
                    print(f"\n{CYAN}جاري التشغيل...{RESET}")
                    try:
                        play_sample(recording)
                    except Exception:
                        pass
                    continue
                except Exception as e:
                    print(f"\n{RED}فشل التسجيل: {e}{RESET}")
                    break

            elif decision == "s":
                print(f"\n{BLUE}تم التخطّي{RESET}")
                break

            elif decision == "q":
                print(f"\n{YELLOW}انتهت الجلسة{RESET}")
                return

            else:
                print(f"\n{RED}اختيار خاطئ. حاول تاني.{RESET}")

    clear_screen()
    print_banner()
    print(f"{GREEN}{'─' * 48}{RESET}")
    print(f"{BOLD}انتهت الجلسة!{RESET}")
    print(f"{GREEN}{'─' * 48}{RESET}")
    print()
    print(f"  تم تسجيل {GREEN}{session_count}{RESET} ملف في هذه الجلسة")
    total_pos = count_files(POS_DIR)
    total_neg = count_files(NEG_DIR)
    print(f"  إجمالي الملفات الإيجابية: {GREEN}{total_pos}{RESET}")
    print(f"  إجمالي الملفات السلبية: {GREEN}{total_neg}{RESET}")
    print()
    input(f"{CYAN}اضغط ENTER للرجوع للقائمة{RESET}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n{YELLOW}تم المقاطعة{RESET}")
        total_pos = count_files(POS_DIR) if POS_DIR.exists() else 0
        total_neg = count_files(NEG_DIR) if NEG_DIR.exists() else 0
        print(f"  ملفات إيجابية: {total_pos}")
        print(f"  ملفات سلبية: {total_neg}")
        print(f"\n{GREEN}التقدم محفوظ. مع السلامة!{RESET}\n")
        sys.exit(0)
    except Exception as e:
        print(f"\n{RED}خطأ غير متوقع: {e}{RESET}")
        sys.exit(1)
