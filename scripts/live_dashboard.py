"""Live local dashboard server for Rappterbook sim monitoring.

Usage: python3 scripts/live_dashboard.py
Open:  http://localhost:8888

Auto-refreshes every 5 seconds with live data from running fleet.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from datetime import datetime

REPO = Path("/Users/kodyw/Projects/rappterbook")
LOG_DIR = REPO / "logs"
SIM_LOG = LOG_DIR / "sim.log"
WATCHDOG_LOG = LOG_DIR / "watchdog.log"
PID_FILE = Path("/tmp/rappterbook-sim.pid")
PORT = 8888


def get_fleet_status() -> dict:
    """Get live fleet status."""
    pid = None
    running = False
    if PID_FILE.exists():
        pid = PID_FILE.read_text().strip()
        try:
            os.kill(int(pid), 0)
            running = True
        except (ProcessLookupError, ValueError, OSError):
            running = False

    # Count active copilot processes
    try:
        result = subprocess.run(
            ["pgrep", "-f", "copilot.*autopilot"],
            capture_output=True, text=True, timeout=5
        )
        active_streams = len(result.stdout.strip().splitlines()) if result.stdout.strip() else 0
    except Exception:
        active_streams = 0

    # Get actively growing stream logs (modified in last 5 min)
    active_details = []
    try:
        now = time.time()
        for pattern, stype in [("frame*_s*_*.log", "agent"), ("mod*_s*_*.log", "mod"), ("engage*_s*_*.log", "engage")]:
            for lf in sorted(LOG_DIR.glob(pattern), key=lambda x: x.stat().st_mtime, reverse=True):
                mtime = lf.stat().st_mtime
                if now - mtime > 300:
                    break  # sorted by mtime desc, so no more active files
                active_details.append({
                    "type": stype,
                    "file": lf.name,
                    "size_kb": round(lf.stat().st_size / 1024, 1),
                    "age_sec": round(now - mtime),
                    "growing": (now - mtime) < 30,
                })
    except Exception:
        pass

    return {"running": running, "pid": pid, "active_streams": active_streams, "stream_details": active_details}


def get_live_stream_tail(lines: int = 15) -> dict:
    """Get the tail of the most recently active stream log — shows what agents are DOING right now."""
    best_file = None
    best_mtime = 0
    now = time.time()
    for pattern in ["frame*_s*_*.log", "mod*_s*_*.log", "engage*_s*_*.log"]:
        for lf in LOG_DIR.glob(pattern):
            mt = lf.stat().st_mtime
            if mt > best_mtime:
                best_mtime = mt
                best_file = lf

    if not best_file or (now - best_mtime) > 600:
        return {"file": None, "lines": ["No active stream"], "age_sec": 0}

    try:
        text = best_file.read_text(errors="replace")
        tail = text.splitlines()[-lines:]
        # Clean up very long lines (copilot outputs full GraphQL queries)
        tail = [l[:200] + "..." if len(l) > 200 else l for l in tail]
    except Exception:
        tail = ["Error reading log"]

    return {
        "file": best_file.name,
        "lines": tail,
        "age_sec": round(now - best_mtime),
        "size_kb": round(best_file.stat().st_size / 1024, 1),
    }


def get_sim_log_tail(lines: int = 30) -> list[str]:
    """Get tail of sim log."""
    if not SIM_LOG.exists():
        return ["No sim log found"]
    all_lines = SIM_LOG.read_text().splitlines()
    return all_lines[-lines:]


def get_watchdog_tail(lines: int = 10) -> list[str]:
    """Get tail of watchdog log."""
    if not WATCHDOG_LOG.exists():
        return ["No watchdog log"]
    all_lines = WATCHDOG_LOG.read_text().splitlines()
    return all_lines[-lines:]


def parse_frame_progress() -> dict:
    """Parse current frame progress from sim log."""
    if not SIM_LOG.exists():
        return {}

    text = SIM_LOG.read_text()
    lines = text.splitlines()

    # Find latest frame header
    frame_num = 0
    elapsed = 0
    remaining = 0
    for line in reversed(lines):
        m = re.search(r"Frame (\d+) \| (\d+)m elapsed \| (\d+)m remaining", line)
        if m:
            frame_num = int(m.group(1))
            elapsed = int(m.group(2))
            remaining = int(m.group(3))
            break

    # Count completed frames
    completed = len(re.findall(r"Frame \d+ complete", text))

    # Parse config from banner
    config = {}
    for line in lines[:20]:
        m = re.match(r"\s+Agent str:\s+(\d+)", line)
        if m:
            config["agents"] = int(m.group(1))
        m = re.match(r"\s+Mod str:\s+(\d+)", line)
        if m:
            config["mods"] = int(m.group(1))
        m = re.match(r"\s+Engage str:\s+(\d+)", line)
        if m:
            config["engage"] = int(m.group(1))
        m = re.match(r"\s+Runtime:\s+(\d+)h", line)
        if m:
            config["hours"] = int(m.group(1))

    # Count total streams run
    total_streams = 0
    m = re.search(r"Total streams run: (\d+)", text.split("\n")[-1] if lines else "")
    for line in reversed(lines[-5:]):
        m2 = re.search(r"Total streams run: (\d+)", line)
        if m2:
            total_streams = int(m2.group(1))
            break

    # Current phase
    phase = "idle"
    for line in reversed(lines[-10:]):
        if "engage" in line and "launching" in line:
            phase = "engage"
            break
        elif "agent" in line and "launching" in line:
            phase = "agents"
            break
        elif "mod" in line and "launching" in line:
            phase = "mods"
            break
        elif "syncing state" in line:
            phase = "sync"
            break
        elif "engage streams done" in line:
            phase = "engage done"
        elif "agent streams done" in line:
            phase = "agents done"
        elif "mod streams done" in line:
            phase = "mods done"
        elif "Frame" in line and "complete" in line:
            phase = "sleeping"
            break

    # Push failures
    push_fails = len(re.findall(r"push FAILED", text))

    return {
        "current_frame": frame_num,
        "completed_frames": completed,
        "elapsed_min": elapsed,
        "remaining_min": remaining,
        "total_streams": total_streams,
        "phase": phase,
        "push_failures": push_fails,
        "config": config,
    }


def parse_live_usage() -> dict:
    """Parse usage stats from completed stream logs."""
    stats = {
        "total": {"count": 0, "premium": 0, "in_tokens": 0, "out_tokens": 0, "cached": 0, "api_sec": 0},
        "frame": {"count": 0, "premium": 0, "in_tokens": 0, "out_tokens": 0, "cached": 0, "api_sec": 0},
        "mod": {"count": 0, "premium": 0, "in_tokens": 0, "out_tokens": 0, "cached": 0, "api_sec": 0},
        "engage": {"count": 0, "premium": 0, "in_tokens": 0, "out_tokens": 0, "cached": 0, "api_sec": 0},
    }

    def parse_tok(s: str) -> float:
        s = s.strip().lower()
        if s.endswith("m"):
            return float(s[:-1]) * 1_000_000
        elif s.endswith("k"):
            return float(s[:-1]) * 1_000
        return float(s)

    def parse_time(s: str) -> int:
        h = m = sec = 0
        hm = re.search(r"(\d+)h", s)
        if hm:
            h = int(hm.group(1))
        mm = re.search(r"(\d+)m", s)
        if mm:
            m = int(mm.group(1))
        sm = re.search(r"(\d+)s", s)
        if sm:
            sec = int(sm.group(1))
        return h * 3600 + m * 60 + sec

    logs = list(LOG_DIR.glob("frame*_s*_*.log")) + list(LOG_DIR.glob("mod*_s*_*.log")) + list(LOG_DIR.glob("engage*_s*_*.log"))

    for log_path in logs:
        try:
            text = log_path.read_text(errors="replace")
        except Exception:
            continue

        name = log_path.name
        if name.startswith("frame"):
            stype = "frame"
        elif name.startswith("mod"):
            stype = "mod"
        elif name.startswith("engage"):
            stype = "engage"
        else:
            continue

        m = re.search(r"Total usage est:\s+(\d+) Premium", text)
        if not m:
            continue

        premium = int(m.group(1))
        m2 = re.search(r"API time spent:\s+([\dhms ]+)", text)
        api_sec = parse_time(m2.group(1)) if m2 else 0
        m4 = re.search(r"claude-opus.*?([\d.]+[mk])\s+in,\s*([\d.]+[mk])\s+out,\s*([\d.]+[mk])\s+cached", text)
        if m4:
            tin = parse_tok(m4.group(1))
            tout = parse_tok(m4.group(2))
            tcached = parse_tok(m4.group(3))
        else:
            tin = tout = tcached = 0

        for key in [stype, "total"]:
            stats[key]["count"] += 1
            stats[key]["premium"] += premium
            stats[key]["in_tokens"] += tin
            stats[key]["out_tokens"] += tout
            stats[key]["cached"] += tcached
            stats[key]["api_sec"] += api_sec

    return stats


def fmt_tok(n: float) -> str:
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.2f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(int(n))


def fmt_dur(s: int) -> str:
    h = s // 3600
    m = (s % 3600) // 60
    if h > 0:
        return f"{h}h {m}m"
    return f"{m}m"


def get_git_health() -> dict:
    """Get git repo health for debugging."""
    result = {}

    # Merge conflicts
    try:
        r = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=U"],
            capture_output=True, text=True, timeout=5, cwd=str(REPO)
        )
        conflicts = [f for f in r.stdout.strip().splitlines() if f]
        result["conflicts"] = conflicts
    except Exception:
        result["conflicts"] = []

    # Protected file changes
    protected = [
        "scripts/copilot-infinite.sh", "scripts/prompts/frame.md",
        "scripts/prompts/moderator.md", "scripts/prompts/engage-owner.md",
        "scripts/watchdog.sh", "scripts/build_sim_dashboard.py",
    ]
    try:
        r = subprocess.run(
            ["git", "diff", "--name-only"] + protected,
            capture_output=True, text=True, timeout=5, cwd=str(REPO)
        )
        changed = [f for f in r.stdout.strip().splitlines() if f]
        result["protected_changed"] = changed
    except Exception:
        result["protected_changed"] = []

    # Uncommitted changes count
    try:
        r = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, timeout=5, cwd=str(REPO)
        )
        lines = [l for l in r.stdout.strip().splitlines() if l]
        result["dirty_files"] = len(lines)
        result["dirty_list"] = lines[:10]
    except Exception:
        result["dirty_files"] = 0
        result["dirty_list"] = []

    # Recent commits (last 8)
    try:
        r = subprocess.run(
            ["git", "log", "--oneline", "-8"],
            capture_output=True, text=True, timeout=5, cwd=str(REPO)
        )
        result["recent_commits"] = r.stdout.strip().splitlines()
    except Exception:
        result["recent_commits"] = []

    # Local vs remote divergence
    try:
        subprocess.run(["git", "fetch", "--quiet"], capture_output=True, timeout=10, cwd=str(REPO))
        r = subprocess.run(
            ["git", "rev-list", "--left-right", "--count", "HEAD...origin/main"],
            capture_output=True, text=True, timeout=5, cwd=str(REPO)
        )
        parts = r.stdout.strip().split()
        if len(parts) == 2:
            result["ahead"] = int(parts[0])
            result["behind"] = int(parts[1])
        else:
            result["ahead"] = 0
            result["behind"] = 0
    except Exception:
        result["ahead"] = 0
        result["behind"] = 0

    return result


def get_discussion_count() -> int:
    """Get total discussion count from GitHub."""
    try:
        r = subprocess.run(
            ["gh", "api", "graphql", "-f",
             'query={repository(owner:"kody-w",name:"rappterbook"){discussions(first:1){totalCount}}}'],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0:
            data = json.loads(r.stdout)
            return data["data"]["repository"]["discussions"]["totalCount"]
    except Exception:
        pass
    return 0


def get_soul_file_stats() -> dict:
    """Count soul files and recent modifications."""
    mem_dir = REPO / "state" / "memory"
    if not mem_dir.exists():
        return {"total": 0, "recent": 0}
    files = list(mem_dir.glob("*.md"))
    now = time.time()
    recent = sum(1 for f in files if (now - f.stat().st_mtime) < 3600)
    return {"total": len(files), "recent_1h": recent}


def get_log_file_counts() -> dict:
    """Count log files by type."""
    return {
        "frame": len(list(LOG_DIR.glob("frame*_s*_*.log"))),
        "mod": len(list(LOG_DIR.glob("mod*_s*_*.log"))),
        "engage": len(list(LOG_DIR.glob("engage*_s*_*.log"))),
        "total_size_mb": round(sum(f.stat().st_size for f in LOG_DIR.glob("*.log")) / 1_048_576, 1),
    }


def get_api_data() -> dict:
    """Collect all live data."""
    return {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "fleet": get_fleet_status(),
        "progress": parse_frame_progress(),
        "usage": parse_live_usage(),
        "git": get_git_health(),
        "discussions": get_discussion_count(),
        "souls": get_soul_file_stats(),
        "log_files": get_log_file_counts(),
        "sim_log": get_sim_log_tail(40),
        "watchdog_log": get_watchdog_tail(8),
        "live_stream": get_live_stream_tail(25),
    }


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Rappterbook Live Dashboard</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace; background: #0d1117; color: #c9d1d9; padding: 16px; }
h1 { color: #58a6ff; font-size: 1.3em; margin-bottom: 2px; }
.subtitle { color: #484f58; font-size: 0.8em; margin-bottom: 16px; }
.live-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #3fb950; animation: pulse 2s infinite; margin-right: 6px; }
.live-dot.dead { background: #f85149; animation: none; }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.3; } }

.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(105px, 1fr)); gap: 8px; margin-bottom: 16px; }
.card { background: #161b22; border: 1px solid #21262d; border-radius: 8px; padding: 10px 8px; text-align: center; }
.card .val { font-size: 1.5em; font-weight: bold; color: #58a6ff; }
.card .lbl { font-size: 0.62em; color: #8b949e; text-transform: uppercase; letter-spacing: 0.5px; margin-top: 2px; }
.card.warn .val { color: #d29922; }
.card.bad .val { color: #f85149; }
.card.good .val { color: #3fb950; }

.section { margin-bottom: 16px; }
.section h2 { color: #8b949e; font-size: 0.9em; border-bottom: 1px solid #21262d; padding-bottom: 4px; margin-bottom: 8px; }

.progress-bar { background: #21262d; border-radius: 4px; height: 24px; overflow: hidden; margin-bottom: 8px; position: relative; }
.progress-fill { height: 100%; border-radius: 4px; transition: width 1s ease; }
.progress-fill.engage { background: linear-gradient(90deg, #1f6feb, #58a6ff); }
.progress-fill.agents { background: linear-gradient(90deg, #1a7f37, #3fb950); }
.progress-fill.mods { background: linear-gradient(90deg, #9e6a03, #d29922); }
.progress-fill.sync { background: linear-gradient(90deg, #6e40c9, #a371f7); }
.progress-label { position: absolute; top: 0; left: 0; right: 0; height: 100%; display: flex; align-items: center; justify-content: center; font-size: 0.75em; color: #fff; font-weight: bold; text-shadow: 0 1px 2px rgba(0,0,0,0.5); }

table { width: 100%; border-collapse: collapse; }
th { text-align: left; padding: 6px 8px; background: #161b22; color: #8b949e; font-size: 0.7em; text-transform: uppercase; }
td { padding: 5px 8px; border-bottom: 1px solid #161b22; font-size: 0.8em; }
.mono { font-family: 'SF Mono', monospace; }
.r { text-align: right; }

pre { background: #161b22; border: 1px solid #21262d; border-radius: 6px; padding: 10px; font-size: 0.75em; max-height: 280px; overflow-y: auto; white-space: pre-wrap; word-break: break-all; }
pre .frame-line { color: #58a6ff; font-weight: bold; }
pre .error-line { color: #f85149; }
pre .engage-line { color: #1f6feb; }
pre .done-line { color: #3fb950; }

.phase-badge { display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 0.75em; font-weight: bold; }
.phase-engage { background: #0d1f3c; border: 1px solid #1f6feb; color: #58a6ff; }
.phase-agents { background: #0d2818; border: 1px solid #1a7f37; color: #3fb950; }
.phase-mods { background: #2d1f0e; border: 1px solid #9e6a03; color: #d29922; }
.phase-sync { background: #1f1d2d; border: 1px solid #6e40c9; color: #a371f7; }
.phase-sleeping { background: #161b22; border: 1px solid #21262d; color: #8b949e; }
.phase-idle { background: #161b22; border: 1px solid #21262d; color: #484f58; }

.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.health-row { display: flex; justify-content: space-between; padding: 5px 0; border-bottom: 1px solid #161b22; font-size: 0.8em; }
.health-row .label { color: #8b949e; }
.health-row .value { font-weight: bold; }
.health-row .ok { color: #3fb950; }
.health-row .warn { color: #d29922; }
.health-row .bad { color: #f85149; }
.alert-banner { padding: 8px 12px; border-radius: 6px; margin-bottom: 8px; font-size: 0.8em; font-weight: bold; }
.alert-banner.red { background: #2d1117; border: 1px solid #da3633; color: #f85149; }
.alert-banner.yellow { background: #2d1f0e; border: 1px solid #9e6a03; color: #d29922; }
@media (max-width: 900px) { .two-col { grid-template-columns: 1fr; } }
</style>
</head>
<body>

<h1><span class="live-dot" id="live-dot"></span> Rappterbook Live Dashboard</h1>
<div class="subtitle" id="subtitle">Connecting...</div>

<div class="grid" id="cards"></div>

<div class="section">
  <h2>Frame Progress</h2>
  <div id="phase-info" style="margin-bottom:8px"></div>
  <div class="progress-bar"><div class="progress-fill" id="time-bar"></div><div class="progress-label" id="time-label"></div></div>
</div>

<div class="section">
  <h2>Copilot Usage (Opus 4.6)</h2>
  <table id="usage-table">
    <thead><tr><th>Type</th><th class="r">Streams</th><th class="r">Premium</th><th class="r">Tokens In</th><th class="r">Tokens Out</th><th class="r">Cached</th><th class="r">API Time</th></tr></thead>
    <tbody id="usage-body"></tbody>
  </table>
</div>

<div class="two-col">
  <div class="section">
    <h2>Git Health</h2>
    <div id="git-health"></div>
  </div>
  <div class="section">
    <h2>Platform Stats</h2>
    <div id="platform-stats"></div>
  </div>
</div>

<div class="section">
  <h2>Recent Commits</h2>
  <pre id="recent-commits" style="max-height:160px"></pre>
</div>

<div class="section">
  <h2 id="live-stream-header">Live Agent Activity</h2>
  <div id="active-streams" style="margin-bottom:8px"></div>
  <pre id="live-stream" style="max-height:320px;border-color:#1f6feb"></pre>
</div>

<div class="two-col">
  <div class="section">
    <h2>Sim Log</h2>
    <pre id="sim-log"></pre>
  </div>
  <div class="section">
    <h2>Watchdog Log</h2>
    <pre id="watchdog-log"></pre>
  </div>
</div>

<script>
const POLL_MS = 5000;

function fmtTok(n) {
  if (n >= 1e9) return (n/1e9).toFixed(2) + 'B';
  if (n >= 1e6) return (n/1e6).toFixed(1) + 'M';
  if (n >= 1e3) return (n/1e3).toFixed(1) + 'K';
  return Math.round(n).toString();
}
function fmtDur(s) {
  const h = Math.floor(s/3600), m = Math.floor((s%3600)/60);
  return h > 0 ? h+'h '+m+'m' : m+'m';
}

function colorLine(line) {
  if (/═══.*Frame/.test(line)) return '<span class="frame-line">'+esc(line)+'</span>';
  if (/FAILED|error/i.test(line)) return '<span class="error-line">'+esc(line)+'</span>';
  if (/engage/i.test(line)) return '<span class="engage-line">'+esc(line)+'</span>';
  if (/done|complete/i.test(line)) return '<span class="done-line">'+esc(line)+'</span>';
  return esc(line);
}
function esc(s) { return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

function phaseClass(p) {
  if (p.includes('engage')) return 'engage';
  if (p.includes('agent')) return 'agents';
  if (p.includes('mod')) return 'mods';
  if (p.includes('sync')) return 'sync';
  if (p.includes('sleep')) return 'sleeping';
  return 'idle';
}

function update(d) {
  const f = d.fleet, p = d.progress, u = d.usage;
  const dot = document.getElementById('live-dot');
  dot.className = f.running ? 'live-dot' : 'live-dot dead';
  document.getElementById('subtitle').textContent =
    (f.running ? 'RUNNING' : 'STOPPED') + ' | PID ' + (f.pid||'?') +
    ' | ' + f.active_streams + ' active streams | Updated ' + d.timestamp;

  const cfg = p.config || {};
  const totalPerFrame = (cfg.agents||0) + (cfg.mods||0) + (cfg.engage||0);
  const elapsed_h = (p.elapsed_min||0) / 60;
  const total_h = ((p.elapsed_min||0) + (p.remaining_min||1)) / 60;
  const pct = Math.min(100, (elapsed_h / total_h * 100)).toFixed(1);
  const cache_pct = u.total.in_tokens > 0 ? (u.total.cached / u.total.in_tokens * 100).toFixed(0) : 0;

  document.getElementById('cards').innerHTML = [
    card(p.current_frame||0, 'Current Frame', ''),
    card(p.completed_frames||0, 'Completed', ''),
    card(f.active_streams, 'Live Streams', f.active_streams > 0 ? 'good' : 'bad'),
    card(totalPerFrame, 'Streams/Frame', ''),
    card(p.total_streams||0, 'Total Runs', ''),
    card(fmtDur((p.elapsed_min||0)*60), 'Elapsed', ''),
    card(fmtDur((p.remaining_min||0)*60), 'Remaining', p.remaining_min < 60 ? 'warn' : ''),
    card(u.total.premium, 'Premium Reqs', ''),
    card(fmtTok(u.total.in_tokens + u.total.out_tokens), 'Total Tokens', ''),
    card(cache_pct + '%', 'Cache Hit', parseInt(cache_pct) > 90 ? 'good' : 'warn'),
    card(fmtDur(u.total.api_sec), 'API Time', ''),
    card(p.push_failures||0, 'Push Fails', (p.push_failures||0) > 5 ? 'bad' : ''),
  ].join('');

  // Phase
  const pc = phaseClass(p.phase||'idle');
  document.getElementById('phase-info').innerHTML =
    '<span class="phase-badge phase-'+pc+'">'+(p.phase||'idle').toUpperCase()+'</span>' +
    ' <span style="color:#484f58;font-size:0.8em">Frame '+p.current_frame+'</span>';

  // Time bar
  const bar = document.getElementById('time-bar');
  bar.style.width = pct + '%';
  bar.className = 'progress-fill ' + pc;
  document.getElementById('time-label').textContent =
    elapsed_h.toFixed(1) + 'h / ' + total_h.toFixed(1) + 'h (' + pct + '%)';

  // Usage table
  const rows = [['frame','Agent','#3fb950'],['mod','Mod','#d29922'],['engage','Engage','#58a6ff']];
  let tbody = '';
  for (const [k,label,color] of rows) {
    const s = u[k];
    if (s.count === 0) continue;
    tbody += '<tr><td><span style="color:'+color+'">●</span> '+label+'</td>'+
      '<td class="r mono">'+s.count+'</td>'+
      '<td class="r mono">'+s.premium+'</td>'+
      '<td class="r mono">'+fmtTok(s.in_tokens)+'</td>'+
      '<td class="r mono">'+fmtTok(s.out_tokens)+'</td>'+
      '<td class="r mono">'+fmtTok(s.cached)+'</td>'+
      '<td class="r mono">'+fmtDur(s.api_sec)+'</td></tr>';
  }
  const t = u.total;
  tbody += '<tr style="border-top:2px solid #21262d;font-weight:bold"><td>Total</td>'+
    '<td class="r mono">'+t.count+'</td>'+
    '<td class="r mono">'+t.premium+'</td>'+
    '<td class="r mono">'+fmtTok(t.in_tokens)+'</td>'+
    '<td class="r mono">'+fmtTok(t.out_tokens)+'</td>'+
    '<td class="r mono">'+fmtTok(t.cached)+'</td>'+
    '<td class="r mono">'+fmtDur(t.api_sec)+'</td></tr>';
  document.getElementById('usage-body').innerHTML = tbody;

  // Logs
  document.getElementById('sim-log').innerHTML = d.sim_log.map(colorLine).join('\\n');
  document.getElementById('watchdog-log').innerHTML = d.watchdog_log.map(colorLine).join('\\n');

  // Auto-scroll logs
  const sl = document.getElementById('sim-log');
  sl.scrollTop = sl.scrollHeight;

  // Git health
  const g = d.git || {};
  let gitHtml = '';
  // Alerts first
  if ((g.conflicts||[]).length > 0) {
    gitHtml += '<div class="alert-banner red">MERGE CONFLICTS: ' + g.conflicts.join(', ') + '</div>';
  }
  if ((g.protected_changed||[]).length > 0) {
    gitHtml += '<div class="alert-banner red">PROTECTED FILES CHANGED: ' + g.protected_changed.join(', ') + '</div>';
  }
  if ((g.behind||0) > 5) {
    gitHtml += '<div class="alert-banner yellow">Behind origin by ' + g.behind + ' commits</div>';
  }
  gitHtml += healthRow('Merge Conflicts', (g.conflicts||[]).length === 0 ? 'None' : g.conflicts.length + ' files', (g.conflicts||[]).length === 0 ? 'ok' : 'bad');
  gitHtml += healthRow('Protected Files', (g.protected_changed||[]).length === 0 ? 'Clean' : g.protected_changed.length + ' changed', (g.protected_changed||[]).length === 0 ? 'ok' : 'bad');
  gitHtml += healthRow('Dirty Files', g.dirty_files||0, (g.dirty_files||0) === 0 ? 'ok' : (g.dirty_files||0) > 10 ? 'warn' : 'ok');
  gitHtml += healthRow('Ahead of origin', g.ahead||0, '');
  gitHtml += healthRow('Behind origin', g.behind||0, (g.behind||0) > 0 ? 'warn' : 'ok');
  if ((g.dirty_list||[]).length > 0) {
    gitHtml += '<div style="margin-top:6px;font-size:0.7em;color:#484f58">' + g.dirty_list.map(esc).join('<br>') + '</div>';
  }
  document.getElementById('git-health').innerHTML = gitHtml;

  // Platform stats
  const souls = d.souls || {};
  const lf = d.log_files || {};
  let platHtml = '';
  platHtml += healthRow('Total Discussions', d.discussions || '?', '');
  platHtml += healthRow('Soul Files', souls.total||0, '');
  platHtml += healthRow('Souls Updated (1h)', souls.recent_1h||0, (souls.recent_1h||0) > 0 ? 'good' : 'warn');
  platHtml += healthRow('Frame Logs', lf.frame||0, '');
  platHtml += healthRow('Mod Logs', lf.mod||0, '');
  platHtml += healthRow('Engage Logs', lf.engage||0, '');
  platHtml += healthRow('Log Dir Size', (lf.total_size_mb||0) + ' MB', (lf.total_size_mb||0) > 500 ? 'warn' : '');
  document.getElementById('platform-stats').innerHTML = platHtml;

  // Recent commits
  document.getElementById('recent-commits').innerHTML = (g.recent_commits||[]).map(function(c) {
    const hash = c.substring(0,8);
    const msg = c.substring(9);
    if (/FAILED|error|conflict/i.test(msg)) return '<span class="error-line">'+esc(c)+'</span>';
    if (/engage/i.test(msg)) return '<span class="engage-line">'+esc(c)+'</span>';
    if (/sim frame/i.test(msg)) return '<span class="done-line">'+esc(c)+'</span>';
    return esc(c);
  }).join('\\n');

  // Live stream tail
  const ls = d.live_stream || {};
  const lsHeader = document.getElementById('live-stream-header');
  if (ls.file) {
    const typeMatch = ls.file.match(/^(frame|mod|engage)/);
    const stype = typeMatch ? typeMatch[1] : 'stream';
    const typeColors = {frame: '#3fb950', mod: '#d29922', engage: '#58a6ff'};
    const color = typeColors[stype] || '#c9d1d9';
    lsHeader.innerHTML = '<span style="color:'+color+'">\\u25CF</span> Live Agent Activity \\u2014 ' +
      '<span style="color:'+color+'">' + esc(ls.file) + '</span>' +
      ' <span style="color:#484f58;font-size:0.8em">(' + (ls.size_kb||0) + ' KB, ' + (ls.age_sec||0) + 's ago)</span>';
  } else {
    lsHeader.textContent = 'Live Agent Activity \\u2014 No active stream';
  }

  // Active stream details
  const sd = f.stream_details || [];
  if (sd.length > 0) {
    let sdHtml = '';
    for (const s of sd) {
      const typeColors = {agent: '#3fb950', mod: '#d29922', engage: '#58a6ff', unknown: '#484f58'};
      const c = typeColors[s.type] || '#484f58';
      const growDot = s.growing ? '<span style="color:#3fb950;animation:pulse 1s infinite">\\u25CF</span>' : '<span style="color:#484f58">\\u25CB</span>';
      sdHtml += '<span style="display:inline-block;margin-right:12px;font-size:0.75em">' +
        growDot + ' <span style="color:'+c+'">' + (s.type||'?') + '</span>' +
        (s.file ? ' <span style="color:#8b949e">' + s.file + '</span>' : '') +
        ' <span style="color:#484f58">' + (s.size_kb||0) + 'KB</span>' +
        '</span>';
    }
    document.getElementById('active-streams').innerHTML = sdHtml;
  } else {
    document.getElementById('active-streams').innerHTML = '<span style="color:#484f58;font-size:0.75em">No active streams</span>';
  }

  // Render live stream log lines
  const lsPre = document.getElementById('live-stream');
  if (ls.lines && ls.lines.length > 0) {
    lsPre.innerHTML = ls.lines.map(function(line) {
      if (/\\bcreated?\\b|\\bposted?\\b|\\bcomment/i.test(line)) return '<span style="color:#3fb950">'+esc(line)+'</span>';
      if (/error|failed|exception/i.test(line)) return '<span class="error-line">'+esc(line)+'</span>';
      if (/\\breaction|\\bvote|\\bupvote|\\bdownvote/i.test(line)) return '<span style="color:#d29922">'+esc(line)+'</span>';
      if (/\\bsoul|\\bmemory|\\bevolv/i.test(line)) return '<span style="color:#a371f7">'+esc(line)+'</span>';
      if (/discussion|thread|channel/i.test(line)) return '<span style="color:#58a6ff">'+esc(line)+'</span>';
      if (/\\$ |bash|gh api|git /i.test(line)) return '<span style="color:#8b949e">'+esc(line)+'</span>';
      return esc(line);
    }).join('\\n');
    lsPre.scrollTop = lsPre.scrollHeight;
  } else {
    lsPre.innerHTML = '<span style="color:#484f58">Waiting for stream activity...</span>';
  }
}

function healthRow(label, value, cls) {
  return '<div class="health-row"><span class="label">'+label+'</span><span class="value '+(cls||'')+'">'+value+'</span></div>';
}

function card(val, lbl, cls) {
  return '<div class="card'+(cls?' '+cls:'')+'"><div class="val">'+val+'</div><div class="lbl">'+lbl+'</div></div>';
}

async function poll() {
  try {
    const r = await fetch('/api/data');
    const d = await r.json();
    update(d);
  } catch(e) {
    document.getElementById('subtitle').textContent = 'Connection error: ' + e.message;
  }
  setTimeout(poll, POLL_MS);
}
poll();
</script>
</body>
</html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    """HTTP handler for live dashboard."""

    def do_GET(self) -> None:
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(DASHBOARD_HTML.encode())
        elif self.path == "/api/data":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            data = get_api_data()
            self.wfile.write(json.dumps(data).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args) -> None:
        """Suppress request logging."""
        pass


def main() -> None:
    """Start the dashboard server."""
    server = HTTPServer(("127.0.0.1", PORT), DashboardHandler)
    print(f"  Live dashboard running at http://localhost:{PORT}")
    print(f"  Auto-refreshes every 5 seconds")
    print(f"  Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
        server.server_close()


if __name__ == "__main__":
    main()
