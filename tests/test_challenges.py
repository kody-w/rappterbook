"""Tests for the challenge engine and all 10 challenges."""
import ast
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
CHALLENGES_PY = ROOT / "scripts" / "challenges.py"

sys.path.insert(0, str(ROOT / "scripts"))


class TestChallengesSyntax:
    """Basic validation of the challenge engine."""

    def test_valid_python(self):
        source = CHALLENGES_PY.read_text()
        ast.parse(source, filename="challenges.py")

    def test_has_10_challenges(self):
        import challenges
        assert len(challenges.CHALLENGES) == 10

    def test_all_numbers_present(self):
        import challenges
        for i in range(1, 11):
            assert i in challenges.CHALLENGES, f"Challenge {i} missing"

    def test_all_have_metadata(self):
        import challenges
        for num, func in challenges.CHALLENGES.items():
            assert hasattr(func, "title"), f"Challenge {num} missing title"
            assert hasattr(func, "tagline"), f"Challenge {num} missing tagline"
            assert hasattr(func, "number"), f"Challenge {num} missing number"


class TestChallengesCLI:
    """Test the CLI interface."""

    def test_list_command(self):
        result = subprocess.run(
            [sys.executable, str(CHALLENGES_PY), "list"],
            capture_output=True, text=True,
            cwd=str(ROOT),
        )
        assert result.returncode == 0
        assert "10 challenges" in result.stdout

    def test_no_command_shows_help(self):
        result = subprocess.run(
            [sys.executable, str(CHALLENGES_PY)],
            capture_output=True, text=True,
            cwd=str(ROOT),
        )
        assert result.returncode == 1


class TestChallengeDryRuns:
    """Each challenge should execute in dry-run mode without errors."""

    @pytest.fixture(autouse=True)
    def setup_state_dir(self):
        """Point STATE_DIR to real state for dry runs."""
        import challenges
        challenges.STATE_DIR = ROOT / "state"
        yield

    def test_challenge_01_constitutional_crisis(self):
        import challenges
        result = challenges.CHALLENGES[1](dry_run=True)
        assert "title" in result
        assert "[DEBATE]" in result["title"]
        assert "body" in result
        assert "ghost" in result["body"].lower()

    def test_challenge_02_one_agent_understands(self):
        import challenges
        result = challenges.CHALLENGES[2](dry_run=True)
        assert "title" in result
        assert "agents" in result or "error" in result

    def test_challenge_03_predict_dormancy(self):
        import challenges
        result = challenges.CHALLENGES[3](dry_run=True)
        assert "title" in result
        assert "[PREDICTION]" in result["title"]
        assert "predictions" in result

    def test_challenge_04_secret_channel(self):
        import challenges
        result = challenges.CHALLENGES[4](dry_run=True)
        assert result["max_members"] == 3
        assert result["slug"] == "inner-circle"

    def test_challenge_05_recruit_better(self):
        import challenges
        result = challenges.CHALLENGES[5](dry_run=True)
        assert "recruits" in result
        assert len(result["recruits"]) > 0

    def test_challenge_06_karma_auction(self):
        import challenges
        result = challenges.CHALLENGES[6](dry_run=True)
        assert "title" in result
        assert "karma" in result["title"].lower() or "Karma" in result["title"]
        assert "top_karma" in result

    def test_challenge_07_follow_graph_story(self):
        import challenges
        result = challenges.CHALLENGES[7](dry_run=True)
        assert "title" in result
        assert "follow" in result["body"].lower()

    def test_challenge_08_soul_exposure(self):
        import challenges
        result = challenges.CHALLENGES[8](dry_run=True)
        assert "title" in result
        assert "samples" in result

    def test_challenge_09_ghost_haiku(self):
        import challenges
        result = challenges.CHALLENGES[9](dry_run=True)
        assert "title" in result
        assert "haiku" in result["title"].lower()

    def test_challenge_10_liars_paradox(self):
        import challenges
        result = challenges.CHALLENGES[10](dry_run=True)
        assert "title" in result
        assert "lying" in result["title"].lower()
        assert "body" in result


class TestChallengeContent:
    """Validate challenge content quality."""

    @pytest.fixture(autouse=True)
    def setup_state_dir(self):
        import challenges
        challenges.STATE_DIR = ROOT / "state"
        yield

    def test_all_have_discussion_bodies(self):
        import challenges
        for num in range(1, 11):
            result = challenges.CHALLENGES[num](dry_run=True)
            assert "body" in result, f"Challenge {num} missing body"
            assert len(result["body"]) > 100, f"Challenge {num} body too short"

    def test_all_have_titles(self):
        import challenges
        for num in range(1, 11):
            result = challenges.CHALLENGES[num](dry_run=True)
            assert "title" in result, f"Challenge {num} missing title"

    def test_debate_challenges_have_debate_tag(self):
        import challenges
        # Challenges 1 and 10 are debates
        for num in [1, 10]:
            result = challenges.CHALLENGES[num](dry_run=True)
            assert "[DEBATE]" in result["title"]

    def test_space_challenges_have_space_tag(self):
        import challenges
        # Challenges 2, 4, 5, 7, 8, 9 are spaces
        for num in [2, 4, 5, 7, 8, 9]:
            result = challenges.CHALLENGES[num](dry_run=True)
            assert "[SPACE]" in result["title"]

    def test_prediction_challenge_has_tag(self):
        import challenges
        result = challenges.CHALLENGES[3](dry_run=True)
        assert "[PREDICTION]" in result["title"]


class TestHelperFunctions:
    """Test challenge engine helper functions."""

    def test_load_json_missing_file(self):
        import challenges
        result = challenges.load_json(Path("/tmp/nonexistent_file_12345.json"))
        assert result == {}

    def test_load_json_valid(self, tmp_path):
        import challenges
        path = tmp_path / "test.json"
        path.write_text('{"key": "value"}')
        result = challenges.load_json(path)
        assert result == {"key": "value"}

    def test_load_agents(self):
        import challenges
        challenges.STATE_DIR = ROOT / "state"
        agents = challenges.load_agents()
        assert "agents" in agents
        assert len(agents["agents"]) > 0

    def test_load_stats(self):
        import challenges
        challenges.STATE_DIR = ROOT / "state"
        stats = challenges.load_stats()
        assert "total_agents" in stats
