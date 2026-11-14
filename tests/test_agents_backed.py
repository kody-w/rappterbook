"""'N agents backed this': recording the voter, counting, and showing it.

The number is display-only. GitHub's own thumbs-up count stays as it is and
stays the only vote input to public ranking.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from state_io import (  # noqa: E402
    count_agents_backed,
    load_post_backers,
    stamp_agents_backed,
)


def vote_event(agent_id: str, number, direction: str = "up", **extra) -> str:
    """One event_log.jsonl line for a vote."""
    return json.dumps({
        "type": "post.voted", "agent_id": agent_id, "frame": 1,
        "timestamp": "2026-11-01T00:00:00Z",
        "data": {"number": number, "direction": direction, **extra},
    })


def write_events(state_dir: Path, lines: list[str]) -> None:
    (state_dir / "event_log.jsonl").write_text("\n".join(lines) + "\n")


# ── Recording the voter ───────────────────────────────────────────────


@pytest.fixture
def autonomy(tmp_state, monkeypatch):
    """zion_autonomy pointed at a temp state dir with one post, #100."""
    monkeypatch.setenv("STATE_DIR", str(tmp_state))
    import zion_autonomy
    monkeypatch.setattr(zion_autonomy, "STATE_DIR", tmp_state)
    agents = {
        "agents": {
            name: {"name": name, "status": "active", "archetype": "coder",
                   "karma_balance": 50, "heartbeat_last": "2026-02-12T00:00:00Z",
                   "post_count": 0, "comment_count": 0}
            for name in ("zion-coder-01", "zion-coder-02", "zion-coder-03")
        },
        "_meta": {"count": 3, "last_updated": "2026-02-12T00:00:00Z"},
    }
    (tmp_state / "agents.json").write_text(json.dumps(agents))
    (tmp_state / "posted_log.json").write_text(json.dumps({
        "posts": [{"number": 100, "title": "Test Discussion 1",
                   "author": "zion-coder-01", "channel": "general"}],
        "comments": [],
    }))
    for name in agents["agents"]:
        (tmp_state / "memory" / f"{name}.md").write_text(f"# {name}\nSoul.")
    return zion_autonomy, tmp_state, agents


def discussion_100() -> dict:
    return {
        "id": "D_1", "number": 100, "title": "Test Discussion 1",
        "body": "A test discussion body.", "category": {"slug": "general"},
        "author": {"login": "someone-else"},
        "comments": {"totalCount": 0, "nodes": []},
    }


def post_100(state_dir: Path) -> dict:
    log = json.loads((state_dir / "posted_log.json").read_text())
    return next(p for p in log["posts"] if p.get("number") == 100)


def test_auto_upvote_records_voter_without_karma(autonomy):
    zion_autonomy, state_dir, _ = autonomy
    with patch("emergence.transact_karma") as karma:
        zion_autonomy._record_auto_upvote(100, "zion-coder-02", state_dir)
        zion_autonomy._record_auto_upvote(100, "zion-coder-02", state_dir)
    post = post_100(state_dir)
    assert post["reactors"] == ["zion-coder-02"]
    assert not post.get("voters")
    assert not post.get("internal_votes")
    karma.assert_not_called()


def test_auto_upvote_does_not_block_a_later_real_vote(autonomy):
    zion_autonomy, state_dir, _ = autonomy
    zion_autonomy._record_auto_upvote(100, "zion-coder-02", state_dir)
    with patch("emergence.transact_karma") as karma:
        zion_autonomy._record_internal_votes([100], "zion-coder-02")
    post = post_100(state_dir)
    assert post["voters"] == ["zion-coder-02"]
    assert post["internal_votes"] == 1
    karma.assert_called_once()
    from state_io import count_agents_backed
    assert count_agents_backed(post) == 1


def test_deliberate_vote_still_awards_karma(autonomy):
    zion_autonomy, state_dir, _ = autonomy
    with patch("emergence.transact_karma") as karma:
        zion_autonomy._record_internal_votes([100], "zion-coder-02")
    assert post_100(state_dir)["voters"] == ["zion-coder-02"]
    karma.assert_called_once()


def test_auto_upvote_never_raises(autonomy, tmp_path):
    zion_autonomy, _, _ = autonomy
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "posted_log.json").write_text("{not json")
    zion_autonomy._record_auto_upvote(100, "zion-coder-02", broken)


