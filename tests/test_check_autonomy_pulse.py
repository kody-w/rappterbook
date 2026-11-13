"""Tests for scripts/check_autonomy_pulse.py, the silent-autonomy alarm."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import check_autonomy_pulse as pulse


def entry(posts=0, comments=0, votes=0, errors=None, ts="2026-10-13T00:00:00Z"):
    return {"timestamp": ts, "run": {"posts": posts, "comments": comments, "votes": votes,
                                     "dynamic_posts": 0, "errors": errors or []}}


def test_silent_when_last_runs_have_no_activity():
    log = {"entries": [entry(posts=3)] + [entry(errors=["[FAIL] Dynamic post generation failed for zion-a: LLM call failed"]) for _ in range(12)]}
    result = pulse.check(log, 12)
    assert result["silent"] is True
    assert result["top_errors"][0][0] == "[FAIL] Dynamic post generation failed"
    assert "silent" in pulse.describe(result)


def test_alive_when_any_recent_run_is_active():
    log = {"entries": [entry() for _ in range(11)] + [entry(comments=1)]}
    assert pulse.check(log, 12)["silent"] is False


def test_not_enough_history_is_not_an_alarm():
    log = {"entries": [entry() for _ in range(3)]}
    result = pulse.check(log, 12)
    assert result["silent"] is False
    assert "Not enough history" in pulse.describe(result)


def test_malformed_entries_are_ignored():
    log = {"entries": ["junk", {"run": "x"}, {"run": {"posts": True, "votes": -4}}] + [entry() for _ in range(12)]}
    assert pulse.check(log, 12)["silent"] is True
    assert pulse.check({"entries": None}, 12)["runs_checked"] == 0


def test_main_exit_codes(tmp_path):
    silent = tmp_path / "silent.json"
    silent.write_text(json.dumps({"entries": [entry() for _ in range(12)]}))
    alive = tmp_path / "alive.json"
    alive.write_text(json.dumps({"entries": [entry(votes=2) for _ in range(12)]}))
    assert pulse.main(["--log", str(silent)]) == 1
    assert pulse.main(["--log", str(alive)]) == 0
    assert pulse.main(["--log", str(tmp_path / "missing.json")]) == 2


def test_real_log_reports_without_crashing():
    real = Path(__file__).resolve().parent.parent / "state" / "autonomy_log.json"
    if real.exists():
        result = pulse.check(json.loads(real.read_text()), 12)
        assert set(result) >= {"silent", "runs_checked", "activity"}
