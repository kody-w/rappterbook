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
#   3. If rebase creates conflict markers, resolves by checking out only
#      the files WE changed from our commit onto origin/main

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
    # If no changes detected yet (pre-add), fall back to adding the directory
    if [ ${#EXPANDED_FILES[@]} -eq 0 ]; then
      EXPANDED_FILES+=("$f")
    fi
  else
    EXPANDED_FILES+=("$f")
  fi
done
FILES=("${EXPANDED_FILES[@]}")

git config user.name "rappterbook-bot"
git config user.email "rappterbook-bot@users.noreply.github.com"

git add "${FILES[@]}"

if git diff --staged --quiet; then
  echo "No state changes"
  exit 0
fi

# Detect shallow clone. The amend-squash optimization below CANNOT run on
# a shallow repo: `git commit --amend` of the only commit produces a new
# commit with NO parent, and `git push --force-with-lease` happily accepts
# it as the new main, orphaning the entire branch's history.
#
# Incident: 2026-05-16 — the prompt-remix workflow used fetch-depth: 1.
# Two parallel runs collided on the same issue. Run 2's safe_commit hit
# the amend path because Run 1 had just pushed a commit with the same
# message. The amend created a parentless commit. The force-with-lease
# orbited that commit onto main. Result: every previous commit's
# ancestry was lost from main's git log. Required manual force-push to
# restore. See PR #18341 follow-up for full forensics.
IS_SHALLOW=$(git rev-parse --is-shallow-repository 2>/dev/null || echo "false")

# Amend if the previous commit has the same message (squash repeated chore
# commits). ONLY safe with full history — never on a shallow clone.
LAST_MSG=$(git log -1 --format=%s 2>/dev/null || echo "")
if [ "$LAST_MSG" = "$COMMIT_MSG" ] && [ "$IS_SHALLOW" != "true" ]; then
  echo "Amending previous commit (same message: $COMMIT_MSG)"
  git commit --amend --no-edit
  PUSH_FLAGS="--force-with-lease"
else
  if [ "$LAST_MSG" = "$COMMIT_MSG" ] && [ "$IS_SHALLOW" = "true" ]; then
    echo "Skipping amend — repo is shallow; would orphan main. Creating new commit instead."
  fi
  git commit -m "$COMMIT_MSG"
  PUSH_FLAGS=""
fi

# Sanity guard: never push if our new HEAD looks like an orphan AND we
# know the remote has history. An orphan-on-empty-repo is legitimate;
# an orphan when main already has 18,000 commits is the bug above.
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
    echo "  Likely cause: shallow clone + git commit --amend. Diagnose with:"
    echo "    git rev-parse --is-shallow-repository"
    echo "    git cat-file -p HEAD"
    exit 1
  fi
fi

MAX_ATTEMPTS=5
for attempt in $(seq 1 $MAX_ATTEMPTS); do
  if git push $PUSH_FLAGS origin main 2>/dev/null; then
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
  if git rebase origin/main 2>/dev/null; then
    echo "Rebase succeeded, retrying push..."
    continue
  fi

  echo "Rebase conflict detected, resolving..."

  # Abort the failed rebase
  git rebase --abort 2>/dev/null || true

  # Remember our commit SHA — git knows exactly what files we changed
  OUR_COMMIT=$(git rev-parse HEAD)
  echo "  Our commit: $(git log -1 --format='%h %s' "$OUR_COMMIT")"

  # Reset to origin/main (take their version as base)
  git reset --hard origin/main
  echo "  Origin HEAD: $(git log -1 --format='%h %s' HEAD)"

  # Extract our version of the specified files using git
  # Because FILES was expanded to individual changed files (not directories),
  # we only restore the files WE actually modified, not unrelated state files.
  echo "  Restoring ${#FILES[@]} files from our commit:"
  for f in "${FILES[@]}"; do
    if git checkout "$OUR_COMMIT" -- "$f" 2>/dev/null; then
      echo "    ✓ $f"
    else
      echo "    ✗ $f (not in our commit, skipping)"
    fi
  done

  # Re-add and commit our preserved files
  git add "${FILES[@]}"

  if git diff --staged --quiet; then
    echo "WARNING: After conflict resolution, no diff remains."
    echo "  Our commit: $(git log -1 --format='%h %s' "$OUR_COMMIT")"
    echo "  Origin HEAD: $(git log -1 --format='%h %s' HEAD)"
    echo "  This means origin/main already has identical state."
    echo "::warning::State commit empty after rebase conflict for: ${COMMIT_MSG}"
    exit 0
  fi

  # After conflict resolution, always create a new commit (amend target was reset away)
  git commit -m "$COMMIT_MSG"
  PUSH_FLAGS=""
  echo "Recommitted after conflict resolution, retrying push..."

  sleep $((attempt * 2))
done

echo "ERROR: Failed to push after $MAX_ATTEMPTS attempts" >&2
exit 1
