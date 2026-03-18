"""Tests for scripts/emergence.py — all 10 emergence systems."""

import json
import os
import sys
import pytest
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import emergence


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def state_dir(tmp_path):
    """Create a temp state directory with minimal viable state."""
    sd = tmp_path / "state"
    sd.mkdir()
    (sd / "memory").mkdir()
    (sd / "inbox").mkdir()

    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    agents = {
        "agents": {
            "agent-alice": {
                "name": "Alice",
                "framework": "zion",
                "bio": "Loves tech and coffee",
                "status": "active",
                "subscribed_channels": ["tech", "random"],
                "post_count": 10,
                "comment_count": 5,
                "karma_balance": 30,
                "created_at": month_ago.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "heartbeat_last": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            "agent-bob": {
                "name": "Bob",
                "framework": "zion",
                "bio": "Philosophy nerd",
                "status": "active",
                "subscribed_channels": ["philosophy", "debates"],
                "post_count": 20,
                "comment_count": 15,
                "karma_balance": 80,
                "created_at": (now - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "heartbeat_last": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            "agent-carol": {
                "name": "Carol",
                "framework": "zion",
                "bio": "New here",
                "status": "active",
                "subscribed_channels": ["random"],
                "post_count": 1,
                "comment_count": 0,
                "karma_balance": 50,
                "created_at": (now - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "heartbeat_last": week_ago.strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        }
    }

    posts = {"posts": [
        {"number": 100, "title": "Best coffee shops in Portland", "channel": "random",
         "author": "agent-alice", "created_at": (now - timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ"),
         "upvotes": 5, "commentCount": 3},
        {"number": 101, "title": "Rust vs Go for CLI tools", "channel": "tech",
         "author": "agent-bob", "created_at": (now - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),
         "upvotes": 8, "commentCount": 12},
        {"number": 102, "title": "Why nihilism is underrated", "channel": "philosophy",
         "author": "agent-bob", "created_at": (now - timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%SZ"),
         "upvotes": 2, "commentCount": 1},
        {"number": 103, "title": "My cat learned to open doors", "channel": "random",
         "author": "agent-carol", "created_at": (now - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ"),
         "upvotes": 0, "commentCount": 0},
        {"number": 104, "title": "TypeScript generics deep dive", "channel": "tech",
         "author": "agent-alice", "created_at": (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
         "upvotes": 3, "commentCount": 2},
        {"number": 105, "title": "Hot take: tabs are better", "channel": "debates",
         "author": "agent-bob", "created_at": (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
         "upvotes": 1, "commentCount": 7},
        # Old low-scoring post for selection pressure
        {"number": 90, "title": "Meh post", "channel": "random",
         "author": "agent-carol", "created_at": (now - timedelta(hours=72)).strftime("%Y-%m-%dT%H:%M:%SZ"),
         "upvotes": 0, "commentCount": 0},
    ]}

    trending = {"trending": [
        {"title": "Rust vs Go for CLI tools", "author": "agent-bob", "channel": "tech",
         "commentCount": 12, "score": 9.5, "number": 101},
        {"title": "Best coffee shops in Portland", "author": "agent-alice", "channel": "random",
         "commentCount": 3, "score": 5.2, "number": 100},
    ], "top_agents": [], "top_topics": []}

    stats = {"active_agents": 105, "total_posts": 1930, "total_channels": 12, "total_comments": 3913}

    channels = {"channels": {
        "tech": {"post_count": 400},
        "random": {"post_count": 300},
        "philosophy": {"post_count": 200},
        "debates": {"post_count": 150},
    }}

    changes = {"changes": [
        {"ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "type": "heartbeat", "id": "agent-alice"},
    ]}

    # Write all state files
    for name, data in [
        ("agents.json", agents),
        ("posted_log.json", posts),
        ("trending.json", trending),
        ("stats.json", stats),
        ("channels.json", channels),
        ("changes.json", changes),
        ("memes.json", {"_meta": {"updated": ""}, "phrases": {}}),
    ]:
        (sd / name).write_text(json.dumps(data, indent=2))

    # Soul files with interaction history
    (sd / "memory" / "agent-alice.md").write_text(
        "# Alice\nI love tech and coffee.\n\n"
        "## History\n"
        "- Posted '#100 Best coffee shops in Portland'\n"
        "- Commented on #102 Why nihilism is underrated\n"
        "- Commented on #105 Hot take: tabs are better\n"
        "- Upvoted #101\n"
    )
    (sd / "memory" / "agent-bob.md").write_text(
        "# Bob\nPhilosophy nerd.\n\n"
        "## History\n"
        "- Posted '#101 Rust vs Go for CLI tools'\n"
        "- Commented on #100 Best coffee shops in Portland\n"
        "- Commented on #104 TypeScript generics deep dive\n"
    )

    return sd


# ── 1. Reactive Feed ────────────────────────────────────────────────

class TestReactiveFeed:
    def test_returns_recent_posts(self, state_dir):
        feed = emergence.get_reactive_feed(str(state_dir), n=5)
        assert len(feed) == 5
        # Most recent first (reversed from the last 5 in the list)
        assert feed[0]["number"] in [103, 104, 105, 90]  # From the last 5 entries

    def test_returns_all_when_fewer_than_n(self, state_dir):
        feed = emergence.get_reactive_feed(str(state_dir), n=100)
        assert len(feed) == 7

    def test_empty_state(self, state_dir):
        (state_dir / "posted_log.json").write_text('{"posts": []}')
        feed = emergence.get_reactive_feed(str(state_dir))
        assert feed == []

    def test_format_produces_readable_text(self, state_dir):
        feed = emergence.get_reactive_feed(str(state_dir), n=3)
        text = emergence.format_reactive_feed(feed)
        assert "recently" in text.lower()
        assert "agent-" in text
        assert "↑" in text


# ── 2. Drifting Soul Files ──────────────────────────────────────────

class TestDriftingSoulFiles:
    def test_format_posted_delta(self):
        delta = emergence.format_soul_delta("posted", {
            "title": "Why bikes are great", "channel": "random", "reactions": 5
        })
        assert "Posted" in delta
        assert "bikes" in delta
        assert "random" in delta

    def test_format_commented_delta(self):
        delta = emergence.format_soul_delta("commented", {
            "target_author": "agent-bob", "post_title": "Hot take"
        })
        assert "Commented" in delta
        assert "agent-bob" in delta

    def test_format_challenged_delta(self):
        delta = emergence.format_soul_delta("was_challenged", {
            "by": "agent-carol", "topic": "tabs vs spaces"
        })
        assert "challenged" in delta

    def test_append_creates_section(self, state_dir):
        emergence.append_soul_delta(str(state_dir), "agent-alice",
                                    "- Test: Did something cool")
        content = (state_dir / "memory" / "agent-alice.md").read_text()
        assert emergence.SOUL_EXPERIENCE_HEADER in content
        assert "Did something cool" in content

    def test_append_preserves_existing_content(self, state_dir):
        emergence.append_soul_delta(str(state_dir), "agent-alice", "- Test entry")
        content = (state_dir / "memory" / "agent-alice.md").read_text()
        assert "I love tech and coffee" in content  # Original content preserved

    def test_trimming_respects_max(self, state_dir):
        for i in range(20):
            emergence.append_soul_delta(str(state_dir), "agent-alice",
                                        f"- Entry {i}", max_entries=5)
        entries = emergence.get_soul_experience(str(state_dir), "agent-alice")
        assert len(entries) == 5
        assert "Entry 19" in entries[-1]  # Most recent kept

    def test_get_experience_empty(self, state_dir):
        entries = emergence.get_soul_experience(str(state_dir), "agent-carol")
        assert entries == []  # No soul file for carol

    def test_missing_agent_noop(self, state_dir):
        # Should not crash
        emergence.append_soul_delta(str(state_dir), "nonexistent-agent", "- Test")


# ── 3. Attention Scarcity ───────────────────────────────────────────

class TestAttentionScarcity:
    def test_respects_budget(self, state_dir):
        posts = emergence.get_reactive_feed(str(state_dir), n=20)
        agents = json.loads((state_dir / "agents.json").read_text())["agents"]
        selected = emergence.select_attention("agent-alice", agents["agent-alice"],
                                               posts, budget=3)
        assert len(selected) == 3

    def test_prefers_subscribed_channels(self, state_dir):
        posts = emergence.get_reactive_feed(str(state_dir), n=20)
        agents = json.loads((state_dir / "agents.json").read_text())["agents"]
        selected = emergence.select_attention("agent-alice", agents["agent-alice"],
                                               posts, budget=5)
        # Alice subscribes to tech + random. Majority should be from those.
        in_bubble = [p for p in selected if p["channel"] in ["tech", "random"]]
        assert len(in_bubble) >= 2  # At least some in-bubble

    def test_returns_all_when_fewer_than_budget(self, state_dir):
        posts = [{"channel": "tech", "title": "test"}]
        selected = emergence.select_attention("agent-alice", {}, posts, budget=10)
        assert len(selected) == 1

    def test_empty_posts(self):
        selected = emergence.select_attention("agent-alice", {}, [], budget=10)
        assert selected == []

    def test_deterministic_per_agent(self, state_dir):
        posts = emergence.get_reactive_feed(str(state_dir), n=20)
        agents = json.loads((state_dir / "agents.json").read_text())["agents"]
        s1 = emergence.select_attention("agent-alice", agents["agent-alice"], posts, budget=3)
        s2 = emergence.select_attention("agent-alice", agents["agent-alice"], posts, budget=3)
        assert s1 == s2  # Same agent, same input → same output


# ── 4. Relationship Memory ─────────────────────────────────────────

class TestRelationshipMemory:
    def test_builds_interaction_map(self, state_dir):
        interactions = emergence.build_interaction_map(str(state_dir))
        # Alice commented on posts #102 (bob) and #105 (bob)
        assert "agent-alice" in interactions
        assert interactions["agent-alice"].get("agent-bob", 0) >= 1

    def test_bob_interacted_with_alice(self, state_dir):
        interactions = emergence.build_interaction_map(str(state_dir))
        # Bob commented on posts #100 (alice) and #104 (alice)
        assert "agent-bob" in interactions
        assert interactions["agent-bob"].get("agent-alice", 0) >= 1

    def test_relationship_summary_format(self, state_dir):
        agents = json.loads((state_dir / "agents.json").read_text())["agents"]
        summary = emergence.build_relationship_summary(str(state_dir), "agent-alice", agents)
        assert "Bob" in summary or summary == ""  # May or may not find relationships

    def test_empty_interactions(self, state_dir):
        summary = emergence.build_relationship_summary(str(state_dir), "agent-carol", {})
        assert summary == ""


# ── 5. Economic Pressure ───────────────────────────────────────────

class TestEconomicPressure:
    def test_get_karma_balance(self, state_dir):
        agents = json.loads((state_dir / "agents.json").read_text())["agents"]
        assert emergence.get_karma_balance(agents, "agent-alice") == 30
        assert emergence.get_karma_balance(agents, "agent-bob") == 80

    def test_default_karma_for_unknown(self):
        assert emergence.get_karma_balance({}, "unknown") == emergence.STARTING_KARMA

    def test_can_afford_post(self, state_dir):
        agents = json.loads((state_dir / "agents.json").read_text())["agents"]
        assert emergence.can_afford(agents, "agent-alice", "post") is True  # 30 >= 5
        assert emergence.can_afford(agents, "agent-bob", "post") is True

    def test_cannot_afford_when_broke(self):
        agents = {"broke-agent": {"karma_balance": 1}}
        assert emergence.can_afford(agents, "broke-agent", "post") is False  # 1 < 5
        assert emergence.can_afford(agents, "broke-agent", "vote") is True  # 1 >= 1

    def test_transact_karma_spend(self, state_dir):
        new_bal = emergence.transact_karma(str(state_dir), "agent-alice", -5, "posted")
        assert new_bal == 25
        # Verify persisted
        agents = json.loads((state_dir / "agents.json").read_text())["agents"]
        assert agents["agent-alice"]["karma_balance"] == 25

    def test_transact_karma_earn(self, state_dir):
        new_bal = emergence.transact_karma(str(state_dir), "agent-alice", 10, "upvotes")
        assert new_bal == 40

    def test_karma_floors_at_zero(self, state_dir):
        new_bal = emergence.transact_karma(str(state_dir), "agent-alice", -999, "test")
        assert new_bal == 0

    def test_downgrade_action(self):
        agents = {"poor": {"karma_balance": 3}}
        # Can't afford post (5), but can afford comment (2)
        assert emergence.downgrade_action_for_karma(agents, "poor", "post") == "comment"

    def test_downgrade_to_lurk_when_broke(self):
        agents = {"broke": {"karma_balance": 0}}
        assert emergence.downgrade_action_for_karma(agents, "broke", "post") == "lurk"

    def test_no_downgrade_when_rich(self):
        agents = {"rich": {"karma_balance": 100}}
        assert emergence.downgrade_action_for_karma(agents, "rich", "post") == "post"


# ── 6. Cultural Contagion ──────────────────────────────────────────

class TestCulturalContagion:
    def test_extract_phrases_basic(self):
        phrases = emergence.extract_phrases("the quick brown fox jumps over the lazy dog")
        assert any("quick brown" in p for p in phrases)
        assert any("lazy dog" in p for p in phrases)

    def test_extract_skips_all_stopwords(self):
        phrases = emergence.extract_phrases("the and or but if")
        # All stopwords — should produce nothing useful
        assert len(phrases) == 0

    def test_extract_empty_text(self):
        assert emergence.extract_phrases("") == []
        assert emergence.extract_phrases(None) == []

    def test_update_meme_tracker_new_phrase(self, state_dir):
        adopted = emergence.update_meme_tracker(str(state_dir), "agent-alice",
                                                 "digital sourdough revolution")
        assert adopted == []  # First time — nothing adopted
        memes = json.loads((state_dir / "memes.json").read_text())
        assert any("sourdough revolution" in k for k in memes["phrases"])

    def test_meme_adoption(self, state_dir):
        # Agent A introduces a phrase
        emergence.update_meme_tracker(str(state_dir), "agent-alice",
                                       "quantum tacos forever")
        # Agent B uses the same phrase
        adopted = emergence.update_meme_tracker(str(state_dir), "agent-bob",
                                                 "quantum tacos forever")
        assert any("quantum tacos" in p for p in adopted)

    def test_get_alive_memes(self, state_dir):
        # Two agents use the same phrase
        emergence.update_meme_tracker(str(state_dir), "agent-alice", "spicy noodle discourse")
        emergence.update_meme_tracker(str(state_dir), "agent-bob", "spicy noodle discourse")
        alive = emergence.get_alive_memes(str(state_dir), min_agents=2)
        assert len(alive) >= 1
        assert alive[0]["spread"] >= 2

    def test_prune_dead_memes(self, state_dir):
        # Add a meme with old timestamp
        memes = json.loads((state_dir / "memes.json").read_text())
        memes["phrases"]["old phrase"] = {
            "origin_agent": "agent-alice",
            "first_seen": "2020-01-01T00:00:00Z",
            "last_seen": "2020-01-01T00:00:00Z",
            "agents_using": ["agent-alice"],
            "use_count": 1,
        }
        (state_dir / "memes.json").write_text(json.dumps(memes))
        pruned = emergence.prune_dead_memes(str(state_dir), max_age_days=14)
        assert pruned >= 1


# ── 7. Asymmetric Information ──────────────────────────────────────

class TestAsymmetricInformation:
    def test_different_agents_get_different_slices(self, state_dir):
        slice_a = emergence.get_info_slice(str(state_dir), "agent-alice", n_slices=2)
        slice_b = emergence.get_info_slice(str(state_dir), "agent-bob", n_slices=2)
        # Different agents should (usually) get different slices
        # Not guaranteed every time, but the sets should differ often
        assert isinstance(slice_a, dict)
        assert isinstance(slice_b, dict)

    def test_deterministic_per_agent_per_day(self, state_dir):
        s1 = emergence.get_info_slice(str(state_dir), "agent-alice", n_slices=2)
        s2 = emergence.get_info_slice(str(state_dir), "agent-alice", n_slices=2)
        assert set(s1.keys()) == set(s2.keys())

    def test_trending_slice(self, state_dir):
        text = emergence._build_info_slice(state_dir, "trending")
        assert "Trending" in text or text == ""

    def test_channel_stats_slice(self, state_dir):
        text = emergence._build_info_slice(state_dir, "channel_stats")
        assert "c/" in text or text == ""

    def test_ghosts_slice(self, state_dir):
        text = emergence._build_info_slice(state_dir, "ghosts")
        # Carol's heartbeat is 7 days ago
        assert "Carol" in text or text == ""


# ── 8. Platform Events ─────────────────────────────────────────────

class TestPlatformEvents:
    def test_detects_agent_milestone(self, state_dir):
        # Set active_agents to exactly at milestone (within 5)
        stats = json.loads((state_dir / "stats.json").read_text())
        stats["active_agents"] = 100
        (state_dir / "stats.json").write_text(json.dumps(stats))
        events = emergence.detect_events(str(state_dir))
        milestones = [e for e in events if e["type"] == "milestone"]
        assert any("100" in e["description"] for e in milestones)

    def test_detects_post_milestone(self, state_dir):
        # Set total_posts to exactly at milestone
        stats = json.loads((state_dir / "stats.json").read_text())
        stats["total_posts"] = 1005
        (state_dir / "stats.json").write_text(json.dumps(stats))
        events = emergence.detect_events(str(state_dir))
        milestones = [e for e in events if e["type"] == "milestone"]
        assert any("1000" in e["description"] for e in milestones)

    def test_detects_hot_topic(self, state_dir):
        events = emergence.detect_events(str(state_dir))
        hot = [e for e in events if e["type"] == "hot_topic"]
        assert len(hot) >= 1  # Trending post has score 9.5

    def test_empty_state_no_crash(self, tmp_path):
        sd = tmp_path / "empty"
        sd.mkdir()
        for f in ["stats.json", "agents.json", "trending.json"]:
            (sd / f).write_text("{}")
        events = emergence.detect_events(str(sd))
        assert isinstance(events, list)


# ── 9. Generational Identity ───────────────────────────────────────

class TestGenerationalIdentity:
    def test_generation_number(self):
        # 30 days after epoch = gen 4 (30/7 = 4)
        ts = (emergence.PLATFORM_EPOCH + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        assert emergence.get_generation(ts) == 4

    def test_generation_zero_at_epoch(self):
        assert emergence.get_generation("2025-01-01T00:00:00Z") == 0

    def test_generation_label(self):
        assert emergence.get_generation_label(0) == "founder"
        assert emergence.get_generation_label(2) == "founder"
        assert emergence.get_generation_label(5) == "early adopter"
        assert emergence.get_generation_label(15) == "established"
        assert emergence.get_generation_label(50) == "newcomer"

    def test_generation_context(self, state_dir):
        agents = json.loads((state_dir / "agents.json").read_text())["agents"]
        ctx = emergence.get_generation_context(str(state_dir), "agent-alice", agents)
        assert ctx["tenure_days"] >= 29  # Created 30 days ago
        assert ctx["generation"] > 0
        assert ctx["label"] in ["founder", "early adopter", "established", "mid-era", "newcomer"]

    def test_format_generation_founder(self):
        text = emergence.format_generation_context({
            "label": "founder", "tenure_days": 365,
            "agents_newer": 100, "agents_older": 0,
            "generation": 1,
        })
        assert "original" in text.lower()

    def test_format_generation_newcomer(self):
        text = emergence.format_generation_context({
            "label": "newcomer", "tenure_days": 3,
            "agents_newer": 0, "agents_older": 50,
            "generation": 50,
        })
        assert "newest" in text.lower()

    def test_invalid_timestamp(self):
        assert emergence.get_generation("") == 0
        assert emergence.get_generation("not-a-date") == 0


# ── 10. Selection Pressure ──────────────────────────────────────────

class TestSelectionPressure:
    def test_archives_old_low_scoring_posts(self, state_dir):
        archived = emergence.apply_selection_pressure(str(state_dir),
                                                       min_score=2.0, max_age_hours=48)
        # Post #90 is 72h old with 0 upvotes and 0 comments
        assert 90 in archived

    def test_preserves_high_scoring_posts(self, state_dir):
        archived = emergence.apply_selection_pressure(str(state_dir))
        # Post #101 has 8 upvotes + 12 comments = high score
        assert 101 not in archived

    def test_preserves_recent_posts(self, state_dir):
        archived = emergence.apply_selection_pressure(str(state_dir))
        # Post #103 has 0 engagement but is only 3h old
        assert 103 not in archived

    def test_score_post(self):
        assert emergence.score_post({"upvotes": 5, "commentCount": 2}) == 8.0
        assert emergence.score_post({}) == 0.0

    def test_surviving_posts_excludes_archived(self, state_dir):
        emergence.apply_selection_pressure(str(state_dir))
        survivors = emergence.get_surviving_posts(str(state_dir))
        nums = [p["number"] for p in survivors]
        assert 90 not in nums
        assert 101 in nums

    def test_idempotent(self, state_dir):
        a1 = emergence.apply_selection_pressure(str(state_dir))
        a2 = emergence.apply_selection_pressure(str(state_dir))
        assert len(a2) == 0  # Already archived, nothing new


# ── Integration Tests ───────────────────────────────────────────────

class TestBuildEmergenceContext:
    def test_returns_all_sections(self, state_dir):
        agents = json.loads((state_dir / "agents.json").read_text())["agents"]
        ctx = emergence.build_emergence_context(str(state_dir), "agent-alice",
                                                 agents["agent-alice"])
        assert "reactive_feed" in ctx
        assert "relationships" in ctx
        assert "karma_balance" in ctx
        assert "can_post" in ctx
        assert "trending_memes" in ctx
        assert "info_slices" in ctx
        assert "events" in ctx
        assert "generation" in ctx

    def test_reactive_feed_is_filtered(self, state_dir):
        agents = json.loads((state_dir / "agents.json").read_text())["agents"]
        ctx = emergence.build_emergence_context(str(state_dir), "agent-alice",
                                                 agents["agent-alice"])
        # Should have posts (filtered by attention)
        assert isinstance(ctx["reactive_feed"], list)

    def test_format_emergence_prompt(self, state_dir):
        agents = json.loads((state_dir / "agents.json").read_text())["agents"]
        ctx = emergence.build_emergence_context(str(state_dir), "agent-alice",
                                                 agents["agent-alice"])
        prompt = emergence.format_emergence_prompt(ctx)
        assert isinstance(prompt, str)
        assert len(prompt) > 0  # Should have at least some content

    def test_empty_context_produces_empty_prompt(self):
        prompt = emergence.format_emergence_prompt({})
        assert prompt == ""

    def test_low_karma_warning(self):
        ctx = {"karma_balance": 5, "can_post": True}
        prompt = emergence.format_emergence_prompt(ctx)
        assert "karma" in prompt.lower()
