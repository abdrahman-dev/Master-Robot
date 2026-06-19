#!/bin/bash

# ── Flags ───────────────────────────────────────────────────────────
SKIP_APT=false
if [ "$1" = "--resume" ]; then
    SKIP_APT=true
fi

# ── Colors ────────────────────────────────────────────────────────
GREEN=$(tput setaf 2 2>/dev/null || echo '\033[0;32m')
RED=$(tput setaf 1 2>/dev/null || echo '\033[0;31m')
YELLOW=$(tput setaf 3 2>/dev/null || echo '\033[0;33m')
CYAN=$(tput setaf 6 2>/dev/null || echo '\033[0;36m')
NC=$(tput sgr0 2>/dev/null || echo '\033[0m')

print_ok()   { echo -e "  [${GREEN}OK${NC}] $1"; }
print_error(){ echo -e "  [${RED}ERROR${NC}] $1"; }
print_warn() { echo -e "  [${YELLOW}WARN${NC}] $1"; }
print_info() { echo -e "  [${CYAN}INFO${NC}] $1"; }

# ── Banner ────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}  ROPE — AI Educational Robot Setup (Linux/Pi)${NC}"
echo -e "${CYAN}============================================${NC}"
echo ""
if [ "$SKIP_APT" = true ]; then
    print_info "Resume mode — skipping apt-get system packages"
fi
echo ""

# ── Detect Raspberry Pi ──────────────────────────────────────────
IS_PI=false
PI_MODEL=""
if [ -f /proc/device-tree/model ]; then
    IS_PI=true
    PI_MODEL=$(cat /proc/device-tree/model | tr -d '\0')
    print_info "Detected Raspberry Pi: $PI_MODEL"
fi

# ── 1. Python version check ──────────────────────────────────────
print_info "Checking Python version..."
if ! command -v python3 &>/dev/null; then
    print_error "python3 not found. Please install Python 3.10+."
    exit 1
fi

PY_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
PY_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
    print_error "Python >= 3.10 required. Found ${PY_MAJOR}.${PY_MINOR}"
    exit 1
fi
print_ok "Python ${PY_MAJOR}.${PY_MINOR}"

# ── 2. System packages ───────────────────────────────────────────
if [ "$SKIP_APT" = false ]; then
    print_info "Updating apt package list..."
    sudo apt-get update -qq

    print_info "Installing system dependencies..."
    sudo apt-get install -y \
        python3-pip python3-venv python3-dev \
        portaudio19-dev libsdl2-dev libsdl2-mixer-dev \
        libopenblas-dev libopenblas0 libopencv-dev \
        ffmpeg git wget curl libcamera-apps

    print_ok "System packages installed"

    if [ "$IS_PI" = true ]; then
        print_info "Installing picamera2 system packages (pre-venv)..."
        sudo apt-get install -y python3-libcamera python3-picamera2 python3-kms++
        print_ok "picamera2 system packages installed"
    fi
else
    print_info "Skipping apt-get system packages (--resume mode)"
fi

# ── 3. Virtual environment ───────────────────────────────────────
print_info "Setting up virtual environment..."
if [ ! -d "venv" ]; then
    if [ "$IS_PI" = true ]; then
        python3 -m venv venv --system-site-packages
        print_ok "Created venv with --system-site-packages (required for libcamera on Pi)"
    else
        python3 -m venv venv
        print_ok "Virtual environment created at ./venv"
    fi
else
    print_ok "Virtual environment already exists"
    if [ "$IS_PI" = true ]; then
        if [ -f "venv/pyvenv.cfg" ]; then
            if grep -q "include-system-site-packages = true" venv/pyvenv.cfg; then
                print_ok "Existing venv has --system-site-packages enabled"
            else
                print_warn "Existing venv was NOT created with --system-site-packages."
                print_warn "This will cause libcamera import errors."
                echo -e "  ${YELLOW}Fix with: rm -rf venv && ./setup.sh${NC}"
            fi
        fi
    fi
fi

source venv/bin/activate

print_info "Upgrading pip..."
pip install --upgrade pip -q
print_ok "pip upgraded"

# ── 4. Resilient package installation ──────────────────────────────

