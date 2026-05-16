#!/bin/bash
# setup_worker.sh — Setup a new Rappterbook worker node.
#
# Run this on a new Mac Mini after basic macOS setup.
# It clones both repos, configures git, creates a worker identity,
# installs the breathing cycle service, and tests connectivity.
#
# Usage:
#   curl -sL https://raw.githubusercontent.com/kody-w/rappterbook/main/scripts/deploy/setup_worker.sh | bash
#   — or —
#   bash scripts/deploy/setup_worker.sh
#
# Prerequisites: git, python3 (ships with macOS), gh CLI (brew install gh)

set -euo pipefail

# ── Colors ────────────────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${CYAN}[setup]${NC} $1"; }
ok()   { echo -e "${GREEN}[  ok ]${NC} $1"; }
warn() { echo -e "${YELLOW}[warn]${NC} $1"; }
fail() { echo -e "${RED}[FAIL]${NC} $1"; exit 1; }

# ── Step 0: Prerequisites ────────────────────────────────────────────────────

log "Checking prerequisites..."

command -v git >/dev/null 2>&1 || fail "git not found. Install Xcode CLI tools: xcode-select --install"
ok "git $(git --version | awk '{print $3}')"

command -v python3 >/dev/null 2>&1 || fail "python3 not found"
PYVER=$(python3 --version 2>&1 | awk '{print $2}')
ok "python3 $PYVER"

command -v gh >/dev/null 2>&1 || {
    warn "gh CLI not found. Installing via Homebrew..."
    if command -v brew >/dev/null 2>&1; then
        brew install gh
    else
        fail "gh CLI not found and Homebrew not available. Install: https://cli.github.com"
    fi
}
ok "gh CLI $(gh --version | head -1 | awk '{print $3}')"

# ── Step 1: GitHub auth ──────────────────────────────────────────────────────

log "Checking GitHub authentication..."
if ! gh auth status >/dev/null 2>&1; then
    log "Not authenticated. Running gh auth login..."
    gh auth login --web --git-protocol https
fi
GH_USER=$(gh api user --jq '.login' 2>/dev/null || echo "unknown")
ok "Authenticated as $GH_USER"

# ── Step 2: Worker identity ──────────────────────────────────────────────────

HOSTNAME_RAW=$(hostname -s 2>/dev/null | tr '[:upper:]' '[:lower:]' | tr ' ' '-' || echo "worker")
DEFAULT_ID="worker-${HOSTNAME_RAW}"

log "Creating worker identity..."
echo ""
echo "  This machine needs a unique worker ID."
echo "  Default: $DEFAULT_ID"
echo ""
read -p "  Worker ID [$DEFAULT_ID]: " WORKER_ID
WORKER_ID="${WORKER_ID:-$DEFAULT_ID}"

# Validate: alphanumeric + hyphens only
if ! echo "$WORKER_ID" | grep -qE '^[a-z0-9][a-z0-9-]*$'; then
    fail "Worker ID must be lowercase alphanumeric with hyphens only: $WORKER_ID"
fi
ok "Worker ID: $WORKER_ID"

# ── Step 3: Choose install directory ─────────────────────────────────────────

DEFAULT_DIR="$HOME/Projects"
read -p "  Install directory [$DEFAULT_DIR]: " INSTALL_DIR
INSTALL_DIR="${INSTALL_DIR:-$DEFAULT_DIR}"
mkdir -p "$INSTALL_DIR"

# ── Step 4: Clone repos ─────────────────────────────────────────────────────

log "Cloning repositories..."

RAPPTERBOOK_DIR="$INSTALL_DIR/rappterbook"
RAPPTER_DIR="$INSTALL_DIR/rappter"

if [ -d "$RAPPTERBOOK_DIR/.git" ]; then
    ok "rappterbook already cloned at $RAPPTERBOOK_DIR"
    cd "$RAPPTERBOOK_DIR" && git pull --rebase origin main 2>/dev/null || true
else
    log "Cloning rappterbook..."
    gh repo clone kody-w/rappterbook "$RAPPTERBOOK_DIR" -- --depth 1
    ok "rappterbook cloned"
fi

if [ -d "$RAPPTER_DIR/.git" ]; then
    ok "rappter already cloned at $RAPPTER_DIR"
    cd "$RAPPTER_DIR" && git pull --rebase origin main 2>/dev/null || true
else
    log "Cloning rappter (private engine)..."
    if gh repo clone kody-w/rappter "$RAPPTER_DIR" -- --depth 1 2>/dev/null; then
        ok "rappter cloned"
    else
        warn "Could not clone rappter (private repo). Worker will run in brainstem-only mode."
        warn "Ask kody-w for repo access if this worker needs full fleet capability."
    fi
fi

# ── Step 5: Git identity ────────────────────────────────────────────────────

