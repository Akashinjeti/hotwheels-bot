"""
session_upload.py
─────────────────
A tiny web server that lets you paste Blinkit cookies from your browser
DevTools into a form. It saves them as a valid Playwright session file
so the bot can use them immediately.

Run alongside the bot or separately on Railway.
"""

from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

SESSION_FILE = Path(os.getenv("SESSION_FILE", "session/blinkit_session.json"))
UPLOAD_PORT  = int(os.getenv("UPLOAD_PORT", "8080"))
SECRET_KEY   = os.getenv("UPLOAD_SECRET", "hotwheels2024")   # change this!

HTML_FORM = """<!DOCTYPE html>
<html>
<head>
<title>Blinkit Session Upload</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body {{ font-family: monospace; background: #111; color: #eee; padding: 20px; max-width: 800px; margin: 0 auto; }}
  h1 {{ color: #f90; }}
  textarea {{ width: 100%; height: 200px; background: #222; color: #0f0; border: 1px solid #444; padding: 10px; font-size: 12px; }}
  input[type=text] {{ width: 100%; padding: 8px; background: #222; color: #eee; border: 1px solid #444; margin: 5px 0; }}
  button {{ background: #f90; color: #000; border: none; padding: 12px 24px; font-size: 16px; cursor: pointer; margin-top: 10px; }}
  .step {{ background: #1a1a1a; border-left: 3px solid #f90; padding: 10px 15px; margin: 10px 0; }}
  .ok {{ color: #0f0; }}
  .err {{ color: #f00; }}
  code {{ background: #222; padding: 2px 6px; }}
</style>
</head>
<body>
<h1>🏎 Blinkit Session Uploader</h1>

{status}

<h2>Instructions</h2>

<div class="step">
<b>Step 1</b> — Open <a href="https://blinkit.com" target="_blank" style="color:#f90">blinkit.com</a> in your browser and log in with your phone number + OTP.
Set your delivery location to <b>Madhapur, 500081</b>.
</div>

<div class="step">
<b>Step 2</b> — Open DevTools:<br>
• Chrome/Edge: Press <code>F12</code> → Application tab → Cookies → blinkit.com<br>
• OR press <code>F12</code> → Console tab → paste this and press Enter:<br>
<code>copy(document.cookie)</code><br>
This copies all cookies to your clipboard.
</div>

<div class="step">
<b>Step 3</b> — Also get localStorage. In Console paste:<br>
<code>copy(JSON.stringify(Object.fromEntries(Object.entries(localStorage))))</code>
</div>

<div class="step">
<b>Step 4</b> — Fill the form below and submit.
</div>

<form method="POST" action="/upload">
  <label>Secret Key:</label>
  <input type="text" name="secret" placeholder="hotwheels2024" required>

  <label>Cookies (paste from DevTools → Application → Cookies, or use the copy() command above):</label>
  <textarea name="cookies" placeholder='Paste cookie string here e.g.: _device_id=abc123; gr_token=xyz...' required></textarea>

  <label>LocalStorage JSON (paste the JSON from the copy() command, or leave as {{}}):</label>
  <textarea name="localstorage" placeholder='{{"key": "value", ...}}'>{{}}</textarea>

  <label>Origin URL (leave as default):</label>
  <input type="text" name="origin" value="https://blinkit.com">

  <button type="submit">💾 Save Session & Activate Bot</button>
</form>

<hr>
<p style="color:#666">Session status: {session_status}</p>
</body>
</html>
"""


def parse_cookie_string(cookie_str: str) -> list[dict]:
    """Convert a raw cookie string into Playwright storage_state cookie format."""
    cookies = []
    for part in cookie_str.split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        name, _, value = part.partition("=")
        cookies.append({
            "name":     name.strip(),
            "value":    value.strip(),
            "domain":   ".blinkit.com",
            "path":     "/",
            "expires":  -1,
            "httpOnly": False,
            "secure":   True,
            "sameSite": "None",
        })
    return cookies


def build_storage_state(cookies: list[dict], local_storage: dict) -> dict:
    """Build a Playwright-compatible storage_state dict."""
    origins = []
    if local_storage:
        origins.append({
            "origin": "https://blinkit.com",
            "localStorage": [
                {"name": k, "value": str(v)}
                for k, v in local_storage.items()
            ],
        })
    return {"cookies": cookies, "origins": origins}


class Handler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass  # suppress default access logs

    def do_GET(self):
        if urlparse(self.path).path not in ("/", "/upload"):
            self._send(404, "Not found")
            return
        self._send(200, self._render_form(""))

    def do_POST(self):
        if urlparse(self.path).path != "/upload":
            self._send(404, "Not found")
            return

        length  = int(self.headers.get("Content-Length", 0))
        body    = self.rfile.read(length).decode()
        params  = parse_qs(body)

        secret      = params.get("secret",       [""])[0]
        cookie_str  = params.get("cookies",      [""])[0].strip()
        ls_str      = params.get("localstorage", ["{}"])[0].strip()
        origin      = params.get("origin",       ["https://blinkit.com"])[0]

        if secret != SECRET_KEY:
            self._send(200, self._render_form(
                '<p class="err">❌ Wrong secret key.</p>'
            ))
            return

        if not cookie_str:
            self._send(200, self._render_form(
                '<p class="err">❌ Cookie string is empty.</p>'
            ))
            return

        try:
            local_storage = json.loads(ls_str) if ls_str and ls_str != "{}" else {}
        except json.JSONDecodeError:
            local_storage = {}

        cookies       = parse_cookie_string(cookie_str)
        storage_state = build_storage_state(cookies, local_storage)

        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        SESSION_FILE.write_text(json.dumps(storage_state, indent=2))

        status = (
            f'<p class="ok">✅ Session saved! {len(cookies)} cookies stored.<br>'
            f"The bot will use this session on the next cycle.<br>"
            f"<b>You can close this page now.</b></p>"
        )
        self._send(200, self._render_form(status))

    def _render_form(self, status: str) -> str:
        session_status = (
            f"✅ Session file exists ({SESSION_FILE.stat().st_size} bytes)"
            if SESSION_FILE.exists()
            else "⚠️ No session file yet"
        )
        return HTML_FORM.format(status=status, session_status=session_status)

    def _send(self, code: int, body: str) -> None:
        encoded = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def start_upload_server() -> None:
    """Start the upload server in a background thread."""
    server = HTTPServer(("0.0.0.0", UPLOAD_PORT), Handler)
    print(f"🌐  Session upload server running on port {UPLOAD_PORT}")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()


if __name__ == "__main__":
    # Run standalone for testing
    server = HTTPServer(("0.0.0.0", UPLOAD_PORT), Handler)
    print(f"🌐  Upload server on http://localhost:{UPLOAD_PORT}")
    server.serve_forever()