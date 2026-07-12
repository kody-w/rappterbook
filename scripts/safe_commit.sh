#!/usr/bin/env bash
# safe_commit.sh — conflict-safe state commit for GitHub Actions
#
# Usage: bash scripts/safe_commit.sh "commit message" file1 file2 ...
#
# Handles the case where another workflow pushed while this one ran.
# Disjoint commits are rebased and retried. Same-file conflicts fail closed
# so stale whole-file snapshots can never replace newer remote state.

set -euo pipefail

COMMIT_MSG="${1:?Usage: safe_commit.sh 'message' file1 file2 ...}"
shift
FILES=("$@")

if [ ${#FILES[@]} -eq 0 ]; then
  echo "No files specified"
  exit 1
fi

# Expand any directory arguments to individual files that actually have changes.
# This prevents overwriting concurrent changes to files we didn't touch.
EXPANDED_FILES=()
for f in "${FILES[@]}"; do
  if [ -d "$f" ]; then
    while IFS= read -r changed; do
      [ -n "$changed" ] && EXPANDED_FILES+=("$changed")
    done < <(git diff --name-only HEAD -- "$f" 2>/dev/null; git ls-files --others --exclude-standard "$f" 2>/dev/null)
  elif ! git diff --quiet HEAD -- "$f" 2>/dev/null ||
       [ -n "$(git ls-files --others --exclude-standard -- "$f" 2>/dev/null)" ]; then
    EXPANDED_FILES+=("$f")
  fi
done
FILES=("${EXPANDED_FILES[@]}")

if [ ${#FILES[@]} -eq 0 ]; then
  echo "No state changes"
  exit 0
fi

git config user.name "rappterbook-bot"
git config user.email "rappterbook-bot@users.noreply.github.com"

git add -A -- "${FILES[@]}"

if git diff --staged --quiet; then
  echo "No state changes"
  exit 0
fi

git commit -m "$COMMIT_MSG"

# Sanity guard: never push if our new HEAD looks like an orphan AND we
# know the remote has history. An orphan-on-empty-repo is legitimate;
# an orphan when main already has history would destroy branch ancestry.
#
# Implementation note: `git rev-list --parents -n 1 HEAD` prints one line
# of the form "<sha> <parent1> <parent2> ...". Parent count = NF - 1.
# Do NOT add --count — that collapses output to a single integer and
# breaks the awk parsing (this is why an earlier version of this guard
# misfired on legitimate commits).
HEAD_PARENT_COUNT=$(git rev-list --parents -n 1 HEAD 2>/dev/null | awk '{print NF-1}')
if [ "${HEAD_PARENT_COUNT:-1}" = "0" ]; then
  # Local HEAD has no parent. Check if remote main has any history.
  REMOTE_HAS_HISTORY=$(git ls-remote origin main 2>/dev/null | wc -l | tr -d ' ')
  if [ "$REMOTE_HAS_HISTORY" != "0" ]; then
    echo "::error::REFUSING TO PUSH — local HEAD is parentless but remote main has history."
    echo "  This would orphan the entire branch. Aborting before damage."
    echo "  Diagnose the checkout before retrying:"
    echo "    git rev-parse --is-shallow-repository"
    echo "    git cat-file -p HEAD"
    exit 1
  fi
fi

MAX_ATTEMPTS=5
for attempt in $(seq 1 $MAX_ATTEMPTS); do
  if git push origin main; then
    echo "Push succeeded (attempt $attempt)"

    # Post-commit consistency check
    DRIFT=$(python3 scripts/state_io.py --verify 2>&1) || true
    if [ -n "$DRIFT" ] && [ "$DRIFT" != "State consistency OK" ]; then
      echo "WARNING: State drift detected after commit:"
      echo "$DRIFT"
      echo "::warning::State drift detected: $DRIFT"
    fi

    exit 0
  fi

  echo "Push failed (attempt $attempt/$MAX_ATTEMPTS), pulling latest..."

  # Fetch latest without modifying working tree
  git fetch origin main

  # Try rebase
  if git rebase origin/main; then
    echo "Rebase succeeded, retrying push..."
    continue
  fi

  echo "ERROR: Rebase conflict detected; refusing to overwrite remote state." >&2
  git rebase --abort 2>/dev/null || true
  exit 1
done

echo "ERROR: Failed to push after $MAX_ATTEMPTS attempts" >&2
exit 1
