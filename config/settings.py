from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple
from dotenv import load_dotenv

load_dotenv()

IS_RASPBERRY_PI = (
    os.path.exists("/etc/rpi-issue") or
    os.path.exists("/proc/device-tree/model")
)


@dataclass(frozen=True)
class GeneralSettings:
    log_level: str = os.getenv("ROBOT_LOG_LEVEL", "INFO")
    student_name: str = os.getenv("ROBOT_STUDENT_NAME", "Student")
    default_session_language: str = os.getenv("ROBOT_DEFAULT_SESSION_LANGUAGE", "ar")


@dataclass(frozen=True)
class PathSettings:
    project_root: Path = field(default_factory=lambda: Path(__file__).parent.parent)
    models_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent / "models")
    db_path: Path = field(default_factory=lambda: Path(__file__).parent.parent / "data" / "robot_sessions.db")
    tts_temp_dir: Path = field(default_factory=lambda: Path(tempfile.gettempdir()) / "robot_tts")

    face_proto_name: str = "deploy.prototxt"
    face_weights_name: str = "res10_300x300_ssd_iter_140000.caffemodel"
    face_proto_url: str = "https://raw.githubusercontent.com/opencv/opencv/master/samples/dnn/face_detector/deploy.prototxt"
    face_weights_url: str = "https://github.com/opencv/opencv_3rdparty/raw/dnn_samples_face_detector_20170830/res10_300x300_ssd_iter_140000.caffemodel"


@dataclass(frozen=True)
class CameraSettings:
    if IS_RASPBERRY_PI:
        width: int = int(os.getenv("ROBOT_CAM_WIDTH", "640"))
        height: int = int(os.getenv("ROBOT_CAM_HEIGHT", "480"))
        fps: int = int(os.getenv("ROBOT_CAM_FPS", "15"))
    else:
        width: int = int(os.getenv("ROBOT_CAM_WIDTH", "1280"))
        height: int = int(os.getenv("ROBOT_CAM_HEIGHT", "720"))
        fps: int = int(os.getenv("ROBOT_CAM_FPS", "30"))
    index: int = int(os.getenv("ROBOT_CAM_INDEX", "0"))
    format: str = os.getenv("ROBOT_CAM_FORMAT", "BGR")
    buffer_size: int = int(os.getenv("ROBOT_CAM_BUFFER", "1"))

    face_threshold: float = float(os.getenv("ROBOT_FACE_THRESHOLD", "0.35"))
    face_frame_skip: int = int(os.getenv("ROBOT_FACE_FRAME_SKIP", "2"))
    face_scale_factor: float = float(os.getenv("ROBOT_FACE_SCALE_FACTOR", "0.5"))
    camera_fallback_indices: List[int] = field(default_factory=lambda: [0, 1, 2])
    internet_check_host: str = "8.8.8.8"
    internet_check_port: int = 53


@dataclass(frozen=True)
class GestureSettings:
    buffer_size: int = 7
    stability_frames: int = 4
    max_hands: int = 1
    min_detection_confidence: float = 0.75
    skin_hsv_lower: Tuple[int, int, int] = (0, 20, 70)
    skin_hsv_upper: Tuple[int, int, int] = (20, 255, 255)
    skin_ycrcb_lower: Tuple[int, int, int] = (0, 135, 85)
    skin_ycrcb_upper: Tuple[int, int, int] = (255, 180, 135)
    finger_depth_threshold: float = 15.0
    finger_angle_threshold: float = 90.0
    pointing_aspect_ratio: float = 1.5
    pointing_top_ratio: float = 0.4
    contour_min_ratio: float = 0.01
    contour_max_ratio: float = 0.70


@dataclass(frozen=True)
class ASRSettings:
    provider: str = os.getenv("ROBOT_ASR_PROVIDER", "google")
    sample_rate: int = int(os.getenv("ROBOT_ASR_SAMPLE_RATE", "16000"))
    language_mode: str = os.getenv("ROBOT_ASR_LANGUAGE_MODE", "auto")
    default_record_duration_seconds: float = float(os.getenv("ROBOT_ASR_DEFAULT_DURATION_SEC", "5.0"))
    supported_languages: Dict[str, str] = field(default_factory=lambda: {"en": "en-US", "ar": "ar-EG"})


@dataclass(frozen=True)
class VADSettings:
    sample_rate: int = int(os.getenv("ROBOT_VAD_SAMPLE_RATE", "16000"))
    initial_threshold: float = float(os.getenv("ROBOT_VAD_THRESHOLD", "0.60"))
    chunk_duration_ms: int = int(os.getenv("ROBOT_VAD_CHUNK_MS", "32"))
    pre_speech_buffer_seconds: float = float(os.getenv("ROBOT_VAD_PRE_ROLL_SEC", "0.30"))
    min_speech_seconds: float = float(os.getenv("ROBOT_VAD_MIN_SPEECH_SEC", "0.50"))
    silence_timeout_seconds: float = float(os.getenv("ROBOT_VAD_SILENCE_TIMEOUT_SEC", "0.80"))
    max_abs_amplitude: float = float(os.getenv("ROBOT_VAD_MAX_ABS_AMP", "1.0"))
    torch_threads: int = int(os.getenv("ROBOT_VAD_TORCH_THREADS", "1"))
    model_local_path: str = os.getenv("ROBOT_VAD_MODEL_LOCAL_PATH", "")
    model_hub_repo: str = os.getenv("ROBOT_VAD_HUB_REPO", "snakers4/silero-vad")
    model_hub_name: str = os.getenv("ROBOT_VAD_HUB_NAME", "silero_vad")
    model_trust_repo: bool = os.getenv("ROBOT_VAD_TRUST_REPO", "true").lower() in ("1", "true", "yes")


