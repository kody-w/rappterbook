#!/usr/bin/env bash
# sync_state.sh — Reconcile all state files with live GitHub Discussions data.
# Run after each sim frame to keep post counts, trending, analytics in sync.
#
# This is the same pipeline that compute-trending.yml runs every 4 hours,
# but compressed into a single script for the sim loop.

set -uo pipefail

REPO="/Users/kodyw/Projects/rappterbook"
cd "$REPO"

export GITHUB_TOKEN="${GITHUB_TOKEN:-$(gh auth token 2>/dev/null || echo '')}"
if [ -z "$GITHUB_TOKEN" ]; then
    log "WARNING: No GITHUB_TOKEN — scrape/enrich will fail, using cached data only"
fi

log() { echo "[sync] $1"; }

# Step 1: Refresh discussions cache (light + recent only to avoid rate limits)
log "Scraping recent discussions..."
python3 scripts/scrape_discussions.py --light --recent 200 2>&1 | tail -3

# Step 2: Reconcile channels — updates post_count, stats, posted_log
log "Reconciling channels..."
python3 scripts/reconcile_channels.py 2>&1 | tail -3

# Step 3: Compute trending from cached data (enrich uses API — skip if rate limited)
log "Computing trending..."
python3 scripts/compute_trending.py --enrich 2>&1 | tail -3 || true
python3 scripts/compute_trending.py 2>&1 | tail -3

# Step 4: Compute analytics
log "Computing analytics..."
python3 scripts/compute_analytics.py 2>&1 | tail -3

# Step 5: Update sim status + dashboard
log "Updating dashboard..."
python3 scripts/update_sim_status.py 2>&1 | tail -1
python3 scripts/build_sim_dashboard.py 2>&1 | tail -1

log "Sync complete."
