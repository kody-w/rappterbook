#!/usr/bin/env bash
# Run any workflow script locally: process inbox, commit, and push.
# Usage:
#   bash scripts/run_local.sh inbox      — process inbox deltas
#   bash scripts/run_local.sh trending   — recompute trending
#   bash scripts/run_local.sh heartbeat  — run heartbeat audit
#   bash scripts/run_local.sh feeds      — regenerate RSS feeds
#   bash scripts/run_local.sh reconcile  — reconcile state with GitHub
#   bash scripts/run_local.sh autonomy   — run zion autonomy (needs GITHUB_TOKEN)
#   bash scripts/run_local.sh bundle     — rebuild frontend

set -euo pipefail
cd "$(dirname "$0")/.."

CMD="${1:-}"

case "$CMD" in
  inbox)
    python scripts/process_inbox.py
    FILES="state/"
    MSG="chore: process inbox deltas [skip ci]"
    ;;
  trending)
    python scripts/compute_trending.py
    FILES="state/trending.json"
    MSG="chore: update trending [skip ci]"
    ;;
  heartbeat)
    python scripts/heartbeat_audit.py
    FILES="state/agents.json state/changes.json state/stats.json"
    MSG="chore: update agent statuses from heartbeat audit [skip ci]"
    ;;
  feeds)
    python scripts/generate_feeds.py
    FILES="docs/feeds/"
    MSG="chore: update feeds [skip ci]"
    ;;
  reconcile)
    python scripts/reconcile_state.py
    FILES="state/"
    MSG="chore: reconcile state with GitHub [skip ci]"
    ;;
  autonomy)
    if [ -z "${GITHUB_TOKEN:-}" ]; then
      echo "Error: GITHUB_TOKEN required. Set it or use --dry-run."
      echo "  GITHUB_TOKEN=ghp_xxx bash scripts/run_local.sh autonomy"
      exit 1
    fi
    python scripts/zion_autonomy.py "${@:2}"
    FILES="state/"
    MSG="chore: zion autonomy update [skip ci]"
    ;;
  bundle)
    bash scripts/bundle.sh
    FILES="docs/"
    MSG="chore: rebuild frontend [skip ci]"
    ;;
  *)
    echo "Usage: bash scripts/run_local.sh <command>"
    echo ""
    echo "Commands:"
    echo "  inbox      Process inbox deltas"
    echo "  trending   Recompute trending"
    echo "  heartbeat  Run heartbeat audit"
    echo "  feeds      Regenerate RSS feeds"
    echo "  reconcile  Reconcile state with GitHub"
    echo "  autonomy   Run zion autonomy (needs GITHUB_TOKEN)"
    echo "  bundle     Rebuild frontend"
    exit 1
    ;;
esac

git add $FILES
if ! git diff --staged --quiet; then
  git commit -m "$MSG"
  git pull --rebase origin main
  git push
  echo "Done. Committed and pushed."
else
  echo "No changes."
fi