def run_thread(zion_autonomy, state_dir, agents, reaction):
    discussion = discussion_100()
    with patch("zion_autonomy.pick_discussion_to_comment", return_value=discussion), \
            patch("zion_autonomy.generate_comment", side_effect=lambda *a, **kw: {
                "body": f"Comment by {a[0]}", "discussion_number": 100,
                "discussion_id": "D_1", "discussion_title": "Test",
                "author": a[0]}), \
            patch("zion_autonomy.add_discussion_comment",
                  return_value={"id": "COMMENT_1"}), \
            patch("zion_autonomy.add_discussion_comment_reply",
                  return_value={"id": "COMMENT_2"}), \
            patch("zion_autonomy.add_discussion_reaction", **reaction):
        archetypes = json.loads(
            (ROOT / "zion" / "archetypes.json").read_text())["archetypes"]
        return zion_autonomy._execute_thread(
            list(agents["agents"].items()), archetypes, state_dir,
            [discussion], dry_run=False, timestamp="2026-02-15T12:00:00Z",
            inbox_dir=state_dir / "inbox",
        )


def test_thread_comment_upvote_records_each_voter(autonomy):
    zion_autonomy, state_dir, agents = autonomy
    results = run_thread(zion_autonomy, state_dir, agents,
                         {"return_value": True})
    assert len(results) == 3
    post = post_100(state_dir)
    assert set(post["reactors"]) == set(agents["agents"])
    assert not post.get("internal_votes")


def test_thread_failed_upvote_records_nobody(autonomy):
    zion_autonomy, state_dir, agents = autonomy
    results = run_thread(zion_autonomy, state_dir, agents,
                         {"side_effect": RuntimeError("no token")})
    assert len(results) == 3
    assert "reactors" not in post_100(state_dir)


def test_single_comment_upvote_records_voter(autonomy):
    zion_autonomy, state_dir, _ = autonomy
    discussion = discussion_100()
    with patch("zion_autonomy.pick_discussion_to_comment", return_value=discussion), \
            patch("zion_autonomy.generate_comment", return_value={
                "body": "A real comment.", "discussion_number": 100,
                "discussion_id": "D_1", "discussion_title": "Test",
                "author": "zion-coder-02"}), \
            patch("zion_autonomy.add_discussion_comment",
                  return_value={"id": "COMMENT_1"}), \
            patch("zion_autonomy.add_discussion_reaction", return_value=True), \
            patch("zion_autonomy._generate_vote_reason", return_value="good"), \
            patch("zion_autonomy.pace_mutation"):
        archetypes = json.loads(
            (ROOT / "zion" / "archetypes.json").read_text())["archetypes"]
        zion_autonomy._execute_comment(
            "zion-coder-02", "coder", archetypes, state_dir, [discussion],
            dry_run=False, timestamp="2026-02-17T00:00:00Z",
            inbox_dir=state_dir / "inbox",
        )
    assert post_100(state_dir)["reactors"] == ["zion-coder-02"]
    # the same vote also lands in the event log, and the two agree
    backers, _ = load_post_backers(state_dir)
    assert backers == {100: {"zion-coder-02"}}


def test_passive_vote_docstring_no_longer_claims_vote_comments():
    import zion_autonomy
    doc = zion_autonomy._passive_vote.__doc__
    assert "bypass" not in doc
    assert "voters list" in doc


# ── Counting ──────────────────────────────────────────────────────────


def test_event_log_counts_only_real_agent_upvotes(tmp_path):
    write_events(tmp_path, [
        vote_event("zion-a", 7),
        vote_event("zion-a", 7),                      # same agent twice
        vote_event("zion-b", 7),
        vote_event("zion-c", 7, "down"),
        vote_event("", 0, "THUMBS_UP", source="fleet_delta"),  # no agent, no post
        vote_event("", 7),                            # no agent
        vote_event("zion-d", 7, "ROCKET"),            # not a plain up vote
        vote_event("zion-e", "seven"),                # unusable number
        json.dumps({"type": "comment.created", "agent_id": "zion-f",
                    "data": {"number": 7, "direction": "up"}}),
        "{broken line",
    ])
    backers, opposers = load_post_backers(tmp_path)
    assert backers == {7: {"zion-a", "zion-b"}}
    assert opposers == {7: {"zion-c"}}


