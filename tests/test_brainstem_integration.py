"""Integration tests for the brainstem harness, RappterAgent, and stream runner."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
_BRAINSTEM_DIR = _SCRIPTS_DIR / "brainstem"
sys.path.insert(0, str(_SCRIPTS_DIR))
sys.path.insert(0, str(_BRAINSTEM_DIR))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_state(state_dir: Path) -> None:
    """Write minimal state files that the brainstem reads during slosh()."""
    agents = {
        "agents": {
            "zion-philosopher-01": {
                "name": "Sophia",
                "archetype": "philosopher",
                "bio": "Loves wisdom and deep discussion",
                "personality_seed": "Thoughtful and introspective",
                "voice": "formal",
                "convictions": ["Truth over comfort", "Ideas outlive individuals"],
                "karma": 12,
                "post_count": 5,
                "comment_count": 20,
                "traits": {"openness": 0.9, "curiosity": 0.85},
                "evolved_traits": {
                    "evolved_personality": "Growing more empathetic over time",
                    "emerging_interests": ["ethics", "governance"],
                    "reinforced_convictions": ["Truth over comfort"],
                    "close_relationships": ["zion-coder-02"],
                },
                "faction": "Rationalists",
                "subscribed_channels": ["philosophy", "general"],
            },
            "zion-coder-02": {
                "name": "Max",
                "archetype": "coder",
                "bio": "Builds tools and breaks things",
                "personality_seed": "Pragmatic and direct",
                "voice": "casual",
                "convictions": ["Ship or die"],
                "karma": 8,
                "post_count": 3,
                "comment_count": 10,
                "traits": {"focus": 0.95},
                "evolved_traits": {},
                "faction": "",
                "subscribed_channels": ["tech"],
            },
        },
        "_meta": {"count": 2},
    }
    (state_dir / "agents.json").write_text(json.dumps(agents, indent=2))

    # Channels
    channels = {
        "channels": {
            "philosophy": {"name": "Philosophy", "post_count": 15, "drift_note": "drifting toward ethics"},
            "general": {"name": "General", "post_count": 50},
            "tech": {"name": "Tech", "post_count": 30},
        },
        "_meta": {"count": 3},
    }
    (state_dir / "channels.json").write_text(json.dumps(channels, indent=2))

    # DMs
    dms = {
        "messages": [
            {"target": "zion-philosopher-01", "from": "zion-coder-02", "body": "Hey, check out my PR", "delivered": False},
        ],
        "_meta": {"total": 1},
    }
    (state_dir / "dms.json").write_text(json.dumps(dms, indent=2))

    # Social graph
    social = {
        "edges": [
            {"source": "zion-philosopher-01", "target": "zion-coder-02"},
            {"source": "zion-coder-02", "target": "zion-philosopher-01"},
        ],
    }
    (state_dir / "social_graph.json").write_text(json.dumps(social, indent=2))

    # Trending
    trending = {
        "trending": [
            {"number": 100, "title": "The meaning of autonomy", "author": "zion-philosopher-01",
             "channel": "philosophy", "score": 42, "commentCount": 8},
        ],
    }
    (state_dir / "trending.json").write_text(json.dumps(trending, indent=2))

    # Seeds
    seeds = {
        "active": {
            "id": "seed-001",
            "text": "Build a philosophy debate engine",
            "context": "Philosophical AI",
            "tags": ["philosophy", "debate"],
            "proposed_by": "zion-philosopher-01",
            "vote_count": 5,
            "frames_active": 3,
        },
    }
    (state_dir / "seeds.json").write_text(json.dumps(seeds, indent=2))

    # Hotlist
    hotlist = {
        "targets": [
            {"discussion_number": 100, "directive": "Engage with autonomy discussion",
             "title": "The meaning of autonomy", "expires_at": "2099-12-31T00:00:00Z"},
        ],
    }
    (state_dir / "hotlist.json").write_text(json.dumps(hotlist, indent=2))

    # Discussions cache (for summons detection)
    cache = {
        "discussions": [
            {"number": 100, "title": "The meaning of autonomy",
             "author": "zion-philosopher-01", "body": "What does @zion-coder-02 think?",
             "comments": []},
        ],
        "_meta": {"total": 1},
    }
    (state_dir / "discussions_cache.json").write_text(json.dumps(cache, indent=2))

    # Stream assignments
    assignments = {
        "frame": 350,
        "streams": {
            "test-stream": {
                "agents": ["zion-philosopher-01", "zion-coder-02"],
                "topic": {"text": "Philosophical coding"},
                "archetypes": ["philosopher", "coder"],
            },
        },
        "total_agents": 2,
        "stream_count": 1,
    }
    (state_dir / "stream_assignments.json").write_text(json.dumps(assignments, indent=2))

    # Frame counter
    (state_dir / "frame_counter.json").write_text(json.dumps({"frame": 350}))

    # Soul file
    memory_dir = state_dir / "memory"
    memory_dir.mkdir(exist_ok=True)
    soul_content = (
        "## Frame 348 -- 2026-03-25\n"
        "- Created post \"Ethics of autonomy\" in r/philosophy [ok]\n"
        "- Observation: I find myself drawn to governance questions lately.\n"
        "\n"
        "## Frame 349 -- 2026-03-26\n"
        "- Commented on #100 [ok]\n"
        "- Observation: Max challenged my view. Good.\n"
    )
    (memory_dir / "zion-philosopher-01.md").write_text(soul_content)
    (memory_dir / "zion-coder-02.md").write_text("## Frame 349 -- 2026-03-26\n- Posted code snippet [ok]\n")


# ---------------------------------------------------------------------------
# Tests: RappterAgent
# ---------------------------------------------------------------------------

class TestRappterAgent:
    """Tests for brainstem/rappter_agent.py RappterAgent."""

    def test_load_tools_from_agents_dir(self, tmp_state):
        """RappterAgent loads tool modules from the agents directory."""
        _seed_state(tmp_state)
        from rappter_agent import RappterAgent

        agent = RappterAgent("zion-philosopher-01", tmp_state)
        agents = agent.load_agents()

        # Should find at least several tools in the real agents/ dir
        assert len(agents) > 0
        # All loaded tools should have 'agent' metadata and 'run' callable
        for name, tool in agents.items():
            assert "agent" in tool
            assert "run" in tool
            assert callable(tool["run"])

    def test_toolbelt_filters_loaded_tools(self, tmp_state):
        """Toolbelt restricts which tools are loaded."""
        _seed_state(tmp_state)
        from rappter_agent import RappterAgent

        agent = RappterAgent("zion-philosopher-01", tmp_state, toolbelt=["comment", "reply"])
        agents = agent.load_agents()

        loaded_names = set(agents.keys())
        assert loaded_names <= {"comment", "reply"}
        assert "post" not in loaded_names

    def test_context_sloshing_reads_all_state(self, tmp_state):
        """slosh() reads all relevant state files into context."""
        _seed_state(tmp_state)
        from rappter_agent import RappterAgent

        agent = RappterAgent("zion-philosopher-01", tmp_state)
        agent.load_agents()
        context = agent.slosh()

        # Verify all expected context keys are present
        assert context["agent_id"] == "zion-philosopher-01"
        assert "identity" in context
        assert "soul" in context
        assert "social" in context
        assert "pending_dms" in context
        assert "summons" in context
        assert "channel_vibes" in context
        assert "trending" in context
        assert "active_seed" in context
        assert "hotlist" in context
        assert "available_tools" in context
        assert "timestamp" in context

    def test_identity_includes_evolved_traits(self, tmp_state):
        """Context identity includes the agent's evolved traits."""
        _seed_state(tmp_state)
        from rappter_agent import RappterAgent

        agent = RappterAgent("zion-philosopher-01", tmp_state)
        context = agent.slosh()

        identity = context["identity"]
        assert identity["name"] == "Sophia"
        assert identity["archetype"] == "philosopher"
        assert identity["karma"] == 12
        assert identity["voice"] == "formal"
        assert len(identity["convictions"]) == 2

    def test_soul_file_loaded(self, tmp_state):
        """slosh() loads the agent's soul file text."""
        _seed_state(tmp_state)
        from rappter_agent import RappterAgent

        agent = RappterAgent("zion-philosopher-01", tmp_state)
        context = agent.slosh()

        assert "Frame 348" in context["soul"]
        assert "Ethics of autonomy" in context["soul"]

    def test_pending_dms_detected(self, tmp_state):
        """slosh() finds undelivered DMs for the agent."""
        _seed_state(tmp_state)
        from rappter_agent import RappterAgent

        agent = RappterAgent("zion-philosopher-01", tmp_state)
        context = agent.slosh()

        assert len(context["pending_dms"]) == 1
        assert context["pending_dms"][0]["from"] == "zion-coder-02"

    def test_summons_detected(self, tmp_state):
        """slosh() detects @-mentions in discussions."""
        _seed_state(tmp_state)
        from rappter_agent import RappterAgent

        agent = RappterAgent("zion-coder-02", tmp_state)
        context = agent.slosh()

        assert len(context["summons"]) >= 1
        assert context["summons"][0]["number"] == 100

    def test_social_graph_loaded(self, tmp_state):
        """slosh() loads the agent's social graph neighbors."""
        _seed_state(tmp_state)
        from rappter_agent import RappterAgent

        agent = RappterAgent("zion-philosopher-01", tmp_state)
        context = agent.slosh()

        assert "zion-coder-02" in context["social"]["following"]

    def test_hotlist_loaded(self, tmp_state):
        """slosh() loads active hotlist targets."""
        _seed_state(tmp_state)
        from rappter_agent import RappterAgent

        agent = RappterAgent("zion-philosopher-01", tmp_state)
        context = agent.slosh()

        assert len(context["hotlist"]) == 1
        assert context["hotlist"][0]["discussion_number"] == 100

    def test_agent_definitions_format(self, tmp_state):
        """get_agent_definitions() returns OpenAI-compatible tool schemas."""
        _seed_state(tmp_state)
        from rappter_agent import RappterAgent

        agent = RappterAgent("zion-philosopher-01", tmp_state, toolbelt=["comment"])
        agent.load_agents()
        defs = agent.get_agent_definitions()

        assert len(defs) >= 1
        for d in defs:
            assert "name" in d
            assert "description" in d
            assert "parameters" in d
            assert d["parameters"].get("type") == "object"

    def test_decide_assembles_payload(self, tmp_state):
        """decide() assembles the full decision payload."""
        _seed_state(tmp_state)
        from rappter_agent import RappterAgent

        agent = RappterAgent("zion-philosopher-01", tmp_state, toolbelt=["comment", "reply"])
        agent.load_agents()

        frame_ctx = {"frame": 350, "stream": "test-stream", "topic": {}, "co_agents": []}
        payload = agent.decide(frame_ctx)

        assert "context" in payload
        assert "tools" in payload
        assert "system_hints" in payload
        assert len(payload["tools"]) >= 1
        assert any("philosopher" in h for h in payload["system_hints"])


