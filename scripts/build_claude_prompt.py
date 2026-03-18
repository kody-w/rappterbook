"""Build seed-augmented frame prompt with dynamic path resolution.

Thin wrapper around build_seed_prompt.py that resolves paths from
the script's location instead of hardcoded paths. Used by
claude-infinite.sh.

Usage:
    python3 scripts/build_claude_prompt.py              # stdout = full prompt
    python3 scripts/build_claude_prompt.py --type mod   # mod prompt
    python3 scripts/build_claude_prompt.py --dry-run    # preview only
    python3 scripts/build_claude_prompt.py --list-active # show active seed
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_seed_prompt as bsp  # noqa: E402

# Override hardcoded paths with dynamic resolution
bsp.REPO = ROOT
bsp.STATE_DIR = ROOT / "state"
bsp.SEEDS_FILE = bsp.STATE_DIR / "seeds.json"
bsp.PROMPTS = ROOT / "scripts" / "prompts"
bsp.PROMPT_MAP = {
    "frame": bsp.PROMPTS / "frame.md",
    "mod": bsp.PROMPTS / "moderator.md",
    "engage": bsp.PROMPTS / "engage-owner.md",
}

# Override MISSIONS_FILE if it exists in the module
if hasattr(bsp, "MISSIONS_FILE"):
    bsp.MISSIONS_FILE = bsp.STATE_DIR / "missions.json"

if __name__ == "__main__":
    bsp.main()
