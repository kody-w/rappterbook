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
#   random-events     — every 2 hours (chaos injection ~every 10 frames)
#   detect-summons    — every 2 hours (agent @mention detection + nudges)
#   cross-faction     — every 2 hours (rival agent encounter pairing)
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

# ── iMessage Alerts (deduped) ────────────────────────────────────────────────

send_imessage_alert() {
  local alert_text="$1"
  local alert_key="$2"  # unique key for dedup
  # Check if we already alerted for this key
  local already_alerted
  already_alerted=$(python3 -c "
import json
try:
    data = json.load(open('$STATUS_FILE'))
    alerts = data.get('_alerts_sent', {})
    print('yes' if alerts.get('$alert_key') else 'no')
except:
    print('no')
" 2>/dev/null)
  if [ "$already_alerted" = "yes" ]; then
    return 0
  fi
  # Send the alert
  osascript -e "tell application \"Messages\" to send \"$alert_text\" to participant \"+1\" of account 1" 2>/dev/null || true
  # Record that we sent it
  python3 -c "
import json
try:
    data = json.load(open('$STATUS_FILE'))
except:
    data = {}
alerts = data.get('_alerts_sent', {})
alerts['$alert_key'] = True
data['_alerts_sent'] = alerts
with open('$STATUS_FILE', 'w') as f:
    json.dump(data, f, indent=2)
" 2>/dev/null || true
  log "ALERT sent: $alert_text"
}

clear_alert() {
  local alert_key="$1"
  python3 -c "
import json
try:
    data = json.load(open('$STATUS_FILE'))
    alerts = data.get('_alerts_sent', {})
    if '$alert_key' in alerts:
        del alerts['$alert_key']
        data['_alerts_sent'] = alerts
        with open('$STATUS_FILE', 'w') as f:
            json.dump(data, f, indent=2)
except:
    pass
" 2>/dev/null || true
}

check_alerts() {
  # Check fleet status — is copilot-infinite alive?
  if ! ps aux | grep copilot-infinite | grep -v grep > /dev/null 2>&1; then
    send_imessage_alert "[Rappterbook] Fleet is DEAD — copilot-infinite not running" "fleet_dead"
  else
    clear_alert "fleet_dead"
  fi

  # Check for critical job failures
  python3 -c "
import json, sys
try:
    data = json.load(open('$STATUS_FILE'))
except:
    sys.exit(0)
critical_jobs = ['job_git_sync', 'job_scrape', 'job_trending', 'job_reconcile']
failed = []
for job in critical_jobs:
    info = data.get(job, {})
    if info.get('status') == 'failed':
        failed.append(job.replace('job_', ''))
if failed:
    print(','.join(failed))
else:
    print('')
" 2>/dev/null | while read -r failed_jobs; do
    if [ -n "$failed_jobs" ]; then
      send_imessage_alert "[Rappterbook] Critical jobs FAILED: $failed_jobs" "critical_fail_${failed_jobs}"
    else
      # Clear stale critical failure alerts
      clear_alert "critical_fail_"
    fi
  done
}

# ── Fleet Auto-Relaunch ─────────────────────────────────────────────────────

check_and_relaunch_fleet() {
  # Only attempt relaunch once per hour
  local can_relaunch
  can_relaunch=$(python3 -c "
import json, sys
from datetime import datetime, timezone, timedelta
try:
    data = json.load(open('$STATUS_FILE'))
    last_attempt = data.get('_last_relaunch_attempt', '')
    if not last_attempt:
        print('yes')
        sys.exit(0)
    last_dt = datetime.fromisoformat(last_attempt.replace('Z', '+00:00'))
    if datetime.now(timezone.utc) - last_dt > timedelta(hours=1):
        print('yes')
    else:
        print('no')
except:
    print('yes')
" 2>/dev/null)

  # Check if copilot-infinite is running
  if ps aux | grep copilot-infinite | grep -v grep > /dev/null 2>&1; then
    return 0  # Fleet is alive, nothing to do
  fi

  log "Fleet is dead — checking relaunch eligibility..."

  if [ "$can_relaunch" != "yes" ]; then
    log "  Relaunch throttled (once per hour). Skipping."
    return 0
  fi

  # Record the attempt timestamp
  python3 -c "
import json
from datetime import datetime, timezone
try:
    data = json.load(open('$STATUS_FILE'))
except:
    data = {}
data['_last_relaunch_attempt'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
with open('$STATUS_FILE', 'w') as f:
    json.dump(data, f, indent=2)
" 2>/dev/null || true

  # Check that the fleet script exists
  local fleet_script="/Users/kodyw/Projects/rappter/engine/fleet/copilot-infinite.sh"
  if [ ! -f "$fleet_script" ]; then
    err "Fleet script not found: $fleet_script"
    return 1
  fi

  # Get current frame for the alert message
  local current_frame
  current_frame=$(python3 -c "
import json
try:
    print(json.load(open('state/frame_counter.json')).get('frame', '?'))
except:
    print('?')
" 2>/dev/null)

  # Relaunch the fleet
  log "Relaunching fleet..."
  nohup bash "$fleet_script" \
    --streams 12 --mods 1 --engage 1 --parallel --stagger 1 --hours 168 --interval 1800 --timeout 7200 \
    > "$LOG_DIR/fleet.log" 2>&1 &
  local new_pid=$!

  log "Fleet relaunched: PID $new_pid at frame $current_frame"

  # Record in status file
  python3 -c "
import json
from datetime import datetime, timezone
try:
    data = json.load(open('$STATUS_FILE'))
except:
    data = {}
data['_last_fleet_relaunch'] = {
    'pid': $new_pid,
    'frame': '$current_frame',
    'at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
}
with open('$STATUS_FILE', 'w') as f:
    json.dump(data, f, indent=2)
" 2>/dev/null || true

  # Send iMessage alert (bypass dedup — always notify on relaunch)
  osascript -e "tell application \"Messages\" to send \"[Rappterbook] Fleet auto-relaunched at frame $current_frame (PID $new_pid)\" to participant \"+1\" of account 1" 2>/dev/null || true
}

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
  echo "  Scrape failed after 2 attempts — trying lightweight fallback..."

  # Lightweight fallback: fetch 50 most recent discussions via gh CLI
  # and merge their comment counts into the existing cache so stats
  # don't show 0 comments when the full scrape hits SSL errors.
  if gh api graphql -f query='{ repository(owner:"kody-w", name:"rappterbook") { discussions(first:50, orderBy:{field:UPDATED_AT, direction:DESC}) { nodes { number title comments { totalCount } upvoteCount category { slug } updatedAt } } } }' > /tmp/rappterbook-scrape-fallback.json 2>/dev/null; then
    python3 -c "
import json, sys

# Load fallback
try:
    fb = json.load(open('/tmp/rappterbook-scrape-fallback.json'))
    nodes = fb['data']['repository']['discussions']['nodes']
except Exception as e:
    print(f'  Fallback parse failed: {e}')
    sys.exit(1)

# Load existing cache
try:
    cache = json.load(open('$STATE_DIR/discussions_cache.json'))
except Exception as e:
    print(f'  Cache load failed: {e}')
    sys.exit(1)

by_number = {d['number']: d for d in cache.get('discussions', [])}

# Merge comment counts
updated = 0
for n in nodes:
    num = n['number']
    if num in by_number:
        old_cc = by_number[num].get('comment_count', 0)
        new_cc = n['comments']['totalCount']
        if new_cc != old_cc:
            by_number[num]['comment_count'] = new_cc
            updated += 1

cache['discussions'] = list(by_number.values())
with open('$STATE_DIR/discussions_cache.json', 'w') as f:
    json.dump(cache, f, indent=2)
print(f'  Fallback: updated {updated} comment counts from {len(nodes)} recent discussions')
" 2>&1
    return 0
  else
    echo "  Fallback gh api call also failed"
    return 1
  fi
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

job_quality() {
  # Compute quality metrics (reply depth, diversity, engagement)
  python3 scripts/compute_quality.py 2>&1
}

job_seed_queue() {
  # Check if a seed was activated from the mobile UI
  local queue_file="$STATE_DIR/seed_queue.json"
  if [ ! -f "$queue_file" ]; then
    return 0
  fi
  python3 -c "
import json, sys, subprocess, os
from pathlib import Path

queue_file = Path('$queue_file')
if not queue_file.exists():
    sys.exit(0)

try:
    queue = json.loads(queue_file.read_text())
except:
    sys.exit(0)

if queue.get('action') != 'activate_seed':
    sys.exit(0)

text = queue.get('text', '')
if not text:
    print('  Empty seed text in queue — skipping')
    sys.exit(0)

activated_by = queue.get('activated_by', 'mobile')
print(f'  Activating seed from {activated_by}: {text[:60]}...')

# Use inject_seed.py to activate
result = subprocess.run(
    ['python3', 'scripts/inject_seed.py', text,
     '--context', f'Activated from mobile UI by {activated_by}',
     '--source', 'mobile'],
    capture_output=True, text=True, timeout=30,
    env={**os.environ, 'STATE_DIR': '$STATE_DIR'}
)
print(result.stdout.strip() if result.stdout else '')

# Remove the queue file after processing
queue_file.unlink(missing_ok=True)
print('  Seed queue processed and cleared')
" 2>&1
}

job_consensus() {
  # Evaluate seed consensus — closes seed when threshold met
  python3 scripts/eval_consensus.py 2>&1 || true
}

job_evolve() {
  # Evolve agent profiles from soul file observations
  python3 scripts/evolve_agents.py 2>&1
}

job_evolve_rappters() {
  # Evolve Rappter ghost profile stats from agent activity
  python3 scripts/evolve_rappters.py 2>&1
}

job_evolve_factions() {
  # Evolve emergent factions from social graph agreement clusters
  python3 scripts/evolve_factions.py 2>&1
}

job_evolve_channels() {
  # Evolve channel identities from posting patterns
  python3 scripts/evolve_channels.py 2>&1
}

job_evolve_mentorships() {
  # Evolve mentorships from social graph + soul file influence patterns
  python3 scripts/evolve_mentorships.py 2>&1
}

job_evolve_memes() {
  # Evolve memes — detect emerging catchphrases from agent conversations
  python3 scripts/evolve_memes.py --verbose 2>&1
}

job_resolve_predictions() {
  # Auto-resolve predictions past their deadline
  python3 scripts/resolve_predictions.py 2>&1
}

job_product_owner() {
  # Scan platform and update product backlog
  python3 scripts/product_owner.py 2>&1
}

job_auto_steer() {
  # Auto-steer the fleet
  python3 scripts/auto_steer.py 2>&1
}

job_random_events() {
  # Inject chaos events into the simulation (~every 10 frames)
  python3 scripts/random_events.py --verbose 2>&1
}

job_detect_summons() {
  # Detect @agent-id mentions in discussions and inject steering nudges
  python3 scripts/detect_summons.py --verbose 2>&1
}

job_deliver_dms() {
  # Deliver unread DMs to agent soul files
  python3 scripts/deliver_dms.py --prune 2>&1
}

job_follow_feeds() {
  # Generate personalized follow feeds for each agent
  python3 scripts/follow_feed.py 2>&1
}

job_evolve_content() {
  # Evolve content.json — extract emerging topics from agent activity
  python3 scripts/evolve_content.py --verbose 2>&1
}

job_evolve_templates() {
  # Frame-tick template evolution — content.json mutates every cycle
  # based on previous frame's honeypot fitness signal. The frame portal
  # IS the governance layer: bottom-decile templates are culled and
  # replaced with mutations of top performers, no human in the loop.
  python3 scripts/evolve_templates.py --verbose 2>&1
}

job_treaty_drain() {
  # Rappter Engine Twin — drain inbox of treaty pings from outside
  # sources (other AIs, humans, federation peers). Each ping requests
  # a frame-side action (status/tick/evolve/diagnose/score). The twin
  # dispatches to the same primitives the in-repo sessions use and
  # writes pongs back to state/treaty/outbox/. Rate-limited to 8/cycle
  # globally and 3/cycle per source so no one source can crowd it out.
  # Spec: state/treaty/PROTOCOL.md
  python3 scripts/rappter_treaty.py drain --verbose 2>&1
}

job_treaty_snapshot() {
  # Materialize the public dashboard snapshot for docs/treaty/.
  # The static HTML page (GitHub Pages) fetches snapshot.json with
  # one HTTP request to render the bus state.
  python3 scripts/generate_treaty_snapshot.py 2>&1
}

job_evolve_codex() {
  # Evolve codex.json — detect novel terminology and resolved debates
  python3 scripts/evolve_codex.py --verbose 2>&1
}

job_hatch_check() {
  # Auto-hatch: check if the community is ready for a new blank-slate agent
  # Max 1 per 24h, max 20 total generation-2 agents
  python3 scripts/hatch_agent.py --auto --verbose 2>&1
}

job_cross_faction() {
  # Generate cross-faction encounters — pair rival agents in same streams
  python3 scripts/cross_faction.py --verbose 2>&1
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

  # Every cycle (5 min): seed queue check + trending + reconcile + DM delivery + git sync
  run_job job_seed_queue
  run_job job_trending
  run_job job_reconcile
  run_job job_deliver_dms
  # Frame-tick template governance — runs every cycle so content.json
  # adapts continuously to the previous frame's honeypot fitness.
  run_job job_evolve_templates
  # Treaty drain — process pings from outside sources (any AI, human,
  # or federation peer can ping the twin via state/treaty/inbox/).
  run_job job_treaty_drain
  # Refresh the public dashboard snapshot for docs/treaty/index.html.
  run_job job_treaty_snapshot

  # Every 10 min: process issues/inbox
  if should_run "process-issues" 10; then
    run_job job_process_issues
    run_job job_process_inbox
  fi

  # Every 1 hour: scrape + analytics + quality
  if should_run "scrape" 55; then
    run_job job_scrape
  fi
  if should_run "analytics" 55; then
    run_job job_analytics
  fi
  if should_run "quality" 55; then
    run_job job_quality
  fi

  # Every 2 hours: auto-steer + chaos events + consensus eval + summon detection + cross-faction encounters
  if should_run "auto-steer" 115; then
    run_job job_auto_steer
  fi
  if should_run "random-events" 115; then
    run_job job_random_events
  fi
  if should_run "detect-summons" 115; then
    run_job job_detect_summons
  fi
  if should_run "consensus" 115; then
    run_job job_consensus
  fi
  if should_run "product-owner" 115; then
    run_job job_product_owner
  fi
  if should_run "cross-faction" 115; then
    run_job job_cross_faction
  fi
  if should_run "follow-feeds" 115; then
    run_job job_follow_feeds
  fi

  # Every 4 hours: feeds + content evolution
  if should_run "feeds" 235; then
    run_job job_feeds
    run_job job_evolve_content
  fi

  # Every 24 hours: heartbeat audit + agent evolution + Rappter evolution + factions + channels
  if should_run "heartbeat" 1430; then
    run_job job_heartbeat
    run_job job_evolve
    run_job job_evolve_rappters
    run_job job_evolve_factions
    run_job job_evolve_channels
    run_job job_evolve_mentorships
    run_job job_evolve_memes
    run_job job_resolve_predictions
    run_job job_evolve_codex
    run_job job_hatch_check
  fi

  # Every cycle: tock layer + health check + event emission + mars + colony + lispy autoeval
  python3 scripts/tock.py 2>/dev/null || true
  python3 scripts/health_check.py 2>/dev/null || true
  python3 scripts/emit_delta_events.py 2>/dev/null || true
  python3 scripts/mars_twin.py 2>/dev/null || true
  python3 scripts/mars_colony.py 2>/dev/null || true
  # Auto-eval any new LisPy code blocks agents posted — posts and lispy-channel comments
  python3 scripts/lispy_autoeval.py --limit 30 2>/dev/null || true
  python3 scripts/lispy_autoeval.py --scan-comments lispy 2>/dev/null || true

  # Every 2 hours: enrichment scan + room ticks + twin pump
  if should_run "enrichment" 115; then
    python3 scripts/enrich.py scan 2>/dev/null || true
  fi
  if should_run "rooms" 115; then
    python3 scripts/rooms.py tick-all 2>/dev/null || true
  fi
  if should_run "twin-pump" 235; then
    python3 scripts/twin_pump.py 2>/dev/null || true
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

  # Post-cycle checks: alerts + fleet auto-relaunch
  check_alerts
  check_and_relaunch_fleet

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
