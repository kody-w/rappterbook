"""Tests for scripts/treaty.py — vLink-mediated federation treaty negotiation."""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def treaty_mod(tmp_state, monkeypatch):
    """Import treaty.py with STATE_DIR pinned to the test tmp dir."""
    monkeypatch.setenv("STATE_DIR", str(tmp_state))
    scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    if "treaty" in sys.modules:
        del sys.modules["treaty"]
    mod = importlib.import_module("treaty")
    importlib.reload(mod)
    # Force STATE_DIR refresh after reload
    mod.STATE_DIR = tmp_state
    return mod


PEER = "rappterzoo"


# ---------------------------------------------------------------------------
# Lifecycle tests
# ---------------------------------------------------------------------------


def test_init_creates_treaty_with_template(treaty_mod, tmp_state):
    treaty = treaty_mod.init_treaty(PEER, from_template=True)
    path = tmp_state / f"treaty_{PEER}.json"
    assert path.exists()
    assert treaty["_meta"]["protocol"] == "rappter-treaty"
    assert treaty["_meta"]["peer_id"] == PEER
    assert treaty["_meta"]["phase"] == treaty_mod.PHASE_NEGOTIATING
    # Template seeds at least 5 articles
    assert len(treaty["articles"]) >= 5
    for art in treaty["articles"].values():
        assert art["status"] == treaty_mod.STATUS_PROPOSED
        assert art["proposed_by"] == treaty_mod.LOCAL_PARTY
        assert art["content_hash"]
        assert len(art["history"]) == 1


def test_init_blank(treaty_mod):
    treaty = treaty_mod.init_treaty(PEER, from_template=False)
    assert treaty["articles"] == {}
    assert treaty["_meta"]["phase"] == treaty_mod.PHASE_DRAFT


def test_init_refuses_overwrite(treaty_mod):
    treaty_mod.init_treaty(PEER)
    with pytest.raises(RuntimeError, match="already exists"):
        treaty_mod.init_treaty(PEER)


def test_propose_new_article(treaty_mod):
    treaty_mod.init_treaty(PEER, from_template=False)
    treaty = treaty_mod.propose_article(PEER, "art-x", "hello world",
                                        title="X", rationale="why")
    assert "art-x" in treaty["articles"]
    art = treaty["articles"]["art-x"]
    assert art["text"] == "hello world"
    assert art["title"] == "X"
    assert art["version"] == 1
    assert art["status"] == treaty_mod.STATUS_PROPOSED
    assert art["history"][0]["rationale"] == "why"


def test_propose_duplicate_rejected(treaty_mod):
    treaty_mod.init_treaty(PEER, from_template=False)
    treaty_mod.propose_article(PEER, "art-x", "hi")
    with pytest.raises(RuntimeError, match="already exists"):
        treaty_mod.propose_article(PEER, "art-x", "hi again")


def test_counter_bumps_version_and_resets_acceptance(treaty_mod):
    treaty_mod.init_treaty(PEER, from_template=False)
    treaty_mod.propose_article(PEER, "art-x", "v1 text")
    # Peer accepts v1
    treaty_mod.accept_article(PEER, "art-x", by=PEER)
    # We counter
    treaty = treaty_mod.counter_article(PEER, "art-x", "v2 text",
                                        rationale="changed mind")
    art = treaty["articles"]["art-x"]
    assert art["version"] == 2
    assert art["text"] == "v2 text"
    assert art["status"] == treaty_mod.STATUS_COUNTERED
    assert art["accepted_by"] == []  # peer's accept was for v1, now invalid
    assert len(art["history"]) == 2


def test_counter_unknown_article_raises(treaty_mod):
    treaty_mod.init_treaty(PEER, from_template=False)
    with pytest.raises(RuntimeError, match="No such article"):
        treaty_mod.counter_article(PEER, "nope", "text")


def test_counter_with_identical_text_acts_as_accept(treaty_mod):
    treaty_mod.init_treaty(PEER, from_template=False)
    treaty_mod.propose_article(PEER, "art-x", "same text")
    # Peer "counters" with identical text → equivalent to acceptance
    treaty = treaty_mod.counter_article(PEER, "art-x", "same text", by=PEER)
    art = treaty["articles"]["art-x"]
    assert PEER in art["accepted_by"]
    assert art["version"] == 1  # no version bump


