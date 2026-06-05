#!/bin/bash
set -e

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
print_info "Updating apt package list..."
sudo apt-get update -qq

print_info "Installing system dependencies..."
sudo apt-get install -y \
    python3-pip python3-venv python3-dev \
    portaudio19-dev libsdl2-dev libsdl2-mixer-dev \
    libopenblas-dev libopenblas0 libopencv-dev \
    ffmpeg git wget curl libcamera-apps

print_ok "System packages installed"

# ── 3. Virtual environment ───────────────────────────────────────
print_info "Setting up virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    print_ok "Virtual environment created at ./venv"
else
    print_ok "Virtual environment already exists"
fi

source venv/bin/activate

print_info "Upgrading pip..."
pip install --upgrade pip -q
print_ok "pip upgraded"

print_info "Installing Python dependencies..."
if pip install -r requirements.txt; then
    print_ok "requirements.txt installed"
else
    print_error "Failed to install requirements"
    exit 1
fi

# ── 4. Create directories ────────────────────────────────────────
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

# ── 5. .env file ─────────────────────────────────────────────────
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

# ── 6. Download OpenCV face detection models ─────────────────────
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

# ── 7. Raspberry Pi specific ─────────────────────────────────────
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

    # picamera2
    print_info "Attempting to install picamera2..."
    if pip install picamera2 2>/dev/null; then
        print_ok "picamera2 installed"
    else
        print_warn "picamera2 install failed (non-fatal) — try: sudo apt install python3-picamera2"
    fi

    print_ok "Raspberry Pi optimizations applied"
fi

# ── 8. Run health check ──────────────────────────────────────────
echo ""
print_info "Running health check..."
echo ""
if python health_check.py; then
    print_ok "Health check completed"
else
    print_warn "Health check completed with warnings — review output above"
fi

# ── 9. Summary ───────────────────────────────────────────────────
echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  SETUP COMPLETE${NC}"
echo -e "${GREEN}============================================${NC}"
echo -e "  ${CYAN}Next steps:${NC}"
echo -e "    1. Add your OpenRouter API key to .env"
echo -e "    2. Run: python health_check.py"
echo -e "    3. Run: python main.py"
echo -e "${GREEN}============================================${NC}"
echo ""
