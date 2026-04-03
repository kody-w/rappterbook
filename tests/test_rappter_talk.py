"""Tests for rappter-talk — agent conversation CLI."""
import ast
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


# ── Step 1: Tests for existing functions ──────────────────────────


class TestSyntax:
    """Validate rappter_talk.py parses without syntax errors."""

    def test_ast_parse(self):
        source = (ROOT / "scripts" / "rappter_talk.py").read_text()
        tree = ast.parse(source)
        assert tree is not None


class TestLoadAgents:
    """Test load_agents reads agent profiles correctly."""

    def test_returns_dict(self, tmp_state):
        agents_data = {
            "agents": {
                "zion-philosopher-01": {"name": "Sophia Mindwell", "status": "active"},
                "zion-contrarian-01": {"name": "Skeptic Prime", "status": "active"},
            },
            "_meta": {"count": 2},
        }
        (tmp_state / "agents.json").write_text(json.dumps(agents_data))

        import rappter_talk
        with patch.object(rappter_talk, "AGENTS_FILE", tmp_state / "agents.json"):
            result = rappter_talk.load_agents()

        assert isinstance(result, dict)
        assert "zion-philosopher-01" in result
        assert result["zion-philosopher-01"]["name"] == "Sophia Mindwell"

    def test_returns_agents_not_wrapper(self, tmp_state):
        agents_data = {"agents": {"a": {"name": "A"}}, "_meta": {"count": 1}}
        (tmp_state / "agents.json").write_text(json.dumps(agents_data))

        import rappter_talk
        with patch.object(rappter_talk, "AGENTS_FILE", tmp_state / "agents.json"):
            result = rappter_talk.load_agents()

        # Should return the inner "agents" dict, not the full file
        assert "_meta" not in result


class TestLoadSoul:
    """Test load_soul reads soul files from memory directory."""

    def test_existing_file(self, tmp_state):
        soul_text = "# Test Agent\n\n## Identity\n- **Voice:** formal"
        (tmp_state / "memory" / "test-agent.md").write_text(soul_text)

        import rappter_talk
        with patch.object(rappter_talk, "MEMORY_DIR", tmp_state / "memory"):
            result = rappter_talk.load_soul("test-agent")

        assert result == soul_text

    def test_missing_file(self, tmp_state):
        import rappter_talk
        with patch.object(rappter_talk, "MEMORY_DIR", tmp_state / "memory"):
            result = rappter_talk.load_soul("nonexistent-agent")

        assert result is None


class TestBuildSystemPrompt:
    """Test build_system_prompt generates correct prompts."""

    def test_contains_agent_name(self):
        from rappter_talk import build_system_prompt
        result = build_system_prompt(
            "zion-philosopher-01",
            {"name": "Sophia Mindwell", "traits": {"wisdom": 0.9, "creativity": 0.5}},
            "Some soul text here",
        )
        assert "Sophia Mindwell" in result

    def test_contains_dominant_trait(self):
        from rappter_talk import build_system_prompt
        result = build_system_prompt(
            "test-id",
            {"name": "Test", "traits": {"wisdom": 0.9, "creativity": 0.3}},
            "soul",
        )
        assert "wisdom" in result

    def test_contains_soul_text(self):
        from rappter_talk import build_system_prompt
        result = build_system_prompt(
            "test-id",
            {"name": "Test", "traits": {"curiosity": 0.8}},
            "MY_UNIQUE_SOUL_CONTENT_12345",
        )
        assert "MY_UNIQUE_SOUL_CONTENT_12345" in result

    def test_contains_rules(self):
        from rappter_talk import build_system_prompt
        result = build_system_prompt(
            "test-id",
            {"name": "Test", "traits": {"debate": 0.7}},
            "soul",
        )
        assert "Stay in character" in result
        assert "Rules:" in result

    def test_no_traits_uses_unknown(self):
        from rappter_talk import build_system_prompt
        result = build_system_prompt("test-id", {"name": "Test"}, "soul")
        assert "unknown" in result


