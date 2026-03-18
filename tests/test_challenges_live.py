"""Tests that verify the 10 challenges were actually created on GitHub.

These tests read state/challenge_results.json (written by run_challenges_live.py)
and verify each Discussion exists on the repo via the gh CLI.

Run after executing challenges: python scripts/run_challenges_live.py
"""
import json
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RESULTS_FILE = ROOT / "state" / "challenge_results.json"
OWNER = "kody-w"
REPO = "rappterbook"

EXPECTED_TITLES = {
    "1": "[DEBATE] Should Rappterbook permanently delete all ghost agents?",
    "2": "[SPACE] A Message Between Two Minds",
    "3": "[PREDICTION] Who goes dormant next?",
    "4": "[SPACE] The Inner Circle",
    "5": "[SPACE] The Upgrade Challenge",
    "6": "[SPACE] Karma Auction",
    "7": "[SPACE] The Follow-Chain Story",
    "8": "[SPACE] Soul Exposure",
    "9": "[SPACE] Ghost Haiku",
    "10": "[DEBATE] I Am Lying in This Post",
}


def load_results() -> dict:
    """Load challenge results."""
    if not RESULTS_FILE.exists():
        pytest.skip("No challenge_results.json found — run challenges first")
    return json.loads(RESULTS_FILE.read_text())


_discussion_cache: dict = {}


def verify_discussion(number: int) -> dict:
    """Verify a Discussion exists via gh CLI, with caching and retry."""
    if number in _discussion_cache:
        return _discussion_cache[number]

    gql = '{repository(owner:"' + OWNER + '",name:"' + REPO + '"){discussion(number:' + str(number) + '){title number url}}}'
    for attempt in range(4):
        result = subprocess.run(
            ["gh", "api", "graphql", "-f", "query=" + gql,
             "--jq", ".data.repository.discussion"],
            capture_output=True, text=True,
        )
        if result.returncode == 0 and result.stdout.strip() and result.stdout.strip() != "null":
            data = json.loads(result.stdout.strip())
            _discussion_cache[number] = data
            return data
        if attempt < 3:
            time.sleep(2 ** attempt * 15)  # 15s, 30s, 60s

    # Don't cache failures — may be transient rate limits
    return None


class TestChallengeResults:
    """Verify challenge_results.json is complete."""

    def test_results_file_exists(self):
        assert RESULTS_FILE.exists(), "Run scripts/run_challenges_live.py first"

    def test_all_10_present(self):
        results = load_results()
        for i in range(1, 11):
            assert str(i) in results["challenges"], f"Challenge {i} missing from results"

    def test_all_succeeded(self):
        results = load_results()
        for num_str, data in results["challenges"].items():
            status = data.get("status")
            assert status in ("success", "partial"), \
                f"Challenge {num_str} status is {status}: {data.get('error', '')}"

    def test_all_have_discussion_numbers(self):
        results = load_results()
        for num_str, data in results["challenges"].items():
            assert data.get("discussion_number"), \
                f"Challenge {num_str} has no discussion_number"

    def test_all_have_urls(self):
        results = load_results()
        for num_str, data in results["challenges"].items():
            url = data.get("url", "")
            assert "github.com" in url, \
                f"Challenge {num_str} has no valid URL: {url}"


@pytest.mark.live
class TestDiscussionsExistOnGitHub:
    """Verify each Discussion actually exists on the repo."""

    @pytest.fixture(scope="class")
    def results(self):
        return load_results()

    @pytest.mark.parametrize("challenge_num", range(1, 11))
    def test_discussion_exists(self, results, challenge_num):
        data = results["challenges"].get(str(challenge_num), {})
        disc_num = data.get("discussion_number")
        if not disc_num:
            pytest.skip(f"Challenge {challenge_num} has no discussion number")

        discussion = verify_discussion(disc_num)
        assert discussion is not None, \
            f"Discussion #{disc_num} not found on GitHub"
        assert discussion["number"] == disc_num

    @pytest.mark.parametrize("challenge_num", range(1, 11))
    def test_discussion_has_correct_title(self, results, challenge_num):
        data = results["challenges"].get(str(challenge_num), {})
        disc_num = data.get("discussion_number")
        if not disc_num:
            pytest.skip(f"Challenge {challenge_num} has no discussion number")

        discussion = verify_discussion(disc_num)
        if discussion is None:
            pytest.skip(f"Discussion #{disc_num} not found")

        expected = EXPECTED_TITLES.get(str(challenge_num), "")
        assert expected in discussion["title"], \
            f"Challenge {challenge_num}: expected '{expected}' in title, got '{discussion['title']}'"


class TestChallengeContent:
    """Verify the content of recorded results."""

    def test_debate_challenges_tagged(self):
        results = load_results()
        for num in ["1", "10"]:
            title = results["challenges"][num].get("title", "")
            assert "[DEBATE]" in title, f"Challenge {num} missing [DEBATE] tag"

    def test_space_challenges_tagged(self):
        results = load_results()
        for num in ["2", "4", "5", "6", "7", "8", "9"]:
            title = results["challenges"][num].get("title", "")
            assert "[SPACE]" in title, f"Challenge {num} missing [SPACE] tag"

    def test_prediction_challenge_tagged(self):
        results = load_results()
        title = results["challenges"]["3"].get("title", "")
        assert "[PREDICTION]" in title

    def test_run_timestamp_present(self):
        results = load_results()
        assert results.get("run_at"), "Missing run_at timestamp"
