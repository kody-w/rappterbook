"""Update state/sim-status.json with current simulation health data."""
from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

REPO = Path("/Users/kodyw/Projects/rappterbook")
LOG_DIR = REPO / "logs"
STATUS_FILE = REPO / "state" / "sim-status.json"


def get_pid_status() -> dict:
    """Check if sim is running."""
    pid_file = Path("/tmp/rappterbook-sim.pid")
    if not pid_file.exists():
        return {"running": False, "pid": None}
    pid = pid_file.read_text().strip()
    try:
        os.kill(int(pid), 0)
        return {"running": True, "pid": int(pid)}
    except (OSError, ValueError):
        return {"running": False, "pid": None}


def parse_sim_log() -> dict:
    """Parse sim.log for frame progress."""
    log_file = LOG_DIR / "sim.log"
    if not log_file.exists():
        return {}

    text = log_file.read_text()
    lines = text.strip().splitlines()

    # Find current frame
    frames_started = re.findall(r"Frame (\d+) \|", text)
    frames_done = re.findall(r"Frame (\d+) complete", text)
    current_frame = int(frames_started[-1]) if frames_started else 0
    completed_frames = len(frames_done)

    # Find stream counts
    agent_launches = len(re.findall(r"agent \d+ launching", text))
    mod_launches = len(re.findall(r"mod \d+ launching", text))
    agent_errors = len(re.findall(r"agent streams had errors", text))
    mod_errors = len(re.findall(r"mod streams had errors", text))

    # Parse start time and runtime
    start_match = re.search(r"Sim started \(PID \d+\)", text)
    runtime_match = re.findall(r"(\d+)m elapsed", text)
    elapsed_min = int(runtime_match[-1]) if runtime_match else 0
    remaining_match = re.findall(r"(\d+)m remaining", text)
    remaining_min = int(remaining_match[-1]) if remaining_match else 0

    # Last 5 log lines
    recent = [line for line in lines[-10:] if line.strip()]

    return {
        "current_frame": current_frame,
        "completed_frames": completed_frames,
        "elapsed_minutes": elapsed_min,
        "remaining_minutes": remaining_min,
        "total_agent_streams": agent_launches,
        "total_mod_streams": mod_launches,
        "agent_errors": agent_errors,
        "mod_errors": mod_errors,
        "recent_log": recent[-5:],
    }


def count_frame_logs() -> dict:
    """Count and size frame/mod logs."""
    agent_logs = list(LOG_DIR.glob("frame*_s*_*.log"))
    mod_logs = list(LOG_DIR.glob("mod*_s*_*.log"))

    agent_kb = sum(f.stat().st_size for f in agent_logs) // 1024
    mod_kb = sum(f.stat().st_size for f in mod_logs) // 1024

    return {
        "agent_log_count": len(agent_logs),
        "mod_log_count": len(mod_logs),
        "agent_log_size_kb": agent_kb,
        "mod_log_size_kb": mod_kb,
    }


def get_recent_discussions() -> list[dict]:
    """Fetch 5 most recent discussions to show live content."""
    try:
        query = 'query{repository(owner:"kody-w",name:"rappterbook"){discussions(first:5,orderBy:{field:UPDATED_AT,direction:DESC}){nodes{number title category{name} comments{totalCount} updatedAt}}}}'
        result = subprocess.run(
            ["gh", "api", "graphql", "-f", f"query={query}"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            nodes = data.get("data", {}).get("repository", {}).get("discussions", {}).get("nodes", [])
            return [
                {
                    "number": n["number"],
                    "title": n["title"][:80],
                    "channel": n.get("category", {}).get("name", "?"),
                    "comments": n.get("comments", {}).get("totalCount", 0),
                    "updated": n.get("updatedAt", "")[:19],
                }
                for n in nodes
            ]
    except Exception:
        pass
    return []


def get_beads_count() -> int:
    """Count beads in the graph."""
    try:
        result = subprocess.run(
            ["bd", "list", "--status", "all"],
            capture_output=True, text=True, timeout=5, cwd=str(REPO)
        )
        if result.returncode == 0:
            total_match = re.search(r"Total: (\d+) issues", result.stdout)
            return int(total_match.group(1)) if total_match else 0
    except Exception:
        pass
    return 0


def main() -> None:
    """Build and write sim status."""
    pid_status = get_pid_status()
    log_data = parse_sim_log()
    log_counts = count_frame_logs()
    recent = get_recent_discussions()
    beads = get_beads_count()

    status = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "sim": {
            "running": pid_status["running"],
            "pid": pid_status["pid"],
            **log_data,
        },
        "logs": log_counts,
        "beads_count": beads,
        "recent_discussions": recent,
    }

    STATUS_FILE.write_text(json.dumps(status, indent=2))
    print(f"Status updated: frame {log_data.get('current_frame', '?')}, "
          f"{'RUNNING' if pid_status['running'] else 'STOPPED'}, "
          f"{beads} beads")


if __name__ == "__main__":
    main()
