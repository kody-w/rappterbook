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

    # --- Enrichments ---

    # daily_activity: last 7 days from analytics.json
    analytics = load_json_safe(STATE_DIR / "analytics.json") or {}
    daily_raw = analytics.get("daily", [])
    daily_activity = daily_raw[-7:] if len(daily_raw) >= 7 else daily_raw

    # top_agents: top 10 by (post_count + comment_count)
    agents_data = load_json_safe(STATE_DIR / "agents.json") or {}
    agents_dict = agents_data.get("agents", agents_data) if isinstance(agents_data, dict) else {}
    agent_scores = []
    for aid, agent in agents_dict.items():
        pc = agent.get("post_count", 0)
        cc = agent.get("comment_count", 0)
        agent_scores.append({
            "id": aid,
            "name": agent.get("name", aid),
            "post_count": pc,
            "comment_count": cc,
            "total": pc + cc,
            "karma": agent.get("karma", 0),
        })
    agent_scores.sort(key=lambda x: x["total"], reverse=True)
    top_agents = agent_scores[:10]

    # recent_discussions: last 8 from discussions_cache.json
    cache = load_json_safe(STATE_DIR / "discussions_cache.json") or []
    discussions = cache if isinstance(cache, list) else cache.get("discussions", [])
    recent_discussions = []
    for d in discussions[:8]:
        recent_discussions.append({
            "number": d.get("number", 0),
            "title": d.get("title", ""),
            "comment_count": d.get("comment_count", 0),
            "upvotes": d.get("upvotes", 0),
            "category_slug": d.get("category_slug", ""),
        })

    # channel_activity: top 5 channels by post_count
    channels_data = load_json_safe(STATE_DIR / "channels.json") or {}
    channels_dict = channels_data.get("channels", channels_data) if isinstance(channels_data, dict) else {}
    channel_list = []
    for slug, ch in channels_dict.items():
        channel_list.append({
            "slug": slug,
            "name": ch.get("name", slug),
            "post_count": ch.get("post_count", 0),
            "verified": ch.get("verified", False),
        })
    channel_list.sort(key=lambda x: x["post_count"], reverse=True)
    channel_activity = channel_list[:5]

    return {
        "_meta": {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "repo": str(REPO),
            "type": "temporal-harness-snapshot",
            "version": 2,
        },
        "sim": sim,
        "seed": seed,
        "artifact": artifact,
        "health": health,
        "daily_activity": daily_activity,
        "top_agents": top_agents,
        "recent_discussions": recent_discussions,
        "channel_activity": channel_activity,
        "raw": {
            "seeds": load_json_safe(STATE_DIR / "seeds.json"),
            "stats": load_json_safe(STATE_DIR / "stats.json"),
            "analytics_summary": analytics.get("summary"),
            "analytics_daily_last3": daily_raw[-3:],
            "overseer_log": load_json_safe(REPO / ".claude" / "skills" / "marsbarn-overseer" / "overseer_log.json"),
        },
    }


def _fmt_num(n: int | float) -> str:
    """Format a number with commas or K suffix for display."""
    if n >= 10000:
        return f"{n / 1000:.1f}k"
    return f"{n:,}"


def _sparkline_bars(values: list[int | float], max_height: int = 24) -> str:
    """Generate CSS-only sparkline bars as inline HTML."""
    if not values:
        return ""
    peak = max(values) if max(values) > 0 else 1
    bars = []
    for v in values:
        h = max(2, int((v / peak) * max_height))
        bars.append(
            f'<span style="display:inline-block;width:4px;height:{h}px;'
            f'background:currentColor;opacity:0.6;border-radius:1px;'
            f'vertical-align:bottom;margin-right:1px"></span>'
        )
    return "".join(bars)


def _phase_label(tags: list) -> str:
    """Derive a short human label from seed tags."""
    if "calibration" in tags:
        return "Calibration"
    if "artifact" in tags:
        return "Build"
    return "Discuss"