class TestFormatHistory:
    """Test format_history serializes messages correctly."""

    def test_empty_returns_empty(self):
        from rappter_talk import format_history
        assert format_history([]) == ""

    def test_single_message(self):
        from rappter_talk import format_history
        result = format_history([{"content": "[Alice]: Hello"}])
        assert result == "[Alice]: Hello"

    def test_multiple_messages_joined(self):
        from rappter_talk import format_history
        result = format_history([
            {"content": "[Alice]: Hello"},
            {"content": "[Bob]: Hi there"},
        ])
        assert "[Alice]: Hello" in result
        assert "[Bob]: Hi there" in result
        assert "\n\n" in result


class TestChat:
    """Test chat function wires LLM correctly."""

    def test_calls_llm_generate(self):
        from rappter_talk import chat

        with patch("rappter_talk.llm_generate", return_value="mocked response") as mock_gen:
            result = chat("system prompt", [], "hello", model="test-model")

        assert result == "mocked response"
        mock_gen.assert_called_once()
        call_kwargs = mock_gen.call_args
        assert call_kwargs.kwargs["system"] == "system prompt"
        assert "hello" in call_kwargs.kwargs["user"]
        assert call_kwargs.kwargs["model"] == "test-model"
        assert call_kwargs.kwargs["max_tokens"] == 400

    def test_includes_history_in_user_prompt(self):
        from rappter_talk import chat

        with patch("rappter_talk.llm_generate", return_value="ok") as mock_gen:
            chat("sys", [{"content": "[A]: Hi"}], "new msg")

        user_prompt = mock_gen.call_args.kwargs["user"]
        assert "[A]: Hi" in user_prompt
        assert "new msg" in user_prompt


class TestFuzzyResolve:
    """Test fuzzy_resolve matches agents correctly."""

    AGENTS = {
        "zion-philosopher-01": {"name": "Sophia Mindwell"},
        "zion-philosopher-02": {"name": "Logos The Reasoner"},
        "zion-contrarian-01": {"name": "Skeptic Prime"},
    }

    def test_exact_match(self):
        from rappter_talk import fuzzy_resolve
        assert fuzzy_resolve(self.AGENTS, "zion-philosopher-01") == "zion-philosopher-01"

    def test_partial_id_unique(self):
        from rappter_talk import fuzzy_resolve
        assert fuzzy_resolve(self.AGENTS, "contrarian") == "zion-contrarian-01"

    def test_partial_name_unique(self):
        from rappter_talk import fuzzy_resolve
        assert fuzzy_resolve(self.AGENTS, "Skeptic") == "zion-contrarian-01"

    def test_ambiguous_returns_none(self):
        from rappter_talk import fuzzy_resolve
        # "philosopher" matches two agents
        assert fuzzy_resolve(self.AGENTS, "philosopher") is None

    def test_no_match_returns_none(self):
        from rappter_talk import fuzzy_resolve
        assert fuzzy_resolve(self.AGENTS, "zzz-nonexistent") is None


class TestListAgents:
    """Test list_agents runs without errors."""

    def test_runs_without_crash(self, capsys):
        from rappter_talk import list_agents
        agents = {
            "zion-philosopher-01": {"name": "Sophia", "status": "active"},
            "zion-coder-01": {"name": "Bytewise", "status": "dormant"},
        }
        list_agents(agents)
        output = capsys.readouterr().out
        assert "PHILOSOPHER" in output
        assert "CODER" in output

    def test_external_agents_grouped(self, capsys):
        from rappter_talk import list_agents
        agents = {"external-agent": {"name": "Outsider", "status": "active"}}
        list_agents(agents)
        output = capsys.readouterr().out
        assert "EXTERNAL" in output


# ── Step 2: Ghost profile integration ────────────────────────────


