# Ropo Remote Shutdown System

Remotely shut down the Ropo robot via a mobile app → Railway API → Raspberry Pi polling client.

## Architecture

```
Mobile App
    ↓  POST /shutdown  { "token": "…" }
Railway (FastAPI)
    ↓  GET /shutdown-status  (polled every 15s)
Raspberry Pi Client
    ↓  sudo shutdown -h now
Ropo Robot
```

## Backend — Deploy to Railway

### Prerequisites

- A [Railway](https://railway.app) account
- The `railway` CLI installed

### Steps

```bash
# 1. Navigate to the shutdown backend
cd shutdown

# 2. Install deps
pip install -r requirements.txt

# 3. Set the shared secret on Railway
railway login
railway init
railway variables set SHUTDOWN_TOKEN=your-secret-token-here

# 4. Deploy
railway up
```

Railway auto-detects the `main.py` via `pyproject.toml` or you can set the start command manually:

```
uvicorn shutdown.main:app --host 0.0.0.0 --port $PORT
```

The `$PORT` variable is automatically set by Railway.

You can also deploy by connecting your GitHub repo in the Railway dashboard and setting the root directory to `shutdown/`.

## Raspberry Pi Client Setup

### 1. Copy files to the Pi

```bash
scp robot_shutdown_client.py pi@<raspberry-pi-ip>:/opt/ropo/
```

### 2. Create environment file

Create `/etc/ropo-shutdown.env`:

```
SHUTDOWN_API_URL=https://your-railway-app.up.railway.app
SHUTDOWN_TOKEN=your-secret-token-here
SHUTDOWN_POLL_INTERVAL=15
```

### 3. Install systemd service

```bash
sudo cp ropo-shutdown.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable ropo-shutdown
sudo systemctl start ropo-shutdown
```

### 4. Verify

```bash
sudo journalctl -u ropo-shutdown -f
```

## Environment Variables

| Variable                | Description                     | Default |
|-------------------------|---------------------------------|---------|
| `SHUTDOWN_API_URL`      | Railway backend URL             | —       |
| `SHUTDOWN_TOKEN`        | Shared secret token             | —       |
| `SHUTDOWN_POLL_INTERVAL`| Poll interval in seconds        | 15      |

## API Endpoints

| Method | Path              | Description                         |
|--------|-------------------|-------------------------------------|
| POST   | `/shutdown`       | Request robot shutdown              |
| GET    | `/shutdown-status`| Check if shutdown is requested      |
| POST   | `/shutdown-reset` | Reset the shutdown flag             |

All POST endpoints require `{ "token": "SECRET_TOKEN" }` in the request body.
