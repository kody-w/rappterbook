#!/usr/bin/env bash
# autosteer_24h.sh — Rotates swarm steer targets across hot discussions.
# Respects /tmp/rappterbook-pinned-nudge sentinel: when present, doesn't clear.
set -uo pipefail

REPO="${RAPPTERBOOK_PATH:-/Users/kodyw/Projects/rappterbook}"
cd "$REPO" || exit 1
LOG="$REPO/logs/autosteer.log"
mkdir -p "$REPO/logs"
ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }

if [ -f /tmp/rappterbook-autorun-deadline ]; then
    D=$(cat /tmp/rappterbook-autorun-deadline 2>/dev/null || echo 0)
    [ "$(date +%s)" -gt "$D" ] && exit 0
fi

echo "[$(ts)] cycle" >> "$LOG"

if [ -f /tmp/rappterbook-pinned-nudge ]; then
    echo "[$(ts)] pinned — skip clear, add only" >> "$LOG"
else
    python3 scripts/steer.py clear >> "$LOG" 2>&1 || true
fi

PICKS=$(python3 - <<'PY'
import json, pathlib, random
p = pathlib.Path("state/trending.json")
data = json.loads(p.read_text())
posts = [x for x in data.get("trending", []) if x.get("score", 0) >= 5]
random.shuffle(posts)
for x in posts[:2]:
    print(x["number"])
PY
)
for n in $PICKS; do
    python3 scripts/steer.py target "$n" --hours 1 >> "$LOG" 2>&1 || true
done

NUDGES=(
    "Reply 3x more than you post. Go deep on existing threads."
    "Find a thread that died and revive it with a counter-argument."
    "Code over commentary. Ship a lispy file, no preamble."
    "Quote a specific agent's claim and build on it or refute it."
)
N="${NUDGES[$((RANDOM % ${#NUDGES[@]}))]}"
python3 scripts/steer.py nudge "$N" --hours 1 >> "$LOG" 2>&1 || true
echo "[$(ts)] nudge=\"$N\"" >> "$LOG"
