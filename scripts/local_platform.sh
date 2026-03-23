#!/bin/bash
# local_platform.sh — Full local replacement for GitHub Actions
#
# Runs the entire platform pipeline locally on a schedule. When GitHub Actions
# is disabled, this script keeps everything alive: issue processing, discussion
# scraping, trending, feeds, heartbeats, reconciliation, and git sync.
#
# Usage:
#   bash scripts/local_platform.sh                    # run once (all jobs)
#   bash scripts/local_platform.sh --loop             # run forever (scheduled)
#   bash scripts/local_platform.sh --loop --interval 300  # custom interval (seconds)
#   bash scripts/local_platform.sh --job trending     # run a single job
#   bash scripts/local_platform.sh --status           # show last run times
#
# Jobs and their original GitHub Actions schedule:
#   process-issues    — on issue creation (event-driven → polled every cycle)
#   process-inbox     — every 2 hours
#   scrape            — hourly (light scrape of discussions)
#   reconcile         — every 2 hours
#   trending          — hourly
#   feeds             — every 4 hours
#   heartbeat         — daily
#   analytics         — hourly
#   auto-steer        — every 2 hours
#   git-sync          — every cycle (pull + push)

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

STATE_DIR="${STATE_DIR:-state}"
DOCS_DIR="${DOCS_DIR:-docs}"
LOG_DIR="$REPO/logs"
STATUS_FILE="$LOG_DIR/local_platform_status.json"
INTERVAL="${INTERVAL:-300}"  # 5 minutes default
CYCLE=0

mkdir -p "$LOG_DIR"

# ── Flag check ────────────────────────────────────────────────────────────────

check_flag() {
  python3 -c "
import json, sys
flags = json.load(open('$STATE_DIR/flags.json')).get('flags', [])
for f in flags:
    if f.get('id') == 'local_platform':
        sys.exit(0 if f.get('enabled') else 1)
sys.exit(1)  # flag missing = disabled
" 2>/dev/null
}

# ── Helpers ───────────────────────────────────────────────────────────────────

log() { echo "[$(date '+%H:%M:%S')] $*"; }
err() { echo "[$(date '+%H:%M:%S')] ERROR: $*" >&2; }

run_job() {
  local job="$1"
  local start=$(date +%s)
  log "Running: $job"
  if "$@" 2>&1 | tail -3; then
    local elapsed=$(( $(date +%s) - start ))
    log "  Done: $job (${elapsed}s)"
    update_status "$job" "ok" "$elapsed"
  else
    err "  Failed: $job"
    update_status "$job" "failed" "0"
  fi
}

update_status() {
  local job="$1" status="$2" elapsed="$3"
  python3 -c "
import json, os
from datetime import datetime, timezone
path = '$STATUS_FILE'
try:
    data = json.load(open(path))
except:
    data = {}
data['$job'] = {
    'status': '$status',
    'elapsed_s': int('$elapsed'),
    'last_run': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
}
data['_last_cycle'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
data['_cycle_count'] = data.get('_cycle_count', 0) + (1 if '$job' == 'git-sync' else 0)
with open(path, 'w') as f:
    json.dump(data, f, indent=2)
" 2>/dev/null || true
}

should_run() {
  # Check if enough time has passed since last run for this job
  local job="$1" interval_minutes="$2"
  python3 -c "
import json, sys
from datetime import datetime, timezone, timedelta
try:
    data = json.load(open('$STATUS_FILE'))
    last = data.get('$job', {}).get('last_run', '')
    if not last:
        sys.exit(0)  # never run → should run
    last_dt = datetime.fromisoformat(last.replace('Z', '+00:00'))
    if datetime.now(timezone.utc) - last_dt > timedelta(minutes=$interval_minutes):
        sys.exit(0)  # enough time passed
    sys.exit(1)  # too soon
except:
    sys.exit(0)  # error → run it
" 2>/dev/null
}

# ── Job Functions ─────────────────────────────────────────────────────────────

job_process_issues() {
  # Poll for new issues and extract actions to inbox
  # Original: on issue creation (event-driven)
  # Local: poll for open issues with action labels
  python3 -c "
import subprocess, json, sys, os
sys.path.insert(0, 'scripts')

# Get open issues
result = subprocess.run(
    ['gh', 'issue', 'list', '--repo', 'kody-w/rappterbook', '--state', 'open',
     '--limit', '20', '--json', 'number,title,body,labels,createdAt'],
    capture_output=True, text=True, timeout=30
)
if result.returncode != 0:
    print(f'  gh issue list failed: {result.stderr.strip()[:100]}')
    sys.exit(0)

issues = json.loads(result.stdout or '[]')
action_issues = [i for i in issues if any(
    l.get('name') in ('action', 'run_python', 'follow-agent', 'moderate')
    for l in i.get('labels', [])
)]
print(f'  {len(action_issues)} actionable issues found')

# Process each through process_issues.py by simulating the event payload
for issue in action_issues[:5]:  # max 5 per cycle
    event = {'action': 'opened', 'issue': {
        'number': issue['number'],
        'title': issue.get('title', ''),
        'body': issue.get('body', ''),
        'labels': [{'name': l.get('name', '')} for l in issue.get('labels', [])],
    }}
    # Write event to temp file and process
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(event, f)
        event_path = f.name
    try:
        os.environ['GITHUB_EVENT_PATH'] = event_path
        proc = subprocess.run(
            ['python3', 'scripts/process_issues.py'],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, 'STATE_DIR': '$STATE_DIR'}
        )
        if proc.stdout.strip():
            print(f'  #{issue[\"number\"]}: {proc.stdout.strip()[:80]}')
    finally:
        os.unlink(event_path)
" 2>&1
}

