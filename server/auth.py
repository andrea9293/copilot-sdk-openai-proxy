"""Authentication endpoints: GitHub OAuth device flow + status check + HTML UI."""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from .state import extract_token, get_client

logger = logging.getLogger("copilot_proxy")

# GitHub CLI OAuth App — accepted by the Copilot CLI (see `copilot login --help`).
_GH_CLIENT_ID = "Iv1.b507a08c87ecfe98"
_GH_DEVICE_CODE_URL = "https://github.com/login/device/code"
_GH_TOKEN_URL = "https://github.com/login/oauth/access_token"
_GH_SCOPES = "read:user,copilot"

router = APIRouter(prefix="/auth", tags=["auth"])


# ── HTML UI ──────────────────────────────────────────────────────────────────

_AUTH_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Copilot Proxy — Login</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: #0d1117; color: #e6edf3;
      min-height: 100vh; display: flex; align-items: center; justify-content: center;
      padding: 24px;
    }
    .container { width: 100%; max-width: 580px; }
    .header { margin-bottom: 32px; }
    .header h1 { font-size: 22px; font-weight: 600; display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
    .header p { color: #7d8590; font-size: 14px; }
    .card {
      background: #161b22; border: 1px solid #30363d; border-radius: 12px;
      padding: 24px; margin-bottom: 16px;
    }
    .card h2 { font-size: 15px; font-weight: 600; margin-bottom: 6px; }
    .card > p { color: #7d8590; font-size: 13px; margin-bottom: 16px; }
    .btn {
      display: inline-flex; align-items: center; gap: 6px;
      padding: 8px 16px; border-radius: 6px; border: none;
      font-size: 14px; font-weight: 500; cursor: pointer;
      transition: opacity 0.15s;
    }
    .btn:hover:not(:disabled) { opacity: 0.85; }
    .btn:disabled { opacity: 0.5; cursor: not-allowed; }
    .btn-green  { background: #238636; color: #fff; }
    .btn-dark   { background: #21262d; color: #e6edf3; border: 1px solid #30363d; }
    .code-box {
      background: #0d1117; border: 2px solid #1f6feb; border-radius: 8px;
      padding: 20px; text-align: center; margin: 16px 0;
    }
    .code-hint { font-size: 12px; color: #7d8590; margin-bottom: 6px; }
    .verify-link { color: #58a6ff; text-decoration: none; font-size: 13px; }
    .verify-link:hover { text-decoration: underline; }
    .user-code {
      font-family: 'SF Mono', 'Cascadia Code', 'Courier New', monospace;
      font-size: 34px; font-weight: 700; letter-spacing: 6px; color: #388bfd;
      margin: 8px 0 12px;
    }
    .status-row { display: flex; align-items: center; gap: 8px; font-size: 13px; color: #7d8590; margin-top: 12px; }
    .spinner {
      width: 14px; height: 14px; border: 2px solid #30363d;
      border-top-color: #388bfd; border-radius: 50%;
      animation: spin 0.8s linear infinite; flex-shrink: 0;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    .actions-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 12px; }
    input[type="password"] {
      width: 100%; padding: 8px 12px;
      background: #0d1117; border: 1px solid #30363d; border-radius: 6px;
      color: #e6edf3; font-size: 14px; font-family: monospace; outline: none;
      transition: border-color 0.15s; margin-bottom: 12px;
    }
    input[type="password"]:focus { border-color: #388bfd; }
    .success-card {
      background: #0d4429; border: 1px solid #238636; border-radius: 12px;
      padding: 24px; margin-bottom: 16px;
    }
    .success-card h2 { font-size: 15px; font-weight: 600; color: #3fb950; margin-bottom: 6px; }
    .success-card .login { font-size: 13px; color: #7d8590; margin-bottom: 12px; }
    .token-display {
      background: #0d1117; border: 1px solid #30363d; border-radius: 6px;
      padding: 10px 12px; font-family: monospace; font-size: 12px;
      word-break: break-all; color: #a5d6ff; margin-bottom: 12px;
    }
    .info-note {
      background: #0c2d6b; border: 1px solid #1f6feb; border-radius: 6px;
      padding: 12px; font-size: 13px; color: #79c0ff;
      margin-top: 16px; line-height: 1.6;
    }
    .info-note code { font-family: monospace; font-size: 12px; background: rgba(0,0,0,0.3); padding: 1px 4px; border-radius: 3px; }
    .err { color: #f85149; font-size: 13px; margin-top: 8px; }
    .hidden { display: none !important; }
  </style>
</head>
<body>
<div class="container">

  <div class="header">
    <h1>
      <svg width="22" height="22" viewBox="0 0 16 16" fill="currentColor">
        <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/>
      </svg>
      Copilot Proxy — Login
    </h1>
    <p>Authenticate with GitHub to obtain a token for the Copilot OpenAI proxy.</p>
  </div>

  <!-- ── Success banner ──────────────────────────────────────────────── -->
  <div class="success-card hidden" id="result-card">
    <h2>✓ Authenticated</h2>
    <p class="login" id="result-login"></p>
    <div class="token-display" id="result-token"></div>
    <div class="actions-row">
      <button class="btn btn-dark" id="btn-copy-token">Copy Token</button>
      <button class="btn btn-dark" onclick="resetAll()">Use a different account</button>
    </div>
    <div class="info-note">
      Use this token as the <strong>api_key</strong> in your OpenAI client:<br />
      <code>client = OpenAI(base_url="http://&lt;host&gt;:8081/v1", api_key="&lt;token&gt;")</code>
    </div>
  </div>

  <!-- ── Device flow card ────────────────────────────────────────────── -->
  <div class="card" id="device-card">
    <h2>Login with GitHub (OAuth Device Flow)</h2>
    <p>Authorize in your browser — no password needed.</p>

    <button class="btn btn-green" id="btn-start-flow">
      <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor">
        <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/>
      </svg>
      Start GitHub Login
    </button>

    <div id="flow-ui" class="hidden">
      <div class="code-box">
        <p class="code-hint">Go to this URL and enter the code below:</p>
        <a id="verify-link" href="https://github.com/login/device" target="_blank" class="verify-link">github.com/login/device</a>
        <div class="user-code" id="user-code-display">XXXX-XXXX</div>
        <button class="btn btn-dark" onclick="copyUserCode(this)">Copy Code</button>
      </div>
      <div class="status-row">
        <div class="spinner"></div>
        <span id="flow-status-text">Waiting for authorization…</span>
      </div>
      <div class="err hidden" id="flow-err"></div>
    </div>
  </div>

  <!-- ── Token input card ────────────────────────────────────────────── -->
  <div class="card">
    <h2>Use an existing token</h2>
    <p>Paste a GitHub fine-grained PAT (with "Copilot Requests" permission) or a token from <code style="font-size:12px">gh auth token</code>.</p>
    <input type="password" id="token-input" placeholder="github_pat_… or gho_…" />
    <div class="actions-row">
      <button class="btn btn-dark" id="btn-verify-token">Verify &amp; Use Token</button>
      <span id="verify-status" style="font-size:13px;color:#7d8590"></span>
    </div>
    <div class="err hidden" id="verify-err"></div>
  </div>

</div>

<script>
  "use strict";

  let deviceCode = null;
  let pollInterval = 5;
  let pollTimer = null;
  let currentToken = null;

  document.getElementById("btn-start-flow").addEventListener("click", startDeviceFlow);
  document.getElementById("btn-verify-token").addEventListener("click", verifyToken);
  document.getElementById("btn-copy-token").addEventListener("click", copyToken);

  // ── Device flow ──────────────────────────────────────────────────────────

  async function startDeviceFlow() {
    const btn = document.getElementById("btn-start-flow");
    btn.disabled = true;
    btn.textContent = "Starting…";
    hideErr("flow-err");

    try {
      const resp = await fetch("/auth/device/start", { method: "POST" });
      if (!resp.ok) throw new Error("Server error: " + resp.status);
      const data = await resp.json();

      deviceCode   = data.device_code;
      pollInterval = data.interval || 5;

      document.getElementById("user-code-display").textContent = data.user_code;
      const link = document.getElementById("verify-link");
      link.href        = data.verification_uri;
      link.textContent = data.verification_uri;

      show("flow-ui");
      window.open(data.verification_uri, "_blank");

      btn.textContent = "Cancel";
      btn.disabled    = false;
      btn.onclick     = cancelFlow;

      schedulePoll();
    } catch (e) {
      showErr("flow-err", e.message);
      btn.disabled    = false;
      btn.textContent = "Start GitHub Login";
      btn.onclick     = startDeviceFlow;
    }
  }

  function schedulePoll() {
    pollTimer = setTimeout(pollDeviceFlow, pollInterval * 1000);
  }

  async function pollDeviceFlow() {
    if (!deviceCode) return;
    try {
      const resp = await fetch("/auth/device/poll", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ device_code: deviceCode }),
      });
      const data = await resp.json();

      if (data.access_token) {
        clearPoll();
        await showSuccess(data.access_token);
        return;
      }

      const err = data.error;
      if (err === "slow_down")          { pollInterval += 5; schedulePoll(); }
      else if (err === "expired_token") { showErr("flow-err", "Code expired. Please start again."); cancelFlow(); }
      else if (err === "access_denied") { showErr("flow-err", "Access denied."); cancelFlow(); }
      else                              { schedulePoll(); }   // authorization_pending or unknown
    } catch (_) {
      schedulePoll(); // network hiccup — retry
    }
  }

  function cancelFlow() {
    clearPoll();
    deviceCode = null;
    hide("flow-ui");
    const btn = document.getElementById("btn-start-flow");
    btn.disabled    = false;
    btn.textContent = "Start GitHub Login";
    btn.onclick     = startDeviceFlow;
  }

  function clearPoll() {
    if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
  }

  // ── Manual token ─────────────────────────────────────────────────────────

  async function verifyToken() {
    const token = document.getElementById("token-input").value.trim();
    if (!token) { showErr("verify-err", "Please enter a token."); return; }

    const btn = document.getElementById("btn-verify-token");
    btn.disabled = true;
    document.getElementById("verify-status").textContent = "Verifying…";
    hideErr("verify-err");

    try {
      const resp = await fetch("/auth/status", {
        headers: { "Authorization": "Bearer " + token },
      });
      const data = await resp.json();
      if (data.authenticated) {
        await showSuccess(token, data.login);
      } else {
        showErr("verify-err", data.error || "Token is not valid for Copilot.");
      }
    } catch (e) {
      showErr("verify-err", "Failed to verify: " + e.message);
    } finally {
      btn.disabled = false;
      document.getElementById("verify-status").textContent = "";
    }
  }

  // ── Helpers ───────────────────────────────────────────────────────────────

  async function showSuccess(token, login) {
    currentToken = token;
    document.getElementById("result-token").textContent = token;
    document.getElementById("result-login").textContent =
      login ? "Logged in as @" + login : "Authenticated successfully";
    show("result-card");
    document.getElementById("result-card").scrollIntoView({ behavior: "smooth" });
    cancelFlow();
  }

  function resetAll() {
    currentToken = null;
    hide("result-card");
    document.getElementById("token-input").value = "";
    cancelFlow();
  }

  function copyUserCode(btn) {
    const code = document.getElementById("user-code-display").textContent;
    navigator.clipboard.writeText(code).catch(() => {});
    btn.textContent = "Copied!";
    setTimeout(() => (btn.textContent = "Copy Code"), 2000);
  }

  function copyToken() {
    if (!currentToken) return;
    navigator.clipboard.writeText(currentToken).catch(() => {});
    const btn = document.getElementById("btn-copy-token");
    btn.textContent = "Copied!";
    setTimeout(() => (btn.textContent = "Copy Token"), 2000);
  }

  function show(id)  { document.getElementById(id).classList.remove("hidden"); }
  function hide(id)  { document.getElementById(id).classList.add("hidden"); }
  function showErr(id, msg) { const el = document.getElementById(id); el.textContent = msg; show(id); }
  function hideErr(id)      { hide(id); }
</script>
</body>
</html>"""


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("", response_class=HTMLResponse, include_in_schema=False)
async def auth_page():
    """Serve the authentication UI."""
    return HTMLResponse(_AUTH_HTML)


@router.post("/device/start")
async def device_start():
    """Initiate the GitHub OAuth device flow and return the user code."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            _GH_DEVICE_CODE_URL,
            data={"client_id": _GH_CLIENT_ID, "scope": _GH_SCOPES},
            headers={"Accept": "application/json"},
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()

    return JSONResponse({
        "device_code":      data["device_code"],
        "user_code":        data["user_code"],
        "verification_uri": data.get("verification_uri", "https://github.com/login/device"),
        "expires_in":       data.get("expires_in", 900),
        "interval":         data.get("interval", 5),
    })


@router.post("/device/poll")
async def device_poll(request: Request):
    """Poll GitHub for device flow completion. Returns the access token when ready."""
    body = await request.json()
    code = body.get("device_code")
    if not code:
        return JSONResponse({"error": "device_code is required"}, status_code=400)

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            _GH_TOKEN_URL,
            data={
                "client_id":  _GH_CLIENT_ID,
                "device_code": code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
            headers={"Accept": "application/json"},
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()

    if "access_token" in data:
        return JSONResponse({
            "access_token": data["access_token"],
            "token_type":   data.get("token_type", "bearer"),
        })
    return JSONResponse({"pending": True, "error": data.get("error")})


@router.get("/status")
async def auth_status(request: Request):
    """Return the authentication status for the token in the Authorization header."""
    token = extract_token(request)
    if not token:
        return JSONResponse({"authenticated": False, "message": "No token provided"})

    try:
        copilot_client = await get_client(token)
        status = await copilot_client.get_auth_status()
        return JSONResponse({
            "authenticated": status.isAuthenticated,
            "login":         status.login,
            "auth_type":     status.authType,
        })
    except Exception:
        logger.exception("Error checking auth status")
        return JSONResponse(
            {"authenticated": False, "error": "Failed to verify token with Copilot SDK"},
            status_code=500,
        )