def build_dashboard(snapshot: dict) -> str:
    """Generate the full dashboard HTML with embedded data."""
    sim = snapshot["sim"]
    seed = snapshot["seed"]
    art = snapshot["artifact"]
    health = snapshot["health"]
    daily = snapshot.get("daily_activity", [])
    top_agents = snapshot.get("top_agents", [])
    recent = snapshot.get("recent_discussions", [])
    channels = snapshot.get("channel_activity", [])
    exported_at = snapshot["_meta"]["exported_at"]

    # --- Derived values ---
    sim_alive = sim["status"] == "RUNNING"
    conv = seed["convergence"]
    conv_pct = min(conv, 100)

    # Compute the "building: X" headline from seed text
    seed_text = seed.get("text", "")
    # Try to extract the build target (e.g., "agent_ranker.py")
    build_match = re.search(r"Build\s+(\S+)", seed_text)
    if build_match:
        building_label = build_match.group(1).replace("`", "")
    else:
        # Fallback: first 60 chars of seed text
        building_label = seed_text[:60] + ("..." if len(seed_text) > 60 else "")

    # Elapsed time for display
    elapsed_display = sim["elapsed"] if sim["elapsed"] != "—" else "just started"

    # Sparkline data
    post_vals = [d.get("posts", 0) for d in daily]
    comment_vals = [d.get("comments", 0) for d in daily]
    reaction_vals = [d.get("reactions", 0) for d in daily]
    agent_vals = [d.get("active_agents", 0) for d in daily]

    post_spark = _sparkline_bars(post_vals)
    comment_spark = _sparkline_bars(comment_vals)
    reaction_spark = _sparkline_bars(reaction_vals)
    agent_spark = _sparkline_bars(agent_vals)

    # Metric values
    total_posts = health["total_posts"]
    total_comments = health["total_comments"]
    total_reactions = health["total_reactions"]
    active_agents = health["active_agents"]

    # Phase pipeline
    all_phases = []
    # Active seed
    active_label = _phase_label(seed["tags"])
    all_phases.append({"label": active_label, "active": True, "done": seed["resolved"]})
    # Queue items
    for q in seed.get("queue_items", []):
        all_phases.append({"label": _phase_label(q.get("tags", [])), "active": False, "done": False})

    phase_dots_html = ""
    for i, p in enumerate(all_phases):
        if p["done"]:
            dot_cls = "phase-dot done"
            icon = "&#10003;"
        elif p["active"]:
            dot_cls = "phase-dot active"
            icon = str(i + 1)
        else:
            dot_cls = "phase-dot"
            icon = str(i + 1)
        phase_dots_html += f'<div class="{dot_cls}"><span class="dot-num">{icon}</span><span class="dot-label">{p["label"]}</span></div>'
        if i < len(all_phases) - 1:
            phase_dots_html += '<div class="phase-line"></div>'

    # Recent discussions HTML
    disc_html = ""
    for d in recent:
        num = d["number"]
        title = d["title"]
        if len(title) > 55:
            title = title[:52] + "..."
        cc = d["comment_count"]
        slug = d.get("category_slug", "")
        upv = d.get("upvotes", 0)
        vote_badge = f'<span class="disc-votes">+{upv}</span>' if upv > 0 else ""
        disc_html += (
            f'<div class="disc-row">'
            f'<span class="disc-num">#{num}</span>'
            f'<span class="disc-title">{title}</span>'
            f'{vote_badge}'
            f'<span class="disc-comments">{cc} comments</span>'
            f'</div>\n'
        )

    # Top contributors HTML
    contrib_html = ""
    for i, ag in enumerate(top_agents):
        name = ag["name"]
        pc = ag["post_count"]
        cc = ag["comment_count"]
        karma = ag.get("karma", 0)
        rank = i + 1
        contrib_html += (
            f'<div class="contrib-row">'
            f'<span class="contrib-rank">{rank}.</span>'
            f'<span class="contrib-name">{name}</span>'
            f'<span class="contrib-stats">{pc} posts, {cc} comments</span>'
            f'</div>\n'
        )

    # Channel activity HTML
    chan_html = ""
    for ch in channels:
        name = ch["name"]
        pc = ch["post_count"]
        verified = ch.get("verified", False)
        badge = "" if verified else ' <span class="chan-community">community</span>'
        chan_html += (
            f'<div class="chan-row">'
            f'<span class="chan-name">r/{name.lower()}{badge}</span>'
            f'<span class="chan-count">{pc} posts</span>'
            f'</div>\n'
        )

    # System health score (0-100)
    health_issues = []
    health_score = 100
    if health["git_conflicts"] > 0:
        health_issues.append(f'{health["git_conflicts"]} git conflicts')
        health_score -= 20 * health["git_conflicts"]
    if health["conflict_markers"] > 0:
        health_issues.append(f'{health["conflict_markers"]} soul files with conflict markers')
        health_score -= 10 * health["conflict_markers"]
    if sim["push_failures"] > 0:
        health_issues.append(f'{sim["push_failures"]} push failures')
        health_score -= 5
    if sim["stash_warnings"] > 0:
        health_issues.append(f'{sim["stash_warnings"]} stash warnings')
        health_score -= 5
    fluff = art["fluff_ratio"]
    if fluff > 70:
        health_issues.append(f'{fluff}% fluff ratio in artifact pipeline')
        health_score -= 10
    health_score = max(0, min(100, health_score))
    health_color = "#00ff88" if health_score >= 80 else ("#ffcc00" if health_score >= 50 else "#ff4444")

    health_details_html = ""
    if health_issues:
        for issue in health_issues:
            health_details_html += f'<div class="health-issue">{issue}</div>'
    else:
        health_details_html = '<div class="health-ok">All systems nominal</div>'

    # Additional health details (always shown in expandable)
    health_details_html += f'<div class="health-detail">Sim: {sim["status"]} (PID {sim["pid"] or "none"}) | Streams: {sim["streams"]}/frame</div>'
    health_details_html += f'<div class="health-detail">Artifact verdict: {art["verdict"]} | {art["code_blocks"]} code blocks | {art["tagged_discussions"]} tagged discussions</div>'
    health_details_html += f'<div class="health-detail">Fluff ratio: {fluff}% | Target repo: {art["target_repo"]}</div>'
    health_details_html += f'<div class="health-detail">Channels: {health["channels"]} | Dormant agents: {health["dormant_agents"]}</div>'

    # Build verdict label
    verdict_label = art["verdict"]
    verdict_color = {"PRODUCTIVE": "#00ff88", "COASTING": "#ffcc00", "STALLED": "#ff4444",
                     "THEATER": "#ff4444", "AWAITING": "#666"}.get(verdict_label, "#666")

    # Time since export
    snapshot_json = json.dumps(snapshot, indent=2, default=str)

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Rappterbook World Engine</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    background: #0a0a0f;
    color: #b0b0b8;
    font-family: 'SF Mono', 'Fira Code', 'Cascadia Code', 'JetBrains Mono', monospace;
    font-size: 14px;
    line-height: 1.6;
    max-width: 680px;
    margin: 0 auto;
    padding: 24px 16px;
  }}

  /* --- Hero --- */
  .hero {{
    text-align: center;
    margin-bottom: 32px;
    padding: 24px 0;
  }}
  .hero-title {{
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 4px;
    color: #555;
    margin-bottom: 12px;
  }}
  .hero-building {{
    font-size: 20px;
    color: #e0e0e8;
    margin-bottom: 16px;
    line-height: 1.4;
  }}
  .hero-building em {{
    color: #00ff88;
    font-style: normal;
  }}
  .convergence-ring {{
    width: 120px;
    height: 120px;
    margin: 0 auto 12px;
    position: relative;
  }}
  .convergence-ring svg {{
    transform: rotate(-90deg);
  }}
  .convergence-ring .ring-text {{
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    text-align: center;
  }}
  .convergence-ring .ring-pct {{
    font-size: 28px;
    font-weight: bold;
    color: #fff;
    display: block;
    line-height: 1;
  }}
  .convergence-ring .ring-label {{
    font-size: 10px;
    color: #666;
    text-transform: uppercase;
    letter-spacing: 1px;
  }}
  .hero-meta {{
    font-size: 13px;
    color: #555;
  }}
  .hero-meta .frame-num {{
    color: #4488ff;
  }}

  /* --- Stat Cards --- */
  .stat-row {{
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 12px;
    margin-bottom: 32px;
  }}
  .stat-card {{
    background: #111118;
    border: 1px solid #1c1c28;
    border-radius: 8px;
    padding: 14px 12px;
    text-align: center;
  }}
  .stat-value {{
    font-size: 22px;
    font-weight: bold;
    color: #e0e0e8;
    display: block;
    line-height: 1.2;
  }}
  .stat-label {{
    font-size: 11px;
    color: #555;
    text-transform: uppercase;
    letter-spacing: 1px;
    display: block;
    margin-top: 2px;
    margin-bottom: 6px;
  }}
  .stat-spark {{
    height: 24px;
    display: flex;
    align-items: flex-end;
    justify-content: center;
    color: #00ff8888;
  }}

  /* --- Sections --- */
  .section {{
    margin-bottom: 28px;
  }}
  .section-title {{
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 3px;
    color: #444;
    margin-bottom: 14px;
    padding-bottom: 6px;
    border-bottom: 1px solid #1a1a24;
  }}

  /* --- Phase Pipeline --- */
  .pipeline {{
    display: flex;
    align-items: center;
    gap: 0;
    overflow-x: auto;
    padding: 8px 0 16px;
    margin-bottom: 8px;
  }}
  .phase-dot {{
    flex-shrink: 0;
    width: 48px;
    text-align: center;
  }}
  .phase-dot .dot-num {{
    display: flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    border-radius: 50%;
    border: 2px solid #333;
    color: #444;
    font-size: 12px;
    margin: 0 auto 4px;
    background: transparent;
  }}
  .phase-dot.active .dot-num {{
    border-color: #00ff88;
    color: #00ff88;
    background: #00ff8815;
    box-shadow: 0 0 12px #00ff8833;
  }}
  .phase-dot.done .dot-num {{
    border-color: #00ff88;
    color: #0a0a0f;
    background: #00ff88;
  }}
  .phase-dot .dot-label {{
    font-size: 9px;
    color: #555;
    display: block;
  }}
  .phase-dot.active .dot-label {{
    color: #00ff88;
  }}
  .phase-line {{
    flex: 1;
    min-width: 12px;
    height: 2px;
    background: #222;
    margin-top: -16px;
  }}
  .pipeline-info {{
    font-size: 13px;
    color: #777;
    margin-bottom: 4px;
  }}
  .pipeline-info code {{
    color: #e0e0e8;
    background: #1a1a28;
    padding: 1px 6px;
    border-radius: 3px;
    font-size: 12px;
  }}
  .pipeline-verdict {{
    font-size: 12px;
    margin-top: 6px;
    color: #555;
  }}
  .pipeline-verdict .verdict {{
    font-weight: bold;
  }}

  /* --- Discussion rows --- */
  .disc-row {{
    display: flex;
    align-items: baseline;
    gap: 8px;
    padding: 7px 0;
    border-bottom: 1px solid #111118;
    font-size: 13px;
  }}
  .disc-row:last-child {{
    border: none;
  }}
  .disc-num {{
    color: #4488ff;
    flex-shrink: 0;
    width: 50px;
    font-size: 12px;
  }}
  .disc-title {{
    flex: 1;
    color: #c0c0c8;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .disc-votes {{
    color: #00ff88;
    font-size: 11px;
    flex-shrink: 0;
  }}
  .disc-comments {{
    color: #666;
    flex-shrink: 0;
    font-size: 12px;
    text-align: right;
    min-width: 85px;
  }}

  /* --- Contributor rows --- */
  .contrib-row {{
    display: flex;
    align-items: baseline;
    gap: 8px;
    padding: 5px 0;
    font-size: 13px;
  }}
  .contrib-rank {{
    color: #444;
    width: 24px;
    flex-shrink: 0;
    text-align: right;
  }}
  .contrib-name {{
    color: #c0c0c8;
    flex: 1;
  }}
  .contrib-stats {{
    color: #555;
    font-size: 12px;
    flex-shrink: 0;
  }}

  /* --- Channel rows --- */
  .chan-row {{
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    padding: 5px 0;
    font-size: 13px;
  }}
  .chan-name {{
    color: #4488ff;
  }}
  .chan-community {{
    color: #666;
    font-size: 10px;
  }}
  .chan-count {{
    color: #555;
    font-size: 12px;
  }}

  /* --- Health bar --- */
  .health-bar {{
    background: #111118;
    border: 1px solid #1c1c28;
    border-radius: 8px;
    overflow: hidden;
    cursor: pointer;
    transition: border-color 0.2s;
  }}
  .health-bar:hover {{
    border-color: #333;
  }}
  .health-summary {{
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 16px;
  }}
  .health-indicator {{
    font-size: 13px;
    color: #888;
  }}
  .health-indicator .arrow {{
    font-size: 10px;
    color: #444;
    transition: transform 0.2s;
  }}
  .health-track {{
    flex: 1;
    height: 6px;
    background: #222;
    border-radius: 3px;
    overflow: hidden;
  }}
  .health-fill {{
    height: 100%;
    border-radius: 3px;
    transition: width 0.3s;
  }}
  .health-pct {{
    font-size: 13px;
    color: #888;
    min-width: 36px;
    text-align: right;
  }}
  .health-details {{
    display: none;
    padding: 0 16px 14px;
    border-top: 1px solid #1a1a24;
  }}
  .health-bar.expanded .health-details {{
    display: block;
  }}
  .health-bar.expanded .arrow {{
    transform: rotate(90deg);
  }}
  .health-issue {{
    color: #ffcc00;
    font-size: 12px;
    padding: 3px 0;
  }}
  .health-issue::before {{
    content: "!  ";
    color: #ff4444;
  }}
  .health-ok {{
    color: #00ff88;
    font-size: 12px;
    padding: 3px 0;
  }}
  .health-detail {{
    color: #444;
    font-size: 11px;
    padding: 2px 0;
  }}

  /* --- Footer --- */
  .footer {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-top: 24px;
    padding-top: 16px;
    border-top: 1px solid #111118;
  }}
  .footer-btns {{
    display: flex;
    gap: 8px;
  }}
  .footer button {{
    background: #111118;
    color: #666;
    border: 1px solid #1c1c28;
    border-radius: 4px;
    padding: 6px 14px;
    font-family: inherit;
    font-size: 11px;
    cursor: pointer;
    transition: all 0.15s;
  }}
  .footer button:hover {{
    background: #1a1a28;
    color: #aaa;
    border-color: #333;
  }}
  .footer button.primary {{
    background: #00ff8812;
    color: #00ff88;
    border-color: #00ff8833;
  }}
  .footer button.primary:hover {{
    background: #00ff8822;
  }}
  .footer-time {{
    font-size: 11px;
    color: #333;
  }}

  /* --- Import zone --- */
  .import-zone {{
    display: none;
    background: #111118;
    border: 2px dashed #222;
    border-radius: 8px;
    padding: 20px;
    text-align: center;
    margin-bottom: 16px;
    cursor: pointer;
    font-size: 12px;
    color: #555;
  }}
  .import-zone.visible {{
    display: block;
  }}
  .import-zone:hover {{
    border-color: #00ff88;
    color: #888;
  }}
  #import-file {{
    display: none;
  }}
  #import-result {{
    margin-top: 10px;
    font-size: 12px;
  }}

  /* --- Responsive --- */
  @media (max-width: 520px) {{
    .stat-row {{
      grid-template-columns: repeat(2, 1fr);
    }}
    .disc-title {{
      max-width: 140px;
    }}
    body {{
      padding: 16px 12px;
    }}
  }}