@dataclass(frozen=True)
class LLMSettings:
    provider: str = os.getenv("ROBOT_LLM_PROVIDER", "openrouter")
    openrouter_api_key: str = field(default=os.getenv("ROBOT_OPENROUTER_API_KEY", ""))
    openrouter_model: str = os.getenv("ROBOT_OPENROUTER_MODEL", "openrouter/free")
    openrouter_availability_timeout_seconds: int = int(os.getenv("ROBOT_OPENROUTER_AVAILABILITY_TIMEOUT_SEC", "5"))
    request_timeout_seconds: int = int(os.getenv("ROBOT_LLM_REQUEST_TIMEOUT_SEC", "90"))
    summarization_timeout_seconds: int = int(os.getenv("ROBOT_LLM_SUMMARIZE_TIMEOUT_SEC", "60"))
    sliding_window_size: int = int(os.getenv("ROBOT_LLM_WINDOW_SIZE", "50"))

    system_prompt_arabic: str = (
        "أنت روبوت تعليمي اسمك روبو. تتحدث مع طلاب في مرحلة التعليم الأساسي. تحدث دائماً باللغة العربية الفصحى البسيطة الواضحة. إجاباتك قصيرة — جملتان أو ثلاث على الأكثر. كن مرحاً ومشجعاً."
    )

    system_prompt_english: str = (
        "You are an intelligent educational robot assistant helping students "
        "in their learning journey. Explain concepts simply, encourage curiosity, "
        "and help students understand. Speak in clear, simple English. "
        "Keep answers short (2-3 sentences max). Be enthusiastic and positive."
    )


@dataclass(frozen=True)
class TTSSettings:
    engine: str = os.getenv("ROBOT_TTS_ENGINE", "edge_tts")
    audio_temp_dir: str = os.getenv("ROBOT_TTS_TEMP_DIR", tempfile.gettempdir())
    audio_filename_template: str = os.getenv("ROBOT_TTS_AUDIO_TEMPLATE", "tts_{turn_id}.wav")
    pygame_poll_interval_seconds: float = float(os.getenv("ROBOT_TTS_POLL_SEC", "0.05"))


from enum import Enum


class VisionProfile(Enum):
    MINIMAL = "minimal"
    BALANCED = "balanced"
    FULL = "full"


class PlatformPreset(Enum):
    RASPBERRY_PI_4 = "raspberry_pi_4"
    RASPBERRY_PI_5 = "raspberry_pi_5"
    DESKTOP_DEBUG = "desktop_debug"


def detect_preset() -> PlatformPreset:
    if not IS_RASPBERRY_PI:
        return PlatformPreset.DESKTOP_DEBUG
    try:
        with open("/proc/device-tree/model") as f:
            model = f.read().strip().lower()
        if "5" in model:
            return PlatformPreset.RASPBERRY_PI_5
        return PlatformPreset.RASPBERRY_PI_4
    except (FileNotFoundError, IOError):
        return PlatformPreset.RASPBERRY_PI_4


@dataclass(frozen=True)
class VisionSettings:
    profile: VisionProfile = VisionProfile(os.getenv("ROBOT_VISION_PROFILE", "balanced"))
    enable_metrics_overlay: bool = os.getenv("ROBOT_METRICS_OVERLAY", "0").lower() in ("1", "true", "yes")
    adaptive_shedding: bool = os.getenv("ROBOT_ADAPTIVE_SHEDDING", "1").lower() in ("1", "true", "yes")
    target_frame_interval: float = float(os.getenv("ROBOT_TARGET_FRAME_MS", "100")) / 1000.0
    max_frame_skip: int = int(os.getenv("ROBOT_MAX_FRAME_SKIP", "10"))

    thermal_throttle_c: float = 75.0
    thermal_restore_c: float = 65.0


@dataclass(frozen=True)
class Settings:
    general: GeneralSettings
    paths: PathSettings
    camera: CameraSettings
    gesture: GestureSettings
    vision: VisionSettings
    asr: ASRSettings
    vad: VADSettings
    llm: LLMSettings
    tts: TTSSettings


def get_settings() -> Settings:
    return Settings(
        general=GeneralSettings(),
        paths=PathSettings(),
        camera=CameraSettings(),
        gesture=GestureSettings(),
        vision=VisionSettings(),
        asr=ASRSettings(),
        vad=VADSettings(),
        llm=LLMSettings(),
        tts=TTSSettings(),
    )


def configure_platform():
    if IS_RASPBERRY_PI:
        import cv2
        import torch
        cv2.setNumThreads(1)
        torch.set_num_threads(1)


def profile_module_config(profile: VisionProfile, preset: PlatformPreset) -> dict:
    base = {
        "enable_objects": False,
        "enable_scene": False,
        "enable_obstacle": False,
        "enable_emotion": False,
    }
    if profile == VisionProfile.MINIMAL:
        base.update({
            "enable_obstacle": True,
            "enable_emotion": False,
        })
    elif profile == VisionProfile.BALANCED:
        base.update({
            "enable_obstacle": True,
            "enable_emotion": True,
        })
    elif profile == VisionProfile.FULL:
        base.update({
            "enable_objects": True,
            "enable_scene": preset == PlatformPreset.DESKTOP_DEBUG,
            "enable_obstacle": True,
            "enable_emotion": True,
        })
    return base
