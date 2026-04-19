"""
session_upload.py  (v2)
────────────────────────
Saves Blinkit session both to file AND to a Railway environment variable
so it survives container restarts without needing a Volume.
"""

from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import base64

SESSION_FILE  = Path(os.getenv("SESSION_FILE", "session/blinkit_session.json"))
UPLOAD_PORT   = int(os.getenv("UPLOAD_PORT", "8080"))
SECRET_KEY    = os.getenv("UPLOAD_SECRET", "hotwheels2024")

# On startup, restore session from env var if file doesn't exist
def restore_session_from_env() -> bool:
    encoded = os.environ.get("BLINKIT_SESSION_B64", "")
    if encoded and not SESSION_FILE.exists():
        try:
            SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
            decoded = base64.b64decode(encoded).decode()
            SESSION_FILE.write_text(decoded)
            print(f"✅  Session restored from environment variable ({len(decoded)} bytes)")
            return True
        except Exception as e:
            print(f"⚠️  Could not restore session from env: {e}")
    return False


HTML_FORM = """<!DOCTYPE html>
<html>
<head>
<title>Blinkit Session Upload</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body {{ font-family: monospace; background: #111; color: #eee; padding: 20px; max-width: 800px; margin: 0 auto; }}
  h1 {{ color: #f90; }}
  textarea {{ width: 100%; height: 180px; background: #222; color: #0f0; border: 1px solid #444; padding: 10px; font-size: 12px; box-sizing: border-box; }}
  input[type=text], input[type=password] {{ width: 100%; padding: 8px; background: #222; color: #eee; border: 1px solid #444; margin: 5px 0; box-sizing: border-box; }}
  button {{ background: #f90; color: #000; border: none; padding: 12px 24px; font-size: 16px; cursor: pointer; margin-top: 10px; width: 100%; }}
  .step {{ background: #1a1a1a; border-left: 3px solid #f90; padding: 10px 15px; margin: 10px 0; }}
  .ok {{ color: #0f0; font-weight: bold; font-size: 18px; }}
  .err {{ color: #f00; font-weight: bold; }}
  code {{ background: #222; padding: 2px 6px; border-radius: 3px; }}
  label {{ display: block; margin-top: 12px; color: #f90; }}
</style>
</head>
<body>
<h1>🏎 Blinkit Session Uploader</h1>

{status}

<div class="step"><b>Step 1</b> — Open <a href="https://blinkit.com" target="_blank" style="color:#f90">blinkit.com</a>, log in, set location to <b>Madhapur 500081</b></div>
<div class="step"><b>Step 2</b> — Press <b>F12</b> → Console → type <code>allow pasting</code> → Enter</div>
<div class="step"><b>Step 3</b> — Paste this → Enter → Ctrl+C won't work, it auto-copies:<br><code>copy(document.cookie)</code></div>
<div class="step"><b>Step 4</b> — Paste cookies below, then repeat with:<br><code>copy(JSON.stringify(Object.fromEntries(Object.entries(localStorage))))</code></div>

<form method="POST" action="/upload">
  <label>Secret Key:</label>
  <input type="password" name="secret" placeholder="hotwheels2024" required>

  <label>Cookies (from copy(document.cookie)):</label>
  <textarea name="cookies" placeholder="Paste cookie string here..." required></textarea>

  <label>LocalStorage JSON (from copy(JSON.stringify(...)) or leave as {{}}):</label>
  <textarea name="localstorage">{{}}</textarea>

  <button type="submit">💾 Save Session & Activate Bot</button>
</form>

<hr>
<p style="color:#888">Session status: {session_status}</p>
<p style="color:#888">After saving, copy the BLINKIT_SESSION_B64 value shown and add it as a Railway variable to make the session permanent.</p>
{b64_section}
</body>
</html>
"""


def parse_cookie_string(cookie_str: str) -> list[dict]:
    cookies = []
    for part in cookie_str.split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        name, _, value = part.partition("=")
        cookies.append({
            "name": name.strip(), "value": value.strip(),
            "domain": ".blinkit.com", "path": "/",
            "expires": -1, "httpOnly": False,
            "secure": True, "sameSite": "None",
        })
    return cookies


def build_storage_state(cookies: list[dict], local_storage: dict) -> dict:
    origins = []
    if local_storage:
        origins.append({
            "origin": "https://blinkit.com",
            "localStorage": [{"name": k, "value": str(v)} for k, v in local_storage.items()],
        })
    return {"cookies": cookies, "origins": origins}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args): pass

    def do_GET(self):
        if urlparse(self.path).path not in ("/", "/upload"):
            self._send(404, "Not found"); return
        self._send(200, self._render_form(""))

    def do_POST(self):
        if urlparse(self.path).path != "/upload":
            self._send(404, "Not found"); return

        length  = int(self.headers.get("Content-Length", 0))
        body    = self.rfile.read(length).decode()
        params  = parse_qs(body)

        secret     = params.get("secret",       [""])[0]
        cookie_str = params.get("cookies",      [""])[0].strip()
        ls_str     = params.get("localstorage", ["{}"])[0].strip()

        if secret != SECRET_KEY:
            self._send(200, self._render_form('<p class="err">❌ Wrong secret key.</p>')); return
        if not cookie_str:
            self._send(200, self._render_form('<p class="err">❌ Cookies are empty.</p>')); return

        try:
            local_storage = json.loads(ls_str) if ls_str and ls_str not in ("{}", "") else {}
        except Exception:
            local_storage = {}

        cookies       = parse_cookie_string(cookie_str)
        storage_state = build_storage_state(cookies, local_storage)
        state_json    = json.dumps(storage_state, indent=2)

        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        SESSION_FILE.write_text(state_json)

        # Encode as base64 for Railway variable
        b64 = base64.b64encode(state_json.encode()).decode()

        status = f'<p class="ok">✅ Session saved! {len(cookies)} cookies stored.</p>'
        b64_section = f"""
<div style="background:#1a1a1a; border:1px solid #f90; padding:15px; margin-top:20px;">
<p style="color:#f90; font-weight:bold">⚠️ IMPORTANT — Make session permanent:</p>
<p>Go to Railway → Variables → Add new variable:</p>
<p><b>Name:</b> <code>BLINKIT_SESSION_B64</code></p>
<p><b>Value:</b> (copy everything in the box below)</p>
<textarea readonly onclick="this.select()" style="height:80px; color:#0ff;">{b64}</textarea>
<p>After adding this variable, Railway will automatically restore your session after every restart.</p>
</div>"""

        self._send(200, self._render_form(status, b64_section))

    def _render_form(self, status: str, b64_section: str = "") -> str:
        session_status = (
            f"✅ Session file exists ({SESSION_FILE.stat().st_size} bytes)"
            if SESSION_FILE.exists() else "⚠️ No session file yet"
        )
        return HTML_FORM.format(
            status=status,
            session_status=session_status,
            b64_section=b64_section,
        )

    def _send(self, code: int, body: str) -> None:
        encoded = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def start_upload_server() -> None:
    restore_session_from_env()
    server = HTTPServer(("0.0.0.0", UPLOAD_PORT), Handler)
    print(f"🌐  Session upload server running on port {UPLOAD_PORT}")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()


if __name__ == "__main__":
    restore_session_from_env()
    server = HTTPServer(("0.0.0.0", UPLOAD_PORT), Handler)
    print(f"🌐  Upload server on http://localhost:{UPLOAD_PORT}")
    server.serve_forever()