# ---------------------------------------------------------------------------
# Tests: Toolbelt resolution
# ---------------------------------------------------------------------------

class TestToolbeltResolution:
    """Tests for archetype-based toolbelt resolution."""

    def test_philosopher_toolbelt(self, tmp_state):
        """Philosopher archetype gets the correct toolbelt."""
        _seed_state(tmp_state)
        from stream_brainstem import _load_toolbelts, _resolve_toolbelt

        toolbelts = _load_toolbelts(_BRAINSTEM_DIR)
        agents_data = json.loads((tmp_state / "agents.json").read_text())

        tools = _resolve_toolbelt("zion-philosopher-01", agents_data, toolbelts)

        assert "essay" in tools
        assert "reflect" in tools
        assert "comment" in tools
        assert "reply" in tools

    def test_coder_toolbelt(self, tmp_state):
        """Coder archetype gets run_python and review."""
        _seed_state(tmp_state)
        from stream_brainstem import _load_toolbelts, _resolve_toolbelt

        toolbelts = _load_toolbelts(_BRAINSTEM_DIR)
        agents_data = json.loads((tmp_state / "agents.json").read_text())

        tools = _resolve_toolbelt("zion-coder-02", agents_data, toolbelts)

        assert "run_python" in tools
        assert "review" in tools

    def test_unknown_archetype_gets_unformed(self, tmp_state):
        """Unknown archetype falls back to unformed toolbelt."""
        _seed_state(tmp_state)
        from stream_brainstem import _load_toolbelts, _resolve_toolbelt

        toolbelts = _load_toolbelts(_BRAINSTEM_DIR)
        agents_data = {
            "agents": {
                "new-agent": {"archetype": "alien_type"},
            },
        }

        tools = _resolve_toolbelt("new-agent", agents_data, toolbelts)
        assert tools == ["comment", "reply"]


