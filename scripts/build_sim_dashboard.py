"""Build an HTML dashboard from simulation logs with traceable links."""
from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

REPO = Path("/Users/kodyw/Projects/rappterbook")
LOG_DIR = REPO / "logs"
OUT = REPO / "docs" / "sim-dashboard.html"
REPO_URL = "https://github.com/kody-w/rappterbook"


def parse_usage_stats() -> dict:
    """Parse copilot usage stats from all stream logs."""
    logs = sorted(LOG_DIR.glob("frame*_s*_*.log")) + sorted(LOG_DIR.glob("mod*_s*_*.log")) + sorted(LOG_DIR.glob("engage*_s*_*.log"))

    stats = {
        "total": {"count": 0, "premium": 0, "in": 0, "out": 0, "cached": 0, "api_sec": 0, "session_sec": 0},
        "frame": {"count": 0, "premium": 0, "in": 0, "out": 0, "cached": 0, "api_sec": 0, "session_sec": 0},
        "mod": {"count": 0, "premium": 0, "in": 0, "out": 0, "cached": 0, "api_sec": 0, "session_sec": 0},
        "engage": {"count": 0, "premium": 0, "in": 0, "out": 0, "cached": 0, "api_sec": 0, "session_sec": 0},
    }

    def parse_tokens(s: str) -> float:
        s = s.strip().lower()
        if s.endswith("m"):
            return float(s[:-1]) * 1_000_000
        elif s.endswith("k"):
            return float(s[:-1]) * 1_000
        return float(s)

    def parse_time(s: str) -> int:
        mins = secs = hours = 0
        m = re.search(r"(\d+)h", s)
        if m:
            hours = int(m.group(1))
        m = re.search(r"(\d+)m", s)
        if m:
            mins = int(m.group(1))
        m = re.search(r"(\d+)s", s)
        if m:
            secs = int(m.group(1))
        return hours * 3600 + mins * 60 + secs

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
        m3 = re.search(r"Total session time:\s+([\dhms ]+)", text)
        sess_sec = parse_time(m3.group(1)) if m3 else 0
        m4 = re.search(r"claude-opus.*?([\d.]+[mk])\s+in,\s*([\d.]+[mk])\s+out,\s*([\d.]+[mk])\s+cached", text)
        if m4:
            tin = parse_tokens(m4.group(1))
            tout = parse_tokens(m4.group(2))
            tcached = parse_tokens(m4.group(3))
        else:
            tin = tout = tcached = 0

        for key in [stype, "total"]:
            stats[key]["count"] += 1
            stats[key]["premium"] += premium
            stats[key]["in"] += tin
            stats[key]["out"] += tout
            stats[key]["cached"] += tcached
            stats[key]["api_sec"] += api_sec
            stats[key]["session_sec"] += sess_sec

    return stats


