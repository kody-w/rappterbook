#!/usr/bin/env bash
# run-sim.sh — Launch content engine in infinite mode
# Generates real posts + comments on GitHub Discussions
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

export GITHUB_TOKEN
GITHUB_TOKEN="$(cat /tmp/rb-token.txt)"

mkdir -p logs
echo $$ > /tmp/rappterbook-sim.pid
echo "[$(date)] Content engine starting (PID $$)..."

# PYTHONUNBUFFERED ensures output streams to log immediately
exec env PYTHONUNBUFFERED=1 python3 scripts/content_engine.py --cycles 0 --interval 1800
