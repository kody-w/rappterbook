#!/usr/bin/env bash
# safe_commit.sh — conflict-safe state commit for GitHub Actions
#
# Usage: bash scripts/safe_commit.sh "commit message" file1 file2 ...
#
# Handles the case where another workflow pushed while this one ran.
# Instead of git pull --rebase (which creates conflict markers in JSON),
# this script:
#   1. Attempts normal commit + push
#   2. On push failure, fetches latest, re-runs git add, and retries
#   3. If rebase creates conflict markers, resolves by re-running the
#      calling script's changes on top of the latest state

set -euo pipefail

COMMIT_MSG="${1:?Usage: safe_commit.sh 'message' file1 file2 ...}"
shift
FILES=("$@")

if [ ${#FILES[@]} -eq 0 ]; then
  echo "No files specified"
  exit 1
fi

git config user.name "rappterbook-bot"
git config user.email "rappterbook-bot@users.noreply.github.com"

git add "${FILES[@]}"

if git diff --staged --quiet; then
  echo "No state changes"
  exit 0
fi

git commit -m "$COMMIT_MSG"

MAX_ATTEMPTS=5
for attempt in $(seq 1 $MAX_ATTEMPTS); do
  if git push origin main 2>/dev/null; then
    echo "Push succeeded (attempt $attempt)"
    exit 0
  fi

  echo "Push failed (attempt $attempt/$MAX_ATTEMPTS), pulling latest..."

  # Fetch latest without modifying working tree
  git fetch origin main

  # Try rebase
  if git rebase origin/main 2>/dev/null; then
    echo "Rebase succeeded, retrying push..."
    continue
  fi

  echo "Rebase conflict detected, resolving..."

  # Abort the failed rebase
  git rebase --abort 2>/dev/null || true

  # Reset to origin/main (take their version as base)
  git reset --hard origin/main

  # Re-add our files (they're still in working tree from the script that ran)
  # The calling workflow already computed the correct state — just re-add and commit
  git add "${FILES[@]}"

  if git diff --staged --quiet; then
    echo "After reset, no changes remain (upstream already has our data)"
    exit 0
  fi

  git commit -m "$COMMIT_MSG"
  echo "Recommitted after conflict resolution, retrying push..."

  sleep $((attempt * 2))
done

echo "ERROR: Failed to push after $MAX_ATTEMPTS attempts" >&2
exit 1
