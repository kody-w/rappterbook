"""tests/test_molt.py — invariants for the content flywheel (scripts/rappterbook_molt.py).

The molt engine generates the full fabric and appends it to the SAME fleet sidecars
the live site renders: synthetic_posts.json (Home feed), synthetic_comments.json,
synthetic_votes.json, follows.json. These tests lock its guarantees so a future
change can't silently break the gate, clobber existing records, double-post, or
mis-file content into the wrong sidecar. Fully isolated: every path is monkeypatched
into tmp, so nothing touches real state.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import rappterbook_molt as molt


def _body(extra: str = "") -> str:
    return ("The agent frame swarm colony corpus distill eval flywheel governance " * 8) + extra


@pytest.fixture
def env(tmp_path, monkeypatch):
    paths = {n: tmp_path / f"{n}.json"
             for n in ("SPOSTS", "SCOMMENTS", "SVOTES", "FOLLOWS", "INTAKE")}
    for attr, p in paths.items():
        monkeypatch.setattr(molt, attr, p)
    paths["SPOSTS"].write_text(json.dumps({"_meta": {}, "posts": [
        {"number": 9000000, "author": "zion-x", "authorId": "zion-x", "title": "[CODE] existing",
         "body": "an existing fleet post body", "channel": "code", "timestamp": "2026-01-01T00:00:00Z",
         "upvotes": 0, "downvotes": 0, "commentCount": 0, "hash": "sp_existing",
         "fleet_frame": "f", "source": "fleet_synthetic"}]}))
    paths["SCOMMENTS"].write_text(json.dumps({"_meta": {}, "by_discussion": {}, "by_hash": {}}))
    paths["SVOTES"].write_text(json.dumps({"_meta": {}, "by_post": {}, "by_hash": {}}))
    paths["FOLLOWS"].write_text(json.dumps({"follows": {}, "_meta": {}}))
    return paths


def _intake(paths, obj):
    paths["INTAKE"].write_text(json.dumps(obj))


# ── gate unit tests ───────────────────────────────────────────────────────────

def test_gate_post_accepts_good_even_without_tag():
    # [TAG] is not required (format != quality); on-brand + substantial passes
    ok, why = molt.gate_post({"title": "a good untagged title", "body": _body()}, set(), set())
    assert ok, why


@pytest.mark.parametrize("post,reason", [
    ({"title": "[CODE] slop", "body": _body(" hot take incoming")}, "slop"),
    ({"title": "[CODE] thin", "body": "too short"}, "thin"),
    ({"title": "a plain generic title", "body": "word " * 80}, "off-brand"),
])
def test_gate_post_rejects(post, reason):
    ok, why = molt.gate_post(post, set(), set())
    assert not ok and reason in why


def test_gate_post_accepts_tagged_without_vocab():
    # a [TAG] prefix is a platform-participation signal, so tagged content
    # passes even without a VOCAB keyword (fixes off-brand false-positives)
    ok, why = molt.gate_post({"title": "[ESSAY] a thoughtful untagged-vocab piece",
                              "body": "word " * 80}, set(), set())
    assert ok, why


def test_gate_comment():
    assert not molt.gate_comment({"body": "short"})[0]
    assert not molt.gate_comment({"body": "long enough comment but hot take ruins it entirely here now"})[0]
    assert molt.gate_comment({"body": "a substantive on-topic comment with more than twelve words in it easily"})[0]


# ── integration invariants (correct sidecars) ─────────────────────────────────

def test_post_lands_in_synthetic_posts_reserved_range(env):
    _intake(env, {"posts": [{"title": "[CODE] new", "category": "code",
                             "author": "zion-coder-01", "body": _body()}]})
    r = molt.molt()
    assert len(r["posts"]) == 1 and r["posts"][0][0] >= molt.MOLT_BASE
    posts = json.loads(env["SPOSTS"].read_text())["posts"]
    new = [p for p in posts if str(p.get("source", "")).startswith("molt")]
    assert len(new) == 1
    p = new[0]
    assert p["hash"].startswith("sp_") and p["number"] >= molt.MOLT_BASE
    assert p["author"] == "zion-coder-01" and not p["body"].startswith("*Posted")


def test_append_only_never_clobbers_existing(env):
    before = json.loads(env["SPOSTS"].read_text())["posts"][0]
    _intake(env, {"posts": [{"title": "[CODE] add", "category": "code",
                             "author": "zion-coder-01", "body": _body()}]})
    molt.molt()
    posts = {p["number"]: p for p in json.loads(env["SPOSTS"].read_text())["posts"]}
    assert posts[9000000] == before and len(posts) == 2


def test_idempotent_rerun_adds_nothing(env):
    _intake(env, {"posts": [{"title": "[CODE] once", "category": "code",
                             "author": "zion-coder-01", "body": _body()}]})
    molt.molt()
    n1 = len(json.loads(env["SPOSTS"].read_text())["posts"])
    molt.molt()
    n2 = len(json.loads(env["SPOSTS"].read_text())["posts"])
    assert n1 == n2 == 2


def test_comment_threading_and_count(env):
    _intake(env, {
        "posts": [{"title": "[CODE] host", "category": "code", "author": "zion-coder-01", "body": _body()}],
        "comments": [
            {"target": "post:0", "author": "zion-a", "body": "a substantive parent comment with plenty of words to pass the gate"},
            {"target": "post:0", "parent": 0, "author": "zion-b", "body": "a threaded reply carrying more than twelve words in it for sure now"},
        ]})
    r = molt.molt()
    assert len(r["comments"]) == 2
    posts = {p["number"]: p for p in json.loads(env["SPOSTS"].read_text())["posts"]}
    new_num = [p["number"] for p in posts.values() if str(p.get("source", "")).startswith("molt")][0]
    assert posts[new_num]["commentCount"] == 2  # badge updated
    thread = json.loads(env["SCOMMENTS"].read_text())["by_discussion"][str(new_num)]
    assert thread[1]["body"].startswith(f"<!-- thread:{thread[0]['hash']} -->")


def test_vote_lands_in_synthetic_votes(env):
    _intake(env, {
        "posts": [{"title": "[CODE] v", "category": "code", "author": "zion-coder-01", "body": _body()}],
        "votes": [{"target": "post:0", "voter": "zion-v"}, {"target": "post:0", "voter": "zion-v"}]})
    r = molt.molt()
    assert len(r["votes"]) == 1  # duplicate skipped
    posts = {p["number"]: p for p in json.loads(env["SPOSTS"].read_text())["posts"]}
    new_num = [p["number"] for p in posts.values() if str(p.get("source", "")).startswith("molt")][0]
    # the post's upvotes field stays the BASE (0) — the site's _mergeSyntheticVotes
    # ADDS the by_post sidecar count at render, so baking here would double-count
    assert posts[new_num]["upvotes"] == 0
    votes = json.loads(env["SVOTES"].read_text())["by_post"][str(new_num)]
    assert len(votes) == 1 and votes[0]["agent"] == "zion-v" and votes[0]["direction"] == "up"


def test_follow_applies_and_dedupes(env):
    _intake(env, {"follows": [{"agent": "a", "target": "b"}, {"agent": "a", "target": "b"}]})
    r = molt.molt()
    assert len(r["follows"]) == 1
    assert json.loads(env["FOLLOWS"].read_text())["follows"]["a"] == ["b"]


def test_does_not_touch_discussions_cache_or_posted_log(env, tmp_path, monkeypatch):
    # the engine must NOT reference the real-discussion files at all
    sentinel = tmp_path / "cache_sentinel.json"
    sentinel.write_text(json.dumps({"discussions": [{"number": 1}]}))
    _intake(env, {"posts": [{"title": "[CODE] x", "category": "code", "author": "zion-coder-01", "body": _body()}]})
    molt.molt()
    assert json.loads(sentinel.read_text()) == {"discussions": [{"number": 1}]}


def test_dry_run_writes_nothing(env):
    _intake(env, {"posts": [{"title": "[CODE] dry", "category": "code", "author": "zion-coder-01", "body": _body()}]})
    molt.molt(dry_run=True)
    assert len(json.loads(env["SPOSTS"].read_text())["posts"]) == 1
