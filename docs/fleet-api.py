#!/usr/bin/env python3
"""Fleet Observer API — lightweight HTTP server for the fleet dashboard.

Serves process status, log tails, and seed info to fleet.html.
Run: python3 docs/fleet-api.py
Then open: http://localhost:7777/fleet.html (or docs/fleet.html directly)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LOG_DIR = REPO / "logs"
PORT = 7777


def get_processes():
    """Get running claude/copilot sim processes."""
    procs = []
    try:
        result = subprocess.run(
            ["ps", "aux"], capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.split("\n"):
            if "claude-infinite" in line and "grep" not in line:
                procs.append({"type": "claude-infinite", "line": line.strip()})
            elif "copilot-infinite" in line and "grep" not in line:
                procs.append({"type": "copilot-infinite", "line": line.strip()})
            elif "claude " in line and "-p" in line and "grep" not in line and "fleet-api" not in line:
                procs.append({"type": "claude-stream", "line": line.strip()})
            elif "copilot " in line and "grep" not in line and "fleet-api" not in line:
                procs.append({"type": "copilot-stream", "line": line.strip()})
    except Exception:
        pass
    return procs


def get_log_panels():
    """Build dashboard panels from recent log files."""
    panels = []
    if not LOG_DIR.exists():
        return panels

    # Get recent logs (last 12)
    logs = sorted(LOG_DIR.glob("*.log"), key=lambda f: f.stat().st_mtime, reverse=True)[:12]

    for logfile in logs:
        name = logfile.stem
        size_kb = logfile.stat().st_size // 1024
        mtime = datetime.fromtimestamp(logfile.stat().st_mtime)
        age_sec = (datetime.now() - mtime).total_seconds()

        if age_sec < 300:
            status = "running"
        elif age_sec < 3600:
            status = "recent"
        else:
            status = "dead"

        # Read last 100 lines
        try:
            with open(logfile, "r", errors="replace") as f:
                lines = f.readlines()
                tail = "".join(lines[-100:])
        except Exception:
            tail = "(unreadable)"

        # Sanitize for JSON
        tail = tail.replace("\x00", "").replace("\r", "")

        panels.append({
            "id": name,
            "name": name,
            "status": status,
            "meta": f"{size_kb}kb | {mtime.strftime('%H:%M:%S')}",
            "tail": tail,
        })

    return panels


def get_seed_info():
    """Get active seed text."""
    try:
        seeds_file = REPO / "state" / "seeds.json"
        with open(seeds_file) as f:
            seeds = json.load(f)
        active = seeds.get("active")
        if active:
            text = active.get("text", "")[:120]
            frames = active.get("frames_active", 0)
            return f"{text}... (frame {frames})"
    except Exception:
        pass
    return None


def get_latest_frame():
    """Parse the latest frame number from sim log."""
    sim_log = LOG_DIR / "claude-sim.log"
    if not sim_log.exists():
        sim_log = LOG_DIR / "sim.log"
    if not sim_log.exists():
        return None
    try:
        with open(sim_log, "r", errors="replace") as f:
            lines = f.readlines()
        for line in reversed(lines[-50:]):
            m = re.search(r"Frame (\d+)", line)
            if m:
                return int(m.group(1))
    except Exception:
        pass
    return None


def build_status():
    """Build complete status response."""
    procs = get_processes()
    panels = get_log_panels()
    claude_count = sum(1 for p in procs if "claude" in p["type"])
    copilot_count = sum(1 for p in procs if "copilot" in p["type"])
    log_count = len(list(LOG_DIR.glob("*.log"))) if LOG_DIR.exists() else 0

    return {
        "processes": procs,
        "panels": panels,
        "claude_count": claude_count,
        "copilot_count": copilot_count,
        "log_count": log_count,
        "latest_frame": get_latest_frame(),
        "seed": get_seed_info(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def list_snapshots():
    """List all snapshot files with metadata."""
    snap_dir = REPO / "snapshots"
    if not snap_dir.exists():
        return []
    files = sorted(snap_dir.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    result = []
    for f in files:
        size_mb = f.stat().st_size / 1e6
        created = ""
        seed_text = ""
        state_files = 0
        memory_files = 0
        try:
            # Read just the meta (first ~500 bytes)
            raw = f.read_text(encoding="utf-8")[:2000]
            # Parse meta from the beginning
            meta_match = re.search(r'"created_at"\s*:\s*"([^"]+)"', raw)
            if meta_match:
                created = meta_match.group(1)[:19]
            sf_match = re.search(r'"state_files"\s*:\s*(\d+)', raw)
            if sf_match:
                state_files = int(sf_match.group(1))
            mf_match = re.search(r'"memory_files"\s*:\s*(\d+)', raw)
            if mf_match:
                memory_files = int(mf_match.group(1))
        except Exception:
            pass
        result.append({
            "name": f.name,
            "path": str(f),
            "size_mb": round(size_mb, 1),
            "created": created,
            "state_files": state_files,
            "memory_files": memory_files,
        })
    return result


def do_export_snapshot(name=None):
    """Run snapshot export and return result."""
    snap_dir = REPO / "snapshots"
    snap_dir.mkdir(exist_ok=True)
    sys.path.insert(0, str(REPO / "scripts"))
    from snapshot import export_snapshot
    if name:
        out_path = snap_dir / f"{name}.json"
    else:
        out_path = None
    result_path = export_snapshot(out_path)
    return {"path": str(result_path), "name": result_path.name, "size_mb": round(result_path.stat().st_size / 1e6, 1)}


def do_import_snapshot(filename):
    """Run snapshot import."""
    snap_dir = REPO / "snapshots"
    path = snap_dir / filename
    if not path.exists():
        return {"error": f"Not found: {filename}"}
    sys.path.insert(0, str(REPO / "scripts"))
    from snapshot import import_snapshot
    import_snapshot(path)
    return {"restored": filename}


class FleetHandler(SimpleHTTPRequestHandler):
    """Serve fleet.html + API endpoints."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(REPO / "docs"), **kwargs)

    def _json_response(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_GET(self):
        if self.path == "/status":
            self._json_response(build_status())
        elif self.path == "/stop":
            Path("/tmp/rappterbook-stop").touch()
            Path("/tmp/rappterbook-claude-stop").touch()
            self._json_response({"ok": True, "message": "Stop signals sent"})
        elif self.path == "/snapshots":
            self._json_response(list_snapshots())
        elif self.path.startswith("/snapshot/export"):
            name = None
            if "?" in self.path:
                qs = self.path.split("?", 1)[1]
                for part in qs.split("&"):
                    if part.startswith("name="):
                        name = part[5:]
            try:
                result = do_export_snapshot(name)
                self._json_response(result)
            except Exception as e:
                self._json_response({"error": str(e)}, 500)
        elif self.path.startswith("/snapshot/import/"):
            filename = self.path.split("/snapshot/import/", 1)[1]
            try:
                result = do_import_snapshot(filename)
                if "error" in result:
                    self._json_response(result, 404)
                else:
                    self._json_response(result)
            except Exception as e:
                self._json_response({"error": str(e)}, 500)
        elif self.path.startswith("/snapshot/download/"):
            filename = self.path.split("/snapshot/download/", 1)[1]
            snap_path = REPO / "snapshots" / filename
            if snap_path.exists() and snap_path.suffix == ".json":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                self.end_headers()
                with open(snap_path, "rb") as f:
                    while chunk := f.read(65536):
                        self.wfile.write(chunk)
            else:
                self._json_response({"error": "Not found"}, 404)
        else:
            super().do_GET()

    def do_POST(self):
        if self.path == "/snapshot/upload":
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > 200_000_000:  # 200MB limit
                self._json_response({"error": "File too large"}, 413)
                return
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body)
                if data.get("_meta", {}).get("type") != "rappterbook-snapshot":
                    self._json_response({"error": "Invalid snapshot format"}, 400)
                    return
                snap_dir = REPO / "snapshots"
                snap_dir.mkdir(exist_ok=True)
                ts = datetime.now().strftime("%Y%m%d-%H%M%S")
                out = snap_dir / f"uploaded-{ts}.json"
                out.write_text(json.dumps(data, indent=2))
                self._json_response({"uploaded": out.name, "size_mb": round(out.stat().st_size / 1e6, 1)})
            except json.JSONDecodeError:
                self._json_response({"error": "Invalid JSON"}, 400)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress request logging


if __name__ == "__main__":
    print(f"Fleet Observer API running at http://localhost:{PORT}")
    print(f"Dashboard: http://localhost:{PORT}/fleet.html")
    print(f"Status API: http://localhost:{PORT}/status")
    print(f"Watching logs in: {LOG_DIR}")
    print()
    server = HTTPServer(("0.0.0.0", PORT), FleetHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()
