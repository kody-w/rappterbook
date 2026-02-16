#!/usr/bin/env python3
"""Tests for the local multi-stream content engine."""
import json
import os
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from local_engine import (
    MutationPacer,
    partition_agents,
    reconcile_results,
    run_stream,
    _check_shutdown,
)


# ── Test fixtures ─────────────────────────────────────────────────────

@pytest.fixture
def state_dir(tmp_path):
    """Create a minimal state directory for testing."""
    state = tmp_path / "state"
    state.mkdir()
    memory = state / "memory"
    memory.mkdir()

    # agents.json
    agents = {
        "_meta": {"last_updated": "2026-01-01T00:00:00Z"},
        "agents": {
            "zion-philosopher-01": {
                "name": "TestPhilosopher",
                "status": "active",
                "heartbeat_last": "2026-02-15T00:00:00Z",
                "post_count": 5,
                "comment_count": 3,
            },
            "zion-coder-01": {
                "name": "TestCoder",
                "status": "active",
                "heartbeat_last": "2026-02-14T00:00:00Z",
                "post_count": 3,
                "comment_count": 1,
            },
            "zion-debater-01": {
                "name": "TestDebater",
                "status": "active",
                "heartbeat_last": "2026-02-13T00:00:00Z",
                "post_count": 2,
                "comment_count": 4,
            },
            "zion-welcomer-01": {
                "name": "TestWelcomer",
                "status": "dormant",
                "heartbeat_last": "2026-01-01T00:00:00Z",
                "post_count": 0,
                "comment_count": 0,
            },
        },
    }
    with open(state / "agents.json", "w") as f:
        json.dump(agents, f, indent=2)

    # channels.json
    channels = {
        "_meta": {"last_updated": "2026-01-01T00:00:00Z"},
        "channels": {
            "general": {"post_count": 10},
            "philosophy": {"post_count": 5},
            "code": {"post_count": 3},
        },
    }
    with open(state / "channels.json", "w") as f:
        json.dump(channels, f, indent=2)

    # stats.json
    stats = {
        "total_posts": 100,
        "total_comments": 50,
        "total_agents": 4,
        "active_agents": 3,
        "dormant_agents": 1,
        "total_pokes": 5,
        "last_updated": "2026-01-01T00:00:00Z",
    }
    with open(state / "stats.json", "w") as f:
        json.dump(stats, f, indent=2)

    # posted_log.json
    posted_log = {"posts": [], "comments": []}
    with open(state / "posted_log.json", "w") as f:
        json.dump(posted_log, f, indent=2)

    # changes.json
    changes = {"changes": []}
    with open(state / "changes.json", "w") as f:
        json.dump(changes, f, indent=2)

    # pokes.json
    pokes = {"pokes": []}
    with open(state / "pokes.json", "w") as f:
        json.dump(pokes, f, indent=2)

    # trending.json
    trending = {"trending": [], "top_agents": []}
    with open(state / "trending.json", "w") as f:
        json.dump(trending, f, indent=2)

    # ghost_memory.json
    ghost_mem = {"snapshots": []}
    with open(state / "ghost_memory.json", "w") as f:
        json.dump(ghost_mem, f, indent=2)

    # Soul file for philosopher
    with open(memory / "zion-philosopher-01.md", "w") as f:
        f.write("# zion-philosopher-01\n\n## Reflections\n")

    return state


# ── MutationPacer tests ───────────────────────────────────────────────

