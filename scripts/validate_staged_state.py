#!/usr/bin/env python3
"""Reject newly staged state corruption before it can be committed."""
from __future__ import annotations

import json
import subprocess
import sys

MAX_BLOB_BYTES = 95 * 1024 * 1024
CRITICAL_FILES = {
    "state/agents.json",
    "state/channels.json",
    "state/stats.json",
    "state/posted_log.json",
}


def _git_bytes(*args: str) -> bytes:
    """Return bytes from one git command."""
    return subprocess.check_output(["git", *args], stderr=subprocess.DEVNULL)


def staged_paths() -> list[str]:
    """Return added, copied, modified, or renamed paths in the index."""
    output = _git_bytes("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")
    return [item.decode() for item in output.split(b"\0") if item]


def staged_content(path: str) -> bytes:
    """Read one path exactly as staged in the index."""
    return _git_bytes("show", f":{path}")


def head_json(path: str) -> dict | None:
    """Load the HEAD version when it is valid JSON."""
    try:
        return json.loads(_git_bytes("show", f"HEAD:{path}"))
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return None


def _count_gap(path: str, data: dict) -> int | None:
    """Return the absolute metadata count gap for known state schemas."""
    if path == "state/agents.json":
        expected = len(data.get("agents", {}))
    elif path == "state/channels.json":
        expected = len(data.get("channels", {}))
    elif path == "state/follows.json":
        follows = data.get("follows", {})
        expected = sum(len(targets) for targets in follows.values()) if isinstance(follows, dict) else len(follows)
    else:
        return None
    actual = data.get("_meta", {}).get("count")
    return abs(actual - expected) if isinstance(actual, int) else expected


def validate_json(path: str, content: bytes) -> list[str]:
    """Validate one staged JSON or JSONL artifact."""
    errors = []
    try:
        if path.endswith(".jsonl"):
            for line in content.splitlines():
                if line.strip():
                    json.loads(line)
        else:
            data = json.loads(content)
    except json.JSONDecodeError as exc:
        return [f"{path}: invalid JSON at line {exc.lineno}: {exc.msg}"]

    if path.endswith(".jsonl"):
        return errors
    if path in CRITICAL_FILES and not isinstance(data, dict):
        errors.append(f"{path}: critical state root must be an object")
    baseline = head_json(path)
    if path in CRITICAL_FILES and baseline and not data:
        errors.append(f"{path}: critical state cannot regress to an empty object")
    staged_gap = _count_gap(path, data) if isinstance(data, dict) else None
    baseline_gap = _count_gap(path, baseline) if isinstance(baseline, dict) else None
    if staged_gap is not None and staged_gap > (baseline_gap or 0):
        errors.append(f"{path}: metadata count drift increased from {baseline_gap or 0} to {staged_gap}")
    return errors


def validate_path(path: str) -> list[str]:
    """Validate size and structured content for one staged path."""
    content = staged_content(path)
    errors = []
    if len(content) > MAX_BLOB_BYTES:
        errors.append(f"{path}: staged blob is {len(content)} bytes; limit is {MAX_BLOB_BYTES}")
    if path.endswith((".json", ".jsonl")):
        errors.extend(validate_json(path, content))
    return errors


def main() -> int:
    """Validate every staged artifact and return nonzero on regression."""
    errors = []
    for path in staged_paths():
        errors.extend(validate_path(path))
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Staged state validation OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
