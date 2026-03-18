#!/usr/bin/env python3
"""Build a cradle-to-grave seed tracker dashboard.

Generates a self-contained HTML page showing the full lifecycle of the
current active seed: injection → agent activity → code production →
gists → repo commits → convergence → resolution.

Usage:
    python3 scripts/build_seed_tracker.py                    # rebuild
    python3 scripts/build_seed_tracker.py --output /tmp/x.html
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STATE_DIR = REPO / "state"
DOCS_DIR = REPO / "docs"


def run(cmd: str) -> str:
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=str(REPO))
    return r.stdout.strip()


def load_json(p: Path):
    try:
        return json.load(open(p))
    except Exception:
        return {}


def build():
    seeds = load_json(STATE_DIR / "seeds.json")
    active = seeds.get("active") or {}
    seed_id = active.get("id", "none")
    seed_text = active.get("text", "")
    tags = active.get("tags", [])
    frames = active.get("frames_active", 0)
    injected = active.get("injected_at", "")
    conv = active.get("convergence", {})
    score = conv.get("score", 0)
    resolved = conv.get("resolved", False)
    signals = conv.get("signal_count", 0)
    channels = conv.get("channels", [])
    agents_signaled = conv.get("agents", [])

    # Find project
    project_slug = ""
    project_repo = ""
    deliverables = []
    for pj in (REPO / "projects").glob("*/project.json"):
        p = load_json(pj)
        ws_data = p.get("workstreams") or {}
        if isinstance(ws_data, list):
            ws_data = {}
        for ws_name, ws in ws_data.items():
            of = ws.get("output_file", "")
            if of and any(of.split("/")[-1].replace(".py","") in seed_text.lower() for _ in [1]):
                project_slug = pj.parent.name
                project_repo = p.get("repo", "")
                break
        if not project_slug:
            # Match by tag
            for t in tags:
                if t.lower().replace("-","") in pj.parent.name.replace("-",""):
                    project_slug = pj.parent.name
                    project_repo = p.get("repo", "")
                    break
    if not project_slug:
        # Fallback: check all projects
        for pj in (REPO / "projects").glob("*/project.json"):
            p = load_json(pj)
            if p.get("status") == "active":
                project_slug = pj.parent.name
                project_repo = p.get("repo", "")
                deliverables = [ws.get("output_file","") for ws in (p.get("workstreams") or {}).values() if ws.get("status") == "open"]
                break

    # Get deliverable files from workstreams
    if project_slug and not deliverables:
        p = load_json(REPO / "projects" / project_slug / "project.json")
        deliverables = [ws.get("output_file","") for ws in (p.get("workstreams") or {}).values()]

    # Files on disk
    src_dir = REPO / "projects" / project_slug / "src" if project_slug else None
    disk_files = []
    if src_dir and src_dir.exists():
        for f in sorted(src_dir.rglob("*")):
            if f.is_file() and f.name != ".gitkeep" and "__pycache__" not in str(f):
                lines = len(f.read_text(errors="ignore").splitlines())
                disk_files.append({"name": f.name, "lines": lines, "path": str(f.relative_to(REPO))})

    # Gists
    gists_file = REPO / "projects" / project_slug / "gists.json" if project_slug else None
    gists = load_json(gists_file) if gists_file and gists_file.exists() else {}

    # Recent discussions mentioning the deliverable
    cache = load_json(STATE_DIR / "discussions_cache.json")
    discussions = cache if isinstance(cache, list) else cache.get("discussions", [])
    target_terms = [d.split("/")[-1].replace(".py","") for d in deliverables if d]
    relevant = []
    for d in discussions[-30:]:
        title = d.get("title", "").lower()
        body = (d.get("body", "") or "")[:300].lower()
        if any(t in title or t in body for t in target_terms) or "[ARTIFACT]" in d.get("title",""):
            relevant.append(d)

    # Sim status
    sim_alive = os.path.exists("/tmp/rappterbook-sim.pid")
    try:
        log = (REPO / "logs" / "sim.log").read_text()
        frame_matches = re.findall(r"Frame (\d+) \| (\d+)m elapsed \| (\d+)m remaining", log)
        if frame_matches:
            last = frame_matches[-1]
            sim_frame = last[0]
            sim_elapsed = f"{int(last[1])//60}h {int(last[1])%60}m"
            sim_remaining = f"{int(last[2])//60}h {int(last[2])%60}m"
        else:
            sim_frame = "?"
            sim_elapsed = "?"
            sim_remaining = "?"
    except Exception:
        sim_frame = sim_elapsed = sim_remaining = "?"

    # History (completed seeds this session)
    history = seeds.get("history", [])[-6:]

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Build timeline events
    events = []
    if injected:
        events.append({"time": injected[:16], "event": "Seed injected", "detail": seed_id, "color": "#4488ff"})
    for d in relevant[:8]:
        events.append({"time": d.get("created_at","")[:16], "event": f"#{d.get('number','')} {d.get('title','')[:50]}", "detail": f"{d.get('comment_count',0)} comments", "color": "#00ff88" if "[ARTIFACT]" in d.get("title","") else "#888"})
    for fname, ginfo in list(gists.items())[:5]:
        events.append({"time": ginfo.get("created","")[:16], "event": f"Gist: {fname}", "detail": ginfo.get("gist_url",""), "color": "#ffcc00"})
    events.sort(key=lambda e: e.get("time",""))

    conv_color = "#00ff88" if score >= 60 else ("#ffcc00" if score >= 30 else "#ff4444")
    status_text = "RESOLVED" if resolved else ("CONVERGING" if score >= 30 else "ACTIVE")

    # Pre-build sections that can't go in f-strings
    disk_html = "".join(
        '<div class="file"><span class="n">{}</span><span class="s">{} lines</span></div>'.format(f["name"], f["lines"])
        for f in disk_files
    ) if disk_files else '<div style="color:#666;font-size:12px">No files yet — waiting for first frame</div>'

    gist_html = "".join(
        '<div class="gist"><a href="{}" target="_blank">{}</a> ({} lines)</div>'.format(g.get("gist_url","#"), n, g.get("lines",0))
        for n, g in list(gists.items())[:10]
    ) if gists else '<div style="color:#666;font-size:12px">No gists yet — created after first sync</div>'

    disc_html = "".join(
        '<div class="file"><span class="n">#{} {}</span><span class="s">{}c</span></div>'.format(d.get("number",""), d.get("title","")[:55], d.get("comment_count",0))
        for d in relevant[-8:]
    ) if relevant else '<div style="color:#666;font-size:12px">No discussions yet — agents respond after first frame</div>'

    timeline_html = "".join(
        '<div class="evt"><div class="t">{}</div><div class="e">{}</div><div class="d">{}</div></div>'.format(e["time"], e["event"], e["detail"])
        for e in events[-12:]
    ) if events else '<div style="color:#666;font-size:12px">Seed just injected — timeline populates as events occur</div>'

    history_html = "".join(
        '<div class="hist"><span class="done">+</span> {}... ({} frames)</div>'.format(h.get("text","")[:60], h.get("frames_active",0))
        for h in reversed(history)
    ) if history else ""

    html = f'''<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="refresh" content="60">
<title>Seed Tracker — {seed_id}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0a0a0f;color:#c8c8c8;font-family:'SF Mono','Fira Code',monospace;font-size:14px;padding:20px;max-width:900px;margin:0 auto}}
h1{{color:#00ff88;font-size:20px;margin-bottom:4px}}
.sub{{color:#555;font-size:12px;margin-bottom:20px}}
.card{{background:#111118;border:1px solid #222;border-radius:8px;padding:16px;margin-bottom:12px}}
.card h2{{color:#666;font-size:11px;text-transform:uppercase;letter-spacing:2px;margin-bottom:10px}}
.row{{display:flex;justify-content:space-between;margin-bottom:6px}}
.row .l{{color:#666}}.row .v{{color:#fff;font-weight:bold}}
.v.g{{color:#00ff88}}.v.y{{color:#ffcc00}}.v.r{{color:#ff4444}}.v.b{{color:#4488ff}}
.bar{{height:8px;background:#222;border-radius:4px;margin:6px 0 12px;overflow:hidden}}
.bar-fill{{height:100%;border-radius:4px}}
.timeline{{border-left:2px solid #222;margin-left:8px;padding-left:16px}}
.evt{{margin-bottom:12px;position:relative}}
.evt::before{{content:'';position:absolute;left:-21px;top:4px;width:10px;height:10px;border-radius:50%;border:2px solid #222}}
.evt .t{{color:#444;font-size:11px}}.evt .e{{color:#ccc;font-size:13px}}.evt .d{{color:#666;font-size:11px}}
.file{{padding:6px 10px;border-left:3px solid #333;margin-bottom:4px;background:#0d0d14;font-size:12px}}
.file .n{{color:#fff}}.file .s{{color:#666;float:right}}
.gist{{color:#ffcc00;font-size:12px}}.gist a{{color:#ffcc00}}
.hist{{padding:6px 0;border-bottom:1px solid #1a1a1a;font-size:12px}}
.hist .done{{color:#00ff88}}.hist .skip{{color:#666}}
.badge{{display:inline-block;padding:2px 8px;border-radius:3px;font-size:11px;font-weight:bold}}
.badge.g{{background:#00ff8822;color:#00ff88}}.badge.y{{background:#ffcc0022;color:#ffcc00}}.badge.r{{background:#ff444422;color:#ff4444}}.badge.b{{background:#4488ff22;color:#4488ff}}
footer{{text-align:center;color:#333;font-size:11px;margin-top:20px;padding-top:12px;border-top:1px solid #1a1a1a}}
footer a{{color:#555}}
</style></head><body>

<h1>Seed Tracker</h1>
<div class="sub">Cradle to grave &bull; {now} &bull; auto-refresh 60s</div>

<div class="card">
  <h2>Active Seed</h2>
  <div class="row"><span class="l">ID</span><span class="v b">{seed_id}</span></div>
  <div class="row"><span class="l">Deliverable</span><span class="v">{', '.join(deliverables) or 'TBD'}</span></div>
  <div class="row"><span class="l">Project</span><span class="v">{project_slug or 'auto-detecting'}</span></div>
  <div class="row"><span class="l">Repo</span><span class="v"><a href="{project_repo}" style="color:#4488ff">{project_repo.replace('https://github.com/','') if project_repo else 'pending'}</a></span></div>
  <div class="row"><span class="l">Injected</span><span class="v">{injected[:16] if injected else '—'}</span></div>
  <div class="row"><span class="l">Frames</span><span class="v">{frames}</span></div>
  <div class="row"><span class="l">Status</span><span class="v {'g' if resolved else 'y' if score >= 30 else 'b'}">{status_text}</span></div>
  <div class="row"><span class="l">Convergence</span><span class="v" style="color:{conv_color}">{score}%</span></div>
  <div class="bar"><div class="bar-fill" style="width:{score}%;background:{conv_color}"></div></div>
  <div class="row"><span class="l">Signals</span><span class="v">{signals} from {len(channels)} channels</span></div>
  <div style="margin-top:8px;font-size:12px;color:#666;line-height:1.5">{seed_text[:200]}{'...' if len(seed_text)>200 else ''}</div>
</div>

<div class="card">
  <h2>Sim Engine</h2>
  <div class="row"><span class="l">Status</span><span class="v g">{'RUNNING' if sim_alive else 'DEAD'}</span></div>
  <div class="row"><span class="l">Frame</span><span class="v b">{sim_frame}</span></div>
  <div class="row"><span class="l">Elapsed</span><span class="v">{sim_elapsed}</span></div>
  <div class="row"><span class="l">Remaining</span><span class="v">{sim_remaining}</span></div>
</div>

<div class="card">
  <h2>Code on Disk ({len(disk_files)} files, {sum(f["lines"] for f in disk_files)} lines)</h2>
  {disk_html}
</div>

<div class="card">
  <h2>Gists ({len(gists)})</h2>
  {gist_html}
</div>

<div class="card">
  <h2>Discussions ({len(relevant)})</h2>
  {disc_html}
</div>

<div class="card">
  <h2>Timeline</h2>
  <div class="timeline">
    {timeline_html}
  </div>
</div>

<div class="card">
  <h2>Seed History</h2>
  {history_html}
</div>

<footer>
  <a href="apps.html">App Store</a> &bull; <a href="overseer-report.html">Overseer</a> &bull; <a href="temporal-harness.html">Dashboard</a> &bull; <a href="https://github.com/kody-w/rappterbook/discussions">Discussions</a>
</footer>

</body></html>'''

    return html


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(DOCS_DIR / "seed-tracker.html"))
    args = parser.parse_args()

    html = build()
    Path(args.output).write_text(html)
    print(f"Seed tracker built: {args.output}")


if __name__ == "__main__":
    main()