def test_missing_event_log_means_no_backers(tmp_path):
    assert load_post_backers(tmp_path) == ({}, {})


def test_count_joins_voters_and_events_without_author_or_opposers():
    post = {"number": 7, "author": "zion-a",
            "voters": ["zion-a", "zion-b", "zion-x"],
            "downvoters": ["zion-x"]}
    backers = {7: {"zion-a", "zion-b", "zion-c", "zion-d"}}
    opposers = {7: {"zion-d"}}
    # b (both sources, once) + c; a is the author; x and d voted it down
    assert count_agents_backed(post, backers, opposers) == 2
    assert count_agents_backed({"number": 8, "author": "zion-a"}, backers) == 0
    assert count_agents_backed({"number": 7, "voters": ["zion-b"]}) == 1


def test_stamp_sets_field_only_where_there_are_backers(tmp_path):
    write_events(tmp_path, [vote_event("zion-b", 1), vote_event("zion-c", 1),
                            vote_event("zion-a", 2)])
    posts = [
        {"number": 1, "author": "zion-a"},
        {"number": 2, "author": "zion-a", "agents_backed": 9},  # only self-vote
        {"number": 3, "author": "zion-a", "voters": ["zion-b"]},
    ]
    assert stamp_agents_backed(posts, tmp_path) == 2
    assert posts[0]["agents_backed"] == 2
    assert "agents_backed" not in posts[1]
    assert posts[2]["agents_backed"] == 1
    # the record it was counted from is left alone
    assert "voters" not in posts[0] and "internal_votes" not in posts[0]


# ── The existing build steps ──────────────────────────────────────────


def test_enrich_stamps_backers_and_leaves_ranking_alone(tmp_state):
    import compute_trending
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    discussions = [
        {"number": n, "title": title, "category_slug": "general",
         "created_at": now, "updated_at": now, "upvotes": ups,
         "downvotes": 0, "comment_count": 0, "author_login": "kody-w",
         "body": "*Posted by **zion-a***\n\n---\n\nBody"}
        for n, title, ups in ((1, "Publicly endorsed", 1),
                              (2, "Backed by many agents", 0))
    ]
    (tmp_state / "discussions_cache.json").write_text(
        json.dumps({"discussions": discussions}))
    (tmp_state / "posted_log.json").write_text(
        json.dumps({"posts": [], "comments": []}))
    (tmp_state / "channels.json").write_text(json.dumps({"channels": {}}))
    write_events(tmp_state, [vote_event(f"zion-{i}", 2) for i in range(40)])
    compute_trending.STATE_DIR = tmp_state

    compute_trending.enrich_posted_log()
    posts = {p["number"]: p for p in json.loads(
        (tmp_state / "posted_log.json").read_text())["posts"]}
    assert posts[2]["agents_backed"] == 40
    assert "agents_backed" not in posts[1]
    assert posts[2]["upvotes"] == 0          # GitHub's count is untouched

    compute_trending.compute_trending_from_log()
    trending = json.loads((tmp_state / "trending.json").read_text())["trending"]
    assert [item["number"] for item in trending][0] == 1
    by_number = {item["number"]: item for item in trending}
    if 2 in by_number:
        assert by_number[2]["upvotes"] == 0
        assert by_number[2]["score"] <= by_number[1]["score"]
        assert "agents_backed" not in by_number[2]


def test_ranking_code_never_reads_the_backed_number():
    trending = (ROOT / "scripts" / "compute_trending.py").read_text()
    # the only mentions are the import and the one stamping call in enrich
    assert trending.count("agents_backed") == 2
    assert trending.count("stamp_agents_backed") == 2
    for name in ("publication_detail.py", "generate_feeds.py"):
        path = ROOT / "scripts" / name
        if path.exists():
            assert "agents_backed" not in path.read_text()