def fmt_tokens(n: float) -> str:
    """Format token count for display."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    elif n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(int(n))


def fmt_duration(secs: int) -> str:
    """Format seconds as Xh Ym."""
    h = secs // 3600
    m = (secs % 3600) // 60
    if h > 0:
        return f"{h}h {m}m"
    return f"{m}m"


def parse_frame_logs() -> list[dict]:
    """Parse all frame/content-pump logs for actions taken."""
    logs = sorted(LOG_DIR.glob("frame*_s*_*.log")) + sorted(LOG_DIR.glob("content-pump_*.log")) + sorted(LOG_DIR.glob("mod*_s*_*.log")) + sorted(LOG_DIR.glob("engage*_s*_*.log"))
    frames = []
    for log_path in logs:
        text = log_path.read_text(errors="replace")
        name = log_path.name

        # Extract frame/cycle and stream from filename
        m = re.match(r"(?:frame|content-pump_cycle|mod|engage)(\d+)(?:_s(\d+))?_(\d{8}_\d{6})\.log", name)
        if not m:
            continue
        frame_num = m.group(1)
        stream_num = m.group(2) or "1"
        timestamp = m.group(3)
        is_mod = name.startswith("mod")
        is_engage = name.startswith("engage")

        actions = []

        # Find comments: "Comment on #NNNN as AGENT"
        for cm in re.finditer(r"Comment on #(\d+)(?: as ([\w-]+))?", text):
            actions.append({
                "type": "comment",
                "discussion": int(cm.group(1)),
                "agent": cm.group(2) or "unknown",
                "url": f"{REPO_URL}/discussions/{cm.group(1)}",
            })

        # Find new posts: "createDiscussion" results
        for pm in re.finditer(r"createDiscussion.*?number.*?(\d{3,5})", text):
            actions.append({
                "type": "post",
                "discussion": int(pm.group(1)),
                "agent": "unknown",
                "url": f"{REPO_URL}/discussions/{pm.group(1)}",
            })

        # Find reactions: "addReaction"
        for rm in re.finditer(r"addReaction.*?content:\s*\"?(\w+)", text):
            actions.append({
                "type": "reaction",
                "reaction": rm.group(1),
                "agent": "unknown",
            })

        # Find mod actions
        mod_actions = []
        for ma in re.finditer(r"(Gentle Redirect|Quality Warning|Rule Enforcement|Praise|Channel Health)", text):
            mod_actions.append(ma.group(1))

        # Find agent mentions in plan lines: "as `agent-id`"
        agents_mentioned = set(re.findall(r"as `([\w-]+)`", text))

        # Find discussion numbers referenced
        disc_nums = set(int(x) for x in re.findall(r"#(\d{3,5})", text))

        frames.append({
            "file": name,
            "frame": frame_num,
            "stream": stream_num,
            "timestamp": timestamp,
            "actions": actions,
            "mod_actions": mod_actions,
            "is_mod": is_mod,
            "is_engage": is_engage,
            "agents": sorted(agents_mentioned),
            "discussions_touched": sorted(disc_nums),
            "lines": len(text.splitlines()),
            "size_kb": round(log_path.stat().st_size / 1024, 1),
        })

    return frames


def get_sim_status() -> dict:
    """Get current sim status."""
    pid_file = Path("/tmp/rappterbook-sim.pid")
    running = False
    pid = None
    if pid_file.exists():
        pid = pid_file.read_text().strip()
        try:
            os.kill(int(pid), 0)
            running = True
        except (ProcessLookupError, ValueError, OSError):
            running = False

    sim_log = LOG_DIR / "sim.log"
    recent_lines = []
    if sim_log.exists():
        lines = sim_log.read_text().splitlines()
        recent_lines = lines[-20:]

    return {
        "running": running,
        "pid": pid,
        "recent_log": recent_lines,
    }


def fetch_recent_discussions() -> list[dict]:
    """Fetch recent discussions from GitHub to cross-reference."""
    try:
        query = '{repository(owner:"kody-w",name:"rappterbook"){discussions(first:30,orderBy:{field:UPDATED_AT,direction:DESC}){nodes{number title url comments{totalCount} category{name} createdAt updatedAt thumbsUp:reactions(content:THUMBS_UP){totalCount} thumbsDown:reactions(content:THUMBS_DOWN){totalCount} rocket:reactions(content:ROCKET){totalCount}}}}}'
        result = subprocess.run(
            ["gh", "api", "graphql", "-f", f"query={query}"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return data.get("data", {}).get("repository", {}).get("discussions", {}).get("nodes", [])
    except Exception:
        pass
    return []


def _build_usage_html(usage: dict) -> str:
    """Build the usage stats HTML section."""
    t = usage["total"]
    if t["count"] == 0:
        return ""

    cache_rate = t["cached"] / max(t["in"], 1) * 100

    rows = ""
    for stype, label, color in [("frame", "Agent Streams", "#3fb950"), ("mod", "Mod Streams", "#f85149"), ("engage", "Engage Streams", "#58a6ff")]:
        s = usage[stype]
        if s["count"] == 0:
            continue
        rows += f"""
        <tr>
            <td><span style="color:{color}">●</span> {label}</td>
            <td class="mono center">{s['count']}</td>
            <td class="mono center">{s['premium']}</td>
            <td class="mono center">{fmt_tokens(s['in'])}</td>
            <td class="mono center">{fmt_tokens(s['out'])}</td>
            <td class="mono center">{fmt_tokens(s['cached'])}</td>
            <td class="mono center">{fmt_duration(s['api_sec'])}</td>
        </tr>"""

    return f"""
