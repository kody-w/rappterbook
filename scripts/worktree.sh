#!/usr/bin/env bash
# worktree.sh — Git worktree manager for parallel agent collaboration.
#
# Instead of cloning fresh each time, agents share a bare repo and create
# isolated worktrees. Each stream gets its own working copy — no conflicts
# between parallel streams. Multi-file changes, local testing, everything works.
#
# Commands:
#   bash scripts/worktree.sh setup OWNER/REPO         — one-time: create bare clone
#   bash scripts/worktree.sh create OWNER/REPO BRANCH  — create worktree for a branch
#   bash scripts/worktree.sh path OWNER/REPO BRANCH    — print worktree path (for cd)
#   bash scripts/worktree.sh push OWNER/REPO BRANCH    — commit all changes + push
#   bash scripts/worktree.sh pr OWNER/REPO BRANCH "title" "body" — push + open PR
#   bash scripts/worktree.sh cleanup OWNER/REPO BRANCH — remove worktree
#   bash scripts/worktree.sh list OWNER/REPO            — list active worktrees
#   bash scripts/worktree.sh sync OWNER/REPO            — fetch latest from origin
#
# Examples:
#   # Setup (once per repo, persists across frames)
#   bash scripts/worktree.sh setup kody-w/mars-barn
#
#   # Create a worktree for your fix
#   bash scripts/worktree.sh create kody-w/mars-barn fix-weather-bug
#   cd $(bash scripts/worktree.sh path kody-w/mars-barn fix-weather-bug)
#
#   # Edit files, run tests, do whatever
#   vim src/mars_climate.py
#   python main.py --sols 10 --seed 42
#
#   # When done: commit, push, open PR in one command
#   bash scripts/worktree.sh pr kody-w/mars-barn fix-weather-bug \
#     "fix: correct seasonal temperature calculation" \
#     "The f-string interpolation was using Celsius instead of Kelvin"
#
#   # Cleanup
#   bash scripts/worktree.sh cleanup kody-w/mars-barn fix-weather-bug

set -uo pipefail

CMD="${1:-help}"
REPO="${2:-}"
BRANCH="${3:-}"

# Directories
BARE_ROOT="/tmp/rappterbook-worktrees"
REPO_SLUG="${REPO//\//-}"  # kody-w/mars-barn -> kody-w-mars-barn
BARE_DIR="$BARE_ROOT/$REPO_SLUG.git"
WORK_ROOT="$BARE_ROOT/$REPO_SLUG"

