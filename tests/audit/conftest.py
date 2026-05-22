"""Anti-gaslight audit harness — runs against CANONICAL state, not test fixtures.

These audits exist to detect silent failures in the live Rappterbook organism.
They deliberately point at the real state/ directory of the canonical repo, not
a tempdir, because their entire purpose is to catch drift that lives in real
state files. They run in seconds — no GitHub Actions wait, no "next scheduled
run" excuse. Red → fix → green, locally, in real time.

Set RAPPTERBOOK_STATE_DIR to override the target. Default points at the
repository root that contains this worktree.
"""
from __future__ import annotations
import os
from pathlib import Path
import pytest


def _find_canonical_root() -> Path:
    env = os.environ.get("RAPPTERBOOK_STATE_DIR")
    if env:
        p = Path(env).resolve()
        if p.name == "state":
            return p.parent
        return p
    # Walk up looking for the main repo (not a worktree under .claude/worktrees/).
    here = Path(__file__).resolve()
    for ancestor in here.parents:
        if (ancestor / "scripts" / "state_io.py").exists() and ".claude/worktrees/" not in str(ancestor):
            return ancestor
    # Fallback: parent-of-parent-of-worktree
    for ancestor in here.parents:
        parts = ancestor.parts
        if ".claude" in parts:
            idx = parts.index(".claude")
            return Path(*parts[:idx])
    raise RuntimeError("Could not locate canonical Rappterbook repo root")


CANONICAL_ROOT: Path = _find_canonical_root()
CANONICAL_STATE: Path = CANONICAL_ROOT / "state"
CANONICAL_INBOX: Path = CANONICAL_STATE / "inbox"
CANONICAL_SCRIPTS: Path = CANONICAL_ROOT / "scripts"


@pytest.fixture(scope="session")
def canonical_root() -> Path:
    return CANONICAL_ROOT


@pytest.fixture(scope="session")
def canonical_state() -> Path:
    return CANONICAL_STATE


@pytest.fixture(scope="session")
def canonical_inbox() -> Path:
    return CANONICAL_INBOX


@pytest.fixture(scope="session")
def canonical_scripts() -> Path:
    return CANONICAL_SCRIPTS
