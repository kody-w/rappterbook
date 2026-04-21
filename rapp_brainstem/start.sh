#!/bin/bash
set -e
cd "$(dirname "$0")"

BRAINSTEM_HOME="$HOME/.brainstem"
VENV_PYTHON="$BRAINSTEM_HOME/venv/bin/python"

# Use venv if available; create it if missing
if [ ! -x "$VENV_PYTHON" ]; then
    echo "Setting up virtual environment..."
    PYTHON_CMD=$(command -v python3.11 || command -v python3.12 || command -v python3.13 || command -v python3)
    "$PYTHON_CMD" -m venv "$BRAINSTEM_HOME/venv" 2>/dev/null || {
        echo "Failed to create venv — run the installer: curl -fsSL https://kody-w.github.io/rapp-installer/install.sh | bash"
        exit 1
    }
fi

# Install deps if needed
if ! "$VENV_PYTHON" -c "import flask, requests, dotenv" 2>/dev/null; then
    echo "Installing dependencies..."
    "$BRAINSTEM_HOME/venv/bin/pip" install -r requirements.txt -q
fi

# Create .env from example if missing
if [ ! -f .env ]; then
    cp .env.example .env 2>/dev/null || true
fi

exec "$VENV_PYTHON" brainstem.py