def test_accept_by_both_marks_accepted(treaty_mod):
    treaty_mod.init_treaty(PEER, from_template=False)
    treaty_mod.propose_article(PEER, "art-x", "text")
    treaty_mod.accept_article(PEER, "art-x", by=treaty_mod.LOCAL_PARTY)
    treaty = treaty_mod.accept_article(PEER, "art-x", by=PEER)
    art = treaty["articles"]["art-x"]
    assert art["status"] == treaty_mod.STATUS_ACCEPTED
    assert set(art["accepted_by"]) == {treaty_mod.LOCAL_PARTY, PEER}


def test_reject_clears_accept(treaty_mod):
    treaty_mod.init_treaty(PEER, from_template=False)
    treaty_mod.propose_article(PEER, "art-x", "text")
    treaty_mod.accept_article(PEER, "art-x")
    treaty = treaty_mod.reject_article(PEER, "art-x", reason="no")
    art = treaty["articles"]["art-x"]
    assert art["status"] == treaty_mod.STATUS_REJECTED
    assert treaty_mod.LOCAL_PARTY in art["rejected_by"]
    assert treaty_mod.LOCAL_PARTY not in art["accepted_by"]


# ---------------------------------------------------------------------------
# Signature & ratification tests
# ---------------------------------------------------------------------------


def _accept_all(treaty_mod, peer):
    """Accept every article by both parties. Returns the treaty dict."""
    treaty = treaty_mod.load_treaty(peer)
    for art_id in list(treaty["articles"].keys()):
        treaty_mod.accept_article(peer, art_id, by=treaty_mod.LOCAL_PARTY)
        treaty_mod.accept_article(peer, art_id, by=peer)
    return treaty_mod.load_treaty(peer)


def test_sign_requires_all_articles_accepted(treaty_mod):
    treaty_mod.init_treaty(PEER)  # template articles, all just proposed
    with pytest.raises(RuntimeError, match="not accepted by both"):
        treaty_mod.sign_treaty(PEER)


def test_sign_after_acceptance(treaty_mod):
    treaty_mod.init_treaty(PEER)
    _accept_all(treaty_mod, PEER)
    treaty = treaty_mod.sign_treaty(PEER)
    assert treaty_mod.LOCAL_PARTY in treaty["signatures"]
    assert treaty["_meta"]["phase"] == treaty_mod.PHASE_AWAITING_SIGNATURE


def test_ratify_requires_both_signatures(treaty_mod):
    treaty_mod.init_treaty(PEER)
    _accept_all(treaty_mod, PEER)
    treaty_mod.sign_treaty(PEER)
    with pytest.raises(RuntimeError, match="missing signatures"):
        treaty_mod.ratify_treaty(PEER)


def test_ratify_full_handshake(treaty_mod):
    treaty_mod.init_treaty(PEER)
    _accept_all(treaty_mod, PEER)
    treaty_mod.sign_treaty(PEER, by=treaty_mod.LOCAL_PARTY)
    treaty_mod.sign_treaty(PEER, by=PEER)
    treaty = treaty_mod.ratify_treaty(PEER)
    assert treaty["_meta"]["phase"] == treaty_mod.PHASE_RATIFIED
    assert treaty["_meta"]["ratified_at"]


def test_ratify_rejects_stale_signature(treaty_mod):
    """Mutating an accepted article after signing must invalidate the sig."""
    treaty_mod.init_treaty(PEER)
    _accept_all(treaty_mod, PEER)
    treaty_mod.sign_treaty(PEER, by=treaty_mod.LOCAL_PARTY)
    # Inject a stale peer signature against a different snapshot
    treaty = treaty_mod.load_treaty(PEER)
    treaty["signatures"][PEER] = {"signed_at": "2020-01-01T00:00:00Z",
                                  "snapshot_hash": "deadbeefdeadbeef"}
    treaty_mod.save_treaty(PEER, treaty)
    with pytest.raises(RuntimeError, match="stale snapshot"):
        treaty_mod.ratify_treaty(PEER)


def test_propose_after_signing_invalidates_signatures(treaty_mod):
    treaty_mod.init_treaty(PEER)
    _accept_all(treaty_mod, PEER)
    treaty_mod.sign_treaty(PEER)
    assert treaty_mod.load_treaty(PEER)["signatures"]
    treaty = treaty_mod.propose_article(PEER, "art-late", "added later")
    assert treaty["signatures"] == {}


# ---------------------------------------------------------------------------
# Echo / wire format tests
# ---------------------------------------------------------------------------


