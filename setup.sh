#!/usr/bin/env bash
set -euo pipefail

# ── Colors ────────────────────────────────────────────────────────
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
NC='\033[0m'

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

ok()   { echo -e "  [${GREEN}OK${NC}] $1"; }
err()  { echo -e "  [${RED}ERROR${NC}] $1"; }
warn() { echo -e "  [${YELLOW}WARN${NC}] $1"; }
info() { echo -e "  [INFO] $1"; }

echo ""
echo "========================================"
echo "  Rope — Raspberry Pi Setup"
echo "========================================"
echo ""

# ── 1. Python version check ──────────────────────────────────────
info "Checking Python version..."
if ! command -v python3 &>/dev/null; then
    err "python3 not found. Please install Python 3.10+."
    exit 1
fi

PY_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
PY_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
    err "Python >= 3.10 required. Found ${PY_MAJOR}.${PY_MINOR}"
    exit 1
fi
ok "Python ${PY_MAJOR}.${PY_MINOR}"

# ── 2. System dependencies ───────────────────────────────────────
info "Updating apt and installing system dependencies..."
sudo apt-get update -y || { err "apt-get update failed"; exit 1; }

DEPS=(
    python3-pip
    python3-venv
    portaudio19-dev
    libsdl2-dev
    libsdl2-mixer-dev
    libatlas-base-dev
    libopencv-dev
    libhdf5-dev
    ffmpeg
    git
)

for pkg in "${DEPS[@]}"; do
    if sudo apt-get install -y "$pkg" 2>/dev/null; then
        ok "Installed $pkg"
    else
        warn "Failed to install $pkg (may already be installed or unavailable)"
    fi
done

# ── 3. Virtual environment ───────────────────────────────────────
info "Setting up virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    ok "Virtual environment created"
else
    ok "Virtual environment already exists"
fi

source venv/bin/activate

info "Upgrading pip..."
pip install --upgrade pip -q
ok "pip upgraded"

info "Installing Python dependencies..."
if pip install -r requirements.txt; then
    ok "requirements.txt installed"
else
    err "Failed to install requirements"
    exit 1
fi

# ── 4. Create directories ────────────────────────────────────────
info "Creating project directories..."
for dir in data models piper_models docs; do
    if [ ! -d "$dir" ]; then
        mkdir -p "$dir"
        touch "$dir/.gitkeep"
        ok "Created $dir/"
    else
        ok "$dir/ already exists"
    fi
done

# ── 5. .env file ─────────────────────────────────────────────────
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        ok "Created .env from .env.example"
        warn "Edit .env and add your ROBOT_OPENROUTER_API_KEY"
    else
        warn ".env.example not found — create .env manually"
    fi
else
    ok ".env already exists (not overwritten)"
fi

# ── 6. Raspberry Pi specific ─────────────────────────────────────
IS_PI=false
if [ -f /proc/device-tree/model ]; then
    IS_PI=true
    PI_MODEL=$(cat /proc/device-tree/model)
    info "Detected Raspberry Pi: $PI_MODEL"
fi

if [ "$IS_PI" = true ]; then
    # Enable camera
    if command -v raspi-config &>/dev/null; then
        info "Enabling camera interface..."
        sudo raspi-config nonint do_camera 0 2>/dev/null && ok "Camera enabled" || warn "Could not enable camera via raspi-config"
    fi

    # Set GPU memory
    if [ -f /boot/config.txt ] || [ -f /boot/firmware/config.txt ]; then
        CONFIG_FILE="/boot/config.txt"
        [ -f /boot/firmware/config.txt ] && CONFIG_FILE="/boot/firmware/config.txt"
        if ! grep -q "gpu_mem" "$CONFIG_FILE" 2>/dev/null; then
            echo "gpu_mem=128" | sudo tee -a "$CONFIG_FILE" >/dev/null
            ok "Set gpu_mem=128 in $CONFIG_FILE"
        else
            ok "gpu_mem already configured"
        fi
    fi

    warn "Install picamera2 separately: sudo apt install python3-picamera2"
fi

# ── 7. Download face detection models ────────────────────────────
info "Downloading OpenCV face detection models..."

PROTO_URL="https://raw.githubusercontent.com/opencv/opencv/master/samples/dnn/face_detector/deploy.prototxt"
WEIGHTS_URL="https://github.com/opencv/opencv_3rdparty/raw/dnn_samples_face_detector_20170830/res10_300x300_ssd_iter_140000.caffemodel"

if [ ! -f "models/deploy.prototxt" ]; then
    if wget --show-progress -O models/deploy.prototxt "$PROTO_URL"; then
        ok "Downloaded deploy.prototxt"
    else
        warn "Failed to download deploy.prototxt — download manually from: $PROTO_URL"
    fi
else
    ok "deploy.prototxt already present"
fi

if [ ! -f "models/res10_300x300_ssd_iter_140000.caffemodel" ]; then
    if wget --show-progress -O models/res10_300x300_ssd_iter_140000.caffemodel "$WEIGHTS_URL"; then
        ok "Downloaded res10_300x300_ssd_iter_140000.caffemodel"
    else
        warn "Failed to download caffemodel — download manually from: $WEIGHTS_URL"
    fi
else
    ok "res10_300x300_ssd_iter_140000.caffemodel already present"
fi

# ── 8. Summary ───────────────────────────────────────────────────
echo ""
echo "========================================"
echo "  Setup Complete"
echo "========================================"
echo ""
echo "  Installed:"
echo "    - System dependencies (portaudio, sdl2, atlas, opencv, ffmpeg)"
echo "    - Python virtual environment (venv/)"
echo "    - Python packages (requirements.txt)"
echo "    - Project directories (data/, models/, piper_models/, docs/)"
echo ""
echo "  Next steps:"
echo "    1. Edit .env and add your ROBOT_OPENROUTER_API_KEY"
echo "    2. Run: python health_check.py  (verify everything works)"
echo "    3. Run: python main.py          (start the robot)"
echo ""
echo "========================================"
echo ""
