"""Rapp configuration — paths relative to the Rappterbook engine.

This project lives inside rappterbook/projects/rapp/.
The engine (rappterbook) is two directories up.
"""
from __future__ import annotations

from pathlib import Path

# Engine root — the rappterbook repo
ENGINE = Path(__file__).resolve().parent.parent.parent

# Engine paths
STATE_DIR = ENGINE / "state"
SEEDS_FILE = STATE_DIR / "seeds.json"
AGENTS_FILE = STATE_DIR / "agents.json"
MISSIONS_FILE = STATE_DIR / "missions.json"
PROMPTS_DIR = ENGINE / "scripts" / "prompts"
SCRIPTS_DIR = ENGINE / "scripts"
LOGS_DIR = ENGINE / "logs"

# This project's paths
PROJECT_DIR = Path(__file__).resolve().parent
SESSIONS_FILE = PROJECT_DIR / "sessions.json"
DEFAULT_PORT = 7777
