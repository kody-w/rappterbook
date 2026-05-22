"""Audit #8 — Channel reconciliation idempotency.

`reconcile_channels.py` is supposed to keep `channels.json` aligned with
GitHub Discussions categories AND with per-channel post counts derived from
posted_log / cache. The doctrine: running it twice in a row should produce
no change. If the second run produces a diff, reconciliation is non-
deterministic or has stuck state.
"""
from __future__ import annotations
import hashlib
import subprocess
import sys


def _file_hash(p) -> str:
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def test_reconcile_channels_idempotent(canonical_root, canonical_state):
    """Two consecutive reconcile runs must produce the same channels.json."""
    script = canonical_root / "scripts" / "reconcile_channels.py"
    channels_path = canonical_state / "channels.json"
    if not script.exists():
        return  # nothing to verify

    # First run (may mutate)
    r1 = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(canonical_root),
        capture_output=True, text=True, timeout=120,
    )
    assert r1.returncode == 0, f"first reconcile failed:\n{r1.stderr[:1000]}"
    hash_after_first = _file_hash(channels_path)

    # Second run (must be idempotent)
    r2 = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(canonical_root),
        capture_output=True, text=True, timeout=120,
    )
    assert r2.returncode == 0, f"second reconcile failed:\n{r2.stderr[:1000]}"
    hash_after_second = _file_hash(channels_path)

    assert hash_after_first == hash_after_second, (
        f"reconcile_channels.py is not idempotent — channels.json mutated on "
        f"the second consecutive run. This means reconciliation logic depends "
        f"on order, missing state, or has a non-deterministic merge step."
    )