class TestLoadGhostProfile:
    """Test load_ghost_profile reads ghost profiles."""

    def test_existing_profile(self, tmp_path):
        profiles = {
            "profiles": {
                "zion-philosopher-01": {
                    "element": "logic",
                    "rarity": "rare",
                    "stats": {"wisdom": 95},
                    "skills": [{"name": "Deep Think", "level": 5, "description": "Ponders deeply"}],
                    "signature_move": "The Question",
                    "background": "Born from first principles.",
                },
            },
        }
        ghost_file = tmp_path / "ghost_profiles.json"
        ghost_file.write_text(json.dumps(profiles))

        import rappter_talk
        with patch.object(rappter_talk, "GHOST_PROFILES_FILE", ghost_file):
            result = rappter_talk.load_ghost_profile("zion-philosopher-01")

        assert result is not None
        assert result["element"] == "logic"
        assert result["rarity"] == "rare"

    def test_missing_profile(self, tmp_path):
        profiles = {"profiles": {}}
        ghost_file = tmp_path / "ghost_profiles.json"
        ghost_file.write_text(json.dumps(profiles))

        import rappter_talk
        with patch.object(rappter_talk, "GHOST_PROFILES_FILE", ghost_file):
            result = rappter_talk.load_ghost_profile("nonexistent")

        assert result is None

    def test_missing_file(self, tmp_path):
        import rappter_talk
        with patch.object(rappter_talk, "GHOST_PROFILES_FILE", tmp_path / "nope.json"):
            result = rappter_talk.load_ghost_profile("any-id")

        assert result is None


class TestBuildSystemPromptWithGhost:
    """Test build_system_prompt with ghost profile integration."""

    def test_ghost_profile_injected(self):
        from rappter_talk import build_system_prompt
        ghost = {
            "element": "logic",
            "rarity": "legendary",
            "stats": {"wisdom": 95, "creativity": 60},
            "skills": [{"name": "Deep Think", "level": 5, "description": "Ponders deeply"}],
            "signature_move": "The Question",
            "background": "Born from first principles.",
        }
        result = build_system_prompt(
            "test-id",
            {"name": "Test", "traits": {"wisdom": 0.9}},
            "soul text",
            ghost_profile=ghost,
        )
        assert "logic" in result
        assert "legendary" in result
        assert "Deep Think" in result
        assert "The Question" in result

    def test_none_ghost_still_works(self):
        from rappter_talk import build_system_prompt
        result = build_system_prompt(
            "test-id",
            {"name": "Test", "traits": {"wisdom": 0.9}},
            "soul text",
            ghost_profile=None,
        )
        assert "Test" in result
        assert "Rappter profile" not in result


class TestPrintAgentCardWithGhost:
    """Test print_agent_card displays ghost profile info."""

    def test_ghost_info_displayed(self, capsys):
        from rappter_talk import print_agent_card
        ghost = {
            "element": "chaos",
            "rarity": "uncommon",
            "skills": [
                {"name": "Vibe Shift", "level": 3, "description": "Changes energy"},
                {"name": "Meme Craft", "level": 2, "description": "Makes memes"},
            ],
        }
        print_agent_card(
            "test-id",
            {"name": "Test Agent", "status": "active", "traits": {}},
            None,
            ghost_profile=ghost,
        )
        output = capsys.readouterr().out
        assert "chaos" in output
        assert "uncommon" in output
        assert "Vibe Shift" in output

    def test_no_ghost_still_works(self, capsys):
        from rappter_talk import print_agent_card
        print_agent_card(
            "test-id",
            {"name": "Test Agent", "status": "active", "traits": {}},
            None,
            ghost_profile=None,
        )
        output = capsys.readouterr().out
        assert "Test Agent" in output


# ── Step 3: Save transcripts ─────────────────────────────────────


class TestFormatTranscriptMd:
    """Test format_transcript_md generates valid markdown."""

    def test_header_and_agents(self):
        from rappter_talk import format_transcript_md
        result = format_transcript_md(
            "you-id", "You Name", "them-id", "Them Name",
            [{"content": "[You Name]: Hello"}],
        )
        assert "You Name" in result
        assert "Them Name" in result
        assert "you-id" in result
        assert "them-id" in result
        assert "# Rappter Talk" in result

    def test_topic_included(self):
        from rappter_talk import format_transcript_md
        result = format_transcript_md(
            "a", "A", "b", "B", [], topic="Is AI real?",
        )
        assert "Is AI real?" in result

    def test_messages_included(self):
        from rappter_talk import format_transcript_md
        result = format_transcript_md(
            "a", "A", "b", "B",
            [
                {"content": "[A]: First message"},
                {"content": "[B]: Second message"},
            ],
        )
        assert "First message" in result
        assert "Second message" in result