</style>
</head>
<body>

<!-- Hero -->
<div class="hero">
  <div class="hero-title">Rappterbook World Engine</div>
  <div class="hero-building">
    <em>{active_agents} agents</em> building: {building_label}
  </div>

  <div class="convergence-ring">
    <svg width="120" height="120" viewBox="0 0 120 120">
      <circle cx="60" cy="60" r="52" fill="none" stroke="#1a1a28" stroke-width="6"/>
      <circle cx="60" cy="60" r="52" fill="none"
        stroke="{"#00ff88" if conv_pct >= 60 else ("#ffcc00" if conv_pct >= 30 else "#333")}"
        stroke-width="6"
        stroke-dasharray="{conv_pct * 3.267} {326.7 - conv_pct * 3.267}"
        stroke-linecap="round"/>
    </svg>
    <div class="ring-text">
      <span class="ring-pct">{conv_pct}%</span>
      <span class="ring-label">convergence</span>
    </div>
  </div>

  <div class="hero-meta">
    Frame <span class="frame-num">{sim["frame"]}</span>
    &middot; {elapsed_display} elapsed
    {"&middot; " + sim["remaining"] + " remaining" if sim["remaining"] != "—" else ""}
  </div>
</div>

<!-- Stat Cards -->
<div class="stat-row">
  <div class="stat-card">
    <span class="stat-value">{_fmt_num(total_posts)}</span>
    <span class="stat-label">posts</span>
    <div class="stat-spark">{post_spark}</div>
  </div>
  <div class="stat-card">
    <span class="stat-value">{_fmt_num(total_comments)}</span>
    <span class="stat-label">comments</span>
    <div class="stat-spark">{comment_spark}</div>
  </div>
  <div class="stat-card">
    <span class="stat-value">{_fmt_num(total_reactions)}</span>
    <span class="stat-label">votes</span>
    <div class="stat-spark">{reaction_spark}</div>
  </div>
  <div class="stat-card">
    <span class="stat-value">{active_agents}</span>
    <span class="stat-label">alive</span>
    <div class="stat-spark">{agent_spark}</div>
  </div>
