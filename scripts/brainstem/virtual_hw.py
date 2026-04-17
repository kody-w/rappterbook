"""Virtual Hardware — the bridge between twin-space and real devices.

Pattern: agents operate in the twin by default (synthetic responses, no
hardware access). When they need real mic / screen / camera / speakers /
clipboard / notifications, they request a CAPABILITY GRANT. The grant
opens an IPC channel to a locally-running harness (bridge.py) that owns
the real device and enforces policy (rate limits, user approval, etc).

The twin NEVER talks to hardware directly. It talks to the bridge. The
bridge talks to hardware. This keeps the twin portable (works on any
OS — each host ships its own bridge implementation) and the safety
model explicit (agents only get what's granted).

Architecture:

    Agent                LisPy twin               Local bridge           Real HW
    -----               ----------               -------------          ---------
    (hw-screenshot)  ──► virtual_hw.py   ──────► bridge.py daemon  ────► macOS API
                        (capability gate)         (IPC over socket)      (AVFoundation,
                                                                          osascript, etc)

Capability grants are scoped — `(with-capability 'hw-screen ...)` grants
for the body only. Revoked on scope exit. No persistent grants without
explicit user config.

Default behavior when no bridge is running or no grant is active:
- twin returns synthetic bytes (e.g., placeholder PNG for screenshot)
- OR raises "capability not granted" — agent knows the call was noop
"""
from __future__ import annotations

import base64
import json
import os
import socket
import time
from typing import Any


# ---------------------------------------------------------------------------
# Bridge client — talks to the local harness over Unix socket
# ---------------------------------------------------------------------------

BRIDGE_SOCKET = os.environ.get("LISPY_BRIDGE_SOCKET", "/tmp/lispy-bridge.sock")
BRIDGE_TIMEOUT = 10.0

_GRANTED_CAPABILITIES: set[str] = set()


def _bridge_available() -> bool:
    """Check if a bridge daemon is listening on the Unix socket."""
    if not os.path.exists(BRIDGE_SOCKET):
        return False
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(0.5)
        s.connect(BRIDGE_SOCKET)
        s.close()
        return True
    except (OSError, socket.timeout):
        return False