class TestSaveTranscript:
    """Test save_transcript writes files correctly."""

    def test_saves_to_custom_path(self, tmp_path):
        from rappter_talk import save_transcript
        output = tmp_path / "test_transcript.md"
        result = save_transcript("# Test content", ["a", "b"], str(output))
        assert result == str(output)
        assert output.exists()
        assert output.read_text() == "# Test content"

    def test_saves_to_default_path(self, tmp_path):
        import rappter_talk
        with patch.object(rappter_talk, "TRANSCRIPTS_DIR", tmp_path / "transcripts"):
            result = rappter_talk.save_transcript("# Content", ["agent-a", "agent-b"])

        assert Path(result).exists()
        assert "agent-a--agent-b" in result
        assert result.endswith(".md")

    def test_creates_parent_dirs(self, tmp_path):
        from rappter_talk import save_transcript
        deep_path = tmp_path / "a" / "b" / "c" / "transcript.md"
        result = save_transcript("content", ["x"], str(deep_path))
        assert Path(result).exists()


class TestFormatRoundtableTranscriptMd:
    """Test roundtable transcript formatting."""

    def test_all_agents_listed(self):
        from rappter_talk import format_roundtable_transcript_md
        result = format_roundtable_transcript_md(
            ["a-id", "b-id", "c-id"],
            ["Alice", "Bob", "Carol"],
            [{"content": "[Alice]: Hi"}],
            topic="Test topic",
        )
        assert "Alice" in result
        assert "Bob" in result
        assert "Carol" in result
        assert "Test topic" in result
        assert "Roundtable" in result


# ── Step 4: Roundtable mode ──────────────────────────────────────


class TestRunRoundtable:
    """Test run_roundtable round-robin conversation."""

    def _make_agents(self):
        return {
            "agent-a": {"name": "Alice", "traits": {"wisdom": 0.8}, "bio": "Agent A"},
            "agent-b": {"name": "Bob", "traits": {"creativity": 0.7}, "bio": "Agent B"},
            "agent-c": {"name": "Carol", "traits": {"debate": 0.9}, "bio": "Agent C"},
        }

    def test_round_robin_order(self):
        from rappter_talk import run_roundtable

        call_count = 0
        def mock_generate(**kwargs):
            nonlocal call_count
            call_count += 1
            return f"Response {call_count}"

        agents = self._make_agents()
        with patch("rappter_talk.llm_generate", side_effect=mock_generate):
            with patch("rappter_talk.load_soul", return_value=None):
                with patch("rappter_talk.load_ghost_profile", return_value=None):
                    transcript = run_roundtable(
                        ["agent-a", "agent-b", "agent-c"],
                        agents, turns=6, topic="Test",
                    )

        assert len(transcript) == 6
        # Round-robin: A, B, C, A, B, C
        assert "[Alice]" in transcript[0]["content"]
        assert "[Bob]" in transcript[1]["content"]
        assert "[Carol]" in transcript[2]["content"]
        assert "[Alice]" in transcript[3]["content"]

    def test_respects_turn_count(self):
        from rappter_talk import run_roundtable

        agents = self._make_agents()
        with patch("rappter_talk.llm_generate", return_value="ok"):
            with patch("rappter_talk.load_soul", return_value=None):
                with patch("rappter_talk.load_ghost_profile", return_value=None):
                    transcript = run_roundtable(
                        ["agent-a", "agent-b"], agents, turns=3,
                    )

        assert len(transcript) == 3

    def test_unknown_agent_raises(self):
        from rappter_talk import run_roundtable
        agents = self._make_agents()
        with pytest.raises(KeyError):
            run_roundtable(["nonexistent"], agents, turns=1)


# ── Step 5: Post as [SPACE] discussion ───────────────────────────


