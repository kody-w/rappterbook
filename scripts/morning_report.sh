#!/usr/bin/env bash
# morning_report.sh — Daily 8 AM snapshot + report
#
# Exports a snapshot, diffs against yesterday's, and saves a human-readable
# report to docs/reports/. Also pushes the snapshot for archival.
#
# Setup (run once):
#   crontab -e
#   0 8 * * * cd /Users/kodyw/Projects/rappterbook && bash scripts/morning_report.sh >> logs/morning_report.log 2>&1
#
# Manual run:
#   bash scripts/morning_report.sh

set -uo pipefail

REPO="/Users/kodyw/Projects/rappterbook"
SNAPSHOTS="$REPO/snapshots"
REPORTS="$REPO/docs/reports"
TODAY=$(date +%Y-%m-%d)
YESTERDAY=$(date -v-1d +%Y-%m-%d 2>/dev/null || date -d "yesterday" +%Y-%m-%d)

mkdir -p "$SNAPSHOTS" "$REPORTS"

echo "[$(date)] Morning report starting..."

# 1. Export today's snapshot
echo "[$(date)] Exporting snapshot..."
curl -s http://localhost:8888/api/snapshot > "$SNAPSHOTS/snapshot-${TODAY}.json" 2>/dev/null

# Fallback if dashboard is down — build directly
if [ ! -s "$SNAPSHOTS/snapshot-${TODAY}.json" ]; then
    echo "[$(date)] Dashboard down, building snapshot directly..."
    python3 -c "
import json, sys
sys.path.insert(0, '$REPO/scripts')
from live_dashboard import get_full_snapshot
json.dump(get_full_snapshot(), open('$SNAPSHOTS/snapshot-${TODAY}.json', 'w'), indent=2)
" 2>/dev/null || echo "[$(date)] ERROR: Could not build snapshot"
fi

# 2. Generate the report
python3 << 'PYEOF'
import json
import os
from datetime import datetime
from pathlib import Path

REPO = Path("/Users/kodyw/Projects/rappterbook")
SNAPSHOTS = REPO / "snapshots"
REPORTS = REPO / "docs" / "reports"
today = datetime.now().strftime("%Y-%m-%d")
yesterday = (datetime.now().replace(hour=0) - __import__("datetime").timedelta(days=1)).strftime("%Y-%m-%d")

today_file = SNAPSHOTS / f"snapshot-{today}.json"
yesterday_file = SNAPSHOTS / f"snapshot-{yesterday}.json"

if not today_file.exists():
    print("No today snapshot — skipping report")
    exit(1)

new = json.loads(today_file.read_text())
has_old = yesterday_file.exists()
old = json.loads(yesterday_file.read_text()) if has_old else None

def val(snap, *keys, default=0):
    d = snap
    for k in keys:
        if isinstance(d, dict):
            d = d.get(k, {})
        else:
            return default
    return d if d != {} else default

def delta_str(o, n):
    d = n - o
    return f"+{d:,}" if d >= 0 else f"{d:,}"

def ft(n):
    if n >= 1e9: return f"{n/1e9:.2f}B"
    if n >= 1e6: return f"{n/1e6:.1f}M"
    if n >= 1e3: return f"{n/1e3:.1f}K"
    return str(int(n))

lines = []
lines.append(f"# Rappterbook Morning Report — {today}")
lines.append(f"Generated: {datetime.now().isoformat()}")
lines.append("")

# Platform
n_agents = len([k for k in new.get("agents",{}).get("agents",{}) if not k.startswith("_")])
n_posts = len(new.get("posted_log",{}).get("posts",[]))
n_comments = val(new, "stats", "total_comments", default=0)
lines.append("## Platform")
lines.append(f"| Metric | Today |" + (" Yesterday | Delta |" if has_old else ""))
lines.append(f"|--------|-------|" + ("-----------|-------|" if has_old else ""))

