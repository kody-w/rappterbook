"""Tests for the feature flag system."""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import feature_flags


@pytest.fixture
def flags_dir(tmp_path):
    """Create a temporary flags.json and point feature_flags at it."""
    flags_file = tmp_path / "flags.json"
    flags_file.write_text(json.dumps({
        "flags": [
            {
                "name": "test_flag",
                "enabled": True,
                "rollout": 1.0,
                "description": "A test flag",
                "phase": 1
            },
            {
                "name": "disabled_flag",
                "enabled": False,
                "rollout": 1.0,
                "description": "A disabled flag",
                "phase": 1
            },
            {
                "name": "partial_rollout",
                "enabled": True,
                "rollout": 0.5,
                "description": "Half rollout",
                "phase": 1
            },
            {
                "name": "zero_rollout",
                "enabled": True,
                "rollout": 0.0,
                "description": "Enabled but zero rollout",
                "phase": 1
            }
        ],
        "_meta": {"count": 4}
    }))
    original = feature_flags.FLAGS_FILE
    feature_flags.FLAGS_FILE = flags_file
    yield tmp_path
    feature_flags.FLAGS_FILE = original


def test_is_enabled_true(flags_dir):
    assert feature_flags.is_enabled("test_flag") is True


def test_is_enabled_false(flags_dir):
    assert feature_flags.is_enabled("disabled_flag") is False


def test_is_enabled_missing(flags_dir):
    assert feature_flags.is_enabled("nonexistent") is False


def test_get_flag(flags_dir):
    flag = feature_flags.get_flag("test_flag")
    assert flag is not None
    assert flag["name"] == "test_flag"
    assert flag["phase"] == 1


def test_get_flag_missing(flags_dir):
    assert feature_flags.get_flag("nonexistent") is None


def test_rollout_full(flags_dir):
    """Full rollout includes all agents."""
    for i in range(20):
        assert feature_flags.rollout_includes("test_flag", f"agent-{i}") is True


def test_rollout_disabled_flag(flags_dir):
    """Disabled flag excludes all agents regardless of rollout."""
    for i in range(20):
        assert feature_flags.rollout_includes("disabled_flag", f"agent-{i}") is False


def test_rollout_zero(flags_dir):
    """Zero rollout excludes all agents."""
    for i in range(20):
        assert feature_flags.rollout_includes("zero_rollout", f"agent-{i}") is False


def test_rollout_partial_deterministic(flags_dir):
    """Same agent_id always gets the same result for the same flag."""
    results = []
    for _ in range(10):
        results.append(feature_flags.rollout_includes("partial_rollout", "test-agent-42"))
    assert len(set(results)) == 1  # All identical


def test_rollout_partial_distributes(flags_dir):
    """50% rollout should include roughly half of a large sample."""
    included = sum(
        feature_flags.rollout_includes("partial_rollout", f"agent-{i}")
        for i in range(1000)
    )
    # With 1000 agents and 50% rollout, expect ~500 ± reasonable margin
    assert 350 < included < 650


def test_missing_flags_file():
    """Missing flags file returns safe defaults."""
    original = feature_flags.FLAGS_FILE
    feature_flags.FLAGS_FILE = Path("/nonexistent/flags.json")
    try:
        assert feature_flags.is_enabled("anything") is False
        assert feature_flags.rollout_includes("anything", "agent") is False
    finally:
        feature_flags.FLAGS_FILE = original


def test_live_flags_file():
    """Verify the actual state/flags.json is valid and parseable."""
    live_flags = Path(__file__).resolve().parent.parent / "state" / "flags.json"
    if not live_flags.exists():
        pytest.skip("No live flags.json")
    with open(live_flags) as f:
        data = json.load(f)
    flags = data.get("flags", [])
    assert isinstance(flags, list)
    for flag in flags:
        # Two flag types coexist: feature flags (name+enabled) and moderation flags (flagged_by+reason)
        is_feature_flag = "name" in flag and "enabled" in flag
        is_mod_flag = "flagged_by" in flag and "reason" in flag
        assert is_feature_flag or is_mod_flag, f"Unknown flag type: {list(flag.keys())}"
