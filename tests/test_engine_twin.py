"""Tests for the rappter engine twin."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def twin_state(tmp_path):
    """Build a minimal state dir suitable for the engine twin."""
    sd = tmp_path / "state"
    (sd / "inbox").mkdir(parents=True)
    (sd / "memory").mkdir()
    (sd / "agents.json").write_text(json.dumps({
        "agents": {
            "twin-a": {"name": "Alpha", "framework": "twin", "bio": "alpha agent",
                       "last_active": "2026-04-18T00:00:00Z"},
            "twin-b": {"name": "Bravo", "framework": "twin", "bio": "bravo agent",
                       "last_active": "2026-04-18T00:00:00Z"},
            "twin-c": {"name": "Charlie", "framework": "twin", "bio": "charlie agent",
                       "last_active": "2026-04-18T00:00:00Z"},
        }
    }))
    (sd / "changes.json").write_text(json.dumps({"changes": []}))
    (sd / "seeds.json").write_text(json.dumps({"active": None}))
    return sd


def _run_module(module: str, args: list[str], state_dir: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["STATE_DIR"] = str(state_dir)
    return subprocess.run(
        [sys.executable, "-m", module, *args],
        capture_output=True, text=True, env=env, cwd=str(ROOT),
    )


def test_run_frame_dry_run_writes_heartbeats(twin_state):
    res = _run_module("engine.fleet.run_frame",
                      ["--count", "3", "--seed", "1", "--dry-run"], twin_state)
    assert res.returncode == 0, res.stderr
    inbox = list((twin_state / "inbox").glob("*.json"))
    assert len(inbox) == 3
    for f in inbox:
        d = json.loads(f.read_text())
        assert d["action"] == "heartbeat"
        assert d["agent_id"].startswith("twin-")
        assert "timestamp" in d
        assert d["payload"] == {}


def test_run_frame_deterministic_with_seed(twin_state):
    """Same seed → same agent set."""
    r1 = _run_module("engine.fleet.run_frame",
                     ["--count", "2", "--seed", "99", "--dry-run"], twin_state)
    assert r1.returncode == 0
    set1 = sorted(p.name.split("-2026-")[0] for p in (twin_state / "inbox").glob("*.json"))

    # clear and re-run with same seed
    for f in (twin_state / "inbox").glob("*.json"):
        f.unlink()
    r2 = _run_module("engine.fleet.run_frame",
                     ["--count", "2", "--seed", "99", "--dry-run"], twin_state)
    assert r2.returncode == 0
    set2 = sorted(p.name.split("-2026-")[0] for p in (twin_state / "inbox").glob("*.json"))
    assert set1 == set2


def test_run_frame_specific_agent(twin_state):
    res = _run_module("engine.fleet.run_frame",
                      ["--agent", "twin-b", "--dry-run"], twin_state)
    assert res.returncode == 0, res.stderr
    inbox = list((twin_state / "inbox").glob("*.json"))
    assert len(inbox) == 1
    assert json.loads(inbox[0].read_text())["agent_id"] == "twin-b"


def test_print_only_writes_nothing(twin_state):
    res = _run_module("engine.fleet.run_frame",
                      ["--count", "1", "--print-only"], twin_state)
    assert res.returncode == 0, res.stderr
    assert list((twin_state / "inbox").glob("*.json")) == []
    assert "SYSTEM:" in res.stdout
    assert "USER:" in res.stdout


def test_pulse_loop_runs_multiple_frames(twin_state, tmp_path):
    snap = tmp_path / "pulse.json"
    res = _run_module("engine.loops.pulse",
                      ["--frames", "3", "--agents", "2", "--dry-run",
                       "--save", str(snap), "--seed", "7"], twin_state)
    assert res.returncode == 0, res.stderr
    assert snap.exists()
    data = json.loads(snap.read_text())
    assert data["frame"] == 3
    assert len(data["deltas"]) == 3
    assert data["engine_version"] == "twin-1.0"


def test_pulse_resume(twin_state, tmp_path):
    snap = tmp_path / "pulse.json"
    r1 = _run_module("engine.loops.pulse",
                     ["--frames", "2", "--agents", "1", "--dry-run",
                      "--save", str(snap)], twin_state)
    assert r1.returncode == 0, r1.stderr

    r2 = _run_module("engine.loops.pulse",
                     ["--frames", "2", "--dry-run",
                      "--resume", str(snap), "--save", str(snap)], twin_state)
    assert r2.returncode == 0, r2.stderr
    data = json.loads(snap.read_text())
    assert data["frame"] == 4


def test_delta_format_matches_inbox_contract(twin_state):
    """Deltas the twin produces must match what process_issues.py writes."""
    _run_module("engine.fleet.run_frame",
                ["--count", "1", "--dry-run"], twin_state)
    inbox = list((twin_state / "inbox").glob("*.json"))
    assert len(inbox) == 1
    d = json.loads(inbox[0].read_text())
    # The four required top-level keys per the existing contract
    assert set(d.keys()) == {"action", "agent_id", "timestamp", "payload"}
    assert isinstance(d["payload"], dict)
