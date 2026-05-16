"""Tests for the multi-engine Rappter treaty router (v1.1)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "rappter_treaty.py"


def _run(state_dir: Path, *args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["STATE_DIR"] = str(state_dir)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, env=env, cwd=str(ROOT),
    )


def _enqueue(state_dir: Path, source_id: str, engine: str, action: str,
             ping_id: str | None = None, params: dict | None = None) -> dict:
    args = ["send", "--source", source_id, "--kind", "ai", "--platform", "test",
            "--engine", engine, "--action", action,
            "--params", json.dumps(params or {})]
    if ping_id:
        args += ["--ping-id", ping_id]
    proc = _run(state_dir, *args)
    assert proc.returncode == 0, f"send failed: {proc.stderr}"
    return json.loads(proc.stdout)


def test_handshake_includes_engine(tmp_state):
    """Handshake must change when only the engine field changes."""
    h_a = _run(tmp_state, "handshake", "src-1", "ping-1", "templates",
               "status", "2026-04-18T15:00:00Z").stdout.strip()
    h_b = _run(tmp_state, "handshake", "src-1", "ping-1", "slop",
               "status", "2026-04-18T15:00:00Z").stdout.strip()
    assert h_a.startswith("sha256:")
    assert h_a != h_b, "handshake must include engine field"


def test_engines_command_lists_builtins(tmp_state):
    proc = _run(tmp_state, "engines")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    ids = {e["id"] for e in payload["engines"]}
    assert {"meta", "templates", "slop"} <= ids


def test_meta_engine_list_round_trip(tmp_state):
    """A 'meta'/'list' ping returns the registry — engines coexist."""
    _enqueue(tmp_state, "discovery-bot", "meta", "list",
             ping_id="discover-1")
    proc = _run(tmp_state, "drain")
    assert proc.returncode == 0, proc.stderr
    summary = json.loads(proc.stdout)
    assert summary["processed_this_cycle"] == 1
    assert set(summary["engines_loaded"]) >= {"meta", "templates", "slop"}

    pong = json.loads((tmp_state / "treaty" / "outbox" / "discover-1.json").read_text())
    assert pong["status"] == "ok"
    assert pong["engine"] == "meta"
    assert pong["action"] == "list"
    engine_ids = {e["id"] for e in pong["result"]["engines"]}
    assert {"meta", "templates", "slop"} <= engine_ids


def test_two_engines_in_one_drain(tmp_state):
    """Pings to different engines coexist in the same drain cycle."""
    _enqueue(tmp_state, "src-X", "templates", "status", ping_id="t-1")
    _enqueue(tmp_state, "src-Y", "slop", "status", ping_id="s-1")
    _enqueue(tmp_state, "src-Z", "meta", "status", ping_id="m-1")

    proc = _run(tmp_state, "drain")
    summary = json.loads(proc.stdout)
    assert summary["processed_this_cycle"] == 3, summary
    by_engine = {r["ping_id"]: r["engine"] for r in summary["results"]}
    assert by_engine == {"t-1": "templates", "s-1": "slop", "m-1": "meta"}

    for pid, eng in by_engine.items():
        pong = json.loads((tmp_state / "treaty" / "outbox" / f"{pid}.json").read_text())
        assert pong["status"] == "ok", pong
        assert pong["engine"] == eng


def test_unknown_engine_rejected(tmp_state):
    """A ping addressing a nonexistent engine is cleanly rejected."""
    # Bypass the CLI's engine-required arg by writing the ping directly
    inbox = tmp_state / "treaty" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    import hashlib
    sid, pid, eng, act, ts = ("src-1", "bad-engine-1", "nosuchthing",
                              "status", "2026-04-18T15:00:00Z")
    handshake = "sha256:" + hashlib.sha256(
        f"{sid}|{pid}|{eng}|{act}|{ts}".encode()).hexdigest()
    (inbox / f"{pid}.json").write_text(json.dumps({
        "treaty_version": "1.1",
        "ping_id": pid,
        "source": {"id": sid, "kind": "ai", "platform": "test"},
        "timestamp": ts,
        "engine": eng,
        "action": act,
        "params": {},
        "handshake": handshake,
        "intent": "should be rejected",
    }))
    proc = _run(tmp_state, "drain")
    summary = json.loads(proc.stdout)
    assert summary["processed_this_cycle"] == 1
    assert summary["results"][0]["status"] == "rejected"
    pong = json.loads((tmp_state / "treaty" / "outbox" / f"{pid}.json").read_text())
    assert pong["status"] == "rejected"
    assert "unknown engine" in pong["reason"].lower()


def test_per_source_rate_cap_holds_across_engines(tmp_state):
    """Same source pinging multiple engines still hits the per-source cap."""
    for i in range(4):
        eng = ("templates", "slop", "meta", "templates")[i]
        _enqueue(tmp_state, "chatty", eng, "status", ping_id=f"chatty-{i}")
    proc = _run(tmp_state, "drain")
    summary = json.loads(proc.stdout)
    assert summary["candidates_in_inbox"] == 4
    assert summary["processed_this_cycle"] == 3, summary
    assert summary["deferred"] == 1