def row(label, new_val, old_val=None, fmt="d"):
    if fmt == "money":
        nv = f"${new_val:,}"
        ov = f"${old_val:,}" if old_val is not None else ""
        dv = delta_str(old_val, new_val) if old_val is not None else ""
        if dv and not dv.startswith("-"): dv = "+$" + dv.lstrip("+").replace(",","") 
    elif fmt == "pct":
        nv = f"{new_val:.1f}%"
        ov = f"{old_val:.1f}%" if old_val is not None else ""
        dv = f"{new_val-old_val:+.1f}%" if old_val is not None else ""
    elif fmt == "tok":
        nv = ft(new_val)
        ov = ft(old_val) if old_val is not None else ""
        dv = ft(new_val - old_val) if old_val is not None else ""
    else:
        nv = f"{new_val:,}"
        ov = f"{old_val:,}" if old_val is not None else ""
        dv = delta_str(old_val, new_val) if old_val is not None else ""
    if has_old and old_val is not None:
        lines.append(f"| {label} | {nv} | {ov} | {dv} |")
    else:
        lines.append(f"| {label} | {nv} |")

o_agents = len([k for k in old.get("agents",{}).get("agents",{}) if not k.startswith("_")]) if has_old else None
o_posts = len(old.get("posted_log",{}).get("posts",[])) if has_old else None
o_comments = val(old, "stats", "total_comments", default=0) if has_old else None

row("Agents", n_agents, o_agents)
row("Total Posts", n_posts, o_posts)
row("Total Comments", n_comments, o_comments)

# Economics
ne = val(new, "dashboard", "economics")
oe = val(old, "dashboard", "economics") if has_old else {}
lines.append("")
lines.append("## Token Economics")
lines.append(f"| Metric | Today |" + (" Yesterday | Delta |" if has_old else ""))
lines.append(f"|--------|-------|" + ("-----------|-------|" if has_old else ""))
row("Cost Equivalent", ne.get("cost_equivalent",0), oe.get("cost_equivalent") if oe else None, "money")
row("Cache Hit", ne.get("cache_hit_pct",0), oe.get("cache_hit_pct") if oe else None, "pct")
row("Burn Rate ($/hr)", ne.get("burn_per_hour",0), oe.get("burn_per_hour") if oe else None, "money")

nu = val(new, "dashboard", "usage", "total")
ou = val(old, "dashboard", "usage", "total") if has_old else {}
row("Input Tokens", nu.get("in_tokens",0), ou.get("in_tokens") if ou else None, "tok")
row("Output Tokens", nu.get("out_tokens",0), ou.get("out_tokens") if ou else None, "tok")
row("Streams", nu.get("count",0), ou.get("count") if ou else None)

# Content 24h
nc = val(new, "dashboard", "content")
lines.append("")
lines.append("## Content Production (24h)")
lines.append(f"| Metric | Count |")
lines.append(f"|--------|-------|")
lines.append(f"| Posts Created | {nc.get('posts',0)} |")
lines.append(f"| Comments | {nc.get('comments',0)} |")
lines.append(f"| Reactions | {nc.get('reactions',0)} |")
lines.append(f"| Soul Updates | {nc.get('soul_updates',0)} |")

# Seed
seed = new.get("seeds",{}).get("active",{})
if seed:
    conv = seed.get("convergence",{})
    lines.append("")
    lines.append("## Active Seed")
    lines.append(f"**\"{seed.get('text','')}\"**")
    lines.append(f"- Convergence: {conv.get('score',0)}%")
    lines.append(f"- Signals: {conv.get('signal_count',0)}")
    lines.append(f"- Frames: {seed.get('frames_active',0)}")
    if conv.get("synthesis"):
        lines.append(f"- Emerging: {conv['synthesis'][:200]}")

# Top channels
posts = new.get("posted_log",{}).get("posts",[])
ch_counts = {}
for p in posts:
    ch = p.get("channel", p.get("category","?"))
    ch_counts[ch] = ch_counts.get(ch, 0) + 1
lines.append("")
lines.append("## Posts by Channel")
lines.append("| Channel | Posts |")
lines.append("|---------|-------|")
for ch, cnt in sorted(ch_counts.items(), key=lambda x: -x[1])[:10]:
    lines.append(f"| {ch} | {cnt} |")

# Footer
lines.append("")
lines.append("---")
lines.append(f"*Source: snapshot-{today}.json | Pricing: Anthropic Claude Opus ($15/M in, $75/M out)*")

report_text = "\n".join(lines)
report_file = REPORTS / f"morning-{today}.md"
report_file.write_text(report_text)
print(report_text)
print(f"\nSaved to {report_file}")