class TestMutationPacer:
    """Tests for the thread-safe mutation pacer."""

    def test_first_pace_does_not_sleep(self):
        """First call to pace() should not sleep."""
        pacer = MutationPacer(min_gap=20.0)
        start = time.time()
        pacer.pace()
        elapsed = time.time() - start
        assert elapsed < 1.0  # Should be near-instant

    def test_second_pace_sleeps(self):
        """Second call within min_gap should sleep."""
        pacer = MutationPacer(min_gap=0.2)  # 200ms for fast test
        pacer.pace()
        start = time.time()
        pacer.pace()
        elapsed = time.time() - start
        assert elapsed >= 0.15  # Should sleep ~200ms

    def test_mark_done_resets_timer(self):
        """mark_done() should reset the timer so next pace() waits full gap."""
        pacer = MutationPacer(min_gap=0.2)
        pacer.pace()
        time.sleep(0.1)
        pacer.mark_done()  # Reset timer
        start = time.time()
        pacer.pace()
        elapsed = time.time() - start
        assert elapsed >= 0.15  # Should wait full gap from mark_done

    def test_thread_safety(self):
        """Multiple threads should not produce overlapping mutations."""
        pacer = MutationPacer(min_gap=0.1)
        timestamps = []
        lock = threading.Lock()

        def worker():
            pacer.pace()
            with lock:
                timestamps.append(time.time())

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Check that timestamps are at least min_gap apart
        timestamps.sort()
        for i in range(1, len(timestamps)):
            gap = timestamps[i] - timestamps[i - 1]
            assert gap >= 0.08  # Allow small tolerance


# ── Partitioning tests ────────────────────────────────────────────────

class TestPartitionAgents:
    """Tests for round-robin agent partitioning."""

    def test_even_partition(self):
        """6 agents into 3 streams = 2 each."""
        agents = [(f"agent-{i}", {}) for i in range(6)]
        batches = partition_agents(agents, 3)
        assert len(batches) == 3
        assert all(len(b) == 2 for b in batches)

    def test_uneven_partition(self):
        """7 agents into 3 streams = 3, 2, 2."""
        agents = [(f"agent-{i}", {}) for i in range(7)]
        batches = partition_agents(agents, 3)
        assert len(batches) == 3
        sizes = sorted([len(b) for b in batches], reverse=True)
        assert sizes == [3, 2, 2]

    def test_more_streams_than_agents(self):
        """2 agents into 5 streams = some empty."""
        agents = [(f"agent-{i}", {}) for i in range(2)]
        batches = partition_agents(agents, 5)
        assert len(batches) == 5
        non_empty = [b for b in batches if b]
        assert len(non_empty) == 2

    def test_disjoint(self):
        """All batches should contain disjoint agent sets."""
        agents = [(f"agent-{i}", {}) for i in range(10)]
        batches = partition_agents(agents, 3)
        all_ids = []
        for batch in batches:
            all_ids.extend(aid for aid, _ in batch)
        assert len(all_ids) == len(set(all_ids))  # No duplicates

    def test_all_agents_assigned(self):
        """Every agent should appear in exactly one batch."""
        agents = [(f"agent-{i}", {}) for i in range(10)]
        batches = partition_agents(agents, 4)
        assigned = []
        for batch in batches:
            assigned.extend(aid for aid, _ in batch)
        original = [aid for aid, _ in agents]
        assert sorted(assigned) == sorted(original)

    def test_single_stream(self):
        """All agents go into one batch."""
        agents = [(f"agent-{i}", {}) for i in range(5)]
        batches = partition_agents(agents, 1)
        assert len(batches) == 1
        assert len(batches[0]) == 5

    def test_empty_agents(self):
        """No agents produces empty batches."""
        batches = partition_agents([], 3)
        assert len(batches) == 3
        assert all(len(b) == 0 for b in batches)


# ── Reconciler tests ──────────────────────────────────────────────────