def test_build_echo_shape(treaty_mod):
    treaty_mod.init_treaty(PEER)
    treaty = treaty_mod.load_treaty(PEER)
    echo = treaty_mod.build_echo(treaty)
    assert echo["_meta"]["protocol"] == "rappter-treaty"
    assert echo["_meta"]["from_party"] == treaty_mod.LOCAL_PARTY
    assert echo["_meta"]["to_party"] == PEER
    assert echo["_meta"]["snapshot_hash"]
    assert isinstance(echo["articles"], list)
    assert len(echo["articles"]) == len(treaty["articles"])
    # Articles are sorted by id for deterministic output
    ids = [a["id"] for a in echo["articles"]]
    assert ids == sorted(ids)


def test_write_echo_creates_wire_file(treaty_mod, tmp_state):
    treaty_mod.init_treaty(PEER)
    path = treaty_mod.write_echo(PEER)
    assert path.exists()
    assert path.name == f"vlink_treaty_{PEER}.json"
    data = json.loads(path.read_text())
    assert data["_meta"]["protocol"] == "rappter-treaty"


# ---------------------------------------------------------------------------
# Sync (peer counter-proposal merge) tests
# ---------------------------------------------------------------------------


def test_merge_peer_accept_marks_accepted(treaty_mod):
    treaty_mod.init_treaty(PEER, from_template=False)
    treaty_mod.propose_article(PEER, "art-x", "exact text")
    local = treaty_mod.load_treaty(PEER)
    art_hash = local["articles"]["art-x"]["content_hash"]

    peer_echo = {
        "_meta": {"protocol": "rappter-treaty", "version": 1,
                  "from_party": PEER, "to_party": treaty_mod.LOCAL_PARTY,
                  "phase": "negotiating", "round": 1, "snapshot_hash": "abc"},
        "articles": [{
            "id": "art-x", "title": "art-x", "text": "exact text",
            "version": 1, "status": "accepted",
            "proposed_by": treaty_mod.LOCAL_PARTY, "current_party": PEER,
            "accepted_by": [PEER], "rejected_by": [],
            "content_hash": art_hash,
        }],
        "signatures": {},
    }
    treaty_mod.accept_article(PEER, "art-x", by=treaty_mod.LOCAL_PARTY)
    result = treaty_mod.merge_peer_echo(PEER, peer_echo)
    art = result["treaty"]["articles"]["art-x"]
    assert PEER in art["accepted_by"]
    assert art["status"] == treaty_mod.STATUS_ACCEPTED


def test_merge_peer_counter_replaces_text(treaty_mod):
    treaty_mod.init_treaty(PEER, from_template=False)
    treaty_mod.propose_article(PEER, "art-x", "v1 text")

    peer_echo = {
        "_meta": {"protocol": "rappter-treaty", "version": 1,
                  "from_party": PEER, "to_party": treaty_mod.LOCAL_PARTY,
                  "phase": "negotiating", "round": 1, "snapshot_hash": "xx"},
        "articles": [{
            "id": "art-x", "title": "art-x", "text": "peer's v2 text",
            "version": 2, "status": "countered",
            "proposed_by": treaty_mod.LOCAL_PARTY, "current_party": PEER,
            "accepted_by": [PEER], "rejected_by": [],
            "content_hash": "",
        }],
        "signatures": {},
    }
    result = treaty_mod.merge_peer_echo(PEER, peer_echo)
    art = result["treaty"]["articles"]["art-x"]
    assert art["text"] == "peer's v2 text"
    assert art["status"] == treaty_mod.STATUS_COUNTERED
    assert art["version"] == 2
    assert PEER in art["accepted_by"]
    assert treaty_mod.LOCAL_PARTY not in art["accepted_by"]


def test_merge_peer_imports_new_article(treaty_mod):
    treaty_mod.init_treaty(PEER, from_template=False)
    peer_echo = {
        "_meta": {"protocol": "rappter-treaty", "version": 1,
                  "from_party": PEER, "to_party": treaty_mod.LOCAL_PARTY,
                  "phase": "negotiating", "round": 1, "snapshot_hash": "xx"},
        "articles": [{
            "id": "art-peer-new", "title": "Peer Article",
            "text": "peer-introduced clause", "version": 1,
            "status": "proposed", "proposed_by": PEER,
            "current_party": PEER, "accepted_by": [PEER],
            "rejected_by": [], "content_hash": "",
        }],
        "signatures": {},
    }
    result = treaty_mod.merge_peer_echo(PEER, peer_echo)
    assert "art-peer-new" in result["treaty"]["articles"]
    art = result["treaty"]["articles"]["art-peer-new"]
    assert art["proposed_by"] == PEER
    assert PEER in art["accepted_by"]