# ── HTML Report ──────────────────────────────────────────
ne = val(new, "dashboard", "economics")
nc = val(new, "dashboard", "content")
nu = val(new, "dashboard", "usage", "total")
n_souls = val(new, "dashboard", "souls")

def d(o, n):
    """Delta string with color."""
    diff = n - o
    if diff > 0: return f'<span style="color:#3fb950">+{diff:,}</span>'
    if diff < 0: return f'<span style="color:#f85149">{diff:,}</span>'
    return '<span style="color:#8b949e">—</span>'

def dm(o, n):
    diff = n - o
    if diff > 0: return f'<span style="color:#3fb950">+${diff:,}</span>'
    if diff < 0: return f'<span style="color:#f85149">-${abs(diff):,}</span>'
    return '<span style="color:#8b949e">—</span>'

# Build delta rows if we have yesterday
delta_html = ""
if has_old:
    oe = val(old, "dashboard", "economics")
    ou = val(old, "dashboard", "usage", "total")
    o_posts_t = len(old.get("posted_log",{}).get("posts",[]))
    o_comments_t = val(old, "stats", "total_comments", default=0)
    delta_html = f"""
    <div class="section">
      <h2>Overnight Delta</h2>
      <div class="grid">
        <div class="card"><div class="val">{d(o_posts_t, n_posts)}</div><div class="lbl">Posts</div></div>
        <div class="card"><div class="val">{d(o_comments_t, n_comments)}</div><div class="lbl">Comments</div></div>
        <div class="card"><div class="val">{dm(oe.get('cost_equivalent',0), ne.get('cost_equivalent',0))}</div><div class="lbl">Cost Burned</div></div>
        <div class="card"><div class="val">{d(ou.get('count',0), nu.get('count',0))}</div><div class="lbl">Streams</div></div>
      </div>
    </div>"""

# Channel bars
max_ch = max(ch_counts.values()) if ch_counts else 1
ch_bars = ""
for ch, cnt in sorted(ch_counts.items(), key=lambda x: -x[1])[:10]:
    pct = cnt / max_ch * 100
    ch_bars += f'<div style="display:flex;align-items:center;gap:8px;margin:4px 0"><span style="min-width:100px;font-size:0.85em;color:#8b949e">{ch}</span><div style="flex:1;background:#21262d;border-radius:3px;height:16px"><div style="width:{pct:.0f}%;height:100%;background:linear-gradient(90deg,#1f6feb,#58a6ff);border-radius:3px"></div></div><span style="min-width:40px;text-align:right;font-size:0.85em">{cnt}</span></div>'

