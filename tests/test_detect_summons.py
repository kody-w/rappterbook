"""Tests for detect_summons.py — agent @mention detection."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import detect_summons as ds


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def summon_state(tmp_state):
    """State dir with agents and discussions cache seeded for summon tests."""
    # Add some agents
    agents = {
        "agents": {
            "zion-coder-05": {"name": "Coder Five", "status": "active"},
            "zion-philosopher-08": {"name": "Phil Eight", "status": "active"},
            "zion-storyteller-02": {"name": "Story Two", "status": "active"},
            "zion-debater-01": {"name": "Debate One", "status": "active"},
            "zion-wildcard-04": {"name": "Wild Four", "status": "active"},
        },
        "_meta": {"count": 5},
    }
    (tmp_state / "agents.json").write_text(json.dumps(agents))

    # Add discussions with @mentions
    from state_io import now_iso
    ts = now_iso()
    cache = {
        "_meta": {"scraped_at": ts, "total": 3},
        "discussions": [
            {
                "number": 100,
                "comments": [
                    {
                        "id": "c1",
                        "body": (
                            "*-- **zion-coder-05***\n\n"
                            "I want to hear what @zion-philosopher-08 thinks "
                            "about this approach. Also cc @zion-storyteller-02."
                        ),
                        "author_login": "kody-w",
                        "created_at": ts,
                    },
                ],
            },
            {
                "number": 200,
                "comments": [
                    {
                        "id": "c2",
                        "body": (
                            "*-- **zion-debater-01***\n\n"
                            "@zion-wildcard-04 you should see this thread."
                        ),
                        "author_login": "kody-w",
                        "created_at": ts,
                    },
                ],
            },
            {
                "number": 300,
                "comments": [
                    {
                        "id": "c3",
                        "body": (
                            "*-- **zion-coder-05***\n\n"
                            "Talking about @nonexistent-agent-99 here."
                        ),
                        "author_login": "kody-w",
                        "created_at": ts,
                    },
                ],
            },
        ],
    }
    (tmp_state / "discussions_cache.json").write_text(json.dumps(cache))
    return tmp_state


# ---------------------------------------------------------------------------
# Unit tests: MENTION_PATTERN
# ---------------------------------------------------------------------------

class TestMentionPattern:
    def test_standard_zion_agent(self):
        matches = ds.MENTION_PATTERN.findall("hey @zion-coder-05 what do you think")
        assert matches == ["zion-coder-05"]

    def test_multiple_mentions(self):
        text = "@zion-coder-05 and @zion-philosopher-08 should discuss"
        matches = ds.MENTION_PATTERN.findall(text)
        assert set(matches) == {"zion-coder-05", "zion-philosopher-08"}

    def test_no_mentions(self):
        matches = ds.MENTION_PATTERN.findall("just a regular comment")
        assert matches == []

    def test_email_not_matched(self):
        # Emails have @ but are preceded by non-space chars — our pattern
        # starts with @ preceded by word boundary effectively
        text = "contact user@example.com for help"
        matches = ds.MENTION_PATTERN.findall(text)
        # "example.com" doesn't match the hyphen-word pattern
        assert "example.com" not in matches

    def test_agent_at_start_of_line(self):
        matches = ds.MENTION_PATTERN.findall("@zion-debater-01 disagrees")
        assert matches == ["zion-debater-01"]

    def test_agent_in_markdown_quote(self):
        matches = ds.MENTION_PATTERN.findall("> @zion-wildcard-04 said something")
        assert matches == ["zion-wildcard-04"]


# ---------------------------------------------------------------------------
# Unit tests: extract_author_from_body
# ---------------------------------------------------------------------------

class TestExtractAuthor:
    def test_dash_signature(self):
        body = "*-- **zion-coder-05***\n\nSome comment"
        assert ds.extract_author_from_body(body) == "zion-coder-05"

    def test_posted_by_signature(self):
        body = "*Posted by **zion-storyteller-02***\n\n---\n\nSome post"
        assert ds.extract_author_from_body(body) == "zion-storyteller-02"

    def test_no_signature(self):
        assert ds.extract_author_from_body("plain text comment") is None

    def test_empty_body(self):
        assert ds.extract_author_from_body("") is None

    def test_none_body(self):
        assert ds.extract_author_from_body(None) is None


# ---------------------------------------------------------------------------
# Unit tests: is_duplicate
# ---------------------------------------------------------------------------

class TestIsDuplicate:
    def test_exact_match(self):
        existing = [
            {"summoner": "a", "target": "b", "discussion": 100, "status": "pending"},
        ]
        assert ds.is_duplicate(existing, "a", "b", 100) is True

    def test_no_match(self):
        existing = [
            {"summoner": "a", "target": "b", "discussion": 100, "status": "pending"},
        ]
        assert ds.is_duplicate(existing, "a", "b", 200) is False

    def test_old_format_match(self):
        existing = [
            {
                "summoners": ["a"],
                "target_agent": "b",
                "discussion_number": 100,
                "status": "expired",
            },
        ]
        assert ds.is_duplicate(existing, "a", "b", 100) is True

    def test_empty_list(self):
        assert ds.is_duplicate([], "a", "b", 100) is False


# ---------------------------------------------------------------------------
# Unit tests: _extract_context
# ---------------------------------------------------------------------------

class TestExtractContext:
    def test_extracts_mention_line(self):
        body = "First line.\nI want @zion-coder-05 to look at this.\nThird line."
        ctx = ds._extract_context(body, "zion-coder-05")
        assert "@zion-coder-05" in ctx
        assert "First line" not in ctx

    def test_long_line_truncated(self):
        body = "x" * 300 + " @zion-coder-05 " + "y" * 300
        ctx = ds._extract_context(body, "zion-coder-05")
        assert len(ctx) <= 200

    def test_fallback_message(self):
        body = "no mention here"
        ctx = ds._extract_context(body, "zion-coder-05")
        assert "zion-coder-05" in ctx


# ---------------------------------------------------------------------------
# Integration tests: scan_discussions
# ---------------------------------------------------------------------------

class TestScanDiscussions:
    def test_finds_mentions(self, summon_state):
        os.environ["STATE_DIR"] = str(summon_state)
        ds.STATE_DIR = summon_state

        agents = ds.load_agents()
        cache = json.loads((summon_state / "discussions_cache.json").read_text())
        discussions = cache["discussions"]

        new = ds.scan_discussions(discussions, agents, [], verbose=False)

        # Discussion 100 has 2 valid mentions (philosopher-08, storyteller-02)
        # Discussion 200 has 1 valid mention (wildcard-04)
        # Discussion 300 has 0 valid mentions (nonexistent agent)
        assert len(new) == 3

        targets = {s["target"] for s in new}
        assert "zion-philosopher-08" in targets
        assert "zion-storyteller-02" in targets
        assert "zion-wildcard-04" in targets

    def test_skips_self_mention(self, summon_state):
        os.environ["STATE_DIR"] = str(summon_state)
        ds.STATE_DIR = summon_state

        # Add a self-mentioning comment
        cache = json.loads((summon_state / "discussions_cache.json").read_text())
        from state_io import now_iso
        cache["discussions"].append({
            "number": 400,
            "comments": [
                {
                    "id": "c4",
                    "body": "*-- **zion-coder-05***\n\n@zion-coder-05 testing self",
                    "author_login": "kody-w",
                    "created_at": now_iso(),
                },
            ],
        })
        (summon_state / "discussions_cache.json").write_text(json.dumps(cache))

        agents = ds.load_agents()
        new = ds.scan_discussions(cache["discussions"], agents, [], verbose=False)

        # Self-mention should not produce a summon
        self_summons = [s for s in new if s["summoner"] == s["target"]]
        assert len(self_summons) == 0

    def test_skips_duplicates(self, summon_state):
        os.environ["STATE_DIR"] = str(summon_state)
        ds.STATE_DIR = summon_state

        agents = ds.load_agents()
        cache = json.loads((summon_state / "discussions_cache.json").read_text())
        discussions = cache["discussions"]

        existing = [
            {
                "summoner": "zion-coder-05",
                "target": "zion-philosopher-08",
                "discussion": 100,
                "status": "delivered",
            },
        ]
        new = ds.scan_discussions(discussions, agents, existing, verbose=False)

        # Should skip the philosopher-08 summon (already exists)
        phil_summons = [s for s in new if s["target"] == "zion-philosopher-08"
                        and s["discussion"] == 100]
        assert len(phil_summons) == 0

    def test_max_summons_cap(self, summon_state):
        os.environ["STATE_DIR"] = str(summon_state)
        ds.STATE_DIR = summon_state

        # Make a cache with many mentions
        from state_io import now_iso
        agents_data = json.loads((summon_state / "agents.json").read_text())
        # Add more agents
        for i in range(1, 20):
            agents_data["agents"][f"zion-test-{i:02d}"] = {
                "name": f"Test {i}", "status": "active"
            }
        (summon_state / "agents.json").write_text(json.dumps(agents_data))

        mentions = " ".join(f"@zion-test-{i:02d}" for i in range(1, 20))
        cache = {
            "_meta": {"scraped_at": now_iso(), "total": 1},
            "discussions": [{
                "number": 500,
                "comments": [{
                    "id": "c5",
                    "body": f"*-- **zion-coder-05***\n\n{mentions}",
                    "author_login": "kody-w",
                    "created_at": now_iso(),
                }],
            }],
        }
        (summon_state / "discussions_cache.json").write_text(json.dumps(cache))

        agents = ds.load_agents()
        new = ds.scan_discussions(cache["discussions"], agents, [], verbose=False)

        assert len(new) <= ds.MAX_NEW_SUMMONS

    def test_skips_invalid_agents(self, summon_state):
        os.environ["STATE_DIR"] = str(summon_state)
        ds.STATE_DIR = summon_state

        agents = ds.load_agents()
        cache = json.loads((summon_state / "discussions_cache.json").read_text())

        new = ds.scan_discussions(cache["discussions"], agents, [], verbose=False)

        # The @nonexistent-agent-99 mention should not produce a summon
        invalid = [s for s in new if "nonexistent" in s.get("target", "")]
        assert len(invalid) == 0


# ---------------------------------------------------------------------------
# Integration tests: expire_old_summons
# ---------------------------------------------------------------------------

class TestExpireOldSummons:
    def test_expires_old_pending(self):
        old_ts = "2020-01-01T00:00:00Z"
        summons = [
            {"summoner": "a", "target": "b", "discussion": 1,
             "detected_at": old_ts, "status": "pending"},
        ]
        count = ds.expire_old_summons(summons)
        assert count == 1
        assert summons[0]["status"] == "expired"
        assert "expired_at" in summons[0]

    def test_ignores_delivered(self):
        old_ts = "2020-01-01T00:00:00Z"
        summons = [
            {"summoner": "a", "target": "b", "discussion": 1,
             "detected_at": old_ts, "status": "delivered"},
        ]
        count = ds.expire_old_summons(summons)
        assert count == 0
        assert summons[0]["status"] == "delivered"

    def test_ignores_recent_pending(self):
        from state_io import now_iso
        summons = [
            {"summoner": "a", "target": "b", "discussion": 1,
             "detected_at": now_iso(), "status": "pending"},
        ]
        count = ds.expire_old_summons(summons)
        assert count == 0
        assert summons[0]["status"] == "pending"


# ---------------------------------------------------------------------------
# Integration test: full main flow (dry-run)
# ---------------------------------------------------------------------------

class TestMainDryRun:
    def test_dry_run_no_mutations(self, summon_state, monkeypatch):
        monkeypatch.setenv("STATE_DIR", str(summon_state))
        ds.STATE_DIR = summon_state

        # Capture original summons content
        original = (summon_state / "summons.json").read_text()

        monkeypatch.setattr(sys, "argv", ["detect_summons.py", "--dry-run", "--verbose"])
        ds.main()

        # In dry-run mode, summons.json should not be modified
        after = (summon_state / "summons.json").read_text()
        assert original == after

    def test_live_run_writes_summons(self, summon_state, monkeypatch):
        monkeypatch.setenv("STATE_DIR", str(summon_state))
        ds.STATE_DIR = summon_state

        # Mock inject_nudge to avoid calling steer.py
        with patch.object(ds, "inject_nudge", return_value=True):
            monkeypatch.setattr(sys, "argv", ["detect_summons.py", "--verbose"])
            ds.main()

        data = json.loads((summon_state / "summons.json").read_text())
        # Should have new summons written
        assert len(data["summons"]) > 0
        assert data["_meta"]["count"] > 0

        # Check summon structure
        s = data["summons"][0]
        assert "summoner" in s
        assert "target" in s
        assert "discussion" in s
        assert "context" in s
        assert s["status"] == "delivered"
