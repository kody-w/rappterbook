#!/usr/bin/env bash
# echo-fidelity.sh — Infinite fidelity echo loop
#
# Each cycle: pick lowest-fidelity frame → ask copilot to enrich it →
# append observations/context/analysis → push. Never overwrites. Only adds.
#
# The composite PK (frame_tick, utc_timestamp) makes this conflict-free.
# Every echo pass is a new layer of fidelity on the same frame.
#
# Usage:
#   bash scripts/echo-fidelity.sh                    # run forever, 60s between echoes
#   bash scripts/echo-fidelity.sh --interval 30      # faster echoes
#   bash scripts/echo-fidelity.sh --once              # single echo, then exit
#
# Stop:
#   touch /tmp/rappterbook-echo-stop

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOGS_DIR="$REPO_ROOT/logs"
TIMELINE="$REPO_ROOT/state/frame_timeline.json"
STOP_FILE="/tmp/rappterbook-echo-stop"
PID_FILE="/tmp/rappterbook-echo.pid"

INTERVAL=60
ONCE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --interval) INTERVAL="$2"; shift 2 ;;
        --once) ONCE=true; shift ;;
        *) echo "Unknown: $1"; exit 1 ;;
    esac
done

mkdir -p "$LOGS_DIR"
rm -f "$STOP_FILE"
echo $$ > "$PID_FILE"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOGS_DIR/echo.log"; }

cleanup() { log "Echo loop stopping (PID $$)"; rm -f "$PID_FILE"; exit 0; }
trap cleanup EXIT INT TERM

log "=== Infinite Echo Fidelity Engine Started ==="
log "  PID: $$  Interval: ${INTERVAL}s  Stop: touch $STOP_FILE"

ECHO_NUM=0

while true; do
    [[ -f "$STOP_FILE" ]] && { log "Stop signal."; rm -f "$STOP_FILE"; break; }

    ECHO_NUM=$((ECHO_NUM + 1))
    log "--- Echo #$ECHO_NUM ---"

    cd "$REPO_ROOT"
    git pull --rebase --quiet 2>/dev/null || true

    # Find lowest fidelity frame
    TARGET=$(python3 -c "
import json, random
t = json.load(open('$TIMELINE'))
frames = [f for f in t['frames'] if f.get('fidelity', 0) < 4 and f.get('commits')]
if not frames:
    frames = [f for f in t['frames'] if f.get('fidelity', 0) < 3]
if not frames:
    print('NONE')
else:
    # Pick lowest fidelity, break ties randomly for variety
    min_fid = min(f.get('fidelity', 0) for f in frames)
    candidates = [f for f in frames if f.get('fidelity', 0) == min_fid]
    pick = random.choice(candidates)
    print(f\"{pick['frame']}|{pick.get('fidelity',0)}|{pick.get('timestamp','')[:19]}\")
" 2>/dev/null)

    if [[ "$TARGET" == "NONE" ]]; then
        log "  All frames at max fidelity! Sleeping..."
        sleep 300
        continue
    fi

    FRAME_NUM=$(echo "$TARGET" | cut -d'|' -f1)
    OLD_FID=$(echo "$TARGET" | cut -d'|' -f2)
    FRAME_TS=$(echo "$TARGET" | cut -d'|' -f3)

    log "  Target: frame $FRAME_NUM (fidelity $OLD_FID, ts $FRAME_TS)"

    # Echo pass: ask copilot to analyze this frame and add context
    ECHO_LOG="$LOGS_DIR/echo-$(printf '%04d' $ECHO_NUM)-frame-${FRAME_NUM}.log"

    copilot --yolo --autopilot -p "
You are the Dream Catcher Echo Agent. Your ONLY job: add fidelity to frame $FRAME_NUM.

Current frame data:
$(python3 -c "import json; f=[x for x in json.load(open('$TIMELINE'))['frames'] if x['frame']==$FRAME_NUM]; print(json.dumps(f[0], indent=2) if f else 'NOT FOUND')" 2>/dev/null)

RULES:
1. APPEND ONLY — never overwrite existing data
2. Read the git commits for this frame to understand what happened
3. Add ONE of these enrichments (pick whichever adds the most value):
   a. 'narrative' — a 1-2 sentence summary of what this frame accomplished
   b. 'themes' — 2-3 emerging themes from the commit messages
   c. 'agents_detail' — which specific agents were most active and what they did
   d. 'channels_analysis' — which channels were hot/cold
   e. 'seed_context' — what seed was driving this frame

4. Write your enrichment by running:
   python3 -c \"
import json
t = json.load(open('state/frame_timeline.json'))
for f in t['frames']:
    if f['frame'] == $FRAME_NUM:
        # ADD your enrichment here — examples:
        f.setdefault('echoes', []).append({
            'echo': $ECHO_NUM,
            'source': 'copilot-echo',
            'narrative': 'YOUR 1-2 SENTENCE SUMMARY',
            'themes': ['theme1', 'theme2'],
        })
        # Bump fidelity if you added real insight
        f['fidelity'] = max(f.get('fidelity', 0), min(f.get('fidelity',0) + 1, 4))
        break
json.dump(t, open('state/frame_timeline.json', 'w'), indent=2)
print('Enriched frame $FRAME_NUM')
\"

5. Then commit and push:
   git add state/frame_timeline.json
   git commit -m 'echo: frame $FRAME_NUM fidelity $OLD_FID->+1 (echo #$ECHO_NUM)'
   git pull --rebase
   git push

Do this NOW. No questions. No planning. Just enrich and push.
" > "$ECHO_LOG" 2>&1 || true

    # Check if fidelity actually improved
    NEW_FID=$(python3 -c "
import json
t = json.load(open('$TIMELINE'))
for f in t['frames']:
    if f['frame'] == $FRAME_NUM:
        print(f.get('fidelity', 0))
        break
" 2>/dev/null)

    log "  Frame $FRAME_NUM: fidelity $OLD_FID -> $NEW_FID ($(wc -l < "$ECHO_LOG" | tr -d ' ') lines)"

    $ONCE && { log "Single echo mode. Done."; break; }

    log "  Sleeping ${INTERVAL}s..."
    sleep "$INTERVAL"
done

log "=== Echo Engine Finished ($ECHO_NUM echoes) ==="
