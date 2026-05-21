# ROPE — AI Educational Robot Setup (Windows)
# PowerShell 5.1+ script

$ErrorActionPreference = "Stop"

# ── Colors ────────────────────────────────────────────────────────
function Write-OK   { param($m) Write-Host "  [OK] $m" -ForegroundColor Green }
function Write-Err  { param($m) Write-Host "  [ERROR] $m" -ForegroundColor Red }
function Write-Warn { param($m) Write-Host "  [WARN] $m" -ForegroundColor Yellow }
function Write-Info { param($m) Write-Host "  [INFO] $m" -ForegroundColor Cyan }

# ── Banner ────────────────────────────────────────────────────────
Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  ROPE — AI Educational Robot Setup (Windows)" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# ── 1. Python version check ──────────────────────────────────────
Write-Info "Checking Python version..."
try {
    $pyVer = & python --version 2>&1
    Write-OK "Found: $pyVer"
} catch {
    Write-Err "python not found. Install Python 3.10+ from python.org"
    exit 1
}

$pyOutput = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>&1
$pyParts = $pyOutput.Split('.')
$pyMajor = [int]$pyParts[0]
$pyMinor = [int]$pyParts[1]

if ($pyMajor -lt 3 -or ($pyMajor -eq 3 -and $pyMinor -lt 10)) {
    Write-Err "Python >= 3.10 required. Found $pyMajor.$pyMinor"
    exit 1
}
Write-OK "Python $pyMajor.$pyMinor meets requirement (>= 3.10)"

# ── 2. Check pip ─────────────────────────────────────────────────
Write-Info "Checking pip..."
try {
    $pipVer = & python -m pip --version 2>&1
    Write-OK "pip available: $pipVer"
} catch {
    Write-Err "pip not available"
    exit 1
}

# ── 3. Create venv ───────────────────────────────────────────────
if (-not (Test-Path ".\venv")) {
    Write-Info "Creating virtual environment..."
    try {
        & python -m venv .\venv
        Write-OK "Virtual environment created at .\venv"
    } catch {
        Write-Err "Failed to create virtual environment: $_"
        exit 1
    }
} else {
    Write-OK "Virtual environment already exists"
}

# ── 4. Activate venv ─────────────────────────────────────────────
Write-Info "Activating virtual environment..."
try {
    & ".\venv\Scripts\Activate.ps1"
    Write-OK "Virtual environment activated"
} catch {
    Write-Err "Failed to activate venv: $_"
    exit 1
}

# ── 5. Upgrade pip ───────────────────────────────────────────────
Write-Info "Upgrading pip..."
try {
    & python -m pip install --upgrade pip *> $null
    Write-OK "pip upgraded"
} catch {
    Write-Warn "pip upgrade failed (non-fatal): $_"
}

# ── 6. Install requirements ──────────────────────────────────────
Write-Info "Installing Python dependencies from requirements.txt..."
try {
    & python -m pip install -r requirements.txt
    Write-OK "requirements.txt installed successfully"
} catch {
    Write-Err "Failed to install requirements: $_"
    exit 1
}

# ── 7. Create directories ────────────────────────────────────────
Write-Info "Creating project directories..."
$dirs = @("data", "models", "piper_models", "docs")
foreach ($d in $dirs) {
    if (-not (Test-Path $d)) {
        New-Item -ItemType Directory -Path $d | Out-Null
        New-Item -ItemType File -Path "$d\.gitkeep" -Force | Out-Null
        Write-OK "Created $d/"
    } else {
        if (-not (Test-Path "$d\.gitkeep")) {
            New-Item -ItemType File -Path "$d\.gitkeep" -Force | Out-Null
        }
        Write-OK "$d/ already exists"
    }
}

# ── 8. .env file ─────────────────────────────────────────────────
if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        try {
            Copy-Item ".env.example" ".env"
            Write-OK "Created .env from .env.example"
            Write-Warn "Edit .env and add your ROBOT_OPENROUTER_API_KEY"
        } catch {
            Write-Err "Failed to copy .env.example: $_"
            exit 1
        }
    } else {
        Write-Warn ".env.example not found — create .env manually"
    }
} else {
    Write-Warn ".env already exists, skipping"
}

# ── 9. Download OpenCV face detection models ─────────────────────
Write-Info "Downloading OpenCV face detection models..."

$models = @(
    @{
        name = "deploy.prototxt"
        url  = "https://raw.githubusercontent.com/opencv/opencv/master/samples/dnn/face_detector/deploy.prototxt"
        path = "models\deploy.prototxt"
    },
    @{
        name = "res10_300x300_ssd_iter_140000.caffemodel"
        url  = "https://github.com/opencv/opencv_3rdparty/raw/dnn_samples_face_detector_20170830/res10_300x300_ssd_iter_140000.caffemodel"
        path = "models\res10_300x300_ssd_iter_140000.caffemodel"
    }
)

foreach ($m in $models) {
    if (-not (Test-Path $m.path)) {
        Write-Info "Downloading $($m.name)..."
        try {
            Invoke-WebRequest -Uri $m.url -OutFile $m.path -UseBasicParsing
            Write-OK "Downloaded $($m.name)"
        } catch {
            Write-Warn "Failed to download $($m.name) — download manually from: $($m.url)"
        }
    } else {
        Write-OK "$($m.name) already present"
    }
}

# ── 10. Summary ──────────────────────────────────────────────────
Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  SETUP COMPLETE" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host "  Next steps:" -ForegroundColor Cyan
Write-Host "    1. Add your OpenRouter API key to .env" -ForegroundColor White
Write-Host "    2. Run: python health_check.py" -ForegroundColor White
Write-Host "    3. Run: python main.py" -ForegroundColor White
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
