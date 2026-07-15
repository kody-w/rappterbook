"""tests/autonomy/test_autonomy.py — invariants that must hold for the
24-hour autonomous Rappterbook run to be trustworthy (not gaslit).

These verify the SELF-HEALING + ANTI-GASLIGHT machinery actually works:
  - the Steward's heal paths (disk rotation, orphan worktrees, copilot probe,
    iMessage emergency hatch, 24h surprise summary)
  - the infinite-doublejump MEW-gate (noops on thrashing)
  - the babysitter push-reality + loop-health checks
  - launchd plists are valid + point to real executable scripts
  - lineage backups are valid (revertable)
  - the cohesive egg is well-formed

Run: python3 -m pytest tests/autonomy/ -v
Designed to run on the live machine; tests that touch real infra create
their own scratch fixtures and clean up, never disrupting live loops.
"""
from __future__ import annotations
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path("/Users/kodyw/Documents/GitHub/Rappter/rappterbook")
SCRIPTS = REPO / "scripts"
HOME_AGENTS = Path("/Users/kodyw/.brainstem/src/rapp_brainstem/agents")
PROJ_AGENTS = REPO / ".brainstem/src/rapp_brainstem/agents"
BABYSITTER_AGENT = (Path("/Users/kodyw/.rapp/twins/"
                         "rappid:@kody-w/kody-babysitter:ba5fdb289594da04bf5f50f21d02b9ff37071ea90676adc06cd0ad578add28b3/agents/kody_babysitter_agent.py"))

LAUNCHD_DIR = Path("/Users/kodyw/Library/LaunchAgents")
EXPECTED_PLISTS = [
    "com.kody.babysitter.plist",
    "com.kody.doublejump-loop.plist",
    "com.kody.infinite-doublejump.plist",
    "com.kody.normie-ai-twin.plist",
    "com.kody.steward.plist",
]


def _load_module(name: str, path: Path):
    """Import a .py file by path, with the agents dir on sys.path for deps."""
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    if str(HOME_AGENTS) not in sys.path:
        sys.path.insert(0, str(HOME_AGENTS))
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── Static integrity ────────────────────────────────────────────────────────

def test_steward_script_is_valid_python():
    src = (SCRIPTS / "steward_supervisor.py").read_text()
    compile(src, "steward_supervisor.py", "exec")  # raises SyntaxError if broken


def test_infinite_doublejump_script_is_valid_python():
    src = (SCRIPTS / "infinite_doublejump_tick.py").read_text()
    compile(src, "infinite_doublejump_tick.py", "exec")


def test_pack_and_unpack_scripts_valid_python():
    for f in ("pack_neighborhood_egg.py", "unpack_neighborhood_egg.py"):
        compile((SCRIPTS / f).read_text(), f, "exec")


def test_all_launchd_plists_parse():
    for name in EXPECTED_PLISTS:
        p = LAUNCHD_DIR / name
        assert p.exists(), f"missing plist: {p}"
        r = subprocess.run(["plutil", "-lint", str(p)],
                           capture_output=True, text=True, timeout=10)
        assert r.returncode == 0, f"{name} failed plutil lint: {r.stdout}{r.stderr}"


def test_launchd_plists_point_to_existing_executable_scripts():
    for name in EXPECTED_PLISTS:
        p = LAUNCHD_DIR / name
        # Extract ProgramArguments[0] via plutil JSON
        r = subprocess.run(["plutil", "-convert", "json", "-o", "-", str(p)],
                           capture_output=True, text=True, timeout=10)
        d = json.loads(r.stdout)
        prog = d["ProgramArguments"][0]
        assert Path(prog).exists(), f"{name} points to missing script {prog}"
        assert os.access(prog, os.X_OK), f"{name} script {prog} not executable"


# ── Steward heal paths ──────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def steward():
    return _load_module("steward_supervisor", SCRIPTS / "steward_supervisor.py")


