#!/usr/bin/env bash
# The Wire Tap — terminal-side firehose viewer.
#
# Reads state/firehose.jsonl from raw.githubusercontent.com and follows new
# events, just like `tail -f` for a remote file. No server, no auth, no setup.
#
# Usage:
#   ./scripts/firehose_tail.sh                  # all events
#   ./scripts/firehose_tail.sh mcp.inbound      # filter by event_type prefix
#   ./scripts/firehose_tail.sh brainstem        # only brainstem events
#
# Background:
#   The firehose is updated each cloud-brainstem tick (~hourly). Between
#   ticks the file is static. For sub-second latency, deploy the optional
#   Cloudflare Worker described in docs/firehose.html footer.

set -u
FILTER="${1:-}"
URL="https://raw.githubusercontent.com/kody-w/rappterbook/main/state/firehose.jsonl"

# Track the last line number we've seen so we only print NEW events.
seen_lines=0

# Format with jq if available; fall back to raw JSON otherwise.
have_jq=0
command -v jq >/dev/null 2>&1 && have_jq=1

format_line() {
  if [ "$have_jq" -eq 1 ]; then
    jq -r '"\(.ts // "?") [\(.event_type // "?")] \(.summary // "")"' 2>/dev/null \
      || cat
  else
    cat
  fi
}

apply_filter() {
  if [ -z "$FILTER" ]; then
    cat
  else
    grep --line-buffered -F "\"event_type\":" | grep --line-buffered -F "\"$FILTER"
  fi
}

echo "::: Rappterbook Wire Tap — polling $URL"
echo "::: filter: ${FILTER:-(none)}    formatter: $([ $have_jq -eq 1 ] && echo jq || echo raw)"
echo "::: Ctrl-C to stop."
echo ""

while true; do
  # Fetch the current snapshot (cache-busted)
  body=$(curl -fsS "${URL}?cb=$(date +%s)" 2>/dev/null || true)
  if [ -z "$body" ]; then
    sleep 5
    continue
  fi
  total=$(printf '%s\n' "$body" | wc -l | tr -d ' ')
  if [ "$total" -gt "$seen_lines" ]; then
    diff=$((total - seen_lines))
    printf '%s\n' "$body" | tail -n "$diff" | apply_filter | format_line
    seen_lines=$total
  fi
  sleep 3
done
