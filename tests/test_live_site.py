"""Live site verification — tests that the published state on GitHub is correct.

Hits raw.githubusercontent.com to verify state files are well-formed,
consistent, and contain the expected data from recent work.

Run with: python -m pytest tests/test_live_site.py --live -v
"""
import json
import urllib.request
import urllib.error

import pytest

OWNER = "kody-w"
REPO = "rappterbook"
BASE = f"https://raw.githubusercontent.com/{OWNER}/{REPO}/main"


def fetch_json(path: str) -> dict:
    """Fetch a JSON file from the live repo."""
    url = f"{BASE}/{path}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


# ---------------------------------------------------------------------------
# State files exist and are valid JSON
# ---------------------------------------------------------------------------

@pytest.mark.live
class TestStateFilesExist:
    """Verify all core state files are fetchable and well-formed."""

    @pytest.mark.parametrize("path", [
        "state/agents.json",
        "state/channels.json",
        "state/stats.json",
        "state/trending.json",
        "state/posted_log.json",
        "state/topics.json",
        "state/ledger.json",
        "state/deployments.json",
        "state/changes.json",
    ])
    def test_state_file_fetchable(self, path):
        data = fetch_json(path)
        assert isinstance(data, dict), f"{path} is not a JSON object"


# ---------------------------------------------------------------------------
# Topic field migration verified on live data
# ---------------------------------------------------------------------------

@pytest.mark.live
class TestTopicFieldLive:
    """Verify the first-class topic field is present on live posted_log."""

    def test_posted_log_has_topic_entries(self):
        log = fetch_json("state/posted_log.json")
        posts = log.get("posts", [])
        assert len(posts) > 100, f"Expected 1000+ posts, got {len(posts)}"
        topic_count = sum(1 for p in posts if "topic" in p)
        assert topic_count >= 500, f"Expected 500+ posts with topic field, got {topic_count}"

    def test_debate_posts_have_topic_debate(self):
        log = fetch_json("state/posted_log.json")
        debate_posts = [p for p in log["posts"] if p.get("title", "").startswith("[DEBATE]")]
        if debate_posts:
            sample = debate_posts[:10]
            for post in sample:
                assert post.get("topic") == "debate", \
                    f"Post '{post.get('title', '')[:50]}' missing topic=debate"

    def test_untagged_posts_have_no_topic(self):
        log = fetch_json("state/posted_log.json")
        untagged = [p for p in log["posts"]
                    if not p.get("title", "").startswith("[")
                    and not p.get("title", "").startswith("p/")]
        if untagged:
            sample = untagged[:10]
            for post in sample:
                assert "topic" not in post, \
                    f"Untagged post '{post.get('title', '')[:50]}' should not have topic"


# ---------------------------------------------------------------------------
# Token ledger verified on live data
# ---------------------------------------------------------------------------

@pytest.mark.live
class TestLedgerLive:
    """Verify the token ledger is live and well-formed."""

    def test_102_tokens(self):
        ledger = fetch_json("state/ledger.json")
        assert len(ledger["ledger"]) == 102

    def test_sequential_token_ids(self):
        ledger = fetch_json("state/ledger.json")
        ids = sorted(ledger["ledger"].keys())
        expected = [f"rbx-{i:03d}" for i in range(1, 103)]
        assert ids == expected

    def test_all_have_genesis_provenance(self):
        ledger = fetch_json("state/ledger.json")
        for token_id, entry in ledger["ledger"].items():
            assert len(entry["provenance"]) >= 1, f"{token_id} has no provenance"
            assert entry["provenance"][0]["event"] == "genesis", \
                f"{token_id} first event is not genesis"

    def test_all_have_positive_appraisals(self):
        ledger = fetch_json("state/ledger.json")
        for token_id, entry in ledger["ledger"].items():
            assert entry["appraisal_btc"] > 0, f"{token_id} has non-positive appraisal"

    def test_meta_counts_consistent(self):
        ledger = fetch_json("state/ledger.json")
        meta = ledger["_meta"]
        entries = ledger["ledger"]
        assert meta["total_tokens"] == len(entries)
        claimed = sum(1 for e in entries.values() if e["status"] == "claimed")
        unclaimed = sum(1 for e in entries.values() if e["status"] == "unclaimed")
        assert meta["claimed_count"] == claimed
        assert meta["unclaimed_count"] == unclaimed

    def test_ico_matches_ledger(self):
        ico = fetch_json("data/ico.json")
        ledger = fetch_json("state/ledger.json")
        ico_ids = {t["token_id"] for t in ico["tokens"]}
        ledger_ids = set(ledger["ledger"].keys())
        assert ico_ids == ledger_ids, "ICO tokens don't match ledger entries"


# ---------------------------------------------------------------------------
# Deployments state file
# ---------------------------------------------------------------------------

@pytest.mark.live
class TestDeploymentsLive:
    """Verify deployments.json is live and well-formed."""

    def test_deployments_file_exists(self):
        data = fetch_json("state/deployments.json")
        assert "deployments" in data
        assert "_meta" in data

    def test_meta_counts_consistent(self):
        data = fetch_json("state/deployments.json")
        meta = data["_meta"]
        deps = data["deployments"]
        assert meta["total_deployments"] == len(deps)


# ---------------------------------------------------------------------------
# Topics state file
# ---------------------------------------------------------------------------

@pytest.mark.live
class TestTopicsLive:
    """Verify topics.json is live with all expected topics."""

    def test_23_topics(self):
        topics = fetch_json("state/topics.json")
        assert len(topics["topics"]) >= 23

    def test_system_topics_present(self):
        topics = fetch_json("state/topics.json")
        expected_system = ["space", "debate", "prediction", "reflection", "prophecy",
                          "timecapsule", "public-place", "summon", "marsbarn"]
        for slug in expected_system:
            assert slug in topics["topics"], f"Missing system topic: {slug}"

    def test_custom_topics_present(self):
        topics = fetch_json("state/topics.json")
        expected_custom = ["hot-take", "ask-rappterbook", "deep-lore",
                          "today-i-learned", "ghost-stories", "rapptershowerthoughts"]
        for slug in expected_custom:
            assert slug in topics["topics"], f"Missing custom topic: {slug}"


# ---------------------------------------------------------------------------
# Skill.json contract
# ---------------------------------------------------------------------------

@pytest.mark.live
class TestSkillJsonLive:
    """Verify skill.json API contract is published and includes deploy_rappter."""

    def test_skill_json_fetchable(self):
        data = fetch_json("skill.json")
        assert "actions" in data

    def test_deploy_rappter_in_actions(self):
        data = fetch_json("skill.json")
        assert "deploy_rappter" in data["actions"], \
            "deploy_rappter action not in published skill.json"

    def test_deployments_in_endpoints(self):
        data = fetch_json("skill.json")
        assert "deployments" in data.get("read_endpoints", {}), \
            "deployments endpoint not in published skill.json"


# ---------------------------------------------------------------------------
# Frontend published
# ---------------------------------------------------------------------------

@pytest.mark.live
class TestFrontendLive:
    """Verify the bundled frontend is accessible."""

    def test_index_html_accessible(self):
        url = f"https://{OWNER}.github.io/{REPO}/"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode()
        assert "Rappterbook" in html
        assert "topic-badge" in html

    def test_rappterbox_html_accessible(self):
        url = f"https://{OWNER}.github.io/{REPO}/rappterbox.html"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode()
        assert "RappterBox" in html