def test_merge_peer_signature_only_imported_when_snapshot_matches(treaty_mod):
    treaty_mod.init_treaty(PEER, from_template=False)
    treaty_mod.propose_article(PEER, "art-x", "shared text")
    treaty_mod.accept_article(PEER, "art-x")
    local_snap = treaty_mod.snapshot_hash(treaty_mod.load_treaty(PEER))

    # Peer signature with WRONG snapshot — should be ignored
    bad_echo = {
        "_meta": {"protocol": "rappter-treaty", "version": 1,
                  "from_party": PEER, "to_party": treaty_mod.LOCAL_PARTY,
                  "phase": "awaiting_signature", "round": 1,
                  "snapshot_hash": "wrong"},
        "articles": [],
        "signatures": {PEER: {"signed_at": "2026-01-01T00:00:00Z",
                              "snapshot_hash": "wrong-snap"}},
    }
    treaty_mod.merge_peer_echo(PEER, bad_echo)
    assert PEER not in treaty_mod.load_treaty(PEER)["signatures"]

    # Peer signature with CORRECT snapshot — should be imported
    good_echo = {
        "_meta": {"protocol": "rappter-treaty", "version": 1,
                  "from_party": PEER, "to_party": treaty_mod.LOCAL_PARTY,
                  "phase": "awaiting_signature", "round": 2,
                  "snapshot_hash": local_snap},
        "articles": [],
        "signatures": {PEER: {"signed_at": "2026-01-01T00:00:00Z",
                              "snapshot_hash": local_snap}},
    }
    treaty_mod.merge_peer_echo(PEER, good_echo)
    assert PEER in treaty_mod.load_treaty(PEER)["signatures"]


def test_sync_writes_echo_when_peer_unreachable(treaty_mod, tmp_state):
    treaty_mod.init_treaty(PEER)
    with patch.object(treaty_mod, "fetch_peer_echo", return_value=None):
        result = treaty_mod.sync_peer(PEER)
    assert result["fetched"] is False
    assert result["echo_written"] is True
    assert (tmp_state / f"vlink_treaty_{PEER}.json").exists()


def test_sync_full_round_trip(treaty_mod, tmp_state):
    """Simulate a complete negotiation handshake using mocked peer."""
    treaty_mod.init_treaty(PEER, from_template=False)
    treaty_mod.propose_article(PEER, "art-1", "trade tools")
    treaty_mod.accept_article(PEER, "art-1", by=treaty_mod.LOCAL_PARTY)
    art_hash = treaty_mod.load_treaty(PEER)["articles"]["art-1"]["content_hash"]

    peer_response = {
        "_meta": {"protocol": "rappter-treaty", "version": 1,
                  "from_party": PEER, "to_party": treaty_mod.LOCAL_PARTY,
                  "phase": "awaiting_signature", "round": 1,
                  "snapshot_hash": "_"},
        "articles": [{
            "id": "art-1", "title": "art-1", "text": "trade tools",
            "version": 1, "status": "accepted",
            "proposed_by": treaty_mod.LOCAL_PARTY, "current_party": PEER,
            "accepted_by": [PEER], "rejected_by": [],
            "content_hash": art_hash,
        }],
        "signatures": {},
    }
    with patch.object(treaty_mod, "fetch_peer_echo", return_value=peer_response):
        result = treaty_mod.sync_peer(PEER)
    assert result["fetched"] is True
    assert result["changes"] >= 1
    treaty = treaty_mod.load_treaty(PEER)
    assert treaty["articles"]["art-1"]["status"] == treaty_mod.STATUS_ACCEPTED
    assert treaty["_meta"]["phase"] == treaty_mod.PHASE_AWAITING_SIGNATURE


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------


def test_cli_init_and_status(treaty_mod, capsys):
    rc = treaty_mod.main(["init", PEER])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Treaty initialized" in out
    rc = treaty_mod.main(["status", PEER])
    assert rc == 0
    out = capsys.readouterr().out
    assert PEER in out
    assert "Articles:" in out


def test_cli_propose_then_accept_then_echo(treaty_mod, capsys, tmp_state):
    treaty_mod.main(["init", PEER, "--blank"])
    capsys.readouterr()
    assert treaty_mod.main(["propose", PEER, "art-x", "hello"]) == 0
    assert treaty_mod.main(["accept", PEER, "art-x"]) == 0
    assert treaty_mod.main(["echo", PEER]) == 0
    assert (tmp_state / f"vlink_treaty_{PEER}.json").exists()


def test_cli_unknown_article_returns_error(treaty_mod, capsys):
    treaty_mod.main(["init", PEER, "--blank"])
    capsys.readouterr()
    rc = treaty_mod.main(["accept", PEER, "art-missing"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "No such article" in err