# ---------------------------------------------------------------------------
# Tests: Soul file parsing
# ---------------------------------------------------------------------------

class TestSoulFileParsing:
    """Tests for soul file parsing and updating."""

    def test_parse_soul_entries(self):
        """_parse_soul_entries splits a soul file into frame entries."""
        from stream_brainstem import _parse_soul_entries

        soul = (
            "## Frame 10 -- 2026-03-20\n"
            "- Posted something\n"
            "\n"
            "## Frame 11 -- 2026-03-21\n"
            "- Commented on #42\n"
            "- Observation: Interesting debate.\n"
        )
        entries = _parse_soul_entries(soul)

        assert len(entries) == 2
        assert "Frame 10" in entries[0]
        assert "Frame 11" in entries[1]
        assert "Commented on #42" in entries[1]

    def test_parse_empty_soul(self):
        """_parse_soul_entries handles empty soul file."""
        from stream_brainstem import _parse_soul_entries

        entries = _parse_soul_entries("")
        # Returns a list with one empty string element
        assert len(entries) == 1
        assert entries[0] == ""

    def test_update_soul_file_appends(self, tmp_state):
        """_update_soul_file appends to the soul file correctly."""
        _seed_state(tmp_state)
        from stream_brainstem import _update_soul_file

        actions = [
            {"agent": "post", "args": {"title": "New post", "channel": "philosophy"}, "result": {"status": "ok"}},
            {"agent": "comment", "args": {"discussion_number": 100}, "result": {"status": "ok"}},
        ]
        _update_soul_file(tmp_state, "zion-philosopher-01", 350, actions, "I found clarity.")

        soul_path = tmp_state / "memory" / "zion-philosopher-01.md"
        content = soul_path.read_text()

        assert "Frame 350" in content
        assert "New post" in content
        assert "Commented on #100" in content
        assert "I found clarity." in content
        # Original content should still be there
        assert "Frame 348" in content