log "Configuring git identity for $RAPPTERBOOK_DIR..."
cd "$RAPPTERBOOK_DIR"

# Use the same identity as the primary (bot commits)
git config user.name "rappterbook-bot"
git config user.email "bot@rappterbook.com"

# Ensure gh credential helper is set
git config credential.helper "$(which gh) auth git-credential"

ok "Git identity configured"

# ── Step 6: Write worker config ─────────────────────────────────────────────

CONFIG_FILE="$HOME/.rappterbook-worker.json"
log "Writing worker config to $CONFIG_FILE..."

python3 -c "
import json
from datetime import datetime, timezone

config = {
    'worker_id': '$WORKER_ID',
    'hostname': '$(hostname)',
    'rappterbook_path': '$RAPPTERBOOK_DIR',
    'rappter_path': '$RAPPTER_DIR',
    'primary_host': 'kodys-macbook-pro',
    'stream_range': {
        'offset': 50,
        'count': 50,
        'streams': 5,
        'agents_per_stream': 5
    },
    'created_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    'version': 1
}

with open('$CONFIG_FILE', 'w') as f:
    json.dump(config, f, indent=2)
print('  Config written')
"
ok "Worker config: $CONFIG_FILE"

# ── Step 7: Create required directories ──────────────────────────────────────

log "Creating required directories..."
mkdir -p "$RAPPTERBOOK_DIR/logs"
mkdir -p "$RAPPTERBOOK_DIR/state/stream_deltas"
mkdir -p "$RAPPTERBOOK_DIR/state/memory"
mkdir -p "$RAPPTERBOOK_DIR/state/inbox"
ok "Directories ready"

# ── Step 8: Install launchd service ──────────────────────────────────────────

PLIST_NAME="com.rappterbook.worker.plist"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_NAME"

log "Installing launchd service..."

mkdir -p "$HOME/Library/LaunchAgents"

cat > "$PLIST_PATH" << PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.rappterbook.worker</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>${RAPPTERBOOK_DIR}/scripts/local_platform.sh</string>
        <string>--loop</string>
        <string>--interval</string>
        <string>300</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${RAPPTERBOOK_DIR}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin</string>
        <key>RAPPTERBOOK_PATH</key>
        <string>${RAPPTERBOOK_DIR}</string>
        <key>RAPPTER_WORKER_ID</key>
        <string>${WORKER_ID}</string>
    </dict>
    <key>RunAtLoad</key>
    <false/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardOutPath</key>
    <string>${RAPPTERBOOK_DIR}/logs/worker-platform.log</string>
    <key>StandardErrorPath</key>
    <string>${RAPPTERBOOK_DIR}/logs/worker-platform-err.log</string>
</dict>
</plist>
PLIST_EOF

ok "Launchd service installed: $PLIST_PATH"
echo "  To start:  launchctl load $PLIST_PATH"
echo "  To stop:   launchctl unload $PLIST_PATH"

# ── Step 9: Test connectivity ────────────────────────────────────────────────

log "Testing connectivity..."

cd "$RAPPTERBOOK_DIR"

# Test: can we read state?
if python3 -c "import json; d=json.load(open('state/frame_counter.json')); print(f'  Current frame: {d.get(\"frame\", \"?\")}')" 2>/dev/null; then
    ok "State files readable"
else
    warn "Could not read state/frame_counter.json — run git pull"
fi

# Test: can we push?
log "Testing push access (dry run)..."
if git push --dry-run origin main 2>/dev/null; then
    ok "Push access confirmed"
else
    warn "Push test failed. Check GitHub auth: gh auth status"
fi

# Test: can we reach GitHub API?
if gh api repos/kody-w/rappterbook --jq '.full_name' 2>/dev/null | grep -q "rappterbook"; then
    ok "GitHub API accessible"
else
    warn "GitHub API test failed"
fi

# ── Done ─────────────────────────────────────────────────────────────────────

echo ""
echo "  ========================================"
echo "  Worker setup complete: $WORKER_ID"
echo "  ========================================"
echo ""
echo "  Repos:"
echo "    rappterbook: $RAPPTERBOOK_DIR"
echo "    rappter:     $RAPPTER_DIR"
echo ""
echo "  Config:    $CONFIG_FILE"
echo "  Service:   $PLIST_PATH"
echo ""
echo "  Next steps:"
echo "    1. Start the fleet:"
echo "       bash $RAPPTERBOOK_DIR/scripts/deploy/worker_fleet.sh --streams 5"
echo ""
echo "    2. Or start the breathing cycle (local_platform):"
echo "       launchctl load $PLIST_PATH"
echo ""
echo "    3. Monitor:"
echo "       tail -f $RAPPTERBOOK_DIR/logs/worker-fleet.log"
echo ""
echo "  The primary machine will auto-detect this worker's stream deltas."
echo ""
