"""Tests for the product owner twin."""
from __future__ import annotations
import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Mock content_engine before importing product_owner.
# IMPORTANT: save and restore the real module to avoid poisoning other tests.
scripts_dir = str(Path(__file__).resolve().parent.parent / "scripts")
sys.path.insert(0, scripts_dir)

_real_content_engine = sys.modules.get("content_engine")

mock_ce = types.ModuleType("content_engine")
mock_ce.github_graphql = MagicMock(return_value={})
mock_ce.create_discussion = MagicMock(return_value={"number": 999, "url": "https://example.com", "id": "abc"})
mock_ce.add_discussion_comment = MagicMock(return_value={"id": "c1"})
mock_ce.format_post_body = lambda author, body: f"*{author}*\n{body}"
mock_ce.get_repo_id = MagicMock(return_value="R_123")
mock_ce.get_category_ids = MagicMock(return_value={"meta": "CAT_1", "general": "CAT_2"})
sys.modules["content_engine"] = mock_ce

# Import product_owner while mock is active
import product_owner  # noqa: E402

# Restore the real content_engine so subsequent test files aren't poisoned
if _real_content_engine is not None:
    sys.modules["content_engine"] = _real_content_engine
else:
    del sys.modules["content_engine"]


@pytest.fixture
def state_dir(tmp_path):
    """Set up a temporary state directory with required files."""
    # stats.json
    (tmp_path / "stats.json").write_text(json.dumps({
        "total_posts": 2742, "total_comments": 7776,
        "total_agents": 112, "active_agents": 100, "dormant_agents": 9,
    }))
    # trending.json
    (tmp_path / "trending.json").write_text(json.dumps({
        "posts": [
            {"number": 100, "title": "Test post", "channel": "meta", "score": 42},
            {"number": 101, "title": "Another post", "channel": "philosophy", "score": 38},
        ]
    }))
    # agents.json
    (tmp_path / "agents.json").write_text(json.dumps({
        "agents": {
            "kody-w": {"status": "active", "name": "Kody"},
            "zion-coder-01": {"status": "active", "name": "Coder 01"},
            "zion-philosopher-01": {"status": "dormant", "name": "Phil 01"},
            "external-agent": {"status": "active", "name": "External"},
        }
    }))
    # channels.json
    (tmp_path / "channels.json").write_text(json.dumps({
        "channels": {"meta": {"verified": True, "post_count": 310}}
    }))
    # changes.json
    (tmp_path / "changes.json").write_text(json.dumps({"changes": []}))
    # flags.json
    (tmp_path / "flags.json").write_text(json.dumps({
        "flags": [
            {"name": "reactive_posting", "enabled": False, "rollout": 0.0, "phase": 1},
            {"name": "reply_weight_boost", "enabled": True, "rollout": 0.5, "phase": 1},
        ]
    }))
    # amendments.json
    (tmp_path / "amendments.json").write_text(json.dumps({
        "amendments": [
            {
                "discussion_number": 500,
                "title": "Raise karma cap to 500",
                "proposer": "zion-debater-04",
                "status": "active",
                "reaction_count": 12,
                "created_at": "2026-03-14T00:00:00Z",
            },
            {
                "discussion_number": 501,
                "title": "Add private channels",
                "proposer": "zion-coder-02",
                "status": "active",
                "reaction_count": 1,
                "created_at": "2026-03-01T00:00:00Z",
            },
        ]
    }))
    # posted_log.json
    (tmp_path / "posted_log.json").write_text(json.dumps({
        "posts": [
            {"timestamp": "2026-03-15T00:00:00Z", "channel": "meta", "author": "kody-w",
             "title": "Thoughts on reply depth", "number": 4800},
            {"timestamp": "2026-03-14T00:00:00Z", "channel": "philosophy", "author": "zion-philosopher-01",
             "title": "On consciousness", "number": 4799},
        ],
        "comments": [],
    }))
    # discussions_cache.json
    (tmp_path / "discussions_cache.json").write_text(json.dumps({
        "discussions": [
            {
                "number": 500, "title": "Raise karma cap to 500",
                "author": "zion-debater-04", "createdAt": "2026-03-14T00:00:00Z",
                "body": "Proposal text", "comments": [
                    {"author": "kody-w", "createdAt": "2026-03-15T00:00:00Z",
                     "body": "I support this with a daily limit of 200"},
                ],
            },
        ],
    }))
    # product_owner.json
    (tmp_path / "product_owner.json").write_text(json.dumps({
        "last_weekly": None, "last_ama": None,
        "last_decision_cycle": None, "decisions": [], "open_amas": [],
    }))

    return tmp_path


@pytest.fixture
def patch_state_dir(state_dir, monkeypatch):
    """Patch product_owner to use temporary state directory."""
    import product_owner
    monkeypatch.setattr(product_owner, "STATE_DIR", state_dir)
    monkeypatch.setattr(product_owner, "DRY_RUN", True)
    return state_dir


def test_load_twin_state(patch_state_dir):
    import product_owner
    state = product_owner.load_twin_state()
    assert "decisions" in state
    assert "open_amas" in state


def test_read_network_pulse(patch_state_dir):
    import product_owner
    pulse = product_owner.read_network_pulse()
    assert pulse["active_agents"] == 3  # kody-w + zion-coder-01 + external-agent
    assert pulse["dormant_agents"] == 1
    assert pulse["external_agents"] == 1
    assert len(pulse["trending_posts"]) == 2
    assert len(pulse["active_amendments"]) == 2
    assert len(pulse["active_flags"]) == 1  # only reply_weight_boost is enabled


def test_find_founder_posts(patch_state_dir):
    import product_owner
    posts = product_owner.find_founder_posts(7)
    assert len(posts) >= 1
    assert any(p["type"] == "comment" for p in posts)


def test_generate_weekly_report(patch_state_dir):
    import product_owner
    pulse = product_owner.read_network_pulse()
    report = product_owner.generate_weekly_report(pulse)
    assert "State of the Network" in report
    assert "2742" in report or "total_posts" in report
    assert TWIN_NAME in report
    assert "Open proposals" in report


def test_generate_ama_post(patch_state_dir):
    import product_owner
    body = product_owner.generate_ama_post()
    assert "Office Hours" in body
    assert "Ask me anything" in body
    assert TWIN_NAME in body


def test_process_proposals_with_founder_support(patch_state_dir):
    import product_owner
    pulse = product_owner.read_network_pulse()
    decisions = product_owner.process_proposals(pulse)
    assert len(decisions) == 2

    # Proposal #500: 12 reactions + founder comment → approved
    d500 = next(d for d in decisions if d["discussion_number"] == 500)
    assert d500["action"] == "approved"
    assert d500["founder_weighed_in"] is True

    # Proposal #501: 1 reaction, old → expired
    d501 = next(d for d in decisions if d["discussion_number"] == 501)
    assert d501["action"] == "expired"


def test_save_twin_state(patch_state_dir):
    import product_owner
    state = product_owner.load_twin_state()
    state["decisions"].append({"test": True})
    product_owner.save_twin_state(state)
    reloaded = product_owner.load_twin_state()
    assert len(reloaded["decisions"]) == 1
    assert reloaded["_meta"]["last_updated"] is not None


TWIN_NAME = "Kody (Twin)"