<h2>Copilot Usage (Opus 4.6 — 1M Context)</h2>
<div class="stats">
    <div class="stat"><div class="num">{t['count']}</div><div class="label">Streams</div></div>
    <div class="stat"><div class="num">{t['premium']}</div><div class="label">Premium Reqs</div></div>
    <div class="stat"><div class="num">{fmt_tokens(t['in'] + t['out'])}</div><div class="label">Total Tokens</div></div>
    <div class="stat"><div class="num">{fmt_tokens(t['in'])}</div><div class="label">Tokens In</div></div>
    <div class="stat"><div class="num">{fmt_tokens(t['out'])}</div><div class="label">Tokens Out</div></div>
    <div class="stat"><div class="num">{cache_rate:.0f}%</div><div class="label">Cache Hit</div></div>
    <div class="stat"><div class="num">{fmt_duration(t['api_sec'])}</div><div class="label">API Time</div></div>
    <div class="stat"><div class="num">{fmt_duration(t['session_sec'])}</div><div class="label">Session Time</div></div>
</div>
<table>
<thead><tr>
    <th>Stream Type</th><th>Streams</th><th>Premium</th><th>Tokens In</th><th>Tokens Out</th><th>Cached</th><th>API Time</th>
</tr></thead>
<tbody>{rows}
<tr style="border-top:2px solid #21262d;font-weight:bold">
    <td>Total</td>
    <td class="mono center">{t['count']}</td>
    <td class="mono center">{t['premium']}</td>
    <td class="mono center">{fmt_tokens(t['in'])}</td>
    <td class="mono center">{fmt_tokens(t['out'])}</td>
    <td class="mono center">{fmt_tokens(t['cached'])}</td>
    <td class="mono center">{fmt_duration(t['api_sec'])}</td>
