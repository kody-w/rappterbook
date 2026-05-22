"""Audit #8 — Channel reconciliation idempotency.

`reconcile_channels.py` is supposed to keep `channels.json` aligned with
GitHub Discussions categories AND with per-channel post counts derived from
posted_log / cache. The doctrine: running it twice in a row should produce
no change. If the second run produces a diff, reconciliation is non-
deterministic or has stuck state.

We run the WORKTREE's reconcile_channels.py (the version this branch is
shipping), pointed at canonical state via STATE_DIR. After this PR merges,
main's reconcile_channels.py becomes the same script and the test still
works without modification.
"""
from __future__ import annotations
import hashlib
import os
import subprocess
import sys
from pathlib import Path


def _file_hash(p) -> str:
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def test_reconcile_channels_idempotent(canonical_root, canonical_state):
    """Two consecutive reconcile runs must produce the same channels.json."""
    worktree_root = Path(__file__).resolve().parent.parent.parent
    script = worktree_root / "scripts" / "reconcile_channels.py"
    if not script.exists():
        # Fall back to main if running outside the worktree (post-merge case)
        script = canonical_root / "scripts" / "reconcile_channels.py"
    if not script.exists():
        return

    channels_path = canonical_state / "channels.json"
    env = os.environ.copy()
    env["STATE_DIR"] = str(canonical_state)

    # First run (may mutate)
    r1 = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(canonical_root),
        env=env,
        capture_output=True, text=True, timeout=120,
    )
    assert r1.returncode == 0, f"first reconcile failed:\n{r1.stderr[:1000]}"
    hash_after_first = _file_hash(channels_path)

    # Second run (must be idempotent)
    r2 = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(canonical_root),
        env=env,
        capture_output=True, text=True, timeout=120,
    )
    assert r2.returncode == 0, f"second reconcile failed:\n{r2.stderr[:1000]}"
    hash_after_second = _file_hash(channels_path)

    assert hash_after_first == hash_after_second, (
        f"reconcile_channels.py is not idempotent — channels.json mutated on "
        f"the second consecutive run. This means reconciliation logic depends "
        f"on order, missing state, or has a non-deterministic merge step."
    )