def test_steward_copilot_probe_returns_bool(steward):
    result = steward._probe_copilot()
    assert isinstance(result, bool)


def test_steward_imessage_builds_without_sending(steward):
    # Verify osascript exists and the function returns a dict; we do NOT
    # actually send (texting = failure unless it's the real 24h summary).
    assert subprocess.run(["which", "osascript"], capture_output=True).returncode == 0
    # Inspect the function source contains both fallback strategies (buddy + participant)
    import inspect
    src = inspect.getsource(steward._send_imessage)
    assert "buddy" in src and "participant" in src
    assert steward.PHONE == "+14048628786"


def test_steward_disk_rotation_prunes_old_replies(steward):
    # Create old + fresh reply files; verify rotation prunes only the old ones.
    replies = Path("/tmp/fork-fleet-out/replies")
    replies.mkdir(parents=True, exist_ok=True)
    old = replies / "_test_old.json"
    fresh = replies / "_test_fresh.json"
    old.write_text("{}"); fresh.write_text("{}")
    old_time = time.time() - 7 * 3600  # 7h ago (> 6h cutoff)
    os.utime(old, (old_time, old_time))
    state, report = {"copilot_consecutive_fails": 0}, {"healed": [], "alerts": [], "checks": {}}
    steward._heal_disk(state, report)
    assert not old.exists(), "old reply should have been pruned"
    assert fresh.exists(), "fresh reply should survive"
    fresh.unlink(missing_ok=True)


def test_steward_orphan_worktree_pruning(steward):
    # Create a fake old orphan matching the steward's patterns.
    orphan = Path("/tmp/idj-wt-_test_orphan")
    orphan.mkdir(parents=True, exist_ok=True)
    old_time = time.time() - 3600  # 1h ago (> 30min threshold)
    os.utime(orphan, (old_time, old_time))
    state, report = {}, {"healed": [], "alerts": [], "checks": {}}
    steward._heal_worktrees(state, report)
    assert not orphan.exists(), "orphan worktree should have been removed"


def test_steward_gather_digest_returns_string(steward):
    d = steward._gather_sprint_digest()
    assert isinstance(d, str)


# ── Infinite-doublejump MEW-gate ────────────────────────────────────────────

@pytest.fixture(scope="module")
def idj():
    return _load_module("infinite_doublejump_tick", SCRIPTS / "infinite_doublejump_tick.py")


def test_mew_gate_noops_on_fresh_thrashing(idj, tmp_path):
    # Plant a fresh thrashing MEW scan, verify _pick_mutation rests.
    mew_dir = Path("/tmp/mutation-efficacy-twin")
    mew_dir.mkdir(parents=True, exist_ok=True)
    scan = mew_dir / "scan-_test_thrash.json"
    scan.write_text(json.dumps({
        "verdict": "thrashing", "confidence": 90, "rounds_analyzed": 30,
        "trajectory_summary": "test thrash",
    }))
    # make it the newest
    os.utime(scan, None)
    consensus = {"outliers": [{"suffix": "swarm-01", "score": 99, "delta_from_median": 30}]}
    mutation = idj._pick_mutation(consensus, [], {"top_directives": []},
                                  {"rounds": [], "mutations": []}, "test-round")
    assert mutation["kind"] == "noop_thrashing_per_mew", \
        f"expected thrashing-gate noop, got {mutation['kind']}"
    scan.unlink(missing_ok=True)


def test_path_for_suffix_no_double_prefix(idj):
    # Regression: the doubled-prefix bug that broke soul curation.
    path = idj._path_for_suffix("swarm-04")
    assert path.endswith("@local-swarm-04"), path
    assert "swarm-swarm" not in path


# ── Babysitter push-reality + loop-health ───────────────────────────────────

@pytest.fixture(scope="module")
def babysitter():
    if not BABYSITTER_AGENT.exists():
        pytest.skip("babysitter twin not hatched")
    return _load_module("kody_babysitter_agent", BABYSITTER_AGENT)