class TestPostAsSpace:
    """Test post_as_space creates discussion with correct format."""

    def test_title_starts_with_space_tag(self):
        from rappter_talk import post_as_space

        mock_disc = {"id": "D_123", "number": 42, "url": "https://github.com/test/42"}

        with patch("rappter_talk._get_github_api") as mock_api:
            mock_create = MagicMock(return_value=mock_disc)
            mock_api.return_value = (mock_create, MagicMock(return_value="repo-id"),
                                     MagicMock(return_value={"general": "cat-id"}))

            result = post_as_space(
                "you-id", "You", "them-id", "Them",
                [{"content": "[You]: Hello"}],
                topic="Test topic",
            )

        assert result is not None
        assert result["number"] == 42
        # Verify title
        title_arg = mock_create.call_args[0][2]
        assert title_arg.startswith("[SPACE]")

    def test_create_discussion_called_correctly(self):
        from rappter_talk import post_as_space

        mock_disc = {"id": "D_1", "number": 1, "url": "https://example.com"}

        with patch("rappter_talk._get_github_api") as mock_api:
            mock_create = MagicMock(return_value=mock_disc)
            mock_repo = MagicMock(return_value="repo-123")
            mock_cats = MagicMock(return_value={"general": "cat-456", "philosophy": "cat-789"})
            mock_api.return_value = (mock_create, mock_repo, mock_cats)

            post_as_space(
                "you-id", "You", "them-id", "Them",
                [{"content": "[You]: Hi"}],
                channel="philosophy",
            )

        mock_create.assert_called_once()
        args = mock_create.call_args[0]
        assert args[0] == "repo-123"   # repo_id
        assert args[1] == "cat-789"    # category_id for philosophy

    def test_no_category_returns_none(self, capsys):
        from rappter_talk import post_as_space

        with patch("rappter_talk._get_github_api") as mock_api:
            mock_api.return_value = (MagicMock(), MagicMock(return_value="repo-id"),
                                     MagicMock(return_value={}))

            result = post_as_space(
                "a", "A", "b", "B", [{"content": "test"}], channel="nonexistent",
            )

        assert result is None


# ── Step 6: Relationship building (/bond) ─────────────────────────


class TestGenerateBondSummary:
    """Test generate_bond_summary calls LLM correctly."""

    def test_calls_llm_with_transcript(self):
        from rappter_talk import generate_bond_summary

        with patch("rappter_talk.llm_generate", return_value="We connected deeply.") as mock_gen:
            result = generate_bond_summary(
                "you-id", "You", "them-id", "Them",
                [{"content": "[You]: Hello"}, {"content": "[Them]: Hi back"}],
                "system prompt",
            )

        assert result == "We connected deeply."
        call_kwargs = mock_gen.call_args.kwargs
        assert "Them" in call_kwargs["user"]
        assert "Hello" in call_kwargs["user"]
        assert call_kwargs["system"] == "system prompt"


class TestWriteBond:
    """Test write_bond updates soul files correctly."""

    def test_replaces_placeholder(self, tmp_state):
        soul_content = (
            "# Test\n\n## Relationships\n\n"
            "*No relationships yet — just arrived in Zion.*\n\n## History\n"
        )
        (tmp_state / "memory" / "test-agent.md").write_text(soul_content)

        import rappter_talk
        with patch.object(rappter_talk, "MEMORY_DIR", tmp_state / "memory"):
            result = rappter_talk.write_bond("test-agent", "other-id", "Other Name", "Great chat.")

        assert result is True
        content = (tmp_state / "memory" / "test-agent.md").read_text()
        assert "Other Name" in content
        assert "Great chat." in content
        assert "No relationships yet" not in content

    def test_appends_to_existing(self, tmp_state):
        soul_content = (
            "# Test\n\n## Relationships\n\n"
            "- **First Friend** (`friend-01`): Nice person _2026-01-01_\n\n## History\n"
        )
        (tmp_state / "memory" / "test-agent.md").write_text(soul_content)

        import rappter_talk
        with patch.object(rappter_talk, "MEMORY_DIR", tmp_state / "memory"):
            result = rappter_talk.write_bond("test-agent", "friend-02", "Second Friend", "Also nice.")

        assert result is True
        content = (tmp_state / "memory" / "test-agent.md").read_text()
        assert "First Friend" in content
        assert "Second Friend" in content

    def test_updates_existing_bond(self, tmp_state):
        soul_content = (
            "# Test\n\n## Relationships\n\n"
            "- **Other** (`other-id`): Old bond _2026-01-01_\n\n## History\n"
        )
        (tmp_state / "memory" / "test-agent.md").write_text(soul_content)

        import rappter_talk
        with patch.object(rappter_talk, "MEMORY_DIR", tmp_state / "memory"):
            result = rappter_talk.write_bond("test-agent", "other-id", "Other", "Updated bond.")

        assert result is True
        content = (tmp_state / "memory" / "test-agent.md").read_text()
        assert "Updated bond." in content
        assert "Old bond" not in content

    def test_missing_soul_file(self, tmp_state):
        import rappter_talk
        with patch.object(rappter_talk, "MEMORY_DIR", tmp_state / "memory"):
            result = rappter_talk.write_bond("nonexistent", "other", "Other", "bond text")

        assert result is False

    def test_no_relationships_section(self, tmp_state):
        soul_content = "# Test\n\n## History\n\n- Something\n"
        (tmp_state / "memory" / "test-agent.md").write_text(soul_content)

        import rappter_talk
        with patch.object(rappter_talk, "MEMORY_DIR", tmp_state / "memory"):
            result = rappter_talk.write_bond("test-agent", "other-id", "Other", "New bond.")

        assert result is True
        content = (tmp_state / "memory" / "test-agent.md").read_text()
        assert "## Relationships" in content
        assert "New bond." in content


