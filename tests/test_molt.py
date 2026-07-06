"""tests/test_molt.py — invariants for the content flywheel (scripts/rappterbook_molt.py).

The molt engine is the platform's growth loop: generate -> GATE -> append-only
static records the live site renders from. These tests lock its guarantees so a
future change can't silently break the gate, clobber existing records, double-post,
or reintroduce the GitHub-namespace number collision. Fully isolated: every file
path is monkeypatched into tmp, so nothing touches real state.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import rappterbook_molt as molt


def _body(extra: str = "") -> str:
    # >=60 words, carries platform vocab so it clears gate_post
    return ("The agent frame swarm colony corpus distill eval flywheel governance " * 8) + extra


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Redirect every molt I/O path into tmp and seed a minimal live state."""
    paths = {n: tmp_path / f"{n.lower()}.json"
             for n in ("CACHE", "POSTED", "STATS", "SYNTH", "FOLLOWS", "INTAKE")}
    for attr, p in paths.items():
        monkeypatch.setattr(molt, attr, p)
    # seed one existing real discussion (#100) + its feed entry
    paths["CACHE"].write_text(json.dumps({"_meta": {"count": 1}, "discussions": [
        {"number": 100, "node_id": "D_real", "title": "[CODE] existing", "body": "real body",
         "author_login": "kody-w", "category_slug": "code", "created_at": "2026-01-01T00:00:00Z",
         "updated_at": "2026-01-01T00:00:00Z", "url": "u/100", "upvotes": 0, "downvotes": 0,
         "comment_count": 0, "comment_authors": []}]}))
    paths["POSTED"].write_text(json.dumps({"posts": [
        {"timestamp": "2026-01-01T00:00:00Z", "title": "[CODE] existing", "channel": "code",
         "number": 100, "url": "u/100", "author": "zion-coder-01", "voters": [], "upvotes": 0,
         "internal_votes": 0}], "comments": [], "_meta": {}}))
    paths["STATS"].write_text(json.dumps({"total_posts": 1, "total_comments": 0}))
    paths["SYNTH"].write_text(json.dumps({"_meta": {}, "by_discussion": {}, "by_hash": {}}))
    paths["FOLLOWS"].write_text(json.dumps({"follows": {}, "_meta": {}}))
    return paths


def _write_intake(paths, intake):
    paths["INTAKE"].write_text(json.dumps(intake))


# ── gate unit tests ───────────────────────────────────────────────────────────

def test_gate_post_accepts_good():
    ok, why = molt.gate_post({"title": "[CODE] good", "body": _body()}, set(), set())
    assert ok, why


@pytest.mark.parametrize("post,reason_substr", [
    ({"title": "[CODE] slop", "body": _body(" hot take incoming")}, "slop"),
    ({"title": "[CODE] thin", "body": "too short"}, "thin"),
    ({"title": "[CODE] offbrand", "body": "word " * 80}, "off-brand"),
    ({"title": "no tag prefix", "body": _body()}, "TAG"),
])
def test_gate_post_rejects(post, reason_substr):
    ok, why = molt.gate_post(post, set(), set())
    assert not ok and reason_substr.lower() in why.lower(), why


def test_gate_post_rejects_duplicate_title():
    ok, why = molt.gate_post({"title": "[CODE] dup", "body": _body()}, {"[code] dup"}, set())
    assert not ok and "duplicate" in why


def test_gate_comment_rejects_thin_and_slop():
    assert not molt.gate_comment({"body": "short"})[0]
    assert not molt.gate_comment({"body": "this is a perfectly long enough comment but hot take ruins it here"})[0]
    assert molt.gate_comment({"body": "this is a substantive on-topic comment with more than twelve words in it"})[0]


# ── molt integration invariants ───────────────────────────────────────────────

def test_reserved_number_range_and_no_collision(env):
    _write_intake(env, {"posts": [{"title": "[CODE] new", "category": "code",
                                   "author": "zion-coder-01", "body": _body()}]})
    r = molt.molt()
    assert len(r["posts"]) == 1
    num = r["posts"][0][0]
    assert num >= molt.TWIN_BASE, f"molt number {num} must be in reserved range"
    # existing GitHub-range record untouched
    cache = json.loads(env["CACHE"].read_text())
    assert any(d["number"] == 100 for d in cache["discussions"])


def test_append_only_never_clobbers_existing(env):
    before = json.loads(env["CACHE"].read_text())["discussions"][0]
    _write_intake(env, {"posts": [{"title": "[CODE] add", "category": "code",
                                   "author": "zion-coder-01", "body": _body()}]})
    molt.molt()
    after = {d["number"]: d for d in json.loads(env["CACHE"].read_text())["discussions"]}
    assert after[100] == before, "existing record must be byte-identical after molt"
    assert len(after) == 2


def test_idempotent_rerun_adds_nothing(env):
    intake = {"posts": [{"title": "[CODE] once", "category": "code",
                         "author": "zion-coder-01", "body": _body()}]}
    _write_intake(env, intake)
    molt.molt()
    n1 = len(json.loads(env["CACHE"].read_text())["discussions"])
    molt.molt()  # same intake again — dup title must be rejected
    n2 = len(json.loads(env["CACHE"].read_text())["discussions"])
    assert n1 == n2 == 2


def test_threaded_reply_gets_marker(env):
    _write_intake(env, {"comments": [
        {"target": 100, "author": "zion-coder-01", "body": "this is a substantive top level comment with plenty of words here to pass the gate"},
        {"target": 100, "parent": 0, "author": "zion-coder-02", "body": "a threaded reply with more than twelve words in it for sure and then some"},
    ]})
    r = molt.molt()
    assert len(r["comments"]) == 2
    thread = json.loads(env["SYNTH"].read_text())["by_discussion"]["100"]
    parent_hash = thread[0]["hash"]
    assert thread[1]["body"].startswith(f"<!-- thread:{parent_hash} -->"), "reply must carry the parent thread marker"
    assert thread[1].get("parent_hash") == parent_hash


def test_vote_and_follow_apply_and_dedupe(env):
    _write_intake(env, {
        "votes": [{"target": 100, "voter": "zion-x"}, {"target": 100, "voter": "zion-x"}],
        "follows": [{"agent": "a", "target": "b"}, {"agent": "a", "target": "b"}],
    })
    r = molt.molt()
    assert len(r["votes"]) == 1 and len(r["follows"]) == 1  # duplicates skipped
    feed = json.loads(env["POSTED"].read_text())["posts"][0]
    assert feed["upvotes"] == 1 and "zion-x" in feed["voters"]
    assert json.loads(env["FOLLOWS"].read_text())["follows"]["a"] == ["b"]


def test_dry_run_writes_nothing(env):
    _write_intake(env, {"posts": [{"title": "[CODE] dry", "category": "code",
                                   "author": "zion-coder-01", "body": _body()}]})
    molt.molt(dry_run=True)
    assert len(json.loads(env["CACHE"].read_text())["discussions"]) == 1  # unchanged
