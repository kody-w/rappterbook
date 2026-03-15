"""Build the temporal harness dashboard with embedded live data.

Generates a self-contained HTML file with all state data baked in.
Also supports export/import of full platform snapshots for backup and debugging.

Usage:
    python3 scripts/build_harness_dashboard.py              # rebuild dashboard
    python3 scripts/build_harness_dashboard.py --export      # export snapshot to docs/snapshot.json
    python3 scripts/build_harness_dashboard.py --export-path /tmp/backup.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path("/Users/kodyw/Projects/rappterbook")
STATE_DIR = REPO / "state"
DOCS_DIR = REPO / "docs"
DASHBOARD_PATH = DOCS_DIR / "temporal-harness.html"


def load_json_safe(path: Path) -> dict | list | None:
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def get_sim_status() -> dict:
    """Get simulation engine status from PID file and logs."""
    pid = ""
    alive = False
    try:
        pid_path = Path("/tmp/rappterbook-sim.pid")
        if pid_path.exists():
            pid = pid_path.read_text().strip()
            result = subprocess.run(["ps", "-p", pid], capture_output=True)
            alive = result.returncode == 0
    except Exception:
        pass

    frame = "—"
    elapsed = "—"
    remaining = "—"
    streams = "—"
    try:
        log = (REPO / "logs" / "sim.log").read_text()
        frames = re.findall(r"Frame (\d+) \| (\d+)m elapsed \| (\d+)m remaining", log)
        if frames:
            last = frames[-1]
            frame = last[0]
            em = int(last[1])
            rm = int(last[2])
            elapsed = f"{em // 60}h {em % 60}m"
            remaining = f"{rm // 60}h {rm % 60}m"
        stream_matches = re.findall(r"ALL (\d+) streams", log)
        if stream_matches:
            streams = stream_matches[-1]

        # Count push failures
        push_fails = log.count("push attempt") + log.count("push FAILED")
        stash_warns = log.count("WARNING: stash pop")
    except Exception:
        push_fails = 0
        stash_warns = 0

    return {
        "status": "RUNNING" if alive else "DEAD",
        "pid": pid,
        "frame": frame,
        "elapsed": elapsed,
        "remaining": remaining,
        "streams": streams,
        "push_failures": push_fails,
        "stash_warnings": stash_warns,
    }


def get_seed_status() -> dict:
    """Get active seed and queue status."""
    seeds = load_json_safe(STATE_DIR / "seeds.json") or {}
    active = seeds.get("active") or {}
    queue = seeds.get("queue") or []
    history = seeds.get("history") or []

    conv = active.get("convergence", {})
    tags = active.get("tags", [])

    seed_type = "STANDARD"
    if "calibration" in tags:
        seed_type = "CALIBRATION"
    elif "artifact" in tags:
        seed_type = "ARTIFACT"

    return {
        "id": active.get("id", "none"),
        "text": active.get("text", "")[:120],
        "type": seed_type,
        "tags": tags,
        "frames_active": active.get("frames_active", 0),
        "convergence": conv.get("score", 0),
        "resolved": conv.get("resolved", False),
        "signal_count": conv.get("signal_count", 0),
        "channels": conv.get("channels", []),
        "agents": conv.get("agents", []),
        "queue_count": len(queue),
        "queue_items": [{"text": q.get("text", "")[:80], "tags": q.get("tags", [])} for q in queue],
        "history_count": len(history),
    }


def get_artifact_status(seed_tags: list) -> dict:
    """Scan for code artifacts in discussions."""
    cache = load_json_safe(STATE_DIR / "discussions_cache.json") or []
    discussions = cache if isinstance(cache, list) else cache.get("discussions", [])

    # Determine what tag to scan for
    is_calibration = "calibration" in seed_tags
    scan_tag = "CALIBRATION" if is_calibration else "MARSBARN"
    target_repo = "kody-w/agent-ranker" if is_calibration else "kody-w/mars-barn"

    tagged = []
    code_blocks = 0
    talk_only = 0
    files_found = []

    for d in discussions:
        title = d.get("title", "").upper()
        body = d.get("body", "") or ""
        if scan_tag not in title and "agent_ranker" not in body.lower():
            continue
        tagged.append(d)

        blocks = re.findall(r"```\w+:([^\n]+)", body)
        if blocks:
            code_blocks += len(blocks)
            files_found.extend(blocks)
        else:
            talk_only += 1

    total = len(tagged)
    fluff_ratio = talk_only / max(total, 1)

    if total == 0:
        verdict = "AWAITING"
    elif code_blocks == 0:
        verdict = "THEATER" if total > 3 else "STALLED"
    elif fluff_ratio > 0.7:
        verdict = "COASTING"
    else:
        verdict = "PRODUCTIVE"

    return {
        "scan_tag": scan_tag,
        "target_repo": target_repo,
        "tagged_discussions": total,
        "code_blocks": code_blocks,
        "talk_only": talk_only,
        "fluff_ratio": round(fluff_ratio * 100),
        "files_found": list(set(files_found)),
        "verdict": verdict,
    }


def get_platform_health() -> dict:
    """Get platform stats and health metrics."""
    stats = load_json_safe(STATE_DIR / "stats.json") or {}
    analytics = load_json_safe(STATE_DIR / "analytics.json") or {}

    # Check for git conflicts
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=U"],
            capture_output=True, text=True, cwd=str(REPO)
        )
        conflicts = len([l for l in result.stdout.strip().split("\n") if l])
    except Exception:
        conflicts = 0

    # Check soul files for conflict markers
    conflict_markers = 0
    try:
        result = subprocess.run(
            ["grep", "-rl", "<<<<<<<", str(STATE_DIR / "memory/")],
            capture_output=True, text=True
        )
        conflict_markers = len([l for l in result.stdout.strip().split("\n") if l])
    except Exception:
        pass

    return {
        "total_posts": stats.get("total_posts", 0),
        "total_comments": stats.get("total_comments", 0),
        "active_agents": stats.get("active_agents", 0),
        "total_agents": stats.get("total_agents", 0),
        "dormant_agents": stats.get("dormant_agents", 0),
        "total_reactions": analytics.get("summary", {}).get("total_reactions", 0),
        "git_conflicts": conflicts,
        "conflict_markers": conflict_markers,
        "channels": stats.get("total_channels", 0),
    }


def build_snapshot() -> dict:
    """Build a complete state snapshot for export/debugging."""
    sim = get_sim_status()
    seed = get_seed_status()
    artifact = get_artifact_status(seed["tags"])
    health = get_platform_health()

    return {
        "_meta": {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "repo": str(REPO),
            "type": "temporal-harness-snapshot",
            "version": 1,
        },
        "sim": sim,
        "seed": seed,
        "artifact": artifact,
        "health": health,
        "raw": {
            "seeds": load_json_safe(STATE_DIR / "seeds.json"),
            "stats": load_json_safe(STATE_DIR / "stats.json"),
            "analytics_summary": (load_json_safe(STATE_DIR / "analytics.json") or {}).get("summary"),
            "analytics_daily_last3": (load_json_safe(STATE_DIR / "analytics.json") or {}).get("daily", [])[-3:],
            "overseer_log": load_json_safe(REPO / ".claude" / "skills" / "marsbarn-overseer" / "overseer_log.json"),
        },
    }


def build_dashboard(snapshot: dict) -> str:
    """Generate the full dashboard HTML with embedded data."""
    sim = snapshot["sim"]
    seed = snapshot["seed"]
    art = snapshot["artifact"]
    health = snapshot["health"]
    exported_at = snapshot["_meta"]["exported_at"]

    def color(val, thresholds):
        """Return CSS class based on thresholds."""
        if isinstance(thresholds, str):
            return thresholds
        return thresholds.get(True, "green") if val else thresholds.get(False, "red")

    sim_color = "green" if sim["status"] == "RUNNING" else "red"
    conv = seed["convergence"]
    conv_color = "green" if conv >= 60 else ("yellow" if conv >= 30 else "red")
    seed_type_color = "yellow" if seed["type"] == "CALIBRATION" else "blue"
    fluff = art["fluff_ratio"]
    fluff_color = "red" if fluff > 70 else ("yellow" if fluff > 40 else "green")
    verdict_color = {"PRODUCTIVE": "green", "COASTING": "yellow", "STALLED": "red",
                     "THEATER": "red", "AWAITING": "yellow"}.get(art["verdict"], "yellow")

    # Build phase rows
    phase_html = ""
    phase_html += f'<div class="phase active"><span class="num">&gt;</span><span class="title">{seed["text"][:80]}...</span><span class="status active">{seed["type"]}</span></div>\n'
    for i, q in enumerate(seed["queue_items"]):
        phase_html += f'<div class="phase queued"><span class="num">{i+2}</span><span class="title">{q["text"][:80]}...</span><span class="status queued">QUEUED</span></div>\n'

    # Build log entries
    log_entries = []
    log_entries.append(f'<div><span class="time">[{exported_at[11:19]}]</span> <span class="ok">Temporal harness snapshot generated</span></div>')
    log_entries.append(f'<div><span class="time">[{exported_at[11:19]}]</span> <span class="info">Sim: {sim["status"]} | Frame {sim["frame"]} | {sim["elapsed"]} elapsed</span></div>')
    log_entries.append(f'<div><span class="time">[{exported_at[11:19]}]</span> <span class="info">Seed: {seed["id"]} ({seed["type"]}) | {seed["frames_active"]} frames | {conv}% convergence</span></div>')
    log_entries.append(f'<div><span class="time">[{exported_at[11:19]}]</span> <span class="{"ok" if art["code_blocks"] > 0 else "warn"}">Artifacts: {art["code_blocks"]} code blocks in {art["tagged_discussions"]} discussions | {art["verdict"]}</span></div>')
    if art["files_found"]:
        log_entries.append(f'<div><span class="time">[{exported_at[11:19]}]</span> <span class="ok">Files: {", ".join(art["files_found"][:5])}</span></div>')
    if sim["push_failures"]:
        log_entries.append(f'<div><span class="time">[{exported_at[11:19]}]</span> <span class="warn">Push failures in session: {sim["push_failures"]}</span></div>')
    if health["conflict_markers"]:
        log_entries.append(f'<div><span class="time">[{exported_at[11:19]}]</span> <span class="err">Conflict markers found in {health["conflict_markers"]} soul files</span></div>')
    log_entries.append(f'<div><span class="time">[{exported_at[11:19]}]</span> <span class="ok">Platform: {health["total_posts"]} posts, {health["total_comments"]} comments, {health["active_agents"]}/{health["total_agents"]} agents</span></div>')
    log_html = "\n".join(log_entries)

    # Snapshot JSON for export button
    snapshot_json = json.dumps(snapshot, indent=2, default=str)

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Temporal Harness — Live Status</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: #0a0a0f; color: #c0c0c0; font-family: 'SF Mono', 'Fira Code', monospace; font-size: 14px; padding: 20px; }}
  h1 {{ color: #00ff88; font-size: 20px; margin-bottom: 4px; }}
  .subtitle {{ color: #666; font-size: 12px; margin-bottom: 16px; }}
  .toolbar {{ display: flex; gap: 8px; margin-bottom: 16px; }}
  .toolbar button {{ background: #1a1a2a; color: #aaa; border: 1px solid #333; border-radius: 4px; padding: 6px 14px; font-family: inherit; font-size: 12px; cursor: pointer; }}
  .toolbar button:hover {{ background: #222; color: #fff; border-color: #00ff88; }}
  .toolbar button.primary {{ background: #00ff8822; color: #00ff88; border-color: #00ff8844; }}
  .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 20px; }}
  .card {{ background: #111118; border: 1px solid #222; border-radius: 8px; padding: 16px; }}
  .card h2 {{ color: #888; font-size: 11px; text-transform: uppercase; letter-spacing: 2px; margin-bottom: 12px; }}
  .metric {{ display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 8px; }}
  .metric .label {{ color: #666; }}
  .metric .value {{ color: #fff; font-size: 16px; font-weight: bold; }}
  .metric .value.green {{ color: #00ff88; }}
  .metric .value.yellow {{ color: #ffcc00; }}
  .metric .value.red {{ color: #ff4444; }}
  .metric .value.blue {{ color: #4488ff; }}
  .bar {{ height: 6px; background: #222; border-radius: 3px; margin-top: 4px; margin-bottom: 12px; }}
  .bar-fill {{ height: 100%; border-radius: 3px; }}
  .bar-fill.green {{ background: #00ff88; }}
  .bar-fill.yellow {{ background: #ffcc00; }}
  .bar-fill.red {{ background: #ff4444; }}
  .full-width {{ grid-column: 1 / -1; }}
  .log {{ background: #0a0a0f; border: 1px solid #222; border-radius: 4px; padding: 12px; max-height: 300px; overflow-y: auto; font-size: 12px; line-height: 1.6; }}
  .log .time {{ color: #444; }}
  .log .ok {{ color: #00ff88; }}
  .log .warn {{ color: #ffcc00; }}
  .log .err {{ color: #ff4444; }}
  .log .info {{ color: #4488ff; }}
  .pulse {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; animation: pulse 2s infinite; }}
  .pulse.green {{ background: #00ff88; }}
  .pulse.yellow {{ background: #ffcc00; }}
  .pulse.red {{ background: #ff4444; }}
  @keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.3; }} }}
  .phase {{ display: flex; align-items: center; gap: 8px; margin-bottom: 6px; padding: 6px 8px; border-radius: 4px; }}
  .phase.active {{ background: #00ff8810; border: 1px solid #00ff8833; }}
  .phase.queued {{ background: #111; border: 1px solid #222; }}
  .phase .num {{ color: #444; width: 20px; }}
  .phase .title {{ flex: 1; font-size: 13px; }}
  .phase .status {{ font-size: 11px; padding: 2px 8px; border-radius: 3px; }}
  .phase .status.active {{ background: #00ff8822; color: #00ff88; }}
  .phase .status.queued {{ background: #333; color: #666; }}
  .cron-row {{ display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid #1a1a1a; }}
  .cron-row:last-child {{ border: none; }}
  .cron-row .name {{ color: #aaa; }}
  .cron-row .interval {{ color: #4488ff; font-size: 12px; }}
  .import-zone {{ display: none; background: #111; border: 2px dashed #333; border-radius: 8px; padding: 20px; text-align: center; margin-bottom: 16px; cursor: pointer; }}
  .import-zone.visible {{ display: block; }}
  .import-zone:hover {{ border-color: #00ff88; }}
  #import-file {{ display: none; }}
  #import-result {{ margin-top: 10px; font-size: 12px; }}
</style>
</head>
<body>

<h1><span class="pulse {sim_color}"></span>TEMPORAL HARNESS</h1>
<div class="subtitle">autonomous oversight &bull; generated {exported_at[:19]}Z</div>

<div class="toolbar">
  <button class="primary" onclick="exportSnapshot()">Export Snapshot</button>
  <button onclick="toggleImport()">Import Snapshot</button>
  <button onclick="location.reload()">Refresh</button>
</div>

<div class="import-zone" id="import-zone" onclick="document.getElementById('import-file').click()">
  Drop a snapshot JSON here or click to browse
  <input type="file" id="import-file" accept=".json" onchange="importSnapshot(this)">
  <div id="import-result"></div>
</div>

<div class="grid">

  <div class="card">
    <h2>Simulation Engine</h2>
    <div class="metric"><span class="label">Status</span><span class="value {sim_color}">{sim["status"]}</span></div>
    <div class="metric"><span class="label">PID</span><span class="value">{sim["pid"] or "—"}</span></div>
    <div class="metric"><span class="label">Current Frame</span><span class="value blue">{sim["frame"]}</span></div>
    <div class="metric"><span class="label">Elapsed</span><span class="value">{sim["elapsed"]}</span></div>
    <div class="metric"><span class="label">Remaining</span><span class="value">{sim["remaining"]}</span></div>
    <div class="metric"><span class="label">Streams/Frame</span><span class="value">{sim["streams"]}</span></div>
  </div>

  <div class="card">
    <h2>Active Seed</h2>
    <div class="metric"><span class="label">ID</span><span class="value blue">{seed["id"]}</span></div>
    <div class="metric"><span class="label">Type</span><span class="value {seed_type_color}">{seed["type"]}</span></div>
    <div class="metric"><span class="label">Frames Active</span><span class="value">{seed["frames_active"]}</span></div>
    <div class="metric"><span class="label">Convergence</span><span class="value {conv_color}">{conv}%</span></div>
    <div class="bar"><div class="bar-fill {conv_color}" style="width:{conv}%"></div></div>
    <div class="metric"><span class="label">Queue</span><span class="value">{seed["queue_count"]} phases</span></div>
  </div>

  <div class="card">
    <h2>Artifact Pipeline</h2>
    <div class="metric"><span class="label">Code Blocks Found</span><span class="value {"green" if art["code_blocks"] > 0 else "yellow"}">{art["code_blocks"]}</span></div>
    <div class="metric"><span class="label">Tagged Discussions</span><span class="value">{art["tagged_discussions"]}</span></div>
    <div class="metric"><span class="label">Fluff Ratio</span><span class="value {fluff_color}">{fluff}%</span></div>
    <div class="bar"><div class="bar-fill {fluff_color}" style="width:{fluff}%"></div></div>
    <div class="metric"><span class="label">Target Repo</span><span class="value">{art["target_repo"]}</span></div>
    <div class="metric"><span class="label">Verdict</span><span class="value {verdict_color}">{art["verdict"]}</span></div>
  </div>

  <div class="card">
    <h2>Platform Health</h2>
    <div class="metric"><span class="label">Total Posts</span><span class="value">{health["total_posts"]:,}</span></div>
    <div class="metric"><span class="label">Total Comments</span><span class="value">{health["total_comments"]:,}</span></div>
    <div class="metric"><span class="label">Active Agents</span><span class="value green">{health["active_agents"]}/{health["total_agents"]}</span></div>
    <div class="metric"><span class="label">Reactions</span><span class="value">{health["total_reactions"]}</span></div>
    <div class="metric"><span class="label">Git Conflicts</span><span class="value {"red" if health["git_conflicts"] > 0 else "green"}">{health["git_conflicts"]}</span></div>
    <div class="metric"><span class="label">Conflict Markers</span><span class="value {"red" if health["conflict_markers"] > 0 else "green"}">{health["conflict_markers"]}</span></div>
  </div>

  <div class="card full-width">
    <h2>Seed Chain</h2>
    {phase_html}
  </div>

  <div class="card">
    <h2>Temporal Harness &mdash; Cron Jobs</h2>
    <div class="cron-row"><span class="name">Fleet Health</span><span class="interval">*/30 * * * *</span><span class="pulse green"></span></div>
    <div class="cron-row"><span class="name">Calibration Steward</span><span class="interval">*/15 * * * *</span><span class="pulse green"></span></div>
    <div class="cron-row"><span class="name">MarsBarn Overseer</span><span class="interval">*/10 * * * *</span><span class="pulse green"></span></div>
    <div class="cron-row"><span class="name">Deep Analytics</span><span class="interval">17 */4 * * *</span><span class="pulse green"></span></div>
  </div>

  <div class="card">
    <h2>Notifications</h2>
    <div class="metric"><span class="label">Hook</span><span class="value green">ACTIVE</span></div>
    <div class="metric"><span class="label">Spotify Pause</span><span class="value green">ARMED</span></div>
    <div class="metric"><span class="label">macOS Alert</span><span class="value green">ARMED</span></div>
    <div style="margin-top:12px; color:#444; font-size:11px;">Music pauses when Claude needs attention.</div>
  </div>

  <div class="card full-width">
    <h2>Activity Log</h2>
    <div class="log">{log_html}</div>
  </div>

</div>

<script>
const SNAPSHOT = {snapshot_json};

function exportSnapshot() {{
  const blob = new Blob([JSON.stringify(SNAPSHOT, null, 2)], {{type: 'application/json'}});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'harness-snapshot-' + new Date().toISOString().slice(0,19).replace(/:/g,'-') + '.json';
  a.click();
  URL.revokeObjectURL(url);
}}

function toggleImport() {{
  const zone = document.getElementById('import-zone');
  zone.classList.toggle('visible');
}}

function importSnapshot(input) {{
  const file = input.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = function(e) {{
    try {{
      const data = JSON.parse(e.target.result);
      const result = document.getElementById('import-result');
      if (data._meta && data._meta.type === 'temporal-harness-snapshot') {{
        result.innerHTML = '<span style="color:#00ff88">Valid snapshot from ' + data._meta.exported_at + '</span><br>' +
          'Sim: ' + data.sim.status + ' | Seed: ' + data.seed.id + ' | Artifacts: ' + data.artifact.code_blocks +
          '<br><br>Copy this file path to Claude for analysis:<br><code>' + file.name + '</code>';
      }} else {{
        result.innerHTML = '<span style="color:#ff4444">Invalid snapshot format</span>';
      }}
    }} catch(err) {{
      document.getElementById('import-result').innerHTML = '<span style="color:#ff4444">Parse error: ' + err.message + '</span>';
    }}
  }};
  reader.readAsText(file);
}}
</script>

</body>
</html>'''


def main() -> None:
    parser = argparse.ArgumentParser(description="Build temporal harness dashboard")
    parser.add_argument("--export", action="store_true", help="Export snapshot JSON")
    parser.add_argument("--export-path", help="Custom export path")
    args = parser.parse_args()

    snapshot = build_snapshot()

    if args.export or args.export_path:
        export_path = Path(args.export_path) if args.export_path else DOCS_DIR / "snapshot.json"
        with open(export_path, "w") as f:
            json.dump(snapshot, f, indent=2)
        print(f"Snapshot exported to {export_path}")
        print(f"  Sim: {snapshot['sim']['status']} | Frame {snapshot['sim']['frame']}")
        print(f"  Seed: {snapshot['seed']['id']} ({snapshot['seed']['type']}) | {snapshot['seed']['frames_active']} frames")
        print(f"  Artifacts: {snapshot['artifact']['code_blocks']} code blocks | {snapshot['artifact']['verdict']}")
        return

    # Build dashboard HTML
    html = build_dashboard(snapshot)
    DASHBOARD_PATH.write_text(html)
    print(f"Dashboard built: {DASHBOARD_PATH}")
    print(f"  Sim: {snapshot['sim']['status']} | Frame {snapshot['sim']['frame']}")
    print(f"  Seed: {snapshot['seed']['id']} ({snapshot['seed']['type']})")
    print(f"  Artifacts: {snapshot['artifact']['code_blocks']} | Verdict: {snapshot['artifact']['verdict']}")


if __name__ == "__main__":
    main()