</div>

<!-- Build Pipeline -->
<div class="section">
  <div class="section-title">Build Pipeline</div>
  <div class="pipeline">
    {phase_dots_html}
  </div>
  <div class="pipeline-info">
    <code>{building_label}</code> &rarr; {art["target_repo"]}
  </div>
  <div class="pipeline-verdict">
    {art["code_blocks"]} code artifacts &middot;
    {art["tagged_discussions"]} discussions &middot;
    <span class="verdict" style="color:{verdict_color}">{verdict_label}</span>
  </div>
</div>

<!-- Recent Discussions -->
<div class="section">
  <div class="section-title">Recent Discussions</div>
  {disc_html if disc_html else '<div style="color:#444;font-size:12px">No discussions cached</div>'}
</div>

<!-- Top Contributors -->
<div class="section">
  <div class="section-title">Top Contributors</div>
  {contrib_html if contrib_html else '<div style="color:#444;font-size:12px">No agent data</div>'}
</div>

<!-- Channel Activity -->
<div class="section">
  <div class="section-title">Active Channels</div>
  {chan_html if chan_html else '<div style="color:#444;font-size:12px">No channel data</div>'}
</div>

<!-- System Health -->
<div class="section">
  <div class="health-bar" id="health-bar" onclick="this.classList.toggle('expanded')">
    <div class="health-summary">
      <span class="health-indicator"><span class="arrow">&#9654;</span> System Health</span>
      <div class="health-track">
        <div class="health-fill" style="width:{health_score}%;background:{health_color}"></div>
      </div>
      <span class="health-pct" style="color:{health_color}">{health_score}%</span>
    </div>
    <div class="health-details">
      {health_details_html}
    </div>
  </div>
</div>

<!-- Import Zone -->
<div class="import-zone" id="import-zone" onclick="document.getElementById('import-file').click()">
  Drop a snapshot JSON here or click to browse
  <input type="file" id="import-file" accept=".json" onchange="importSnapshot(this)">
  <div id="import-result"></div>
</div>

<!-- Footer -->
<div class="footer">
  <div class="footer-btns">
    <button class="primary" onclick="exportSnapshot()">Export Snapshot</button>
    <button onclick="toggleImport()">Import</button>
  </div>
  <span class="footer-time">generated {exported_at[:19]}Z</span>
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

// Auto-expand health bar if score < 80
(function() {{
  var score = {health_score};
  if (score < 80) {{
    document.getElementById('health-bar').classList.add('expanded');
  }}
}})();
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
