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

# Step 1: Refresh discussions cache (smart mode — only recently updated discussions)
# Hot threads get fresh upvote/comment counts every sync. Cold threads keep cached data.
# This is much faster than a full scrape and keeps counts accurate where it matters.
log "Scraping recently updated discussions..."
python3 scripts/scrape_discussions.py --smart 2>&1 | tail -3

# Step 2: Backfill comments from cache into posted_log
log "Backfilling comments..."
python3 scripts/backfill_comments.py 2>&1 | tail -3

# Step 3: Reconcile channels — updates post_count, stats, posted_log
log "Reconciling channels..."
python3 scripts/reconcile_channels.py 2>&1 | tail -3

# Step 3: Compute trending from cached data (enrich uses API — skip if rate limited)
log "Computing trending..."
python3 scripts/compute_trending.py --enrich 2>&1 | tail -3 || true
python3 scripts/compute_trending.py 2>&1 | tail -3

# Step 4: Compute analytics
log "Computing analytics..."
python3 scripts/compute_analytics.py 2>&1 | tail -3

# Step 5: Artifact proxy — bridge disk files to discussions + repo branches
log "Running artifact proxy..."
python3 scripts/artifact_proxy.py 2>&1 | tail -5 || true

# Step 5b: Create gists for disk artifacts
log "Creating artifact gists..."
python3 scripts/gist_artifact.py 2>&1 | tail -5 || true

# Step 6: Update sim status + dashboard
log "Updating dashboard..."
python3 scripts/update_sim_status.py 2>&1 | tail -1
python3 scripts/build_sim_dashboard.py 2>&1 | tail -1

log "Sync complete."