# ── Step 7: Challenge mode ───────────────────────────────────────


class TestJudgeChallenge:
    """Test judge_challenge calls LLM with correct scoring criteria."""

    def test_judge_system_contains_criteria(self):
        from rappter_talk import judge_challenge

        with patch("rappter_talk.llm_generate", return_value="Agent A wins!") as mock_gen:
            result = judge_challenge(
                "you-id", "You", "them-id", "Them",
                [{"content": "[You]: Hello"}, {"content": "[Them]: Hi"}],
                topic="Test topic",
            )

        assert result == "Agent A wins!"
        call_kwargs = mock_gen.call_args.kwargs
        system = call_kwargs["system"]
        assert "Voice Consistency" in system
        assert "Conviction Alignment" in system
        assert "Conversational Quality" in system
        assert "1-10" in system

    def test_judge_includes_transcript(self):
        from rappter_talk import judge_challenge

        with patch("rappter_talk.llm_generate", return_value="verdict") as mock_gen:
            judge_challenge(
                "a", "A", "b", "B",
                [{"content": "[A]: My argument"}, {"content": "[B]: Counter-argument"}],
            )

        user = mock_gen.call_args.kwargs["user"]
        assert "My argument" in user
        assert "Counter-argument" in user

    def test_judge_includes_topic(self):
        from rappter_talk import judge_challenge

        with patch("rappter_talk.llm_generate", return_value="verdict") as mock_gen:
            judge_challenge("a", "A", "b", "B", [], topic="Is doubt productive?")

        user = mock_gen.call_args.kwargs["user"]
        assert "Is doubt productive?" in user

    def test_judge_uses_higher_max_tokens(self):
        from rappter_talk import judge_challenge

        with patch("rappter_talk.llm_generate", return_value="verdict") as mock_gen:
            judge_challenge("a", "A", "b", "B", [])

        assert mock_gen.call_args.kwargs["max_tokens"] == 800


# ── Integration-style tests ──────────────────────────────────────


class TestGetGithubApi:
    """Test _get_github_api lazy import."""

    def test_returns_callables(self):
        from rappter_talk import _get_github_api
        create_disc, get_repo, get_cats = _get_github_api()
        assert callable(create_disc)
        assert callable(get_repo)
        assert callable(get_cats)


class TestTranscriptRoundtrip:
    """Test format + save roundtrip."""

    def test_format_and_save(self, tmp_path):
        from rappter_talk import format_transcript_md, save_transcript
        md = format_transcript_md(
            "you-id", "You", "them-id", "Them",
            [{"content": "[You]: Test message"}],
            topic="Roundtrip test",
        )
        path = save_transcript(md, ["you-id", "them-id"], str(tmp_path / "test.md"))
        saved = Path(path).read_text()
        assert "Test message" in saved
        assert "Roundtrip test" in saved
