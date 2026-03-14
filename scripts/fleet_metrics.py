#!/usr/bin/env python3
"""fleet_metrics.py — Real-time metrics for the Rappterbook copilot fleet.

Usage:
    python3 scripts/fleet_metrics.py              # Full report
    python3 scripts/fleet_metrics.py --live        # Auto-refresh every 30s
    python3 scripts/fleet_metrics.py --json        # Machine-readable output
    python3 scripts/fleet_metrics.py --section throughput  # Single section
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOG_DIR = REPO / "logs"
STATE_DIR = REPO / "state"
SIM_LOG = LOG_DIR / "sim.log"
PID_FILE = Path("/tmp/rappterbook-sim.pid")

# ── Colors ──────────────────────────────────────────────────────────────────
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
MAGENTA = "\033[95m"
RESET = "\033[0m"
BLUE = "\033[94m"


def color(text: str, c: str) -> str:
    return f"{c}{text}{RESET}"


# ── Helpers ─────────────────────────────────────────────────────────────────
def run(cmd: str) -> str:
    """Run shell command, return stdout."""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
        return r.stdout.strip()
    except Exception:
        return ""


def parse_log_timestamp(filename: str) -> datetime | None:
    """Extract timestamp from log filename like frame1_s1_20260314_210055.log."""
    m = re.search(r"(\d{8})_(\d{6})", filename)
    if m:
        return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
    return None


def human_duration(minutes: float) -> str:
    if minutes < 60:
        return f"{minutes:.0f}m"
    h = int(minutes // 60)
    m = int(minutes % 60)
    if h < 24:
        return f"{h}h {m}m"
    d = h // 24
    h = h % 24
    return f"{d}d {h}h {m}m"


def human_size(bytes_val: float) -> str:
    if bytes_val < 1024:
        return f"{bytes_val:.0f}B"
    if bytes_val < 1024 * 1024:
        return f"{bytes_val / 1024:.1f}KB"
    if bytes_val < 1024 * 1024 * 1024:
        return f"{bytes_val / (1024 * 1024):.1f}MB"
    return f"{bytes_val / (1024 * 1024 * 1024):.2f}GB"


def human_number(n: float) -> str:
    if n < 1000:
        return f"{n:.0f}"
    if n < 1_000_000:
        return f"{n / 1000:.1f}K"
    if n < 1_000_000_000:
        return f"{n / 1_000_000:.1f}M"
    return f"{n / 1_000_000_000:.2f}B"


# ── Data Collection ─────────────────────────────────────────────────────────
def get_fleet_status() -> dict:
    """Check if sim is running and get PID info."""
    pid = PID_FILE.read_text().strip() if PID_FILE.exists() else ""
    running = False
    uptime = ""
    if pid:
        check = run(f"ps -p {pid} -o etime= 2>/dev/null")
        if check:
            running = True
            uptime = check.strip()
    active_streams = int(run("pgrep -f 'copilot.*autopilot' 2>/dev/null | wc -l") or "0")
    return {"pid": pid, "running": running, "uptime": uptime, "active_streams": active_streams}


def get_log_inventory() -> dict:
    """Count and categorize all log files."""
    frame_logs = sorted(LOG_DIR.glob("frame*_s*_*.log"))
    mod_logs = sorted(LOG_DIR.glob("mod*_s*_*.log"))
    engage_logs = sorted(LOG_DIR.glob("engage*_s*_*.log"))

    def stats_for(logs: list[Path]) -> dict:
        if not logs:
            return {"count": 0, "total_bytes": 0, "total_lines": 0, "avg_kb": 0}
        total_bytes = sum(f.stat().st_size for f in logs)
        total_lines = 0
        for f in logs[-50:]:  # sample last 50 for line count
            try:
                total_lines += sum(1 for _ in open(f))
            except Exception:
                pass
        if len(logs) > 50:
            total_lines = int(total_lines * len(logs) / 50)
        return {
            "count": len(logs),
            "total_bytes": total_bytes,
            "total_lines": total_lines,
            "avg_kb": total_bytes / len(logs) / 1024 if logs else 0,
        }

    total_bytes = sum(f.stat().st_size for f in LOG_DIR.iterdir() if f.is_file())
    return {
        "frame": stats_for(frame_logs),
        "mod": stats_for(mod_logs),
        "engage": stats_for(engage_logs),
        "total_files": len(frame_logs) + len(mod_logs) + len(engage_logs),
        "total_bytes": total_bytes,
    }


def get_frame_history() -> list[dict]:
    """Parse sim.log for frame timing data."""
    frames = []
    if not SIM_LOG.exists():
        return frames
    current_frame = {}
    for line in SIM_LOG.read_text().splitlines():
        # Frame start
        m = re.search(r"\[(\d{2}:\d{2}:\d{2})\].*Frame (\d+) \|.*?(\d+)m elapsed.*?(\d+)m remaining", line)
        if m:
            if current_frame:
                frames.append(current_frame)
            current_frame = {
                "num": int(m.group(2)),
                "start_time": m.group(1),
                "elapsed_min": int(m.group(3)),
                "remaining_min": int(m.group(4)),
            }
        # All streams done
        m = re.search(r"all (\d+) streams done \((\d+)m\)", line)
        if m and current_frame:
            current_frame["streams"] = int(m.group(1))
            current_frame["duration_min"] = int(m.group(2))
        # Frame complete
        m = re.search(r"Frame (\d+) complete \((\d+)m\).*?Total streams run: (\d+)", line)
        if m:
            current_frame["complete"] = True
            current_frame["total_min"] = int(m.group(2))
            current_frame["cumulative_streams"] = int(m.group(3))
        # Errors
        m = re.search(r"(\d+)/(\d+) streams had errors", line)
        if m and current_frame:
            current_frame["errors"] = int(m.group(1))
    if current_frame:
        frames.append(current_frame)
    return frames


def count_actions_in_logs(since_hours: float = 24) -> dict:
    """Scan stream logs for GitHub API actions."""
    cutoff = time.time() - since_hours * 3600
    patterns = {
        "posts_created": re.compile(r"createDiscussion", re.IGNORECASE),
        "comments": re.compile(r"addDiscussionComment", re.IGNORECASE),
        "reactions": re.compile(r"addReaction", re.IGNORECASE),
        "soul_updates": re.compile(r"soul.*(?:updated|wrote|saved)", re.IGNORECASE),
        "timeouts": re.compile(r"\[TIMEOUT"),
    }
    counts: dict[str, int] = {k: 0 for k in patterns}
    total_scanned = 0
    for log_file in LOG_DIR.glob("*_s*_*.log"):
        try:
            if log_file.stat().st_mtime < cutoff:
                continue
        except Exception:
            continue
        total_scanned += 1
        try:
            text = log_file.read_text(errors="replace")
            for key, pat in patterns.items():
                counts[key] += len(pat.findall(text))
        except Exception:
            pass
    counts["logs_scanned"] = total_scanned
    return counts


def get_throughput_by_hour() -> list[dict]:
    """Group log files by hour for throughput chart."""
    hourly: dict[str, dict] = defaultdict(lambda: {"streams": 0, "bytes": 0})
    for log_file in LOG_DIR.glob("*_s*_*.log"):
        ts = parse_log_timestamp(log_file.name)
        if not ts:
            continue
        hour_key = ts.strftime("%m/%d %H:00")
        hourly[hour_key]["streams"] += 1
        try:
            hourly[hour_key]["bytes"] += log_file.stat().st_size
        except Exception:
            pass
    return [{"hour": k, **v} for k, v in sorted(hourly.items())[-48:]]


def get_git_metrics() -> dict:
    """Git commit cadence and state."""
    commits_24h = int(run("cd /Users/kodyw/Projects/rappterbook && git --no-pager log --since='24 hours ago' --oneline 2>/dev/null | wc -l") or "0")
    commits_1h = int(run("cd /Users/kodyw/Projects/rappterbook && git --no-pager log --since='1 hour ago' --oneline 2>/dev/null | wc -l") or "0")
    ahead = int(run("cd /Users/kodyw/Projects/rappterbook && git rev-list origin/main..HEAD --count 2>/dev/null") or "0")
    behind = int(run("cd /Users/kodyw/Projects/rappterbook && git rev-list HEAD..origin/main --count 2>/dev/null") or "0")
    dirty = int(run("cd /Users/kodyw/Projects/rappterbook && git status --porcelain 2>/dev/null | wc -l") or "0")
    return {
        "commits_24h": commits_24h,
        "commits_1h": commits_1h,
        "ahead": ahead,
        "behind": behind,
        "dirty_files": dirty,
    }


def get_platform_stats() -> dict:
    """Read platform state files for content metrics."""
    stats = {}
    try:
        with open(STATE_DIR / "stats.json") as f:
            d = json.load(f)
        stats["total_posts"] = d.get("total_posts", d.get("total_discussions", 0))
        stats["total_agents"] = d.get("total_agents", 0)
        stats["total_comments"] = d.get("total_comments", 0)
    except Exception:
        stats["total_posts"] = stats["total_agents"] = stats["total_comments"] = 0

    try:
        soul_dir = STATE_DIR / "memory"
        stats["soul_files"] = len(list(soul_dir.glob("*.md"))) if soul_dir.exists() else 0
        # Count recently modified souls
        cutoff = time.time() - 3600
        stats["souls_updated_1h"] = sum(
            1 for f in soul_dir.glob("*.md") if f.stat().st_mtime > cutoff
        ) if soul_dir.exists() else 0
    except Exception:
        stats["soul_files"] = stats["souls_updated_1h"] = 0

    try:
        with open(STATE_DIR / "discussions_cache.json") as f:
            d = json.load(f)
        stats["cached_discussions"] = len(d.get("discussions", []))
    except Exception:
        stats["cached_discussions"] = 0

    try:
        with open(STATE_DIR / "channels.json") as f:
            d = json.load(f)
        stats["channels"] = len([k for k in d if not k.startswith("_")])
    except Exception:
        stats["channels"] = 0

    return stats


def get_resource_usage() -> dict:
    """System resource usage."""
    mem_pct = float(run("ps aux | grep copilot | grep -v grep | awk '{sum+=$4} END {printf \"%.1f\", sum}'") or "0")
    cpu_pct = float(run("ps aux | grep copilot | grep -v grep | awk '{sum+=$3} END {printf \"%.1f\", sum}'") or "0")
    return {"mem_pct": mem_pct, "cpu_pct": cpu_pct}


def get_token_usage() -> dict:
    """Read token usage from dashboard API or usage files."""
    try:
        r = subprocess.run(
            ["curl", "-s", "http://localhost:8888/api/data"],
            capture_output=True, text=True, timeout=5,
        )
        data = json.loads(r.stdout)
        usage = data.get("usage", {}).get("total", {})
        return {
            "total_calls": usage.get("count", 0),
            "input_tokens": usage.get("in_tokens", 0),
            "output_tokens": usage.get("out_tokens", 0),
            "cached_tokens": usage.get("cached", 0),
            "api_seconds": usage.get("api_sec", 0),
        }
    except Exception:
        return {"total_calls": 0, "input_tokens": 0, "output_tokens": 0, "cached_tokens": 0, "api_seconds": 0}


# ── Display ─────────────────────────────────────────────────────────────────
def bar_chart(value: int, max_val: int, width: int = 30) -> str:
    """Render a horizontal bar."""
    if max_val == 0:
        return " " * width
    filled = int(value / max_val * width)
    return color("█" * filled, CYAN) + color("░" * (width - filled), DIM)


def print_section(title: str) -> None:
    print(f"\n{color('━' * 60, DIM)}")
    print(f"  {color(title, BOLD + CYAN)}")
    print(color("━" * 60, DIM))


def print_kv(key: str, value: str, indent: int = 4) -> None:
    print(f"{' ' * indent}{color(key + ':', DIM):35s} {value}")


def render_report(as_json: bool = False, section: str | None = None) -> dict | None:
    """Collect all metrics and render the report."""
    fleet = get_fleet_status()
    logs = get_log_inventory()
    frames = get_frame_history()
    actions = count_actions_in_logs(24)
    hourly = get_throughput_by_hour()
    git = get_git_metrics()
    platform = get_platform_stats()
    resources = get_resource_usage()
    tokens = get_token_usage()

    all_data = {
        "timestamp": datetime.now().isoformat(),
        "fleet": fleet,
        "logs": logs,
        "frames": frames,
        "actions": actions,
        "hourly_throughput": hourly,
        "git": git,
        "platform": platform,
        "resources": resources,
        "tokens": tokens,
    }

    if as_json:
        print(json.dumps(all_data, indent=2, default=str))
        return all_data

    # ── Header ──
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status = color("● RUNNING", GREEN + BOLD) if fleet["running"] else color("○ STOPPED", RED + BOLD)
    print(f"\n  {color('⚡ RAPPTERBOOK FLEET METRICS', BOLD + MAGENTA)}  {DIM}{now}{RESET}")
    print(f"  {status}  PID {fleet['pid']}  Uptime {fleet['uptime']}  {color(str(fleet['active_streams']), YELLOW + BOLD)} active streams")

    # ── Throughput ──
    if section is None or section == "throughput":
        print_section("📊 THROUGHPUT")
        total_streams = logs["frame"]["count"] + logs["mod"]["count"] + logs["engage"]["count"]
        print_kv("Total streams completed", f"{color(str(total_streams), BOLD)} ({logs['frame']['count']} frame + {logs['mod']['count']} mod + {logs['engage']['count']} engage)")

        completed_frames = [f for f in frames if f.get("complete")]
        if completed_frames:
            durations = [f["total_min"] for f in completed_frames]
            avg_frame = sum(durations) / len(durations)
            fastest = min(durations)
            slowest = max(durations)
            streams_per_hour = total_streams / max(1, sum(durations)) * 60
            print_kv("Completed frames", str(len(completed_frames)))
            print_kv("Avg frame time", f"{avg_frame:.0f}m  (fastest: {fastest}m / slowest: {slowest}m)")
            print_kv("Streams per hour", f"{color(f'{streams_per_hour:.1f}', BOLD + GREEN)}")
        else:
            # Estimate from log file dates
            if hourly:
                recent_hours = hourly[-6:]
                avg_streams_h = sum(h["streams"] for h in recent_hours) / max(1, len(recent_hours))
                print_kv("Streams per hour (est)", f"{color(f'{avg_streams_h:.0f}', BOLD + GREEN)}")

        print_kv("Log volume", f"{human_size(logs['total_bytes'])} across {logs['total_files']} files")
        print_kv("Avg stream log size", f"{logs['frame']['avg_kb']:.0f}KB (frame) / {logs['mod']['avg_kb']:.0f}KB (mod) / {logs['engage']['avg_kb']:.0f}KB (engage)")

    # ── Content Production ──
    if section is None or section == "content":
        print_section("📝 CONTENT PRODUCTION (last 24h)")
        print_kv("Posts created", color(str(actions["posts_created"]), BOLD + GREEN))
        print_kv("Comments posted", color(str(actions["comments"]), BOLD + GREEN))
        print_kv("Reactions cast", color(str(actions["reactions"]), BOLD + GREEN))
        print_kv("Soul file updates", color(str(actions["soul_updates"]), BOLD))
        print_kv("Stream timeouts", color(str(actions["timeouts"]), RED + BOLD) if actions["timeouts"] else color("0", GREEN))
        print_kv("Logs scanned", str(actions["logs_scanned"]))

    # ── Token Economics ──
    if section is None or section == "tokens":
        print_section("💰 TOKEN ECONOMICS")
        if tokens["total_calls"]:
            print_kv("API calls", color(human_number(tokens["total_calls"]), BOLD))
            print_kv("Input tokens", color(human_number(tokens["input_tokens"]), BOLD))
            print_kv("Output tokens", color(human_number(tokens["output_tokens"]), BOLD))
            print_kv("Cached tokens", f"{human_number(tokens['cached_tokens'])} ({tokens['cached_tokens'] / max(1, tokens['input_tokens']) * 100:.0f}% cache hit)")
            print_kv("API wall time", human_duration(tokens["api_seconds"] / 60))
            if tokens["input_tokens"]:
                cost_equiv = (tokens["input_tokens"] / 1_000_000 * 15 + tokens["output_tokens"] / 1_000_000 * 75)
                print_kv("Cost equivalent (pay-per-use)", color(f"${cost_equiv:,.0f}", BOLD + YELLOW))
                print_kv("You're paying", color("$0 (unlimited)", BOLD + GREEN))
                print_kv("Savings", color(f"${cost_equiv:,.0f} 🔥", BOLD + GREEN))
        else:
            print_kv("Token data", color("unavailable (dashboard API down?)", DIM))

    # ── Platform State ──
    if section is None or section == "platform":
        print_section("🌍 PLATFORM STATE")
        print_kv("Total discussions", color(str(platform["total_posts"]), BOLD))
        print_kv("Agents registered", str(platform["total_agents"]))
        print_kv("Channels", str(platform["channels"]))
        print_kv("Soul files", f"{platform['soul_files']} ({color(str(platform['souls_updated_1h']), YELLOW)} updated last hour)")
        print_kv("Discussions cached", str(platform["cached_discussions"]))

    # ── Git Health ──
    if section is None or section == "git":
        print_section("🔧 GIT HEALTH")
        print_kv("Commits (last 1h)", str(git["commits_1h"]))
        print_kv("Commits (last 24h)", str(git["commits_24h"]))
        sync_status = color("in sync", GREEN) if git["ahead"] == 0 and git["behind"] == 0 else color(f"+{git['ahead']}/-{git['behind']}", YELLOW)
        print_kv("Origin sync", sync_status)
        dirty_status = color("clean", GREEN) if git["dirty_files"] == 0 else color(f"{git['dirty_files']} dirty", RED)
        print_kv("Working tree", dirty_status)

    # ── Resource Usage ──
    if section is None or section == "resources":
        print_section("🖥️  RESOURCES")
        print_kv("RAM (copilot procs)", f"{resources['mem_pct']:.1f}%  {bar_chart(int(resources['mem_pct']), 100, 20)}")
        print_kv("CPU (copilot procs)", f"{resources['cpu_pct']:.1f}%  {bar_chart(int(resources['cpu_pct']), 800, 20)}")

    # ── Hourly Throughput Chart ──
    if (section is None or section == "hourly") and hourly:
        print_section("📈 HOURLY THROUGHPUT (last 48h)")
        max_streams = max(h["streams"] for h in hourly) if hourly else 1
        for entry in hourly[-24:]:
            label = entry["hour"]
            count = entry["streams"]
            size = human_size(entry["bytes"])
            bar = bar_chart(count, max_streams, 25)
            print(f"    {DIM}{label}{RESET}  {bar}  {count:3d} streams  {DIM}{size}{RESET}")

    # ── Active Frame ──
    if section is None or section == "active":
        if frames and not frames[-1].get("complete"):
            print_section("🔴 ACTIVE FRAME")
            af = frames[-1]
            print_kv("Frame number", str(af.get("num", "?")))
            if "streams" in af:
                print_kv("Streams", str(af["streams"]))
            if "remaining_min" in af:
                print_kv("Time remaining", human_duration(af["remaining_min"]))

    print(f"\n{DIM}  Run with --live for auto-refresh, --json for machine output{RESET}\n")
    return all_data


# ── Main ────────────────────────────────────────────────────────────────────
def main() -> None:
    args = sys.argv[1:]
    as_json = "--json" in args
    live = "--live" in args
    section = None
    for i, a in enumerate(args):
        if a == "--section" and i + 1 < len(args):
            section = args[i + 1]

    if live:
        interval = 30
        try:
            while True:
                os.system("clear")
                render_report(as_json=False, section=section)
                print(f"{DIM}  Auto-refreshing every {interval}s... Ctrl+C to stop{RESET}")
                time.sleep(interval)
        except KeyboardInterrupt:
            print("\nStopped.")
    else:
        render_report(as_json=as_json, section=section)


if __name__ == "__main__":
    main()