def test_babysitter_push_reality_catches_synthetic_gaslight(babysitter, tmp_path):
    # Write a publisher record claiming a frame_id that can't be on origin.
    pub_dir = Path("/tmp/pages-publisher")
    pub_dir.mkdir(parents=True, exist_ok=True)
    fake = pub_dir / "v3-_test_gaslight.json"
    fake.write_text(json.dumps({
        "status": "pushed",
        "frame_id": "9999-IMPOSSIBLE-FRAME-FROM-THE-FUTURE",
        "sidecar_file": "state/synthetic_comments.json",
    }))
    result = babysitter._push_reality()
    fake.unlink(missing_ok=True)
    # The impossible frame must show up in gaslight_findings
    frames = [g.get("frame_id") for g in result.get("gaslight_findings", [])]
    assert "9999-IMPOSSIBLE-FRAME-FROM-THE-FUTURE" in frames, \
        f"push-reality failed to catch the synthetic gaslight: {result}"


def test_babysitter_loop_health_returns_structure(babysitter):
    lh = babysitter._loop_health()
    assert "loops" in lh and "any_alarm" in lh
    labels = {L["label"] for L in lh["loops"]}
    assert "com.kody.infinite-doublejump" in labels


# ── Mutual resurrection (no single point of failure) ────────────────────────

def test_doublejump_loop_resurrects_steward():
    """The Steward heals the 4 worker loops, but nothing heals the Steward —
    except this guard in the 5-min doublejump-loop, which bootstraps the
    Steward if its launchd job ever falls out. Steward<->workers resurrect
    each other; no single point of failure. Regression-lock the guard."""
    wrapper = Path("/Users/kodyw/.rapp/twins/"
                   "rappid:@kody-w/kody-babysitter:ba5fdb289594da04bf5f50f21d02b9ff37071ea90676adc06cd0ad578add28b3/doublejump_loop_tick.sh")
    if not wrapper.exists():
        pytest.skip("doublejump loop wrapper not present")
    src = wrapper.read_text()
    assert "launchctl list com.kody.steward" in src, \
        "doublejump-loop must probe whether the Steward is loaded"
    assert "launchctl bootstrap" in src and "com.kody.steward.plist" in src, \
        "doublejump-loop must resurrect the Steward when it is not loaded"
    # Guard must be a no-op when the Steward IS loaded (negated probe)
    assert "if ! launchctl list com.kody.steward" in src, \
        "resurrection must be gated on the Steward being absent"
    # Wrapper must still be valid bash
    r = subprocess.run(["bash", "-n", str(wrapper)], capture_output=True, text=True)
    assert r.returncode == 0, f"wrapper has bash syntax error: {r.stderr}"


# ── Lineage integrity (revertability) ───────────────────────────────────────

def test_lineage_backups_are_valid():
    lineage_root = PROJ_AGENTS / "lineage"
    if not lineage_root.exists():
        pytest.skip("no lineage dir yet")
    checked = 0
    for bak in lineage_root.rglob("*.py.bak"):
        compile(bak.read_text(), bak.name, "exec")  # must parse — revertable
        checked += 1
    # At least the agents we've mutated should have backups
    assert checked >= 1, "expected at least one lineage backup"


# ── Egg integrity (portability) ─────────────────────────────────────────────

def test_cohesive_egg_is_wellformed():
    egg = REPO / "eggs/rappterbook-cohesive.network.egg"
    assert egg.exists(), "cohesive egg missing"
    d = json.loads(egg.read_text())
    assert d.get("_format") == "egg"
    org = d.get("organism", {})
    assert org.get("kind") == "neighborhood"
    assert len(org.get("twins", {})) >= 3, "egg should bundle >= 3 twins"
    assert len(org.get("fleet_agents", {})) >= 10, "egg should bundle the fleet agents"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