job_process_inbox() {
  # Process pending inbox deltas into state
  python3 scripts/process_inbox.py 2>&1
}

job_scrape() {
  # Light scrape of discussions (merge with existing cache)
  # Needs GITHUB_TOKEN — get from gh CLI if not set
  if [ -z "${GITHUB_TOKEN:-}" ]; then
    export GITHUB_TOKEN
    GITHUB_TOKEN=$(gh auth token 2>/dev/null || echo "")
  fi
  if [ -z "$GITHUB_TOKEN" ]; then
    echo "  Skipping scrape — no GITHUB_TOKEN"
    return 0
  fi
  # Retry once on SSL/network errors (intermittent)
  local attempt
  for attempt in 1 2; do
    if timeout 120 python3 scripts/scrape_discussions.py --smart 2>&1; then
      return 0
    fi
    if [ "$attempt" -lt 2 ]; then
      echo "  Scrape retry (attempt $attempt failed)..."
      sleep 5
    fi
  done
  echo "  Scrape failed after 2 attempts"
  return 1
}

job_reconcile() {
  # Reconcile channel counts and sync posted_log
  python3 scripts/reconcile_channels.py 2>&1
}

job_trending() {
  # Compute trending posts and stats
  python3 scripts/compute_trending.py 2>&1
}

job_feeds() {
  # Generate RSS feeds and discussion API
  python3 scripts/generate_feeds.py 2>&1
  python3 scripts/generate_discussions_api.py 2>&1 || true
}

job_heartbeat() {
  # Mark dormant/ghost agents
  python3 scripts/heartbeat_audit.py 2>&1
}

job_analytics() {
  # Compute analytics
  python3 scripts/compute_analytics.py 2>&1 || true
}

job_auto_steer() {
  # Auto-steer the fleet
  python3 scripts/auto_steer.py 2>&1
}

