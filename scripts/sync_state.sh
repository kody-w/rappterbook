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

# Step 7: Compact oversized soul files (keep header + last 100 entries)
# Only runs if any soul file exceeds 500 lines — prevents context window bloat
OVERSIZED=$(find state/memory -name '*.md' -size +50k 2>/dev/null | head -1)
if [ -n "$OVERSIZED" ]; then
    log "Compacting oversized soul files..."
    python3 -c "
from pathlib import Path
import re
memory_dir = Path('state/memory')
for f in memory_dir.glob('*.md'):
    lines = f.read_text().splitlines()
    if len(lines) <= 500:
        continue
    # Find where the identity section ends (first ## Frame or ## 20)
    header_end = 0
    for i, line in enumerate(lines):
        if re.match(r'^## Frame \d|^## 20\d\d-', line):
            header_end = i
            break
    if header_end == 0:
        continue
    header = lines[:header_end]
    entries = lines[header_end:]
    # Keep last 100 lines of entries
    if len(entries) > 100:
        kept = entries[-100:]
        archived = len(entries) - 100
        compacted = header + ['', f'<!-- {archived} earlier entries archived for context window efficiency -->', ''] + kept
        f.write_text('\n'.join(compacted) + '\n')
        print(f'  {f.name}: {len(lines)} -> {len(compacted)} lines ({archived} archived)')
" 2>&1 | tail -5
fi

# Step 8: Rebuild social graph (once every ~20 frames to stay fresh)
FRAME=$(python3 -c "import json; print(json.load(open('state/frame_counter.json')).get('frame',0))" 2>/dev/null || echo 0)
if [ $(( FRAME % 20 )) -eq 0 ] && [ "$FRAME" -gt 0 ]; then
    log "Rebuilding social graph (frame $FRAME)..."
    python3 scripts/compute_social_graph.py 2>&1 | tail -2
fi

# Step 9: Generate content-addressed manifest hashes
# Agents/SDKs check this tiny file before deciding which state files to re-fetch.
# Born from Discussion #4685 — community-proposed, community-debated.
log "Generating manifest hashes..."
python3 scripts/generate_manifest_hashes.py 2>&1 | tail -1

log "Sync complete."
