#!/usr/bin/env bash
# scribe_cron.sh — chat-driven cron for the RappterScribe singleton.
#
# Loop forever, every 30 minutes asks the brainstem (via /chat) to invoke
# RappterScribe.compose. RappterScribe handles everything inside the
# brainstem process: pop a task, ask reference Claude (subprocess), ask
# brainstem itself (recurse through /chat → StyleCoach injects rules),
# judge both, distill rules into ~/.brainstem/state/style_guide.json,
# append to ~/.brainstem/state/scribe_rounds.jsonl.
#
# No Python orchestrator. No file glue. Just chat.
#
# Usage:
#   bash scripts/scribe/scribe_cron.sh                  # every 30 min, foreground
#   nohup bash scripts/scribe/scribe_cron.sh > /tmp/scribe_cron.log 2>&1 &
#
# Env:
#   SCRIBE_INTERVAL_SEC  default 1800
#   BRAINSTEM_URL        default http://127.0.0.1:7071

set -u

INTERVAL="${SCRIBE_INTERVAL_SEC:-1800}"
URL="${BRAINSTEM_URL:-http://127.0.0.1:7071}/chat"
LOG="$HOME/.brainstem/state/scribe_cron.log"
mkdir -p "$(dirname "$LOG")"

while true; do
    TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "[$TS] tick" >> "$LOG"
    PAYLOAD=$(python3 -c '
import json, sys, time
print(json.dumps({
    "user_input": "Use RappterScribe with action=compose. Return only the raw JSON output verbatim.",
    "session_id": f"scribe-cron-{int(time.time())}",
    "conversation_history": [],
}))')
    RESP=$(curl -sS -X POST "$URL" \
        -H "Content-Type: application/json" \
        --max-time 600 \
        -d "$PAYLOAD" || echo '{"error":"curl_failed"}')
    SUMMARY=$(python3 -c '
import json, re, sys
raw = sys.stdin.read()
try:
    out = json.loads(raw)
    resp = out.get("response", "") or ""
    m = re.search(r"\{.*\}", resp, re.S)
    if m:
        j = json.loads(m.group(0))
        print(f"round={j.get(chr(34)+\"round\"+chr(34)) or j.get(\"round\")} ref={j.get(\"score_reference\")} bs={j.get(\"score_brainstem\")} gap={j.get(\"gap\")} winner={j.get(\"winner\")} rules+={len(j.get(\"rules_added\",[]))} -={len(j.get(\"rules_obsoleted\",[]))} v={j.get(\"style_version\")}")
    else:
        print("no JSON in response (cold start? rate limit?)")
except Exception as e:
    print(f"parse-error: {e}")
' <<< "$RESP")
    echo "[$TS] $SUMMARY" >> "$LOG"
    sleep "$INTERVAL"
done