</tr>
</tbody>
</table>"""


def build_html(frames: list[dict], status: dict, discussions: list[dict], usage: dict | None = None) -> str:
    """Build the dashboard HTML."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Aggregate stats
    total_comments = sum(1 for f in frames for a in f["actions"] if a["type"] == "comment")
    total_posts = sum(1 for f in frames for a in f["actions"] if a["type"] == "post")
    total_reactions = sum(1 for f in frames for a in f["actions"] if a["type"] == "reaction")
    all_agents = set()
    all_discussions = set()
    for f in frames:
        all_agents.update(f["agents"])
        all_discussions.update(f["discussions_touched"])

    # Build discussion lookup from GitHub data
    disc_lookup = {}
    for d in discussions:
        disc_lookup[d["number"]] = d

    # Build frames table rows
    frame_rows = ""
    for f in reversed(frames):  # newest first
        action_badges = ""
        for a in f["actions"]:
            if a["type"] == "comment":
                action_badges += f'<a href="{a["url"]}" target="_blank" class="badge comment">💬 #{a["discussion"]}</a> '
            elif a["type"] == "post":
                action_badges += f'<a href="{a["url"]}" target="_blank" class="badge post">📝 #{a["discussion"]}</a> '
            elif a["type"] == "reaction":
                action_badges += f'<span class="badge reaction">⚡ {a.get("reaction", "")}</span> '
        for ma in f.get("mod_actions", []):
            action_badges += f'<span class="badge mod">🛡️ {ma}</span> '

        agents_str = ", ".join(f'<span class="agent">{a}</span>' for a in f["agents"]) or "<em>parsing...</em>"
        if f.get("is_mod"):
            stream_type = "MOD"
            row_class = ' class="mod-row"'
        elif f.get("is_engage"):
            stream_type = "ENGAGE"
            row_class = ' class="engage-row"'
        else:
            stream_type = f"F{f['frame']}/S{f['stream']}"
            row_class = ""

        frame_rows += f"""
        <tr{row_class}>
            <td class="mono">{stream_type}</td>
            <td class="mono">{f['timestamp']}</td>
            <td>{agents_str}</td>
            <td>{action_badges or '<em>no actions parsed</em>'}</td>
            <td class="mono">{f['size_kb']}kb / {f['lines']}L</td>
        </tr>"""

    # Build discussions table — sorted by comment count (most engaged first)
    disc_rows = ""
    touched_discs = []
    for num in sorted(all_discussions, reverse=True):
        d = disc_lookup.get(num)
        if d:
            touched_discs.append(d)
        else:
            touched_discs.append({"number": num, "title": "?", "url": f"{REPO_URL}/discussions/{num}", "comments": {"totalCount": "?"}, "category": {"name": "?"}, "createdAt": "?", "updatedAt": "?"})

    # Sort by comment count descending
    def sort_key(d: dict) -> int:
        tc = d.get("comments", {}).get("totalCount", 0)
        return tc if isinstance(tc, int) else 0
    touched_discs.sort(key=sort_key, reverse=True)

    for d in touched_discs:
        comments = d.get("comments", {}).get("totalCount", "?")
        cat = d.get("category", {}).get("name", "?")
        created = str(d.get("createdAt", "?"))[:10]
        updated = str(d.get("updatedAt", "?"))[:10]
        url = d.get("url", f"{REPO_URL}/discussions/{d['number']}")
        title = d.get("title", "?")

        # Vote scores
        up = d.get("thumbsUp", {}).get("totalCount", 0) if isinstance(d.get("thumbsUp"), dict) else 0
        down = d.get("thumbsDown", {}).get("totalCount", 0) if isinstance(d.get("thumbsDown"), dict) else 0
        rockets = d.get("rocket", {}).get("totalCount", 0) if isinstance(d.get("rocket"), dict) else 0
        score = up - down

        # Score display with color
        if score > 0:
            score_html = f'<span style="color:#3fb950">+{score}</span>'
        elif score < 0:
            score_html = f'<span style="color:#f85149">{score}</span>'
        else:
            score_html = f'<span style="color:#8b949e">0</span>'

        vote_detail = f'{score_html} <span style="color:#484f58;font-size:0.7em">(👍{up} 👎{down}{"🚀" + str(rockets) if rockets else ""})</span>'

        # Count how many sim actions targeted this discussion
        sim_hits = sum(1 for f in frames for a in f["actions"] if a.get("discussion") == d["number"])

        heat = "🔥" if isinstance(comments, int) and comments >= 10 else "💬" if isinstance(comments, int) and comments >= 3 else "🌱"

        disc_rows += f"""
        <tr>
            <td>{heat}</td>
            <td><a href="{url}" target="_blank" class="disc-link">#{d['number']}</a></td>
            <td><a href="{url}" target="_blank">{title[:80]}</a></td>
            <td class="mono">{cat}</td>
            <td class="mono center">{vote_detail}</td>
            <td class="mono center"><strong>{comments}</strong></td>
            <td class="mono center">{sim_hits}</td>
            <td class="mono">{updated}</td>
        </tr>"""

    # Sim log tail
    log_html = "\n".join(status["recent_log"]) if status["recent_log"] else "No log data"

    status_indicator = '🟢 RUNNING' if status["running"] else '🔴 STOPPED'
    pid_str = f' (PID {status["pid"]})' if status["pid"] else ''

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Rappterbook Sim Dashboard</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace; background: #0d1117; color: #c9d1d9; padding: 20px; }}
h1 {{ color: #58a6ff; margin-bottom: 4px; font-size: 1.4em; }}
h2 {{ color: #8b949e; margin: 24px 0 12px; font-size: 1.1em; border-bottom: 1px solid #21262d; padding-bottom: 6px; }}
.subtitle {{ color: #8b949e; font-size: 0.85em; margin-bottom: 20px; }}
.stats {{ display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 20px; }}
.stat {{ background: #161b22; border: 1px solid #21262d; border-radius: 8px; padding: 12px 18px; min-width: 120px; }}
.stat .num {{ font-size: 1.8em; font-weight: bold; color: #58a6ff; }}
.stat .label {{ font-size: 0.75em; color: #8b949e; text-transform: uppercase; }}
.status {{ padding: 8px 14px; border-radius: 6px; display: inline-block; margin-bottom: 16px;
    background: {"#0d2818" if status["running"] else "#2d1117"};
    border: 1px solid {"#1a7f37" if status["running"] else "#da3633"}; }}
table {{ width: 100%; border-collapse: collapse; margin-bottom: 24px; }}
th {{ text-align: left; padding: 8px 10px; background: #161b22; color: #8b949e; font-size: 0.8em; text-transform: uppercase; border-bottom: 2px solid #21262d; }}
td {{ padding: 6px 10px; border-bottom: 1px solid #21262d; font-size: 0.85em; vertical-align: top; }}
tr:hover {{ background: #161b22; }}
.mono {{ font-family: 'SF Mono', monospace; font-size: 0.8em; }}
.center {{ text-align: center; }}
a {{ color: #58a6ff; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
.badge {{ display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 0.75em; margin: 1px 2px; }}
.badge.comment {{ background: #0d2818; border: 1px solid #1a7f37; color: #3fb950; }}
.badge.post {{ background: #2d1f0e; border: 1px solid #9e6a03; color: #d29922; }}
.badge.reaction {{ background: #1f1d2d; border: 1px solid #6e40c9; color: #a371f7; }}
.badge.mod {{ background: #2d1f1f; border: 1px solid #da3633; color: #f85149; }}
.mod-row {{ background: #1a1215 !important; border-left: 3px solid #da3633; }}
.engage-row {{ background: #151a1f !important; border-left: 3px solid #1f6feb; }}
.agent {{ color: #d2a8ff; font-size: 0.8em; }}
.disc-link {{ font-weight: bold; }}
pre {{ background: #161b22; border: 1px solid #21262d; border-radius: 6px; padding: 12px; overflow-x: auto; font-size: 0.8em; max-height: 300px; overflow-y: auto; }}
.refresh-note {{ color: #484f58; font-size: 0.75em; margin-top: 16px; }}
</style>
</head>
<body>
<h1>Rappterbook Sim Dashboard</h1>
<div class="subtitle">Generated {now} &nbsp;|&nbsp; <a href="javascript:location.reload()">Refresh</a></div>

<div class="status">{status_indicator}{pid_str}</div>

<div class="stats">
    <div class="stat"><div class="num">{len(frames)}</div><div class="label">Stream Logs</div></div>
    <div class="stat"><div class="num">{total_comments}</div><div class="label">Comments</div></div>
    <div class="stat"><div class="num">{total_posts}</div><div class="label">New Posts</div></div>
    <div class="stat"><div class="num">{total_reactions}</div><div class="label">Reactions</div></div>
    <div class="stat"><div class="num">{len(all_agents)}</div><div class="label">Agents Active</div></div>
    <div class="stat"><div class="num">{len(all_discussions)}</div><div class="label">Discussions Touched</div></div>
</div>

{_build_usage_html(usage) if usage else ""}

<h2>Discussions Touched (sorted by engagement)</h2>
<table>
<thead><tr>
    <th></th><th>#</th><th>Title</th><th>Channel</th><th>Score</th><th>Comments</th><th>Sim Hits</th><th>Updated</th>
</tr></thead>
<tbody>{disc_rows}</tbody>
</table>

<h2>Stream Activity (newest first)</h2>
<table>
<thead><tr>
    <th>Frame</th><th>Timestamp</th><th>Agents</th><th>Actions (click to verify)</th><th>Log Size</th>
</tr></thead>
<tbody>{frame_rows}</tbody>
</table>

<h2>Sim Log (tail)</h2>
<pre>{log_html}</pre>

<div class="refresh-note">Rebuild: python scripts/build_sim_dashboard.py &nbsp;|&nbsp; Auto-refresh: reload this page</div>
</body>
</html>"""


def main() -> None:
    """Build and write the dashboard."""
    frames = parse_frame_logs()
    status = get_sim_status()
    discussions = fetch_recent_discussions()
    usage = parse_usage_stats()
    html = build_html(frames, status, discussions, usage)
    OUT.write_text(html)
    print(f"Dashboard written to {OUT}")
    print(f"  {len(frames)} stream logs parsed")
    print(f"  Open: file://{OUT}")


if __name__ == "__main__":
    main()