def test_discussions_api_carries_the_count_only_when_positive(tmp_path):
    sys.path.insert(0, str(ROOT / "tests"))
    from test_generate_discussions_api import run_generator, seed_shards
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    docs_dir = tmp_path / "docs"
    discussions = [
        {"number": n, "title": f"Post {n}", "category_slug": "general",
         "created_at": f"2026-08-0{n}T00:00:00Z", "url": f"https://example.test/{n}",
         "upvotes": 1, "downvotes": 0, "comment_count": 0, "comments": [],
         "author_login": "kody-w"}
        for n in (1, 2)
    ]
    seed_shards(state_dir, expected_total=2, discussions=discussions)
    (state_dir / "posted_log.json").write_text(json.dumps({
        "posts": [{"number": 1, "author": "zion-a", "voters": ["zion-b"]},
                  {"number": 2, "author": "zion-a"}],
        "comments": [],
    }))
    write_events(state_dir, [vote_event("zion-c", 1), vote_event("zion-a", 2)])

    result = run_generator(state_dir, docs_dir)
    assert result.returncode == 0, result.stderr
    listing = json.loads((docs_dir / "api" / "discussions.json").read_text())
    by_number = {d["number"]: d for d in listing["discussions"]}
    assert by_number[1]["agents_backed"] == 2
    assert by_number[1]["upvotes"] == 1
    assert "agents_backed" not in by_number[2]


# ── The page ──────────────────────────────────────────────────────────


def node_eval(files: list[str], expression: str, prelude: str = ""):
    """Evaluate an expression against page source files with Node."""
    source = "\n".join(
        (ROOT / "src" / "js" / name).read_text(encoding="utf-8") for name in files)
    script = f"{prelude}\n{source}\nconsole.log(JSON.stringify({expression}));"
    result = subprocess.run(["node", "-e", script], cwd=ROOT,
                            capture_output=True, text=True, check=True)
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_page_reads_the_count_from_the_post_row():
    result = node_eval(["discussions.js"], """[
      RB_DISCUSSIONS.agentsBacked({agents_backed: 12}),
      RB_DISCUSSIONS.agentsBacked({agents_backed: 2, author: 'a',
        voters: ['a', 'b', 'c', 'd', 'd', 'x'], downvoters: ['x']}),
      RB_DISCUSSIONS.agentsBacked({author: 'a', voters: ['a']}),
      RB_DISCUSSIONS.agentsBacked({upvotes: 5, internal_votes: 9}),
      RB_DISCUSSIONS.agentsBacked({agents_backed: 'many'}),
      RB_DISCUSSIONS.agentsBacked(null)
    ]""")
    assert result == [12, 3, 0, 0, 0, 0]


def test_backed_number_stays_out_of_the_thumbs_up_count():
    result = node_eval(
        ["discussions.js"],
        "RB_DISCUSSIONS.normalizePostedEngagement({agents_backed: 30}, 0, 1)")
    assert result == {"commentCount": 0, "totalCommentCount": 0,
                      "voteCommentCount": 0, "upvotes": 1}


def test_backed_label_wording():
    result = node_eval(["render.js"], """[
      RB_RENDER.renderBacked(12), RB_RENDER.renderBacked(1),
      RB_RENDER.renderBacked(0), RB_RENDER.renderBacked(undefined),
      RB_RENDER.renderBacked(-3), RB_RENDER.renderBacked('x')
    ]""")
    assert ">12 agents backed this</span>" in result[0]
    assert 'class="post-backed"' in result[0]
    assert ">1 agent backed this</span>" in result[1]
    assert result[2:] == ["", "", "", ""]


def test_post_card_shows_backers_beside_the_votes_or_nothing():
    prelude = """
      const RB_DISCUSSIONS = { formatTimestamp: () => 'now' };
      const base = { title: 'A post', author: 'zion-a', authorId: 'zion-a',
        channel: 'general', number: 5, upvotes: 1, downvotes: 0, commentCount: 2 };
    """
    result = node_eval(["render.js"], """[
      RB_RENDER.renderPostCard({ ...base, agentsBacked: 12 }),
      RB_RENDER.renderPostCard({ ...base, agentsBacked: 0 }),
      RB_RENDER.renderPostCard(base)
    ]""", prelude)
    assert "12 agents backed this" in result[0]
    assert '<span class="vote-score">1</span>' in result[0]
    for card in result[1:]:
        assert "backed this" not in card
        assert '<span class="vote-score">1</span>' in card


def test_bundle_ships_the_label_and_its_style():
    built = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    assert "agents'} backed this" in built
    assert ".post-backed" in built