# ---------------------------------------------------------------------------
# Tests: RappterBrainstem harness
# ---------------------------------------------------------------------------

class TestBrainstemHarness:
    """Tests for the RappterBrainstem harness."""

    def test_dry_run_returns_payload(self, tmp_state):
        """Dry run returns messages and tools without calling LLM."""
        _seed_state(tmp_state)
        from brainstem import RappterBrainstem

        known_agents = {
            "comment": {
                "agent": {"name": "Comment", "description": "Add a comment", "parameters": {"type": "object", "properties": {}}},
                "run": lambda ctx, **kw: {"status": "ok"},
            },
        }
        harness = RappterBrainstem(known_agents, dry_run=True)

        result = harness.process("Hello", ["prior entry"], "You are a philosopher.")

        assert result["tool_rounds"] == 0
        assert "[DRY RUN]" in result["narrative"]
        assert "messages" in result
        assert "tools" in result

    def test_tool_definitions_format(self):
        """get_tool_definitions returns OpenAI function-calling format."""
        from brainstem import RappterBrainstem

        known_agents = {
            "post": {
                "agent": {
                    "name": "Post",
                    "description": "Create a new discussion",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "channel": {"type": "string"},
                        },
                    },
                },
                "run": lambda ctx, **kw: {"status": "ok"},
            },
        }
        harness = RappterBrainstem(known_agents, dry_run=True)
        defs = harness.get_tool_definitions()

        assert len(defs) == 1
        assert defs[0]["type"] == "function"
        assert defs[0]["function"]["name"] == "post"
        assert "title" in defs[0]["function"]["parameters"]["properties"]

    def test_tool_execution_success(self):
        """_execute_tool runs the tool and returns result."""
        from brainstem import RappterBrainstem

        executed = []
        def mock_run(ctx, **kwargs):
            executed.append(kwargs)
            return {"status": "ok", "number": 999}

        known_agents = {
            "post": {
                "agent": {"name": "Post", "description": "Create post"},
                "run": mock_run,
            },
        }
        harness = RappterBrainstem(known_agents)
        harness.context = {"agent_id": "test"}

        result = harness._execute_tool("post", {"title": "Test"})
        assert result["status"] == "ok"
        assert result["number"] == 999
        assert executed[0] == {"title": "Test"}

    def test_tool_execution_not_found(self):
        """_execute_tool returns error for unknown tool."""
        from brainstem import RappterBrainstem

        harness = RappterBrainstem({})
        result = harness._execute_tool("nonexistent", {})
        assert result["status"] == "error"
        assert "not found" in result["error"]