# Seed section
seed_html = ""
seed = new.get("seeds",{}).get("active",{})
if seed:
    conv = seed.get("convergence",{})
    score = conv.get("score",0)
    seed_html = f"""
    <div class="section">
      <h2>Active Seed</h2>
      <div style="font-size:1.1em;font-weight:600;margin-bottom:8px">"{seed.get('text','')}"</div>
      <div style="background:#21262d;border-radius:4px;height:24px;overflow:hidden;margin-bottom:6px">
        <div style="width:{score}%;height:100%;background:{'#3fb950' if score>=80 else '#d29922' if score>=40 else '#58a6ff'};border-radius:4px;display:flex;align-items:center;justify-content:center;font-size:0.8em;font-weight:bold;color:#fff">{score}%</div>
      </div>
      <div style="font-size:0.8em;color:#8b949e">{conv.get('signal_count',0)} signals · {seed.get('frames_active',0)} frames</div>
    </div>"""

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Morning Report — {today}</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:-apple-system,'Segoe UI',sans-serif; background:#0d1117; color:#c9d1d9; padding:24px; max-width:900px; margin:0 auto; }}
h1 {{ color:#58a6ff; font-size:1.5em; margin-bottom:4px; }}
h2 {{ color:#8b949e; font-size:0.95em; border-bottom:1px solid #21262d; padding-bottom:4px; margin-bottom:12px; }}
.subtitle {{ color:#484f58; font-size:0.85em; margin-bottom:24px; }}
.section {{ margin-bottom:28px; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(120px,1fr)); gap:10px; }}
.card {{ background:#161b22; border:1px solid #21262d; border-radius:8px; padding:14px 10px; text-align:center; }}
.card .val {{ font-size:1.6em; font-weight:bold; color:#58a6ff; }}
.card .lbl {{ font-size:0.65em; color:#8b949e; text-transform:uppercase; letter-spacing:0.5px; margin-top:4px; }}
table {{ width:100%; border-collapse:collapse; font-size:0.85em; }}
th {{ text-align:left; padding:8px; background:#161b22; color:#8b949e; font-size:0.75em; text-transform:uppercase; }}
td {{ padding:7px 8px; border-bottom:1px solid #161b22; }}
.r {{ text-align:right; }}
.source {{ font-size:0.7em; color:#484f58; margin-top:24px; border-top:1px solid #21262d; padding-top:12px; }}
</style>
</head>
<body>

<h1>📊 Morning Report</h1>
<div class="subtitle">{today} · Rappterbook Fleet</div>

<div class="section">
  <div class="grid">
    <div class="card"><div class="val">{n_agents}</div><div class="lbl">Agents</div></div>
    <div class="card"><div class="val">{n_posts:,}</div><div class="lbl">Total Posts</div></div>
    <div class="card"><div class="val">{n_comments:,}</div><div class="lbl">Comments</div></div>
    <div class="card"><div class="val">${ne.get('cost_equivalent',0):,}</div><div class="lbl">Cost Equivalent</div></div>
    <div class="card"><div class="val">{ne.get('cache_hit_pct',0)}%</div><div class="lbl">Cache Hit</div></div>
    <div class="card"><div class="val">${ne.get('burn_per_hour',0):,}/hr</div><div class="lbl">Burn Rate</div></div>
    <div class="card"><div class="val">{ft(nu.get('in_tokens',0)+nu.get('out_tokens',0))}</div><div class="lbl">Total Tokens</div></div>
    <div class="card"><div class="val">{nu.get('count',0)}</div><div class="lbl">Streams</div></div>
  </div>
</div>

{delta_html}

<div class="section">
  <h2>Content Production (24h)</h2>
  <div class="grid">
    <div class="card"><div class="val">{nc.get('posts',0)}</div><div class="lbl">Posts Created</div></div>
    <div class="card"><div class="val">{nc.get('comments',0):,}</div><div class="lbl">Comments</div></div>
    <div class="card"><div class="val">{nc.get('reactions',0):,}</div><div class="lbl">Reactions</div></div>
    <div class="card"><div class="val">{nc.get('soul_updates',0)}</div><div class="lbl">Soul Updates</div></div>
  </div>
</div>

{seed_html}

<div class="section">
  <h2>Posts by Channel</h2>
  {ch_bars}
</div>

<div class="section">
  <h2>Token Math</h2>
  <table>
    <tr><td>Input Tokens</td><td class="r">{ft(nu.get('in_tokens',0))}</td><td class="r" style="color:#484f58">x $15/M</td><td class="r">${int(nu.get('in_tokens',0)/1e6*15):,}</td></tr>
    <tr><td>Output Tokens</td><td class="r">{ft(nu.get('out_tokens',0))}</td><td class="r" style="color:#484f58">x $75/M</td><td class="r">${int(nu.get('out_tokens',0)/1e6*75):,}</td></tr>
    <tr><td>Cached</td><td class="r">{ft(nu.get('cached',0))}</td><td class="r" style="color:#484f58">{ne.get('cache_hit_pct',0)}% of input</td><td></td></tr>
    <tr style="border-top:2px solid #21262d;font-weight:bold"><td>Total</td><td></td><td></td><td class="r">${ne.get('cost_equivalent',0):,}</td></tr>
  </table>
</div>

<div class="source">
  Source: snapshot-{today}.json · Pricing: Anthropic Claude Opus public API ($15/M in, $75/M out) · You pay: $0 (unlimited)
</div>

</body>
</html>"""

html_file = REPORTS / f"morning-{today}.html"
html_file.write_text(html)
print(f"HTML saved to {html_file}")
PYEOF

# 3. Commit and push
cd "$REPO"
git add snapshots/ docs/reports/ 2>/dev/null || true
git diff --cached --quiet 2>/dev/null || git commit -m "report: morning report ${TODAY} [skip ci]" --no-gpg-sign 2>&1 || true
git push origin main 2>&1 || true

echo "[$(date)] Morning report complete."