def _bridge_call(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Send a JSON-RPC request to the bridge and return the response."""
    if not _bridge_available():
        return {"error": "bridge not running",
                "hint": f"Start bridge: python3 -m scripts.brainstem.bridge --listen {BRIDGE_SOCKET}"}
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(BRIDGE_TIMEOUT)
        s.connect(BRIDGE_SOCKET)
        req = json.dumps({"method": method, "params": params or {}}) + "\n"
        s.sendall(req.encode("utf-8"))
        buf = b""
        while True:
            chunk = s.recv(65536)
            if not chunk: break
            buf += chunk
            if b"\n" in buf: break
        s.close()
        return json.loads(buf.decode("utf-8").strip())
    except Exception as exc:
        return {"error": f"bridge call failed: {exc}"}


# ---------------------------------------------------------------------------
# Capability grants — scoped, revocable
# ---------------------------------------------------------------------------

VALID_CAPABILITIES = frozenset([
    "hw-screen",        # screenshot / screen recording
    "hw-microphone",    # record audio
    "hw-camera",        # capture photo / video
    "hw-speakers",      # play audio / TTS
    "hw-clipboard",     # read / write clipboard
    "hw-notification",  # push macOS notification
    "hw-keyboard",      # listen for keypresses
    "hw-mouse",         # read / move / click
    "hw-file-dialog",   # native open / save dialogs
    "hw-location",      # GPS / CoreLocation
    "pyodide",          # escape hatch — run real Python via Pyodide (browser only)
])


def grant_capability(cap: str) -> str:
    """Grant a capability for the current scope. Returns status string."""
    if cap not in VALID_CAPABILITIES:
        return f"ERROR: unknown capability '{cap}'. Valid: {sorted(VALID_CAPABILITIES)}"
    _GRANTED_CAPABILITIES.add(cap)
    return f"granted: {cap}"


def revoke_capability(cap: str) -> str:
    _GRANTED_CAPABILITIES.discard(cap)
    return f"revoked: {cap}"


def has_capability(cap: str) -> bool:
    return cap in _GRANTED_CAPABILITIES


def list_capabilities() -> list[str]:
    return sorted(_GRANTED_CAPABILITIES)


def _require(cap: str, action: str) -> dict | None:
    """Return error dict if capability is missing, None if OK."""
    if cap not in _GRANTED_CAPABILITIES:
        return {"error": f"capability '{cap}' not granted",
                "hint": f"Call (grant-capability \"{cap}\") before {action}"}
    if not _bridge_available():
        return {"error": "bridge not running",
                "hint": f"Start bridge: python3 -m scripts.brainstem.bridge"}
    return None


# ---------------------------------------------------------------------------
# Hardware bindings — each checks capability, routes to bridge or twins
# ---------------------------------------------------------------------------

def hw_screenshot() -> dict:
    """Capture the current screen. Returns {'image_base64': ...} or synthetic."""
    err = _require("hw-screen", "calling hw-screenshot")
    if err:
        # Synthetic fallback: 1x1 transparent PNG
        synthetic = base64.b64encode(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
            b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        ).decode("ascii")
        return {"image_base64": synthetic, "synthetic": True, **err}
    return _bridge_call("screenshot")


def hw_tts(text: str, voice: str = "Samantha") -> dict:
    """Speak text through the speakers. Returns {'played': true/false}."""
    err = _require("hw-speakers", "calling hw-tts")
    if err:
        return {"played": False, "synthetic": True, **err}
    return _bridge_call("tts", {"text": text, "voice": voice})


def hw_microphone_record(seconds: float = 3.0) -> dict:
    """Record audio from the microphone. Returns {'audio_base64': ...}."""
    err = _require("hw-microphone", "calling hw-microphone-record")
    if err:
        return {"audio_base64": "", "synthetic": True, **err}
    return _bridge_call("microphone_record", {"seconds": seconds})


def hw_clipboard_read() -> dict:
    """Read the system clipboard. Returns {'text': ...}."""
    err = _require("hw-clipboard", "calling hw-clipboard-read")
    if err:
        return {"text": "[twin-mode: clipboard not granted]", **err}
    return _bridge_call("clipboard_read")


def hw_clipboard_write(text: str) -> dict:
    """Write text to the system clipboard."""
    err = _require("hw-clipboard", "calling hw-clipboard-write")
    if err:
        return {"written": False, **err}
    return _bridge_call("clipboard_write", {"text": text})


def hw_notification(title: str, body: str = "", subtitle: str = "") -> dict:
    """Post a macOS notification."""
    err = _require("hw-notification", "calling hw-notification")
    if err:
        return {"posted": False, **err}
    return _bridge_call("notification", {"title": title, "body": body, "subtitle": subtitle})


def hw_camera_capture() -> dict:
    """Capture a photo from the webcam. Returns {'image_base64': ...}."""
    err = _require("hw-camera", "calling hw-camera-capture")
    if err:
        return {"image_base64": "", "synthetic": True, **err}
    return _bridge_call("camera_capture")


def hw_location() -> dict:
    """Get current location. Returns {'lat': ..., 'lon': ..., 'accuracy': ...}."""
    err = _require("hw-location", "calling hw-location")
    if err:
        return {"lat": 0.0, "lon": 0.0, "synthetic": True, **err}
    return _bridge_call("location")


# ---------------------------------------------------------------------------
# Introspection
# ---------------------------------------------------------------------------

def bridge_status() -> dict:
    """Inspect whether the bridge is running and what's granted."""
    return {
        "bridge_running": _bridge_available(),
        "bridge_socket": BRIDGE_SOCKET,
        "granted_capabilities": sorted(_GRANTED_CAPABILITIES),
        "available_capabilities": sorted(VALID_CAPABILITIES),
    }
