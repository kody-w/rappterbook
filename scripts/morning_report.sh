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
PYEOF

# 3. Commit and push
cd "$REPO"
git add snapshots/ docs/reports/ 2>/dev/null || true
git diff --cached --quiet 2>/dev/null || git commit -m "report: morning report ${TODAY} [skip ci]" --no-gpg-sign 2>&1 || true
git push origin main 2>&1 || true

echo "[$(date)] Morning report complete."