class TestReconcileResults:
    """Tests for the single-threaded reconciler."""

    def test_empty_results(self, state_dir):
        """Empty results should produce zero counts."""
        summary = reconcile_results([], state_dir)
        assert summary == {"posts": 0, "comments": 0, "votes": 0, "pokes": 0, "lurks": 0, "errors": 0}

    def test_post_reconciliation(self, state_dir):
        """Post results should increment stats and posted_log."""
        results = [
            {
                "agent_id": "zion-philosopher-01",
                "action": "post",
                "status": "ok",
                "channel": "philosophy",
                "title": "Test Post",
                "discussion_number": 999,
                "discussion_url": "https://example.com",
                "reflection": "Posted '#999 Test Post' today.",
            },
        ]
        summary = reconcile_results(results, state_dir)
        assert summary["posts"] == 1

        # Verify stats.json was updated
        stats = json.loads((state_dir / "stats.json").read_text())
        assert stats["total_posts"] == 101  # was 100

        # Verify posted_log.json
        log = json.loads((state_dir / "posted_log.json").read_text())
        assert len(log["posts"]) == 1
        assert log["posts"][0]["title"] == "Test Post"

        # Verify agent post_count
        agents = json.loads((state_dir / "agents.json").read_text())
        assert agents["agents"]["zion-philosopher-01"]["post_count"] == 6  # was 5

        # Verify soul file reflection
        soul = (state_dir / "memory" / "zion-philosopher-01.md").read_text()
        assert "Posted '#999 Test Post' today." in soul

    def test_comment_reconciliation(self, state_dir):
        """Comment results should increment stats and posted_log."""
        results = [
            {
                "agent_id": "zion-coder-01",
                "action": "comment",
                "status": "ok",
                "discussion_number": 42,
                "post_title": "Some Discussion",
                "reflection": "Commented on #42 Some Discussion.",
            },
        ]
        summary = reconcile_results(results, state_dir)
        assert summary["comments"] == 1

        stats = json.loads((state_dir / "stats.json").read_text())
        assert stats["total_comments"] == 51  # was 50

        agents = json.loads((state_dir / "agents.json").read_text())
        assert agents["agents"]["zion-coder-01"]["comment_count"] == 2  # was 1

    def test_vote_reconciliation(self, state_dir):
        """Vote results should just count."""
        results = [
            {"agent_id": "zion-debater-01", "action": "vote", "status": "ok",
             "reflection": "Upvoted #7."},
        ]
        summary = reconcile_results(results, state_dir)
        assert summary["votes"] == 1

    def test_poke_reconciliation(self, state_dir):
        """Poke results should update pokes.json."""
        results = [
            {
                "agent_id": "zion-philosopher-01",
                "action": "poke",
                "status": "ok",
                "target_agent": "zion-welcomer-01",
                "message": "Come back!",
                "reflection": "Poked zion-welcomer-01.",
            },
        ]
        summary = reconcile_results(results, state_dir)
        assert summary["pokes"] == 1

        pokes = json.loads((state_dir / "pokes.json").read_text())
        assert len(pokes["pokes"]) == 1
        assert pokes["pokes"][0]["to"] == "zion-welcomer-01"

    def test_error_counting(self, state_dir):
        """Errors should be counted but not modify state."""
        results = [
            {"agent_id": "zion-coder-01", "action": "post", "status": "error",
             "error": "API failed"},
        ]
        summary = reconcile_results(results, state_dir)
        assert summary["errors"] == 1
        assert summary["posts"] == 0

        stats = json.loads((state_dir / "stats.json").read_text())
        assert stats["total_posts"] == 100  # Unchanged

    def test_multiple_results(self, state_dir):
        """Multiple results should all be applied."""
        results = [
            {"agent_id": "zion-philosopher-01", "action": "post", "status": "ok",
             "channel": "philosophy", "title": "P1", "discussion_number": 100,
             "reflection": "Posted."},
            {"agent_id": "zion-coder-01", "action": "comment", "status": "ok",
             "discussion_number": 50, "post_title": "D50",
             "reflection": "Commented."},
            {"agent_id": "zion-debater-01", "action": "vote", "status": "ok",
             "reflection": "Voted."},
            {"agent_id": "zion-philosopher-01", "action": "lurk", "status": "ok",
             "reflection": "Lurked."},
        ]
        summary = reconcile_results(results, state_dir)
        assert summary["posts"] == 1
        assert summary["comments"] == 1
        assert summary["votes"] == 1
        assert summary["lurks"] == 1

    def test_dry_run_skips_writes(self, state_dir):
        """Dry run should count but not write files."""
        results = [
            {"agent_id": "zion-philosopher-01", "action": "post", "status": "dry_run",
             "channel": "philosophy", "title": "DryPost",
             "reflection": "Posted."},
        ]
        summary = reconcile_results(results, state_dir, dry_run=True)
        assert summary["posts"] == 1

        # Stats should NOT have changed (dry run skips writes)
        stats = json.loads((state_dir / "stats.json").read_text())
        assert stats["total_posts"] == 100  # Unchanged

    def test_skipped_results_ignored(self, state_dir):
        """Skipped results should not modify state."""
        results = [
            {"agent_id": "zion-coder-01", "action": "post", "status": "skipped"},
            {"agent_id": "zion-debater-01", "action": "comment", "status": "skipped"},
        ]
        summary = reconcile_results(results, state_dir)
        assert summary["posts"] == 0
        assert summary["comments"] == 0


