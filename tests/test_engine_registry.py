"""Tests for the engine registry and adapter coexistence."""
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
    sd = tmp_path / "state"
    (sd / "inbox").mkdir(parents=True)
    (sd / "memory").mkdir()
    (sd / "agents.json").write_text(json.dumps({
        "agents": {
            f"reg-{i:02d}": {
                "name": f"Reg {i}",
                "framework": "test",
                "bio": f"agent {i}",
                "last_active": "2026-04-18T00:00:00Z",
            } for i in range(1, 6)
        }
    }))
    (sd / "changes.json").write_text(json.dumps({"changes": []}))
    (sd / "seeds.json").write_text(json.dumps({"active": None}))
    (sd / "stats.json").write_text(json.dumps({}))
    return sd


def _run(args: list[str], state_dir: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["STATE_DIR"] = str(state_dir)
    return subprocess.run(
        [sys.executable, "-m", "engine.run", *args],
        capture_output=True, text=True, env=env, cwd=str(ROOT),
    )


def test_registry_lists_all_engines(twin_state):
    res = _run(["list"], twin_state)
    assert res.returncode == 0, res.stderr
    for name in ("rappter", "ghost", "swarm"):
        assert name in res.stdout


def test_check_reports_no_overlap(twin_state):
    res = _run(["check"], twin_state)
    assert res.returncode == 0, res.stderr
    assert "no domain overlap" in res.stdout


def test_engines_have_disjoint_domains():
    """The whole point: adapters must claim non-overlapping state slices."""
    sys.path.insert(0, str(ROOT))
    from engine import registry
    domains = [a.domain for a in registry.all_engines()]
    assert len(domains) == len(set(domains)), f"domain overlap: {domains}"


def test_tick_each_engine_individually(twin_state):
    for name in ("rappter", "ghost", "swarm"):
        res = _run(["tick", name, "--frame", "1"], twin_state)
        assert res.returncode == 0, f"{name} failed: {res.stderr}"
        # final stdout chunk is the result JSON dump
        last_brace = res.stdout.rfind("{")
        parsed = json.loads(res.stdout[last_brace:].split("\n}")[0] + "\n}")
        assert parsed["engine"] == name
        assert parsed["frame"] == 1


def test_tick_all_runs_every_engine(twin_state):
    res = _run(["tick-all", "--frame", "5"], twin_state)
    assert res.returncode == 0, res.stderr
    for name in ("rappter", "ghost", "swarm"):
        assert f"[{name}]" in res.stdout
    # all three engines reported back
    assert res.stdout.count("\"engine\":") >= 3


def test_rappter_writes_inbox_via_registry(twin_state):
    res = _run(["tick", "rappter", "--opt", "count=2", "--opt", "seed=1"], twin_state)
    assert res.returncode == 0, res.stderr
    inbox_files = list((twin_state / "inbox").glob("*.json"))
    assert len(inbox_files) == 2
    for f in inbox_files:
        d = json.loads(f.read_text())
        assert d["action"] == "heartbeat"
        assert "agent_id" in d


def test_swarm_writes_to_swarms_dir_when_live(twin_state):
    res = _run(["tick", "swarm", "--live", "--opt", "size=3", "--frame", "2"], twin_state)
    assert res.returncode == 0, res.stderr
    swarms = list((twin_state / "swarms").glob("*.json"))
    assert len(swarms) == 1
    snap = json.loads(swarms[0].read_text())
    assert snap["frame"] == 2
    assert "species" in snap and "element" in snap


def test_engines_dont_clobber_each_others_state(twin_state):
    """tick-all then check — rappter wrote inbox, ghost wrote ghost_context, swarm wrote swarms."""
    res = _run(["tick-all", "--live", "--frame", "1"], twin_state)
    assert res.returncode == 0, res.stderr
    assert list((twin_state / "inbox").glob("*.json"))
    assert (twin_state / "ghost_context.json").exists()
    assert list((twin_state / "swarms").glob("*.json"))
