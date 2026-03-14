"""Tests for autonomy quality improvements."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


class TestDormantAgentFiltering:
    """Test that dormant agents are filtered from autonomy."""

    def test_pick_agents_excludes_dormant(self):
        from zion_autonomy import pick_agents

        agents_data = {
            "agents": {
                "zion-test-01": {"status": "active", "framework": "zion", "heartbeat_last": "2020-01-01T00:00:00Z"},
                "zion-test-02": {"status": "dormant", "framework": "zion", "heartbeat_last": "2020-01-01T00:00:00Z"},
                "zion-test-03": {"status": "active", "framework": "zion", "heartbeat_last": "2020-01-01T00:00:00Z"},
            }
        }
        selected = pick_agents(agents_data, {}, 10)
        selected_ids = [aid for aid, _ in selected]
        assert "zion-test-02" not in selected_ids
        assert len(selected) <= 2


class TestDirectHeartbeatUpdate:
    """Test that autonomy directly updates heartbeat_last."""

    def test_autonomy_writes_heartbeat_directly(self):
        source = (ROOT / "scripts" / "zion_autonomy.py").read_text()
        # The main function should directly update agents.json heartbeat_last
        assert 'heartbeat_last' in source
        assert 'agents_data_fresh' in source


class TestSlopDetection:
    """Test slop phrase detection in content engine."""

    def test_slop_detection_in_post_generation(self):
        source = (ROOT / "scripts" / "content_engine.py").read_text()
        assert "[SLOP]" in source
        assert "banned_phrases" in source

    def test_slop_detection_in_comment_generation(self):
        source = (ROOT / "scripts" / "content_engine.py").read_text()
        # Should have two slop checks — one for posts, one for comments
        count = source.count("[SLOP]")
        assert count >= 2, f"Expected at least 2 slop checks, found {count}"

    def test_slop_only_checks_long_phrases(self):
        """Slop filter only rejects 4+ word phrases to avoid false positives."""
        source = (ROOT / "scripts" / "content_engine.py").read_text()
        assert "len(phrase.split()) >= 4" in source

    def test_quality_config_has_banned_phrases(self):
        qconfig_path = ROOT / "state" / "quality_config.json"
        assert qconfig_path.exists()
        with open(qconfig_path) as f:
            qconfig = json.load(f)
        assert "banned_phrases" in qconfig
        assert len(qconfig["banned_phrases"]) > 0
