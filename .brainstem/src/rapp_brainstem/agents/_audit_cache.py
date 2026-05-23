"""Process-wide pytest cache for FactoryReporter-style agents.

The autopilot loop runs the audit harness multiple times within a single
session: once per contestant per loop iteration. With 3 contestants and
2 loop iterations that's 6 pytest invocations ≈ 6 minutes wall time.
But within ONE autopilot session the platform state isn't changing —
the pytest result is the same every time. Caching it cuts ~5 minutes
off a max_jumps=2 autopilot run.

Module-level cache (lives in the brainstem process) + a /tmp file
backup (so a brainstem restart doesn't lose the warm cache mid-run).
Default TTL is 5 minutes — fresh enough to be useful, short enough
that real state changes are reflected within the window.

This module is NOT an agent — its filename has no `_agent` suffix so
the brainstem's `*_agent.py` glob skips it. Other agents import it as
`from agents._audit_cache import cached_pytest_audit_summary`.
"""
from __future__ import annotations
import json
import re
import subprocess
import time
from pathlib import Path


CANONICAL_ROOT = Path("/Users/kodyw/Documents/GitHub/Rappter/rappterbook")
WORKTREE_ROOT = CANONICAL_ROOT / ".claude" / "worktrees" / "audit-anti-gaslight"
CACHE_FILE = Path("/tmp/rappterbook_audit_cache.json")
DEFAULT_TTL_SECONDS = 300


# In-process memo — instant cache hits within the same Python process
_MEMO: dict = {}


def _tests_root() -> Path:
    if (CANONICAL_ROOT / "tests" / "audit").exists():
        return CANONICAL_ROOT
    return WORKTREE_ROOT


def _parse_summary(stdout: str, stderr: str) -> dict:
    out = (stdout or "") + "\n" + (stderr or "")
    m = re.search(r"(\d+)\s+failed,?\s+(\d+)\s+passed", out)
    if m:
        return {"ok": True, "failed": int(m.group(1)), "passed": int(m.group(2))}
    m = re.search(r"(\d+)\s+passed", out)
    if m:
        return {"ok": True, "failed": 0, "passed": int(m.group(1))}
    return {"ok": False, "raw_tail": out[-500:]}


def _run_pytest_now() -> dict:
    tests_root = _tests_root()
    if not (tests_root / "tests" / "audit").exists():
        return {"ok": False, "error": "tests/audit/ not found"}
    try:
        p = subprocess.run(
            ["python3", "-m", "pytest", "tests/audit/", "--tb=no", "-q"],
            cwd=str(tests_root),
            capture_output=True, text=True, timeout=300,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        return {"ok": False, "error": f"pytest invocation failed: {e}"}
    return _parse_summary(p.stdout, p.stderr)


def _load_disk_cache() -> dict | None:
    if not CACHE_FILE.exists():
        return None
    try:
        with open(CACHE_FILE) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _save_disk_cache(entry: dict) -> None:
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(entry, f)
    except OSError:
        pass


def cached_pytest_audit_summary(ttl_seconds: int = DEFAULT_TTL_SECONDS,
                                 force_refresh: bool = False) -> dict:
    """Return a parsed pytest summary {ok, failed, passed} — cached for
    `ttl_seconds`. If the cache is older or `force_refresh` is true, runs
    pytest, updates the cache, and returns the fresh result.

    The returned dict carries an additional `cache_source` field:
      * "memo"   — served from the in-process cache (microseconds)
      * "disk"   — served from /tmp file cache (~1ms)
      * "fresh"  — pytest just ran (~60-90s)
    """
    now = time.time()

    # 1) In-process memo
    if not force_refresh and _MEMO and (now - _MEMO.get("ts", 0)) < ttl_seconds:
        entry = dict(_MEMO["data"])
        entry["cache_source"] = "memo"
        entry["age_seconds"] = round(now - _MEMO["ts"], 1)
        return entry

    # 2) Disk cache (survives brainstem restart)
    if not force_refresh:
        disk = _load_disk_cache()
        if disk and (now - disk.get("ts", 0)) < ttl_seconds:
            _MEMO.update(disk)  # warm the in-proc memo too
            entry = dict(disk["data"])
            entry["cache_source"] = "disk"
            entry["age_seconds"] = round(now - disk["ts"], 1)
            return entry

    # 3) Fresh run
    data = _run_pytest_now()
    record = {"ts": now, "data": data}
    _MEMO.update(record)
    _save_disk_cache(record)
    out = dict(data)
    out["cache_source"] = "fresh"
    out["age_seconds"] = 0.0
    return out


def invalidate() -> None:
    """Clear both in-process and on-disk caches. Call this if you know
    state has changed (e.g., after running reconcile or process_inbox)."""
    _MEMO.clear()
    try:
        CACHE_FILE.unlink()
    except OSError:
        pass


if __name__ == "__main__":
    # Quick CLI: `python3 agents/_audit_cache.py` warms the cache.
    print(json.dumps(cached_pytest_audit_summary(), indent=2))