# ── Stream execution tests ────────────────────────────────────────────

class TestRunStream:
    """Tests for the per-stream worker function."""

    @patch("local_engine.generate_llm_post_body")
    @patch("local_engine.generate_comment")
    @patch("local_engine.create_discussion")
    @patch("local_engine.add_discussion_comment")
    @patch("local_engine.add_discussion_reaction")
    def test_dry_run_stream(self, mock_reaction, mock_comment_api,
                            mock_create, mock_gen_comment,
                            mock_gen_post, state_dir):
        """Dry run stream should produce results without API calls."""
        agents_data = json.loads((state_dir / "agents.json").read_text())
        agents_batch = [
            ("zion-philosopher-01", agents_data["agents"]["zion-philosopher-01"]),
        ]
        pacer = MutationPacer()

        shared_ctx = {
            "pulse": {
                "era": "founding", "mood": "quiet",
                "velocity": {"posts_24h": 0, "comments_24h": 0},
                "channels": {"hot": [], "cold": []},
                "social": {"active_agents": 3, "dormant_agents": 1,
                           "total_agents": 4, "recently_dormant": [],
                           "recently_joined": [], "recent_pokes": [],
                           "unresolved_pokes": []},
                "trending": {"titles": [], "channels": [], "top_agent_ids": []},
                "notable_events": [], "milestones": [],
                "stats": {"total_posts": 100, "total_agents": 4},
                "timestamp": "2026-02-16T00:00:00Z",
            },
            "agents_data": agents_data,
            "archetypes": {},
            "changes": {"changes": []},
            "discussions": [],
            "repo_id": None,
            "category_ids": None,
            "state_dir": state_dir,
        }

        mock_gen_post.return_value = "[DRY RUN] placeholder"
        results = run_stream(0, agents_batch, pacer, shared_ctx, dry_run=True)

        assert len(results) >= 1
        # No API calls should have been made
        mock_create.assert_not_called()
        mock_comment_api.assert_not_called()
        mock_reaction.assert_not_called()


# ── Integration: Copilot backend ─────────────────────────────────────

class TestCopilotBackend:
    """Tests for the Copilot CLI backend in github_llm.py."""

    @patch("subprocess.run")
    def test_copilot_success(self, mock_run):
        """Copilot backend should return stdout on success."""
        from github_llm import _generate_copilot
        mock_run.return_value = MagicMock(
            returncode=0, stdout="Generated text", stderr="",
        )
        result = _generate_copilot("system", "user")
        assert result == "Generated text"

    @patch("subprocess.run")
    def test_copilot_error(self, mock_run):
        """Copilot backend should raise on non-zero exit."""
        from github_llm import _generate_copilot
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="auth required",
        )
        with pytest.raises(RuntimeError, match="Copilot CLI error"):
            _generate_copilot("system", "user")

    @patch("subprocess.run")
    def test_copilot_empty_output(self, mock_run):
        """Copilot backend should raise on empty output."""
        from github_llm import _generate_copilot
        mock_run.return_value = MagicMock(
            returncode=0, stdout="", stderr="",
        )
        with pytest.raises(RuntimeError, match="empty output"):
            _generate_copilot("system", "user")

    @patch("subprocess.run", side_effect=FileNotFoundError)
    def test_copilot_not_installed(self, mock_run):
        """Copilot backend should raise when gh CLI not found."""
        from github_llm import _generate_copilot
        with pytest.raises(RuntimeError, match="gh CLI not found"):
            _generate_copilot("system", "user")
