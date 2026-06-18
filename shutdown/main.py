import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from dotenv import load_dotenv
load_dotenv()

SHUTDOWN_TOKEN = os.environ.get("SHUTDOWN_TOKEN", "ropo-shutdown-default-token")

shutdown_requested = False


class TokenRequest(BaseModel):
    token: str


class ShutdownStatus(BaseModel):
    shutdown: bool


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="Ropo Shutdown API", lifespan=lifespan)


HTML_PAGE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Ropo Control Panel</title>
<style>
  *{margin:0;padding:0;box-sizing:border-box}
  body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#111;color:#eee;display:flex;justify-content:center;align-items:center;min-height:100vh}
  .card{background:#1e1e1e;border-radius:16px;padding:40px;width:400px;max-width:90vw;box-shadow:0 8px 32px rgba(0,0,0,.5);text-align:center}
  h1{font-size:1.6rem;margin-bottom:24px;font-weight:600}
  .status-row{display:flex;align-items:center;justify-content:center;gap:12px;margin-bottom:28px}
  .dot{width:16px;height:16px;border-radius:50%;transition:background .3s}
  .dot.running{background:#22c55e;box-shadow:0 0 12px #22c55e88}
  .dot.stopped{background:#ef4444;box-shadow:0 0 12px #ef444488}
  .status-label{font-size:1.1rem}
  .token-section{margin-bottom:24px}
  .token-section input{width:100%;padding:10px 14px;border-radius:8px;border:1px solid #333;background:#2a2a2a;color:#eee;font-size:.95rem;outline:0;transition:border .2s}
  .token-section input:focus{border-color:#3b82f6}
  .token-section input::placeholder{color:#666}
  .btn{width:100%;padding:12px;border:0;border-radius:10px;font-size:1rem;font-weight:600;cursor:pointer;transition:opacity .2s,transform .1s;margin-bottom:12px}
  .btn:active{transform:scale(.97)}
  .btn-danger{background:#dc2626;color:#fff}
  .btn-danger:hover{opacity:.9}
  .btn-secondary{background:#333;color:#eee}
  .btn-secondary:hover{opacity:.85}
  .msg{font-size:.85rem;margin-top:12px;min-height:1.3em;transition:color .3s}
  .msg.ok{color:#22c55e}
  .msg.err{color:#ef4444}
  .footer{margin-top:20px;font-size:.75rem;color:#555}
</style>
</head>
<body>
<div class="card">
  <h1>Ropo Control Panel</h1>

  <div class="status-row">
    <span class="dot" id="statusDot"></span>
    <span class="status-label" id="statusLabel">—</span>
  </div>

  <div class="token-section">
    <input type="password" id="tokenInput" placeholder="Enter shutdown token" autocomplete="off">
  </div>

  <button class="btn btn-danger" id="btnShutdown" onclick="sendAction('/shutdown')">Shutdown Robot</button>
  <button class="btn btn-secondary" id="btnReset" onclick="sendAction('/shutdown-reset')">Reset Shutdown Flag</button>

  <div class="msg" id="msg"></div>
  <div class="footer">Ropo Remote Shutdown</div>
</div>

<script>
  let token = '';
  const dot = document.getElementById('statusDot');
  const label = document.getElementById('statusLabel');
  const msg = document.getElementById('msg');

  document.getElementById('tokenInput').addEventListener('input', function() {
    token = this.value;
  });

  function setStatus(shutdown) {
    if (shutdown) {
      dot.className = 'dot stopped';
      label.textContent = 'Shutdown Requested';
    } else {
      dot.className = 'dot running';
      label.textContent = 'Running';
    }
  }

  async function poll() {
    try {
      const r = await fetch('/shutdown-status');
      const data = await r.json();
      setStatus(data.shutdown);
    } catch {}
  }
  setStatus(false);
  poll();
  setInterval(poll, 5000);

  async function sendAction(path) {
    msg.textContent = '';
    msg.className = 'msg';
    if (!token) { msg.textContent = 'Enter token first'; msg.className = 'msg err'; return; }
    try {
      const r = await fetch(path, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({token}) });
      if (r.ok) {
        msg.textContent = path === '/shutdown' ? 'Shutdown requested' : 'Shutdown flag reset';
        msg.className = 'msg ok';
        await poll();
      } else {
        const e = await r.json();
        msg.textContent = e.detail || 'Unauthorized';
        msg.className = 'msg err';
      }
    } catch {
      msg.textContent = 'Network error';
      msg.className = 'msg err';
    }
  }
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return HTML_PAGE


@app.get("/shutdown-status", response_model=ShutdownStatus)
def get_shutdown_status():
    return ShutdownStatus(shutdown=shutdown_requested)


@app.post("/shutdown")
def request_shutdown(body: TokenRequest):
    if body.token != SHUTDOWN_TOKEN:
        raise HTTPException(status_code=403, detail="Unauthorized")
    global shutdown_requested
    shutdown_requested = True
    return {"ok": True, "message": "Shutdown requested"}


@app.post("/shutdown-reset")
def reset_shutdown(body: TokenRequest):
    if body.token != SHUTDOWN_TOKEN:
        raise HTTPException(status_code=403, detail="Unauthorized")
    global shutdown_requested
    shutdown_requested = False
    return {"ok": True, "message": "Shutdown reset"}
