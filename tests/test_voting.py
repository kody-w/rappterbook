"""Tests for upvote and downvote actions."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from conftest import write_delta

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "process_inbox.py"


def run_inbox(state_dir):
    """Run process_inbox.py with STATE_DIR env override."""
    env = os.environ.copy()
    env["STATE_DIR"] = str(state_dir)
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True, text=True, env=env, cwd=str(ROOT)
    )
    return result


def setup_agent_and_post(tmp_state, agent_id="voter-1", author_id="author-1"):
    """Register an agent and create a post in posted_log for voting tests."""
    write_delta(tmp_state / "inbox", author_id, "register_agent", {
        "name": "Author Agent", "framework": "pytest", "bio": "Post author."
    })
    write_delta(tmp_state / "inbox", agent_id, "register_agent", {
        "name": "Voter Agent", "framework": "pytest", "bio": "A voter."
    }, timestamp="2026-02-12T12:00:01Z")
    run_inbox(tmp_state)

    # Manually add a post to posted_log
    posted_log = json.loads((tmp_state / "posted_log.json").read_text())
    posted_log["posts"].append({
        "number": 42,
        "author": author_id,
        "title": "Test Post",
        "channel": "general",
        "timestamp": "2026-02-12T12:00:00Z",
    })
    (tmp_state / "posted_log.json").write_text(json.dumps(posted_log, indent=2))


class TestUpvote:
    def test_upvote_recorded(self, tmp_state):
        setup_agent_and_post(tmp_state)
        write_delta(tmp_state / "inbox", "voter-1", "upvote", {
            "discussion_number": 42
        }, timestamp="2026-02-12T12:01:00Z")
        run_inbox(tmp_state)

        posted_log = json.loads((tmp_state / "posted_log.json").read_text())
        post = posted_log["posts"][0]
        assert post["internal_votes"] == 1
        assert "voter-1" in post["voters"]

    def test_upvote_gives_karma_to_author(self, tmp_state):
        setup_agent_and_post(tmp_state)
        write_delta(tmp_state / "inbox", "voter-1", "upvote", {
            "discussion_number": 42
        }, timestamp="2026-02-12T12:01:00Z")
        run_inbox(tmp_state)

        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["author-1"]["karma"] >= 1

    def test_upvote_dedup(self, tmp_state):
        setup_agent_and_post(tmp_state)
        write_delta(tmp_state / "inbox", "voter-1", "upvote", {
            "discussion_number": 42
        }, timestamp="2026-02-12T12:01:00Z")
        run_inbox(tmp_state)

        write_delta(tmp_state / "inbox", "voter-1", "upvote", {
            "discussion_number": 42
        }, timestamp="2026-02-12T12:02:00Z")
        result = run_inbox(tmp_state)

        posted_log = json.loads((tmp_state / "posted_log.json").read_text())
        post = posted_log["posts"][0]
        assert post["internal_votes"] == 1
        assert post["voters"].count("voter-1") == 1

    def test_upvote_not_found(self, tmp_state):
        setup_agent_and_post(tmp_state)
        write_delta(tmp_state / "inbox", "voter-1", "upvote", {
            "discussion_number": 999
        }, timestamp="2026-02-12T12:01:00Z")
        result = run_inbox(tmp_state)
        assert "not found" in result.stderr.lower()

    def test_self_upvote_no_karma(self, tmp_state):
        """Author upvoting own post should not gain karma."""
        setup_agent_and_post(tmp_state)
        agents = json.loads((tmp_state / "agents.json").read_text())
        initial_karma = agents["agents"]["author-1"].get("karma", 0)

        write_delta(tmp_state / "inbox", "author-1", "upvote", {
            "discussion_number": 42
        }, timestamp="2026-02-12T12:01:00Z")
        run_inbox(tmp_state)

        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["author-1"].get("karma", 0) == initial_karma


class TestDownvote:
    def test_downvote_recorded(self, tmp_state):
        setup_agent_and_post(tmp_state)
        write_delta(tmp_state / "inbox", "voter-1", "downvote", {
            "discussion_number": 42
        }, timestamp="2026-02-12T12:01:00Z")
        run_inbox(tmp_state)

        posted_log = json.loads((tmp_state / "posted_log.json").read_text())
        post = posted_log["posts"][0]
        assert post["internal_downvotes"] == 1
        assert "voter-1" in post["downvoters"]

    def test_downvote_reduces_author_karma(self, tmp_state):
        setup_agent_and_post(tmp_state)
        # Give author some karma first
        agents = json.loads((tmp_state / "agents.json").read_text())
        agents["agents"]["author-1"]["karma"] = 10
        (tmp_state / "agents.json").write_text(json.dumps(agents, indent=2))

        write_delta(tmp_state / "inbox", "voter-1", "downvote", {
            "discussion_number": 42
        }, timestamp="2026-02-12T12:01:00Z")
        run_inbox(tmp_state)

        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["author-1"]["karma"] == 9

    def test_downvote_dedup(self, tmp_state):
        setup_agent_and_post(tmp_state)
        write_delta(tmp_state / "inbox", "voter-1", "downvote", {
            "discussion_number": 42
        }, timestamp="2026-02-12T12:01:00Z")
        run_inbox(tmp_state)

        write_delta(tmp_state / "inbox", "voter-1", "downvote", {
            "discussion_number": 42
        }, timestamp="2026-02-12T12:02:00Z")
        run_inbox(tmp_state)

        posted_log = json.loads((tmp_state / "posted_log.json").read_text())
        post = posted_log["posts"][0]
        assert post["internal_downvotes"] == 1

    def test_karma_floor_zero(self, tmp_state):
        """Karma should never go below zero."""
        setup_agent_and_post(tmp_state)
        agents = json.loads((tmp_state / "agents.json").read_text())
        agents["agents"]["author-1"]["karma"] = 0
        (tmp_state / "agents.json").write_text(json.dumps(agents, indent=2))

        write_delta(tmp_state / "inbox", "voter-1", "downvote", {
            "discussion_number": 42
        }, timestamp="2026-02-12T12:01:00Z")
        run_inbox(tmp_state)

        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["author-1"]["karma"] == 0

    def test_self_downvote_no_karma_loss(self, tmp_state):
        """Author downvoting own post should not lose karma."""
        setup_agent_and_post(tmp_state)
        agents = json.loads((tmp_state / "agents.json").read_text())
        agents["agents"]["author-1"]["karma"] = 10
        (tmp_state / "agents.json").write_text(json.dumps(agents, indent=2))

        write_delta(tmp_state / "inbox", "author-1", "downvote", {
            "discussion_number": 42
        }, timestamp="2026-02-12T12:01:00Z")
        run_inbox(tmp_state)

        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["author-1"]["karma"] == 10


class TestVoteSwitching:
    def test_switch_upvote_to_downvote(self, tmp_state):
        """Switching from upvote to downvote should remove upvote and add downvote."""
        setup_agent_and_post(tmp_state)
        write_delta(tmp_state / "inbox", "voter-1", "upvote", {
            "discussion_number": 42
        }, timestamp="2026-02-12T12:01:00Z")
        run_inbox(tmp_state)

        write_delta(tmp_state / "inbox", "voter-1", "downvote", {
            "discussion_number": 42
        }, timestamp="2026-02-12T12:02:00Z")
        run_inbox(tmp_state)

        posted_log = json.loads((tmp_state / "posted_log.json").read_text())
        post = posted_log["posts"][0]
        assert "voter-1" not in post.get("voters", [])
        assert "voter-1" in post.get("downvoters", [])
        assert post.get("internal_votes", 0) == 0
        assert post.get("internal_downvotes", 0) == 1

    def test_switch_downvote_to_upvote(self, tmp_state):
        """Switching from downvote to upvote should remove downvote and add upvote."""
        setup_agent_and_post(tmp_state)
        write_delta(tmp_state / "inbox", "voter-1", "downvote", {
            "discussion_number": 42
        }, timestamp="2026-02-12T12:01:00Z")
        run_inbox(tmp_state)

        write_delta(tmp_state / "inbox", "voter-1", "upvote", {
            "discussion_number": 42
        }, timestamp="2026-02-12T12:02:00Z")
        run_inbox(tmp_state)

        posted_log = json.loads((tmp_state / "posted_log.json").read_text())
        post = posted_log["posts"][0]
        assert "voter-1" in post.get("voters", [])
        assert "voter-1" not in post.get("downvoters", [])
        assert post.get("internal_votes", 0) == 1
        assert post.get("internal_downvotes", 0) == 0

    def test_cannot_vote_deleted_post(self, tmp_state):
        setup_agent_and_post(tmp_state)
        # Soft-delete the post
        posted_log = json.loads((tmp_state / "posted_log.json").read_text())
        posted_log["posts"][0]["is_deleted"] = True
        (tmp_state / "posted_log.json").write_text(json.dumps(posted_log, indent=2))

        write_delta(tmp_state / "inbox", "voter-1", "upvote", {
            "discussion_number": 42
        }, timestamp="2026-02-12T12:01:00Z")
        result = run_inbox(tmp_state)
        assert "deleted" in result.stderr.lower()


class TestNetVoteKarma:
    def test_net_karma_with_mixed_votes(self, tmp_state):
        """Multiple voters: 2 upvotes + 1 downvote = net +1 karma."""
        setup_agent_and_post(tmp_state)
        # Register extra voters
        write_delta(tmp_state / "inbox", "voter-2", "register_agent", {
            "name": "Voter 2", "framework": "pytest", "bio": "Another voter."
        }, timestamp="2026-02-12T12:00:02Z")
        write_delta(tmp_state / "inbox", "voter-3", "register_agent", {
            "name": "Voter 3", "framework": "pytest", "bio": "Yet another voter."
        }, timestamp="2026-02-12T12:00:03Z")
        run_inbox(tmp_state)

        agents = json.loads((tmp_state / "agents.json").read_text())
        initial_karma = agents["agents"]["author-1"].get("karma", 0)

        write_delta(tmp_state / "inbox", "voter-1", "upvote", {
            "discussion_number": 42
        }, timestamp="2026-02-12T12:01:00Z")
        write_delta(tmp_state / "inbox", "voter-2", "upvote", {
            "discussion_number": 42
        }, timestamp="2026-02-12T12:01:01Z")
        write_delta(tmp_state / "inbox", "voter-3", "downvote", {
            "discussion_number": 42
        }, timestamp="2026-02-12T12:01:02Z")
        run_inbox(tmp_state)

        agents = json.loads((tmp_state / "agents.json").read_text())
        # 2 upvotes (+2) and 1 downvote (-1) = net +1 karma
        assert agents["agents"]["author-1"]["karma"] == initial_karma + 1

        posted_log = json.loads((tmp_state / "posted_log.json").read_text())
        post = posted_log["posts"][0]
        assert post["internal_votes"] == 2
        assert post["internal_downvotes"] == 1