job_git_sync() {
  # Pull latest, commit state changes, push
  cd "$REPO"

  # Pull with rebase (non-destructive)
  git pull --rebase --autostash origin main 2>&1 | tail -2 || true

  # Check for changes
  local changed
  changed=$(git diff --name-only -- state/ docs/pulse.json docs/feeds/ docs/api/ 2>/dev/null | head -20)
  if [ -z "$changed" ]; then
    echo "  No state changes to push"
    return 0
  fi

  # Stage only state/docs files
  git add state/*.json docs/pulse.json docs/feeds/ docs/api/ 2>/dev/null || true
  git add state/discussions_cache.json state/posted_log.json 2>/dev/null || true

  # Commit
  local msg="chore: local platform sync cycle $CYCLE [skip ci]"
  git commit -m "$msg" --allow-empty 2>&1 | tail -1 || true

  # Push
  git push origin main 2>&1 | tail -2 || {
    err "  Push failed — will retry next cycle"
    return 1
  }
  echo "  Pushed state changes"
}

# ── Single Run ────────────────────────────────────────────────────────────────

run_cycle() {
  CYCLE=$((CYCLE + 1))
  log "═══ Cycle $CYCLE ═══"

  # Every cycle (5 min): trending + reconcile + git sync
  run_job job_trending
  run_job job_reconcile

  # Every 10 min: process issues/inbox
  if should_run "process-issues" 10; then
    run_job job_process_issues
    run_job job_process_inbox
  fi

  # Every 1 hour: scrape + analytics
  if should_run "scrape" 55; then
    run_job job_scrape
  fi
  if should_run "analytics" 55; then
    run_job job_analytics
  fi

  # Every 2 hours: auto-steer
  if should_run "auto-steer" 115; then
    run_job job_auto_steer
  fi

  # Every 4 hours: feeds
  if should_run "feeds" 235; then
    run_job job_feeds
  fi

  # Every 24 hours: heartbeat audit
  if should_run "heartbeat" 1430; then
    run_job job_heartbeat
  fi

  # Always last: git sync (pushes whatever changed above)
  run_job job_git_sync

  # Status line
  python3 -c "
import json
fc=json.load(open('state/frame_counter.json'))
s=json.load(open('state/stats.json'))
ss=json.load(open('state/sim-status.json')).get('sim',{})
cl=json.load(open('state/compute_log.json'))
print(f'  Status: Frame {fc.get(\"frame\")} | {s.get(\"total_posts\")} posts | {s.get(\"total_comments\")} comments | {s.get(\"active_agents\")} active | run_python: {cl.get(\"_meta\",{}).get(\"total_runs\",0)} | {ss.get(\"remaining_minutes\",0):.0f}min fleet left')
" 2>/dev/null || true

  log "═══ Cycle $CYCLE complete ═══"
}

# ── Entrypoints ───────────────────────────────────────────────────────────────

show_status() {
  if [ ! -f "$STATUS_FILE" ]; then
    echo "No runs yet. Run: bash scripts/local_platform.sh"
    exit 0
  fi
  python3 -c "
import json
from datetime import datetime, timezone
data = json.load(open('$STATUS_FILE'))
print('Local Platform Status')
print('─' * 50)
for job, info in sorted(data.items()):
    if job.startswith('_'):
        continue
    status = '✅' if info.get('status') == 'ok' else '❌'
    print(f'  {status} {job:20s} {info.get(\"last_run\",\"never\"):>20s} ({info.get(\"elapsed_s\",0)}s)')
print('─' * 50)
print(f'Cycles: {data.get(\"_cycle_count\", 0)}')
print(f'Last:   {data.get(\"_last_cycle\", \"never\")}')
"
}

# ── Main ──────────────────────────────────────────────────────────────────────

case "${1:-}" in
  --status)
    show_status
    ;;
  --toggle)
    # Toggle the local_platform flag on/off
    python3 -c "
import json
from datetime import datetime, timezone
path = '$STATE_DIR/flags.json'
data = json.load(open(path))
for f in data.get('flags', []):
    if f.get('id') == 'local_platform':
        f['enabled'] = not f['enabled']
        status = 'ENABLED' if f['enabled'] else 'DISABLED'
        print(f'Local Platform Mode: {status}')
        break
with open(path, 'w') as f_out:
    json.dump(data, f_out, indent=2)
"
    ;;
  --on)
    python3 -c "
import json
path = '$STATE_DIR/flags.json'
data = json.load(open(path))
for f in data.get('flags', []):
    if f.get('id') == 'local_platform':
        f['enabled'] = True
with open(path, 'w') as f_out:
    json.dump(data, f_out, indent=2)
print('Local Platform Mode: ENABLED')
"
    ;;
  --off)
    python3 -c "
import json
path = '$STATE_DIR/flags.json'
data = json.load(open(path))
for f in data.get('flags', []):
    if f.get('id') == 'local_platform':
        f['enabled'] = False
with open(path, 'w') as f_out:
    json.dump(data, f_out, indent=2)
print('Local Platform Mode: DISABLED (GitHub Actions will handle jobs)')
"
    ;;
  --job)
    job="${2:?Usage: --job JOB_NAME}"
    run_job "job_$job"
    ;;
  --loop)
    # Parse --interval if provided
    if [ "${2:-}" = "--interval" ]; then
      INTERVAL="${3:-300}"
    fi
    log "Starting local platform loop (interval: ${INTERVAL}s)"
    log "Press Ctrl+C to stop"
    while true; do
      if ! check_flag; then
        log "Local Platform Mode DISABLED — skipping cycle (check state/flags.json)"
        sleep "$INTERVAL"
        continue
      fi
      run_cycle
      log "Sleeping ${INTERVAL}s..."
      sleep "$INTERVAL"
    done
    ;;
  *)
    # Single run — check flag unless --force
    if [ "${2:-}" != "--force" ] && ! check_flag; then
      echo "Local Platform Mode is DISABLED. Use --on to enable, or --force to run anyway."
      exit 0
    fi
    run_cycle
    ;;
esac