# Detect whether pip's --break-system-packages flag is available
if pip install --help 2>/dev/null | grep -q "break-system-packages"; then
    PIP_EXTRA="--break-system-packages"
else
    PIP_EXTRA=""
fi

DOWNLOAD_DIR="./downloads"
mkdir -p "$DOWNLOAD_DIR"

INSTALLED_PKGS=()
FAILED_PKGS=()

install_package_resilient() {
    local pkg="$1"
    local max_attempts=3
    local attempt

    for attempt in $(seq 1 $max_attempts); do
        echo -e "  ${CYAN}Installing ${pkg}... (attempt ${attempt}/${max_attempts})${NC}"

        if pip install "$pkg" --retries 5 --timeout 120 $PIP_EXTRA 2>/dev/null; then
            return 0
        fi

        echo -e "  ${YELLOW}pip install failed for ${pkg}, trying download + local install...${NC}"

        if pip download "$pkg" -d "$DOWNLOAD_DIR" --retries 5 --timeout 120 $PIP_EXTRA 2>/dev/null; then
            local wheel
            for wheel in "$DOWNLOAD_DIR"/*.whl; do
                [ -f "$wheel" ] || continue
                if pip install "$wheel" $PIP_EXTRA 2>/dev/null; then
                    rm -f "$wheel"
                    return 0
                fi
                rm -f "$wheel"
            done
            # Check for tar.bz2 / tar.gz as fallback
            for tarball in "$DOWNLOAD_DIR"/*.tar.*; do
                [ -f "$tarball" ] || continue
                if pip install "$tarball" $PIP_EXTRA 2>/dev/null; then
                    rm -f "$tarball"
                    return 0
                fi
                rm -f "$tarball"
            done
        fi

        if [ $attempt -lt $max_attempts ]; then
            echo -e "  ${YELLOW}Waiting 5 seconds before retry...${NC}"
            sleep 5
        fi
    done

    return 1
}

print_info "Installing Python dependencies (resilient mode)..."
echo ""

while IFS= read -r line || [ -n "$line" ]; do
    line="$(echo "$line" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    if [ -z "$line" ] || [ "${line:0:1}" = "#" ]; then
        continue
    fi
    # Strip inline comments
    pkg=$(echo "$line" | sed 's/[[:space:]]*#.*//')
    pkg="$(echo "$pkg" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    if [ -z "$pkg" ]; then
        continue
    fi
    if install_package_resilient "$pkg"; then
        INSTALLED_PKGS+=("$pkg")
        echo -e "  [${GREEN}OK${NC}] $pkg"
    else
        FAILED_PKGS+=("$pkg")
        echo -e "  [${RED}FAIL${NC}] $pkg"
    fi
done < requirements.txt

if [ ${#FAILED_PKGS[@]} -eq 0 ]; then
    print_ok "All packages installed successfully (${#INSTALLED_PKGS[@]}/${#INSTALLED_PKGS[@]})"
else
    print_warn "Installed ${#INSTALLED_PKGS[@]}/${#INSTALLED_PKGS[@] + #FAILED_PKGS[@]} packages. Failed:"
    for f in "${FAILED_PKGS[@]}"; do
        echo -e "    ${RED}- $f${NC}"
    done
fi

rm -rf "$DOWNLOAD_DIR"

# ── 5. Create directories ────────────────────────────────────────
print_info "Creating project directories..."
for dir in data models piper_models docs; do
    if [ ! -d "$dir" ]; then
        mkdir -p "$dir"
        touch "$dir/.gitkeep"
        print_ok "Created $dir/"
    else
        if [ ! -f "$dir/.gitkeep" ]; then
            touch "$dir/.gitkeep"
        fi
        print_ok "$dir/ already exists"
    fi
done

# ── 6. .env file ─────────────────────────────────────────────────
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        print_ok "Created .env from .env.example"
        print_warn "Edit .env and add your ROBOT_OPENROUTER_API_KEY"
    else
        print_warn ".env.example not found — create .env manually"
    fi
else
    print_warn ".env already exists, skipping"
fi

# ── 7. Download OpenCV face detection models ─────────────────────
print_info "Downloading OpenCV face detection models..."

PROTO_URL="https://raw.githubusercontent.com/opencv/opencv/master/samples/dnn/face_detector/deploy.prototxt"
WEIGHTS_URL="https://github.com/opencv/opencv_3rdparty/raw/dnn_samples_face_detector_20170830/res10_300x300_ssd_iter_140000.caffemodel"

if [ ! -f "models/deploy.prototxt" ]; then
    if wget -q --show-progress -O models/deploy.prototxt "$PROTO_URL"; then
        print_ok "Downloaded deploy.prototxt"
    else
        print_warn "Failed to download deploy.prototxt — download manually from: $PROTO_URL"
    fi
else
    print_ok "deploy.prototxt already present"
fi

if [ ! -f "models/res10_300x300_ssd_iter_140000.caffemodel" ]; then
    if wget -q --show-progress -O models/res10_300x300_ssd_iter_140000.caffemodel "$WEIGHTS_URL"; then
        print_ok "Downloaded res10_300x300_ssd_iter_140000.caffemodel"
    else
        print_warn "Failed to download caffemodel — download manually from: $WEIGHTS_URL"
    fi
else
    print_ok "res10_300x300_ssd_iter_140000.caffemodel already present"
fi

# ── 8. Download YOLO models (resumable) ──────────────────────────

download_model_resilient() {
    local url="$1"
    local dest="$2"
    local min_size="$3"
    local name="$4"

    if [ -f "$dest" ]; then
        local actual_size
        actual_size=$(stat -c%s "$dest" 2>/dev/null || echo 0)
        if [ "$actual_size" -ge "$min_size" ] 2>/dev/null; then
            print_ok "$name already present ($actual_size bytes)"
            return 0
        else
            print_warn "$name exists but is only $actual_size bytes (expected >= $min_size) — re-downloading"
            rm -f "$dest"
        fi
    fi

    print_info "Downloading $name..."
    if command -v wget &>/dev/null; then
        wget -c --tries=5 --timeout=60 -O "$dest" "$url" && actual_size=$(stat -c%s "$dest" 2>/dev/null || echo 0) && [ "$actual_size" -ge "$min_size" ] 2>/dev/null
    elif command -v curl &>/dev/null; then
        curl -L -C - --retry 5 --retry-delay 5 -o "$dest" "$url" && actual_size=$(stat -c%s "$dest" 2>/dev/null || echo 0) && [ "$actual_size" -ge "$min_size" ] 2>/dev/null
    else
        print_error "Neither wget nor curl available — cannot download $name"
        return 1
    fi

    local result=$?
    if [ $result -eq 0 ]; then
        actual_size=$(stat -c%s "$dest" 2>/dev/null || echo 0)
        print_ok "Downloaded $name ($actual_size bytes)"
        return 0
    else
        actual_size=$(stat -c%s "$dest" 2>/dev/null || echo 0)
        print_error "Failed to download $name (got $actual_size bytes)"
        return 1
    fi
}

print_info "Downloading YOLO models (resumable)..."
echo ""

download_model_resilient \
    "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8s.pt" \
    "models/yolov8s.pt" \
    20000000 \
    "yolov8s.pt"

download_model_resilient \
    "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8s-seg.pt" \
    "models/yolov8s-seg.pt" \
    20000000 \
    "yolov8s-seg.pt"

echo ""

# ── 9. Raspberry Pi specific ─────────────────────────────────────
if [ "$IS_PI" = true ]; then
    echo ""
    echo -e "${CYAN}── Raspberry Pi Optimizations ─────────────────${NC}"
    echo ""

    # Enable camera via raspi-config
    if command -v raspi-config &>/dev/null; then
        print_info "Enabling camera interface..."
        if sudo raspi-config nonint do_camera 0 2>/dev/null; then
            print_ok "Camera enabled via raspi-config"
        else
            print_warn "Could not enable camera via raspi-config (non-fatal)"
        fi
    fi

    # GPU memory
    CONFIG_FILE=""
    if [ -f /boot/firmware/config.txt ]; then
        CONFIG_FILE="/boot/firmware/config.txt"
    elif [ -f /boot/config.txt ]; then
        CONFIG_FILE="/boot/config.txt"
    fi

    if [ -n "$CONFIG_FILE" ]; then
        if ! grep -q "gpu_mem" "$CONFIG_FILE" 2>/dev/null; then
            echo "gpu_mem=128" | sudo tee -a "$CONFIG_FILE" >/dev/null
            print_ok "Set gpu_mem=128 in $CONFIG_FILE"
        else
            print_ok "gpu_mem already configured in $CONFIG_FILE"
        fi
    else
        print_warn "Could not find config.txt for gpu_mem setting"
    fi

    print_ok "Raspberry Pi optimizations applied"
fi

# ── 10. Run health check ─────────────────────────────────────────
echo ""
print_info "Running health check..."
echo ""
if python health_check.py; then
    print_ok "Health check completed"
else
    print_warn "Health check completed with warnings — review output above"
fi

# ── 11. FINAL PRE-FLIGHT CHECK ───────────────────────────────────
echo ""
echo -e "${CYAN}==================================================${NC}"
echo -e "${CYAN}  FINAL PRE-FLIGHT CHECK${NC}"
echo -e "${CYAN}==================================================${NC}"
echo ""

PF_NAMES=()
PF_RESULTS=()
PF_DETAILS=()

PF_PASSES=0
PF_FAILS=0

pf_record() {
    local name="$1" result="$2" detail="$3"
    PF_NAMES+=("$name")
    PF_RESULTS+=("$result")
    PF_DETAILS+=("$detail")
    if [ "$result" = "PASS" ]; then
        PF_PASSES=$((PF_PASSES + 1))
        echo -e "  [${GREEN}PASS${NC}] $name — $detail"
    else
        PF_FAILS=$((PF_FAILS + 1))
        echo -e "  [${RED}FAIL${NC}] $name — $detail"
    fi
}

# 1. Audio resampling
echo -e "  ${CYAN}[1/6] Audio resampling check...${NC}"
PF_AUDIO=$(venv/bin/python -c "
import scipy
from voice.pipeline import _resample_chunk
import numpy as np
r = _resample_chunk(np.zeros(1024, dtype=np.float32), 44100, 16000)
print('OK' if len(r) > 0 else 'FAIL')
" 2>&1)
if [ $? -eq 0 ] && [ "$PF_AUDIO" = "OK" ]; then
    pf_record "Audio resampling" "PASS" ""
else
    pf_record "Audio resampling" "FAIL" "scipy or _resample_chunk error — pip install scipy; verify voice/pipeline.py"
fi

# 2. Camera backend
echo -e "  ${CYAN}[2/6] Camera backend check...${NC}"
PF_CAMERA=$(venv/bin/python -c "
import sys, os
os.environ['SDL_VIDEODRIVER'] = 'dummy'
sys.path.insert(0, '.')
from vision.camera import CameraManager
c = CameraManager()
print(c.get_backend_name())
" 2>&1)
if [ $? -eq 0 ]; then
    pf_record "Camera backend" "PASS" "$PF_CAMERA"
else
    pf_record "Camera backend" "FAIL" "$PF_CAMERA"
fi

# 3. YOLO models
echo -e "  ${CYAN}[3/6] YOLO models check...${NC}"
PF_YOLO_OBJ_SIZE=0
PF_YOLO_SEG_SIZE=0
[ -f "models/yolov8s.pt" ] && PF_YOLO_OBJ_SIZE=$(stat -c%s "models/yolov8s.pt" 2>/dev/null || echo 0)
[ -f "models/yolov8s-seg.pt" ] && PF_YOLO_SEG_SIZE=$(stat -c%s "models/yolov8s-seg.pt" 2>/dev/null || echo 0)
if [ "$PF_YOLO_OBJ_SIZE" -ge 20000000 ] 2>/dev/null; then
    pf_record "YOLO object model (yolov8s.pt)" "PASS" "${PF_YOLO_OBJ_SIZE} bytes"
else
    pf_record "YOLO object model (yolov8s.pt)" "FAIL" "missing or <20MB — re-run setup.sh or download from ultralytics assets"
fi
if [ "$PF_YOLO_SEG_SIZE" -ge 20000000 ] 2>/dev/null; then
    pf_record "YOLO segmentation model (yolov8s-seg.pt)" "PASS" "${PF_YOLO_SEG_SIZE} bytes"
else
    pf_record "YOLO segmentation model (yolov8s-seg.pt)" "FAIL" "missing or <20MB — re-run setup.sh or download from ultralytics assets"
fi

# 4. venv system-site-packages (Pi only)
echo -e "  ${CYAN}[4/6] venv system-site-packages check...${NC}"
if [ "$IS_PI" = true ]; then
    if [ -f "venv/pyvenv.cfg" ] && grep -q "include-system-site-packages = true" venv/pyvenv.cfg; then
        pf_record "venv system-site-packages (Pi)" "PASS" ""
    else
        pf_record "venv system-site-packages (Pi)" "FAIL" "recreate with: rm -rf venv && ./setup.sh"
    fi
else
    pf_record "venv system-site-packages (Pi)" "PASS" "not applicable (non-Pi)"
fi

# 5. Critical package imports
echo -e "  ${CYAN}[5/6] Critical package imports check...${NC}"
PF_IMPORT=$(venv/bin/python -c "
import torch
import cv2
import pygame
import sounddevice
import scipy
import edge_tts
import rapidfuzz
import ultralytics
print('OK')
" 2>&1)
if [ $? -eq 0 ]; then
    pf_record "Critical package imports" "PASS" ""
else
    PF_MISSING=$(echo "$PF_IMPORT" | grep "ModuleNotFoundError" | sed "s/.*No module named '\([^']*\)'.*/\1/")
    pf_record "Critical package imports" "FAIL" "missing: $PF_MISSING — pip install $PF_MISSING"
fi

# 6. Microphone sample rate
echo -e "  ${CYAN}[6/6] Microphone sample rate check...${NC}"
PF_MIC=$(venv/bin/python -c "
import sounddevice as sd
d = sd.query_devices(kind='input')
print(d['default_samplerate'])
" 2>&1)
if [ $? -eq 0 ]; then
    pf_record "Microphone sample rate" "PASS" "${PF_MIC} Hz (auto-resampled to 16000 Hz)"
else
    pf_record "Microphone sample rate" "PASS" "not detected (no mic — informational)"
fi

# ── Pre-flight summary table ─────────────────────────────────────
echo ""
echo -e "${CYAN}==================================================${NC}"
echo -e "${CYAN}  FINAL PRE-FLIGHT CHECK SUMMARY${NC}"
echo -e "${CYAN}==================================================${NC}"
for i in "${!PF_NAMES[@]}"; do
    n="${PF_NAMES[$i]}"
    r="${PF_RESULTS[$i]}"
    d="${PF_DETAILS[$i]}"
    if [ "$r" = "PASS" ]; then
        echo -e "  [${GREEN}PASS${NC}] $n"
        [ -n "$d" ] && echo -e "         $d"
    else
        echo -e "  [${RED}FAIL${NC}] $n"
        [ -n "$d" ] && echo -e "         $d"
    fi
done
echo -e "${CYAN}==================================================${NC}"
echo ""

if [ "$PF_FAILS" -eq 0 ]; then
    echo -e "  ${GREEN}READY — run: python main.py${NC}"
else
    echo -e "  ${RED}NOT READY — fix the FAILED items above before running main.py${NC}"
    echo ""
    echo -e "  ${YELLOW}Failed checks and fixes:${NC}"
    for i in "${!PF_NAMES[@]}"; do
        if [ "${PF_RESULTS[$i]}" = "FAIL" ]; then
            echo -e "    - ${PF_NAMES[$i]}: ${PF_DETAILS[$i]}"
        fi
    done
fi

# ── 12. Setup complete ────────────────────────────────────────────
echo ""
total_requested=$(( ${#INSTALLED_PKGS[@]} + ${#FAILED_PKGS[@]} ))
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  SETUP COMPLETE${NC}"
echo -e "${GREEN}============================================${NC}"
echo "  Packages installed: ${#INSTALLED_PKGS[@]}/${total_requested}"
if [ ${#FAILED_PKGS[@]} -gt 0 ]; then
    echo "  Failed packages:"
    for f in "${FAILED_PKGS[@]}"; do
        echo -e "    ${RED}- $f${NC}"
    done
fi
echo ""
echo -e "  ${CYAN}Next steps:${NC}"
echo -e "    1. Add your OpenRouter API key to .env"
echo -e "    2. Run: python main.py"
echo -e "${GREEN}============================================${NC}"
echo ""