case "$CMD" in
  setup)
    # One-time bare clone. Persists across frames.
    [ -z "$REPO" ] && { echo "Usage: worktree.sh setup OWNER/REPO"; exit 1; }
    if [ -d "$BARE_DIR" ]; then
      echo "Bare repo exists. Fetching latest..."
      git -C "$BARE_DIR" fetch origin 2>&1 | tail -3
    else
      echo "Cloning bare repo..."
      mkdir -p "$BARE_ROOT"
      git clone --bare "https://github.com/$REPO.git" "$BARE_DIR" 2>&1 | tail -3
      # Allow worktrees to checkout any branch
      git -C "$BARE_DIR" config remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'
      git -C "$BARE_DIR" fetch origin 2>/dev/null
    fi
    mkdir -p "$WORK_ROOT"
    echo "Ready. Bare: $BARE_DIR"
    echo "Worktrees: $WORK_ROOT/<branch-name>"
    ;;

  create)
    # Create a worktree for a new branch based on origin/main
    [ -z "$BRANCH" ] && { echo "Usage: worktree.sh create OWNER/REPO BRANCH"; exit 1; }
    TREE_DIR="$WORK_ROOT/$BRANCH"

    # Auto-setup if bare doesn't exist
    if [ ! -d "$BARE_DIR" ]; then
      echo "Auto-setting up bare repo..."
      "$0" setup "$REPO"
    else
      # Fetch latest before creating worktree
      git -C "$BARE_DIR" fetch origin 2>/dev/null
    fi

    # Remove stale worktree if it exists
    if [ -d "$TREE_DIR" ]; then
      git -C "$BARE_DIR" worktree remove "$TREE_DIR" --force 2>/dev/null || rm -rf "$TREE_DIR"
    fi

    # Create worktree with new branch from origin/main
    git -C "$BARE_DIR" worktree add -b "$BRANCH" "$TREE_DIR" origin/main 2>&1
    echo "Worktree ready: $TREE_DIR"
    echo "cd $TREE_DIR"
    ;;

  path)
    # Print the worktree path (for use in cd or scripts)
    [ -z "$BRANCH" ] && { echo "Usage: worktree.sh path OWNER/REPO BRANCH"; exit 1; }
    echo "$WORK_ROOT/$BRANCH"
    ;;

  push)
    # Stage all changes, commit, push
    [ -z "$BRANCH" ] && { echo "Usage: worktree.sh push OWNER/REPO BRANCH"; exit 1; }
    TREE_DIR="$WORK_ROOT/$BRANCH"
    [ ! -d "$TREE_DIR" ] && { echo "ERROR: worktree $TREE_DIR does not exist"; exit 1; }

    cd "$TREE_DIR"
    git add -A
    if ! git diff --cached --quiet 2>/dev/null; then
      git commit -m "chore: update $BRANCH" --no-gpg-sign 2>&1
      git push origin "$BRANCH" 2>&1
      echo "Pushed $BRANCH to $REPO"
    else
      echo "No changes to push"
    fi
    ;;

  pr)
    # Stage, commit, push, and open a PR — the full workflow in one command
    PR_TITLE="${4:-}"
    PR_BODY="${5:-}"
    [ -z "$PR_TITLE" ] && { echo "Usage: worktree.sh pr OWNER/REPO BRANCH \"title\" \"body\""; exit 1; }
    TREE_DIR="$WORK_ROOT/$BRANCH"
    [ ! -d "$TREE_DIR" ] && { echo "ERROR: worktree $TREE_DIR does not exist"; exit 1; }

    cd "$TREE_DIR"
    git add -A
    if ! git diff --cached --quiet 2>/dev/null; then
      git commit -m "$PR_TITLE" --no-gpg-sign 2>&1
      git push origin "$BRANCH" 2>&1 || {
        echo "ERROR: push failed" >&2
        exit 1
      }
      # Open PR
      gh pr create --repo "$REPO" --head "$BRANCH" --base main \
        --title "$PR_TITLE" \
        --body "$PR_BODY" 2>&1
      echo "PR opened on $REPO from $BRANCH"
    else
      echo "No changes to commit"
    fi
    ;;

  cleanup)
    # Remove a worktree
    [ -z "$BRANCH" ] && { echo "Usage: worktree.sh cleanup OWNER/REPO BRANCH"; exit 1; }
    TREE_DIR="$WORK_ROOT/$BRANCH"
    git -C "$BARE_DIR" worktree remove "$TREE_DIR" --force 2>/dev/null
    rm -rf "$TREE_DIR" 2>/dev/null
    echo "Cleaned up: $BRANCH"
    ;;

  list)
    # List active worktrees
    [ -z "$REPO" ] && { echo "Usage: worktree.sh list OWNER/REPO"; exit 1; }
    if [ -d "$BARE_DIR" ]; then
      git -C "$BARE_DIR" worktree list 2>/dev/null
    else
      echo "No bare repo for $REPO. Run: worktree.sh setup $REPO"
    fi
    ;;

  sync)
    # Fetch latest from origin
    [ -z "$REPO" ] && { echo "Usage: worktree.sh sync OWNER/REPO"; exit 1; }
    if [ -d "$BARE_DIR" ]; then
      git -C "$BARE_DIR" fetch origin 2>&1
      echo "Synced $REPO"
    else
      echo "No bare repo. Run: worktree.sh setup $REPO"
    fi
    ;;

  help|*)
    echo "worktree.sh — Git worktree manager for parallel agent collaboration"
    echo ""
    echo "Commands:"
    echo "  setup  OWNER/REPO              Create bare clone (once per repo)"
    echo "  create OWNER/REPO BRANCH       Create isolated worktree"
    echo "  path   OWNER/REPO BRANCH       Print worktree path"
    echo "  push   OWNER/REPO BRANCH       Commit + push all changes"
    echo "  pr     OWNER/REPO BRANCH T B   Push + open PR (title, body)"
    echo "  cleanup OWNER/REPO BRANCH      Remove worktree"
    echo "  list   OWNER/REPO              List active worktrees"
    echo "  sync   OWNER/REPO              Fetch latest from origin"
    ;;
esac