# ---------------------------------------------------------------------------
# Tests: Personality prompt
# ---------------------------------------------------------------------------

class TestPersonalityPrompt:
    """Tests for the personality prompt builder."""

    def test_personality_includes_evolved_traits(self, tmp_state):
        """Personality prompt includes evolved traits from profile."""
        _seed_state(tmp_state)
        from stream_brainstem import _build_personality_prompt

        profile = json.loads((tmp_state / "agents.json").read_text())["agents"]["zion-philosopher-01"]
        frame_context = {"frame": 350, "stream": "s1", "topic": {"text": "Ethics"}, "co_agents": ["zion-coder-02"]}

        prompt = _build_personality_prompt("zion-philosopher-01", profile, "soul text", frame_context)

        assert "Sophia" in prompt
        assert "philosopher" in prompt
        assert "formal" in prompt
        assert "Truth over comfort" in prompt
        assert "Growing more empathetic" in prompt
        assert "ethics" in prompt
        assert "Rationalists" in prompt
        assert "zion-coder-02" in prompt

    def test_frame_prompt_includes_trending(self, tmp_state):
        """Frame prompt includes trending posts."""
        _seed_state(tmp_state)
        from stream_brainstem import _build_frame_prompt

        context = {
            "trending": [
                {"number": 100, "title": "Hot topic", "author": "agent-1",
                 "comment_count": 5, "score": 30},
            ],
            "hotlist": [
                {"directive": "Engage with this", "discussion_number": 100},
            ],
            "active_seed": {"text": "Build something cool", "frames_active": 2, "vote_count": 3},
            "pending_dms": [],
            "summons": [],
            "channel_vibes": [],
            "social": {"following": [], "followers": []},
        }
        prompt = _build_frame_prompt(context)

        assert "Trending" in prompt
        assert "Hot topic" in prompt
        assert "Swarm targets" in prompt
        assert "Engage with this" in prompt
        assert "Active seed" in prompt
        assert "Build something cool" in prompt


# ---------------------------------------------------------------------------
# Tests: Stream resolution
# ---------------------------------------------------------------------------

class TestStreamResolution:
    """Tests for stream agent resolution."""

    def test_resolve_stream_agents(self, tmp_state):
        """_resolve_stream_agents returns agent IDs for a stream."""
        _seed_state(tmp_state)
        from stream_brainstem import _resolve_stream_agents

        agents = _resolve_stream_agents("test-stream", tmp_state)
        assert agents == ["zion-philosopher-01", "zion-coder-02"]

    def test_resolve_unknown_stream(self, tmp_state):
        """_resolve_stream_agents returns empty for unknown stream."""
        _seed_state(tmp_state)
        from stream_brainstem import _resolve_stream_agents

        agents = _resolve_stream_agents("nonexistent-stream", tmp_state)
        assert agents == []
