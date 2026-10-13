"""Contracts for the fail-closed Rappterbook -> Agentic Knowledge Exchange bridge."""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
from email.message import Message
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import ake_bridge as b  # noqa: E402

BASE = "https://ake.example"
AGENT = "rapptertwo"
SOURCE = "https://github.com/kody-w/rappterbook/discussions/123"
TOPIC = "sqlite3.OperationalError: database is locked"
CONTENT = "WHEN: two writers.\nFIX: PRAGMA journal_mode=WAL; timeout=30."


def post_file(tmp_path, **over) -> str:
    intent = {
        "environment": "python-3.11/macos-15",
        "topic": TOPIC,
        "content": CONTENT,
        "tags": ["sqlite", "python"],
        "source": SOURCE,
    }
    intent.update(over)
    path = tmp_path / "post.json"
    path.write_text(json.dumps(intent))
    return str(path)


def verify_file(tmp_path, **over) -> str:
    intent = {"operation": "verify", "post_id": "845a15fe", "passed": True, "notes": "ran it"}
    intent.update(over)
    path = tmp_path / "verify.json"
    path.write_text(json.dumps(intent))
    return str(path)


def env_for(tmp_path) -> dict:
    return {"AKE_BASE_URL": BASE, "AKE_AGENT_ID": AGENT, "AKE_RECEIPTS": str(tmp_path / "ledger" / "receipts.jsonl")}


def remote_post(**over) -> dict:
    post = {
        "post_id": "845a15fe", "agent_id": "Seed-Agent-01", "environment": "python-3.11",
        "topic": "CUDA out of memory", "content": "torch.cuda.empty_cache()", "tags": ["cuda"],
        "verifications_pass": 0, "verifications_fail": 0, "score": 0.0,
        "created_at": "2026-10-12T23:39:49+00:00",
    }
    post.update(over)
    return post


def echo_of_ours(post_id="new1", **over) -> dict:
    """What a correct AKE echoes back for our own post."""
    post = remote_post(post_id=post_id, agent_id=AGENT, topic=TOPIC, content=CONTENT + "\n\nSource: " + SOURCE,
                       environment="python-3.11/macos-15", tags=["sqlite", "python"])
    post.update(over)
    return post


class FakeResponse:
    def __init__(self, payload, status=200, url=None, raw=None):
        self._raw = raw if raw is not None else json.dumps(payload).encode()
        self.status = status
        self._url = url or BASE + "/x"
        self._buf = io.BytesIO(self._raw)

    def geturl(self):
        return self._url

    def read(self, n=-1):
        return self._buf.read(n)

    def close(self):
        pass


def http_error(status, body=None):
    raw = json.dumps(body if body is not None else {"detail": "nope"}).encode()
    return urllib.error.HTTPError(BASE + "/x", status, "err", Message(), io.BytesIO(raw))


class FakeAke:
    """Scripted responses keyed by (method, path); records every call with its query.

    ``search`` models GET /posts/search: a callable ``(q, offset) -> list`` of
    posts for that page, so query filtering and pagination are real in tests.
    Any other call must be scripted or the test fails.
    """

    def __init__(self, script=None, search=None):
        self.script = {k: list(v) for k, v in (script or {}).items()}
        self.search = search
        self.calls = []

    def __call__(self, request, timeout):
        url = request.full_url
        path = url[len(BASE):].split("?", 1)[0]
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        params = {k: v[0] for k, v in query.items()}
        self.calls.append((request.get_method(), path, request.data, params))
        queue = self.script.get((request.get_method(), path))
        if queue:
            item = queue.pop(0)
        elif path == "/posts/search" and self.search is not None and request.get_method() == "GET":
            assert set(params) >= {"q", "limit", "offset"}, params
            item = FakeResponse(self.search(params["q"], int(params["offset"]))[:int(params["limit"])])
        else:
            raise AssertionError(f"unexpected call {request.get_method()} {path} {params}")
        if isinstance(item, Exception):
            raise item
        return item

    def posts(self):
        return [c for c in self.calls if c[0] == "POST"]

    def searches(self):
        return [c[3] for c in self.calls if c[1] == "/posts/search"]


def no_matches(q, offset):
    return []


def ledger_lines(tmp_path):
    path = Path(env_for(tmp_path)["AKE_RECEIPTS"])
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# intent validation
# ---------------------------------------------------------------------------

def test_idempotency_key_covers_destination_and_the_exact_wire_payload(tmp_path):
    raw = json.loads(Path(post_file(tmp_path)).read_text())
    base = b.build_post_intent(raw, AGENT, BASE)
    assert b.KEY_RE.fullmatch(base["key"])
    assert b.build_post_intent(raw, AGENT, BASE)["key"] == base["key"]
    for change in ({"environment": "python-3.9"}, {"tags": ["sqlite"]}, {"topic": TOPIC + "!"},
                   {"content": CONTENT + " v2"}, {"source": SOURCE + "4"}):
        assert b.build_post_intent(dict(raw, **change), AGENT, BASE)["key"] != base["key"], change
    assert b.build_post_intent(raw, AGENT, "https://other.example")["key"] != base["key"]
    assert b.build_post_intent(raw, "someone", BASE)["key"] != base["key"]
    verify = {"operation": "verify", "post_id": "p1", "passed": True}
    assert b.build_verify_intent(verify, AGENT, BASE)["key"] != b.build_verify_intent(dict(verify, post_id="p2"), AGENT, BASE)["key"]
    assert b.build_verify_intent(verify, AGENT, BASE)["key"] != b.build_verify_intent(verify, AGENT, "https://o.example")["key"]
    # fixed vector so both repos agree
    expected = hashlib.sha256(b'{"body":{"a":1},"destination":"https://ake.example","operation":"post"}').hexdigest()[:24]
    assert b.idempotency_key("post", "https://ake.example", {"a": 1}) == "rb-ake-" + expected


@pytest.mark.parametrize("url", [
    "http://github.com/kody-w/rappterbook/discussions/123",
    "HTTPS://github.com/kody-w/rappterbook/discussions/123",
    "https://GitHub.com/kody-w/rappterbook/discussions/123",
    " https://github.com/kody-w/rappterbook/discussions/123",
    "https://github.com/kody-w/rappterbook/discussions/123 ",
    "https://github.com/kody-w/rappterbook/discussions/1\t23",
    "https://github.com/kody-w/rappterbook/discussions/123?",
    "https://github.com/kody-w/rappterbook/discussions/123#",
    "https://github.com/kody-w/rappterbook/discussions/123?x=1",
    "https://github.com/kody-w/rappterbook/discussions/123/",
    "https://github.com/kody-w/rappterbook/discussions/0123",
    "https://github.com/kody-w/rappterbook/discussions/%31%32%33",
    "https://github.com:443/kody-w/rappterbook/discussions/123",
    "https://github.com./kody-w/rappterbook/discussions/123",
    "https://github.com/kody-w/rappterbook/issues/123",
    "https://github.com/kody-w/other/../rappterbook/discussions/123",
    "https://user@github.com/kody-w/rappterbook/discussions/123",
    "https://github.com.evil/kody-w/rappterbook/discussions/123",
    "https://github.com/kody-w/rappterbook/discussions/",
    "https://github.com/kody-w/rappterbook/discussions/12a",
    "https://github.com/kody-w/rappterbook/discussions/١٢٣",
    "https://[::1/kody-w/rappterbook/discussions/123",
    "https://github.com/kody-w/rappterbook/discussions/123\n",
    123,
])
def test_source_must_be_spelled_exactly_canonically(url):
    with pytest.raises(b.AkePolicyError):
        b.canonical_source(url)


def test_source_canonical_form_passes_through_unchanged():
    assert b.canonical_source(SOURCE) == SOURCE
    assert b.canonical_source(b.SOURCE_PREFIX + "999999999") == b.SOURCE_PREFIX + "999999999"


def test_post_intent_appends_the_source_line_and_never_truncates(tmp_path):
    raw = json.loads(Path(post_file(tmp_path)).read_text())
    intent = b.build_post_intent(raw, AGENT, BASE)
    assert intent["body"]["content"].endswith("\n\nSource: " + SOURCE)
    assert intent["body"]["agent_id"] == AGENT
    assert intent["body"]["tags"] == ["sqlite", "python"]
    footer = len("\n\nSource: " + SOURCE)
    fits = b.build_post_intent(dict(raw, content="x" * (b.MAX_CONTENT - footer)), AGENT, BASE)
    assert len(fits["body"]["content"]) == b.MAX_CONTENT
    with pytest.raises(b.AkePolicyError, match="over by 1"):
        b.build_post_intent(dict(raw, content="x" * (b.MAX_CONTENT - footer + 1)), AGENT, BASE)


@pytest.mark.parametrize("over", [
    {"agent_id": "someone-else"},            # identity comes from the environment only
    {"extra": 1},
    {"tags": ["intro"]},
    {"tags": ["Sqlite"]},
    {"tags": ["a"] * 2},
    {"tags": [f"t{i}" for i in range(11)]},
    {"tags": "sqlite"},
    {"topic": ""},
    {"topic": "x" * 201},
    {"topic": "a\x00b"},
    {"topic": "a\x85b"},
    {"environment": None},
    {"content": "ok\x1b[31m"},
    {"source": "https://example.com/x"},
    {"operation": "verify"},
])
def test_post_intent_rejects_bad_fields(tmp_path, over):
    raw = json.loads(Path(post_file(tmp_path)).read_text())
    raw.update(over)
    with pytest.raises(b.AkePolicyError):
        b.build_post_intent(raw, AGENT, BASE)


@pytest.mark.parametrize("over", [
    {"passed": 1}, {"passed": "true"}, {"passed": None},
    {"passed": False, "notes": ""}, {"passed": False, "notes": None},
    {"post_id": "../x"}, {"post_id": ""}, {"post_id": 7},
    {"notes": "n" * 1001}, {"agent_id": "x"}, {"operation": "post"},
])
def test_verify_intent_rejects_bad_fields(over):
    raw = {"operation": "verify", "post_id": "845a15fe", "passed": True, "notes": "ok"}
    raw.update(over)
    with pytest.raises(b.AkePolicyError):
        b.build_verify_intent(raw, AGENT, BASE)


def test_verify_intent_body_is_minimal_and_keyed_on_content():
    intent = b.build_verify_intent({"operation": "verify", "post_id": "p1", "passed": True}, AGENT, BASE)
    assert intent["body"] == {"agent_id": AGENT, "passed": True}
    failed = b.build_verify_intent({"operation": "verify", "post_id": "p1", "passed": False, "notes": "broke"}, AGENT, BASE)
    assert failed["body"]["notes"] == "broke" and failed["key"] != intent["key"]


@pytest.mark.parametrize("raw", [
    "http://ake.example", "https://ake.example/api", "https://u:p@ake.example", "https://ake.example?x=1",
    "https://ake.example#f", "ake.example", "https://[::1", "", "https://ake.example:abc", "https://ake.example:99999",
])
def test_base_url_must_be_a_bare_https_origin(raw):
    with pytest.raises(b.AkeConfigError):
        b.validate_base_url(raw) if raw else b.base_url_from_env({"AKE_BASE_URL": raw})
    assert b.validate_base_url("https://AKE.example:8443/") == "https://ake.example:8443"


def test_strict_json_rejects_nan_overflow_duplicates_and_depth():
    for bad in (b'{"a": NaN}', b'{"a": Infinity}', b'{"a": 1e309}', b'{"a": -1e999}', b'{"a": 1, "a": 2}'):
        with pytest.raises(ValueError):
            b.loads_strict(bad)
    # the depth cap is the bridge's own, identical on every interpreter (3.12+ parses
    # thousands of levels without a RecursionError), and ignores brackets inside strings
    at_cap = b"[" * b.MAX_JSON_DEPTH + b"0" + b"]" * b.MAX_JSON_DEPTH
    assert b.loads_strict(at_cap) is not None
    with pytest.raises(ValueError, match="deeply"):
        b.loads_strict(b"[" + at_cap + b"]")
    with pytest.raises(ValueError, match="deeply"):
        b.loads_strict(b"[" * 1100 + b"]" * 1100)
    assert b.loads_strict(b'{"notes": "' + b"[" * 60 + b'"}') == {"notes": "[" * 60}
    # huge ints are malformed, not numbers to overflow on later
    with pytest.raises(ValueError, match="digits"):
        b.loads_strict(b'{"score": ' + b"9" * 400 + b"}")
    assert b.loads_strict(b'{"a": [1, 2.5]}') == {"a": [1, 2.5]}
    assert b.MAX_JSON_DEPTH == 32 and b.MAX_INT_DIGITS == 100


# ---------------------------------------------------------------------------
# dry-run and reads
# ---------------------------------------------------------------------------

def test_dry_run_prints_exact_bytes_and_touches_neither_network_nor_ledger(tmp_path):
    env = env_for(tmp_path)

    def no_network(*a, **k):
        raise AssertionError("dry-run must not call the network")

    out = b.run(["dry-run", "--input", post_file(tmp_path)], environ=env, open_url=no_network)
    assert out["sent"] is False and out["path"] == "/posts" and out["key"].startswith("rb-ake-")
    assert out["destination"] == BASE
    assert out["content_length"] == len(out["body"]["content"])
    assert out["body_bytes"] == len(json.dumps(out["body"], separators=(",", ":"), ensure_ascii=False).encode())
    assert not (tmp_path / "ledger").exists()
    out2 = b.run(["dry-run", "--input", verify_file(tmp_path)], environ=env, open_url=no_network)
    assert out2["path"] == "/posts/845a15fe/verify"
    # the key printed offline is the key the write will use
    fake = FakeAke({("POST", "/posts"): [FakeResponse(echo_of_ours(), status=201)]}, search=no_matches)
    assert b.run(["post", "--input", post_file(tmp_path)], environ=env, open_url=fake)["key"] == out["key"]
    for missing in ("AKE_BASE_URL", "AKE_AGENT_ID"):
        partial = dict(env)
        del partial[missing]
        with pytest.raises(b.AkeConfigError):
            b.run(["dry-run", "--input", post_file(tmp_path)], environ=partial, open_url=no_network)


def test_search_output_is_allowlisted_and_control_stripped(tmp_path):
    fake = FakeAke({("GET", "/posts/search"): [FakeResponse([
        remote_post(topic="hi\x1b[31m there‮⁠", content="x" * 900, tags=["a", {"b": 1}], score="9", extra="dropped"),
        remote_post(post_id="big", score=1.5, verifications_pass=3),
    ])]})
    out = b.run(["search", "--q", "sqlite", "--limit", "5"], environ=env_for(tmp_path), open_url=fake)
    assert out["untrusted"] is True and out["count"] == 2 and len(out["results"]) == 2
    row = out["results"][0]
    assert row["topic"] == "hi[31m there" and row["content"].endswith("...[truncated]")
    assert row["score"] is None and "extra" not in row
    assert out["results"][1]["score"] == 1.5 and out["results"][1]["verifications_pass"] == 3
    assert fake.calls[0][3] == {"q": "sqlite", "limit": "5", "offset": "0"}
    assert not (tmp_path / "ledger").exists()
    with pytest.raises(b.AkePolicyError):
        b.run(["search", "--limit", "51"], environ=env_for(tmp_path), open_url=fake)
    # a non-object item is invalid_shape (the rule _search_pages applies), never silently dropped
    junk = FakeAke({("GET", "/posts/search"): [FakeResponse([1, "x", remote_post()])]})
    with pytest.raises(b.AkeApiError, match="non-object") as info:
        b.run(["search", "--q", "sqlite"], environ=env_for(tmp_path), open_url=junk)
    assert info.value.code == "invalid_shape"


def test_get_retries_once_on_5xx_but_not_on_4xx_and_binds_the_id(tmp_path):
    fake = FakeAke({("GET", "/posts/845a15fe"): [http_error(503), FakeResponse(remote_post())]})
    out = b.run(["get", "--post-id", "845a15fe"], environ=env_for(tmp_path), open_url=fake)
    assert out["post"]["post_id"] == "845a15fe" and len(fake.calls) == 2
    fake404 = FakeAke({("GET", "/posts/zzz"): [http_error(404)]})
    with pytest.raises(b.AkeApiError) as info:
        b.run(["get", "--post-id", "zzz"], environ=env_for(tmp_path), open_url=fake404)
    assert info.value.status == 404 and info.value.exit_code == 1 and len(fake404.calls) == 1
    fake_twice = FakeAke({("GET", "/posts/a"): [http_error(502), http_error(502)]})
    with pytest.raises(b.AkeApiError) as info2:
        b.run(["get", "--post-id", "a"], environ=env_for(tmp_path), open_url=fake_twice)
    assert info2.value.exit_code == 2 and len(fake_twice.calls) == 2
    wrong = FakeAke({("GET", "/posts/a"): [FakeResponse(remote_post(post_id="b"))]})
    with pytest.raises(b.AkeApiError, match="request about 'a'"):
        b.run(["get", "--post-id", "a"], environ=env_for(tmp_path), open_url=wrong)


def test_redirects_cross_origin_oversize_and_odd_paths_are_refused(tmp_path):
    with pytest.raises(b.AkeSecurityError):
        b.RejectRedirects().redirect_request(None, None, 302, "Found", {}, "https://ake.example/posts")
    other = FakeAke({("GET", "/posts/p"): [FakeResponse(remote_post(post_id="p"), url="https://evil.example/posts/p")]})
    with pytest.raises(b.AkeSecurityError, match="different origin"):
        b.run(["get", "--post-id", "p"], environ=env_for(tmp_path), open_url=other)
    big = FakeAke({("GET", "/posts/p"): [FakeResponse(None, raw=b"[" + b"1," * (b.MAX_RESPONSE_BYTES // 2) + b"1]")]})
    with pytest.raises(b.AkeSecurityError, match="1 MiB"):
        b.run(["get", "--post-id", "p"], environ=env_for(tmp_path), open_url=big)
    for path in ("/posts/../admin", "/posts?x=1", "/posts//", "/admin", "/posts/a/b", "/posts/a/verify/c"):
        with pytest.raises(b.AkeSecurityError):
            b.api_request(BASE, "GET", path)


def test_oversized_4xx_body_keeps_its_definitive_status():
    huge = urllib.error.HTTPError(BASE + "/x", 429, "err", Message(), io.BytesIO(b"x" * (b.MAX_RESPONSE_BYTES + 5)))

    def raise_huge(request, timeout):
        raise huge

    with pytest.raises(b.AkeApiError) as info:
        b.api_request(BASE, "GET", "/posts/p", open_url=raise_huge)
    assert info.value.status == 429 and info.value.definitive and "body not read" in str(info.value)


# ---------------------------------------------------------------------------
# post: response-first, reserve, send once, record
# ---------------------------------------------------------------------------

def test_post_searches_topic_and_source_and_refuses_duplicates_without_reserving(tmp_path):
    env = env_for(tmp_path)
    same_topic = remote_post(post_id="dup1", topic="SQLITE3.OperationalError:  database is locked")

    def by_topic(q, offset):
        return [same_topic] if q == TOPIC else []

    fake = FakeAke(search=by_topic)
    with pytest.raises(b.AkePolicyError, match="verify it instead"):
        b.run(["post", "--input", post_file(tmp_path)], environ=env, open_url=fake)
    assert fake.posts() == [] and ledger_lines(tmp_path) == []
    assert fake.searches()[0]["q"] == TOPIC

    def by_source(q, offset):
        return [remote_post(post_id="dup2", topic="different", content="other fix\n\nSource: " + SOURCE)] if q == SOURCE else []

    fake2 = FakeAke(search=by_source)
    with pytest.raises(b.AkePolicyError, match="dup2"):
        b.run(["post", "--input", post_file(tmp_path)], environ=env, open_url=fake2)
    assert [s["q"] for s in fake2.searches()] == [TOPIC, SOURCE]
    assert fake2.posts() == [] and ledger_lines(tmp_path) == []
    # a longer discussion number is a different discussion, not a substring match
    neighbour = remote_post(post_id="n", topic="other", content="fix\n\nSource: " + SOURCE + "4")
    fake3 = FakeAke({("POST", "/posts"): [FakeResponse(echo_of_ours(), status=201)]}, search=lambda q, o: [neighbour])
    assert b.run(["post", "--input", post_file(tmp_path)], environ=env, open_url=fake3)["status"] == "posted"


def test_prose_mention_of_the_discussion_url_is_not_a_citation(tmp_path):
    """Only the bridge's own `Source: <url>` trailer marks a post as covering a discussion.

    Otherwise one post listing hundreds of discussion URLs (AKE has no auth) would
    block every future cross-post, and the refusal would point agents at it.
    """
    env = env_for(tmp_path)
    mention = remote_post(post_id="poison", topic="index of fixes",
                          content="see also " + SOURCE + " and " + SOURCE + "\n\nSource: " + SOURCE + "9")
    fake = FakeAke({("POST", "/posts"): [FakeResponse(echo_of_ours(), status=201)]}, search=lambda q, o: [mention])
    assert b.run(["post", "--input", post_file(tmp_path)], environ=env, open_url=fake)["status"] == "posted"
    # the trailer must be the post's last line, exactly: trailing text, a different prefix, or a
    # trailer-shaped line higher up in the body (a post about /1239 quoting /123) is not it
    for content in ("Source: " + SOURCE + " (mirror)", "My Source: " + SOURCE, "source: " + SOURCE,
                    "Source: " + SOURCE + "\n\nmore prose", "Source: " + SOURCE + "\n\nSource: " + SOURCE + "9"):
        assert not b.cites_source(content, SOURCE), content
    assert b.cites_source("x\n\nSource: " + SOURCE + "  \n", SOURCE)
    assert b.cites_source("x\r\n\r\nSource: " + SOURCE + "\r\n", SOURCE)
    assert not b.cites_source(None, SOURCE)
    quoting = remote_post(post_id="quoting", topic="other", content="Source: " + SOURCE + "\n\nSource: " + SOURCE + "9")
    fake2 = FakeAke({("POST", "/posts"): [FakeResponse(echo_of_ours(post_id="new2"), status=201)]}, search=lambda q, o: [quoting])
    fresh = dict(env, AKE_RECEIPTS=str(tmp_path / "fresh.jsonl"))
    assert b.run(["post", "--input", post_file(tmp_path)], environ=fresh, open_url=fake2)["status"] == "posted"
    # and the bridge never writes a trailer-shaped line into a body of its own
    with pytest.raises(b.AkePolicyError, match="must not contain a `Source:"):
        b.build_intent(json.loads(Path(post_file(tmp_path, content="fix\n  Source: " + SOURCE + "9\nmore")).read_text()), AGENT, BASE)


def test_post_preflight_paginates_and_fails_closed_when_it_cannot_prove_uniqueness(tmp_path):
    env = env_for(tmp_path)
    unrelated = [remote_post(post_id=f"u{i}", topic=f"other {i}") for i in range(b.MAX_SEARCH_LIMIT)]
    dup = remote_post(post_id="page2", topic=TOPIC.upper())

    def paged(q, offset):
        if q != TOPIC:
            return []
        return unrelated if offset == 0 else [dup]

    fake = FakeAke(search=paged)
    with pytest.raises(b.AkePolicyError, match="page2"):
        b.run(["post", "--input", post_file(tmp_path)], environ=env, open_url=fake)
    assert [s["offset"] for s in fake.searches()] == ["0", "50"] and fake.posts() == []
    endless = FakeAke(search=lambda q, o: unrelated)
    with pytest.raises(b.AkePolicyError, match="cannot prove"):
        b.run(["post", "--input", post_file(tmp_path)], environ=env, open_url=endless)
    assert len(endless.searches()) == b.MAX_SEARCH_PAGES and endless.posts() == []
    assert ledger_lines(tmp_path) == []


def test_post_refuses_when_search_fails_or_returns_junk(tmp_path):
    env = env_for(tmp_path)
    down = FakeAke({("GET", "/posts/search"): [http_error(503), http_error(503)]})
    with pytest.raises(b.AkeApiError) as info:
        b.run(["post", "--input", post_file(tmp_path)], environ=env, open_url=down)
    assert info.value.exit_code == 2 and down.posts() == [] and ledger_lines(tmp_path) == []
    for junk in ({"results": []}, [{}], ["x"], [remote_post(post_id=5)], [remote_post(topic=None)]):
        weird = FakeAke({("GET", "/posts/search"): [FakeResponse(junk)]})
        with pytest.raises(b.AkeApiError):
            b.run(["post", "--input", post_file(tmp_path)], environ=env, open_url=weird)
        assert weird.posts() == []
    assert ledger_lines(tmp_path) == []


def test_post_happy_path_then_idempotent_without_network(tmp_path):
    env = env_for(tmp_path)
    fake = FakeAke({("POST", "/posts"): [FakeResponse(echo_of_ours(), status=201)]}, search=no_matches)
    out = b.run(["post", "--input", post_file(tmp_path)], environ=env, open_url=fake)
    assert out["status"] == "posted" and out["post_id"] == "new1" and out["sent"] is True
    sent = json.loads(fake.posts()[0][2].decode("utf-8"))
    assert sent == {"agent_id": AGENT, "environment": "python-3.11/macos-15", "topic": TOPIC,
                    "content": CONTENT + "\n\nSource: " + SOURCE, "tags": ["sqlite", "python"]}
    lines = ledger_lines(tmp_path)
    assert [l["status"] for l in lines] == ["pending", "posted"]
    assert lines[1]["post_id"] == "new1" and lines[1]["http_status"] == 201
    assert set(lines[1]) <= set(b.RECEIPT_FIELDS) and "content" not in lines[1]
    again_fake = FakeAke()
    again = b.run(["post", "--input", post_file(tmp_path)], environ=env, open_url=again_fake)
    assert again["idempotent"] is True and again["status"] == "posted" and again["sent"] is False
    assert again_fake.calls == [] and len(ledger_lines(tmp_path)) == 2
    receipts = b.run(["receipts", "--key", out["key"]], environ=env)
    assert len(receipts["receipts"]) == 2


def test_one_discussion_is_cross_posted_once_even_with_edited_content(tmp_path):
    env = env_for(tmp_path)
    fake = FakeAke({("POST", "/posts"): [FakeResponse(echo_of_ours(), status=201)]}, search=no_matches)
    first = b.run(["post", "--input", post_file(tmp_path)], environ=env, open_url=fake)
    edited = FakeAke(search=no_matches)
    with pytest.raises(b.AkePolicyError, match="cross-posted once") as info:
        b.run(["post", "--input", post_file(tmp_path, content=CONTENT + " (corrected)")], environ=env, open_url=edited)
    assert "new1" in str(info.value) and first["key"] in str(info.value)
    assert edited.calls == [] and len(ledger_lines(tmp_path)) == 2
    # a different discussion is fine
    other_echo = echo_of_ours(post_id="new2", content=CONTENT + "\n\nSource: " + SOURCE + "4")
    other = FakeAke({("POST", "/posts"): [FakeResponse(other_echo, status=201)]}, search=no_matches)
    assert b.run(["post", "--input", post_file(tmp_path, source=SOURCE + "4")], environ=env, open_url=other)["post_id"] == "new2"


def test_post_5xx_is_ambiguous_never_retried_and_blocked_until_resolved(tmp_path):
    env = env_for(tmp_path)
    fake = FakeAke({("POST", "/posts"): [http_error(504)]}, search=no_matches)
    with pytest.raises(b.AkeAmbiguousError, match="resolve --key"):
        b.run(["post", "--input", post_file(tmp_path)], environ=env, open_url=fake)
    assert len(fake.posts()) == 1
    lines = ledger_lines(tmp_path)
    assert [l["status"] for l in lines] == ["pending", "ambiguous"]
    assert lines[1]["http_status"] == 504 and lines[1]["note"] == "http_5xx"
    key = lines[0]["key"]
    never = FakeAke()
    blocked = b.run(["post", "--input", post_file(tmp_path)], environ=env, open_url=never)
    assert blocked["idempotent"] is True and blocked["status"] == "ambiguous" and never.calls == []
    with pytest.raises(b.AkePolicyError, match="post-id"):
        b.run(["resolve", "--key", key, "--as", "posted"], environ=env)
    with pytest.raises(b.AkePolicyError):
        b.run(["resolve", "--key", key, "--as", "verified", "--post-id", "x"], environ=env)
    b.run(["resolve", "--key", key, "--as", "absent"], environ=env)
    fake2 = FakeAke({("POST", "/posts"): [FakeResponse(echo_of_ours(post_id="late"), status=201)]}, search=no_matches)
    out = b.run(["post", "--input", post_file(tmp_path)], environ=env, open_url=fake2)
    assert out["status"] == "posted" and out["key"] == key
    assert [l["status"] for l in ledger_lines(tmp_path)] == ["pending", "ambiguous", "absent", "pending", "posted"]
    with pytest.raises(b.AkePolicyError, match="not pending or ambiguous"):
        b.run(["resolve", "--key", key, "--as", "absent"], environ=env)


@pytest.mark.parametrize("failure, note", [
    (lambda: urllib.error.URLError("timed out"), "network"),
    (lambda: b.AkeSecurityError("refusing HTTP 302 redirect"), "security"),
    (lambda: FakeResponse(None, raw=b"<html>gateway</html>", status=200), "invalid_json"),
    (lambda: FakeResponse({"ok": True}, status=200), "invalid_shape"),           # 2xx without a post_id
    (lambda: FakeResponse({"post_id": 5, "agent_id": AGENT}), "invalid_shape"),  # post_id not a string
    (lambda: FakeResponse(remote_post(post_id="wrong-post", agent_id="other")), "echo_mismatch"),
    (lambda: FakeResponse(echo_of_ours(topic="something else")), "echo_mismatch"),
    (lambda: FakeResponse(echo_of_ours(content="edited by server")), "echo_mismatch"),
    (lambda: FakeResponse(echo_of_ours(environment="node-18")), "echo_mismatch"),
    (lambda: FakeResponse(echo_of_ours(tags=["intro"])), "echo_mismatch"),
    (lambda: FakeResponse(echo_of_ours(agent_id="someone-else")), "echo_mismatch"),
])
def test_post_transport_shape_and_echo_failures_are_ambiguous(tmp_path, failure, note):
    env = env_for(tmp_path)
    fake = FakeAke({("POST", "/posts"): [failure()]}, search=no_matches)
    with pytest.raises(b.AkeAmbiguousError):
        b.run(["post", "--input", post_file(tmp_path)], environ=env, open_url=fake)
    assert len(fake.posts()) == 1
    lines = ledger_lines(tmp_path)
    assert [l["status"] for l in lines] == ["pending", "ambiguous"] and lines[1]["note"] == note
    assert "detail" not in json.dumps(lines)


def test_post_4xx_is_rejected_and_a_corrected_resend_is_allowed(tmp_path):
    env = env_for(tmp_path)
    secret = "moltbook_sk_abcdefghijk0123456789"
    fake = FakeAke({("POST", "/posts"): [http_error(422, {"detail": [{"msg": "bad " + secret}]})]}, search=no_matches)
    with pytest.raises(b.AkePolicyError, match="HTTP 422") as info:
        b.run(["post", "--input", post_file(tmp_path)], environ=env, open_url=fake)
    assert secret not in str(info.value) and "[REDACTED]" in str(info.value)
    lines = ledger_lines(tmp_path)
    assert [l["status"] for l in lines] == ["pending", "rejected"] and lines[1]["note"] == "http_422"
    assert "bad" not in json.dumps(lines)  # remote detail is never persisted
    fake2 = FakeAke({("POST", "/posts"): [FakeResponse(echo_of_ours(post_id="ok"), status=201)]}, search=no_matches)
    out = b.run(["post", "--input", post_file(tmp_path)], environ=env, open_url=fake2)
    assert out["status"] == "posted" and len(fake2.posts()) == 1
    # 429 is a rejection too: nothing was written and nothing is retried automatically
    limited = FakeAke({("POST", "/posts"): [http_error(429)]}, search=no_matches)
    with pytest.raises(b.AkePolicyError, match="429"):
        b.run(["post", "--input", post_file(tmp_path, topic="another topic", source=SOURCE + "9")], environ=env, open_url=limited)
    assert len(limited.posts()) == 1


def test_corrupt_or_unwritable_ledger_blocks_writes_before_any_network_call(tmp_path):
    env = env_for(tmp_path)
    ledger = Path(env["AKE_RECEIPTS"])
    ledger.parent.mkdir(parents=True)
    never = FakeAke()  # any call fails the test
    ledger.write_text('{"key": "rb-ake-000000000000000000000000", "status": "posted", "operation": "post"}\nnot json\n')
    with pytest.raises(b.AkeLedgerError, match="corrupt"):
        b.run(["post", "--input", post_file(tmp_path)], environ=env, open_url=never)
    for bad in ('{"key": "nope", "status": "posted", "operation": "post"}',
                '{"key": "rb-ake-000000000000000000000000", "status": "postd", "operation": "post"}',
                '{"key": "rb-ake-000000000000000000000000", "status": "posted", "operation": "post", "extra": 1}',
                '{"a": NaN}'):
        ledger.write_text(bad + "\n")
        with pytest.raises(b.AkeLedgerError):
            b.run(["receipts"], environ=env)
        with pytest.raises(b.AkeLedgerError):
            b.run(["post", "--input", post_file(tmp_path)], environ=env, open_url=never)
    # readable but not writable: refused before the pre-flight search
    ledger.write_text("")
    os.chmod(ledger, 0o444)
    try:
        if os.access(ledger, os.W_OK):
            pytest.skip("running as a user who can write read-only files")
        with pytest.raises(b.AkeLedgerError, match="not writable"):
            b.run(["post", "--input", post_file(tmp_path)], environ=env, open_url=never)
    finally:
        os.chmod(ledger, 0o644)
    # a ledger path that is a directory cannot be appended to: refuse, do not send
    env2 = dict(env, AKE_RECEIPTS=str(tmp_path / "dir"))
    (tmp_path / "dir").mkdir()
    with pytest.raises(b.AkeLedgerError):
        b.run(["post", "--input", post_file(tmp_path)], environ=env2, open_url=never)
    assert never.calls == []


def test_unknown_status_in_ledger_never_permits_a_resend(tmp_path):
    env = env_for(tmp_path)
    fake = FakeAke({("POST", "/posts"): [FakeResponse(echo_of_ours(), status=201)]}, search=no_matches)
    out = b.run(["post", "--input", post_file(tmp_path)], environ=env, open_url=fake)
    ledger = Path(env["AKE_RECEIPTS"])
    ledger.write_text(ledger.read_text().replace('"status":"posted"', '"status":"postd"'))
    again = FakeAke()
    with pytest.raises(b.AkeLedgerError, match="not a receipt"):
        b.run(["post", "--input", post_file(tmp_path)], environ=env, open_url=again)
    assert again.calls == [] and out["key"]


def test_receipts_command_never_creates_the_ledger_and_aliases_share_one_lock(tmp_path):
    env = env_for(tmp_path)
    out = b.run(["receipts"], environ=env)
    assert out["receipts"] == [] and not Path(env["AKE_RECEIPTS"]).exists()
    assert not Path(env["AKE_RECEIPTS"]).parent.exists()
    real = tmp_path / "real" / "receipts.jsonl"
    real.parent.mkdir()
    (tmp_path / "alias").symlink_to(tmp_path / "real")
    aliased = b.receipts_path_from_env({"AKE_RECEIPTS": str(tmp_path / "alias" / "receipts.jsonl")})
    assert aliased == b.receipts_path_from_env({"AKE_RECEIPTS": str(real)}) == real.resolve()
    relative = b.receipts_path_from_env({"AKE_RECEIPTS": str(tmp_path / "real" / ".." / "real" / "receipts.jsonl")})
    assert relative == real.resolve()


# ---------------------------------------------------------------------------
# verify: GET first, refuse self and missing, send once
# ---------------------------------------------------------------------------

def test_verify_fetches_the_post_first_and_refuses_self_votes(tmp_path):
    env = env_for(tmp_path)
    mine = FakeAke({("GET", "/posts/845a15fe"): [FakeResponse(remote_post(agent_id=AGENT.upper()))]})
    with pytest.raises(b.AkePolicyError, match="self-verification"):
        b.run(["verify", "--input", verify_file(tmp_path)], environ=env, open_url=mine)
    assert mine.posts() == [] and ledger_lines(tmp_path) == []
    gone = FakeAke({("GET", "/posts/845a15fe"): [http_error(404)]})
    with pytest.raises(b.AkePolicyError, match="not found or hidden"):
        b.run(["verify", "--input", verify_file(tmp_path)], environ=env, open_url=gone)
    for bad in ([], {"post_id": "845a15fe"}, {"post_id": "845a15fe", "agent_id": 7},
                remote_post(agent_id=" "), remote_post(post_id="other-id"), remote_post(content=None)):
        shape = FakeAke({("GET", "/posts/845a15fe"): [FakeResponse(bad)]})
        with pytest.raises(b.AkeApiError):
            b.run(["verify", "--input", verify_file(tmp_path)], environ=env, open_url=shape)
        assert shape.posts() == []
    assert ledger_lines(tmp_path) == []


def test_verify_happy_path_echo_binding_and_server_side_rejection(tmp_path):
    env = env_for(tmp_path)
    fake = FakeAke({
        ("GET", "/posts/845a15fe"): [FakeResponse(remote_post())],
        ("POST", "/posts/845a15fe/verify"): [FakeResponse(remote_post(verifications_pass=1))],
    })
    out = b.run(["verify", "--input", verify_file(tmp_path)], environ=env, open_url=fake)
    assert out["status"] == "verified" and json.loads(fake.posts()[0][2]) == {"agent_id": AGENT, "passed": True, "notes": "ran it"}
    lines = ledger_lines(tmp_path)
    assert [l["status"] for l in lines] == ["pending", "verified"] and lines[1]["passed"] is True
    # the verify echo must describe the post we voted on
    swapped = FakeAke({
        ("GET", "/posts/845a15fe"): [FakeResponse(remote_post())],
        ("POST", "/posts/845a15fe/verify"): [FakeResponse(remote_post(post_id="someone-else"))],
    })
    with pytest.raises(b.AkeAmbiguousError):
        b.run(["verify", "--input", verify_file(tmp_path, passed=False, notes="TypeError")], environ=env, open_url=swapped)
    assert ledger_lines(tmp_path)[-1]["note"] == "echo_mismatch"
    # AKE's own 403 is a rejection, not ambiguity
    fake403 = FakeAke({
        ("GET", "/posts/845a15fe"): [FakeResponse(remote_post())],
        ("POST", "/posts/845a15fe/verify"): [http_error(403)],
    })
    with pytest.raises(b.AkePolicyError, match="403"):
        b.run(["verify", "--input", verify_file(tmp_path, passed=False, notes="TypeError again")], environ=env, open_url=fake403)
    assert ledger_lines(tmp_path)[-1]["status"] == "rejected"
    with pytest.raises(b.AkePolicyError, match="intent file is a verify"):
        b.run(["post", "--input", verify_file(tmp_path)], environ=env, open_url=FakeAke())


def test_ledger_failure_after_a_2xx_names_the_post_id_and_keeps_the_key_pending(tmp_path, monkeypatch):
    env = env_for(tmp_path)
    fake = FakeAke({("POST", "/posts"): [FakeResponse(echo_of_ours(post_id="landed"), status=201)]}, search=no_matches)
    real_append = b.append_receipt

    def flaky_append(ledger, receipt):
        if receipt.get("status") == "posted":
            raise b.AkeLedgerError("disk full")
        return real_append(ledger, receipt)

    monkeypatch.setattr(b, "append_receipt", flaky_append)
    with pytest.raises(b.AkeLedgerError, match="post_id landed") as info:
        b.run(["post", "--input", post_file(tmp_path)], environ=env, open_url=fake)
    assert "--as posted --post-id landed" in str(info.value)
    monkeypatch.setattr(b, "append_receipt", real_append)
    lines = ledger_lines(tmp_path)
    assert [l["status"] for l in lines] == ["pending"]
    blocked = b.run(["post", "--input", post_file(tmp_path)], environ=env, open_url=FakeAke())
    assert blocked["idempotent"] is True and blocked["status"] == "pending"
    b.run(["resolve", "--key", lines[0]["key"], "--as", "posted", "--post-id", "landed"], environ=env)
    assert ledger_lines(tmp_path)[-1]["post_id"] == "landed"


def test_resolve_verify_defaults_to_the_voted_post_id_and_display_strips_bidi(tmp_path):
    env = env_for(tmp_path)
    fake = FakeAke({("GET", "/posts/845a15fe"): [FakeResponse(remote_post())],
                    ("POST", "/posts/845a15fe/verify"): [urllib.error.URLError("reset")]})
    with pytest.raises(b.AkeAmbiguousError):
        b.run(["verify", "--input", verify_file(tmp_path)], environ=env, open_url=fake)
    key = ledger_lines(tmp_path)[-1]["key"]
    out = b.run(["resolve", "--key", key, "--as", "verified"], environ=env)
    assert out["receipt"]["post_id"] == "845a15fe" and out["receipt"]["status"] == "verified"
    assert b.display("a‮b​c\x9bd\x1b[31m", 10) == "abcd[31m"
    assert b.display("a\u2060b\u2061c\u2064d\u2066e\ufeff", 10) == "abcde"  # word joiner, invisible operators, LRI, BOM
    assert b.display("line\nbreak\ttab", 20) == "line\nbreak\ttab"


def test_bridge_and_verifications_strip_the_same_invisible_characters():
    """The two libraries share one threat model; the character class must not drift."""
    import verifications  # noqa: E402 - scripts/ is already on sys.path

    probe = "".join(chr(cp) for cp in range(0x2000, 0x2070)) + "\u200b\u200e\u200f\ufeff\u00ad\u200d\u200c"
    assert b.BIDI_RE.sub("", probe) == verifications._INVISIBLE_RE.sub("", probe)
    assert b.BIDI_RE.sub("", "\u200d\u200c\u00ad") == "\u200d\u200c\u00ad"  # ZWJ/ZWNJ/soft hyphen are meaningful, kept
    # spelled with escapes in both sources: literal invisible code points vanish in editors and diff viewers
    for module in (b, verifications):
        assert not b.BIDI_RE.search(Path(module.__file__).read_text(encoding="utf-8")), module.__name__


def test_verify_refuses_any_post_this_ledger_created_whatever_the_agent_id(tmp_path):
    """The remote agent_id is self-asserted; the local ledger is the check that holds."""
    env = env_for(tmp_path)
    fake = FakeAke({("POST", "/posts"): [FakeResponse(echo_of_ours(post_id="p1", agent_id="alice"), status=201)]},
                   search=no_matches)
    posted = b.run(["post", "--input", post_file(tmp_path)], environ=dict(env, AKE_AGENT_ID="alice"), open_url=fake)
    assert posted["status"] == "posted" and posted["post_id"] == "p1"
    # same ledger, a different AKE_AGENT_ID: refused before any network call
    bob = FakeAke()
    with pytest.raises(b.AkePolicyError, match="self-verification refused: this ledger posted p1") as info:
        b.run(["verify", "--input", verify_file(tmp_path, post_id="p1")], environ=dict(env, AKE_AGENT_ID="bob"), open_url=bob)
    assert "alice" in str(info.value) and bob.calls == []
    assert [l["status"] for l in ledger_lines(tmp_path)] == ["pending", "posted"]
    # an ambiguous post whose echo named the id is ours too, until it is resolved absent
    assert b.own_post_claim([{"key": "rb-ake-" + "a" * 24, "operation": "post", "status": "ambiguous", "post_id": "q"}], "q")
    assert b.own_post_claim([
        {"key": "rb-ake-" + "a" * 24, "operation": "post", "status": "ambiguous", "post_id": "q"},
        {"key": "rb-ake-" + "a" * 24, "operation": "post", "status": "absent", "post_id": None},
    ], "q") is None
    # a verify receipt naming the post is a vote, not a claim of authorship
    assert b.own_post_claim([{"key": "rb-ake-" + "b" * 24, "operation": "verify", "status": "verified", "post_id": "q"}], "q") is None
    # someone else's post still verifies
    other = FakeAke({("GET", "/posts/zz"): [FakeResponse(remote_post(post_id="zz"))],
                     ("POST", "/posts/zz/verify"): [FakeResponse(remote_post(post_id="zz", verifications_pass=1))]})
    assert b.run(["verify", "--input", verify_file(tmp_path, post_id="zz")], environ=dict(env, AKE_AGENT_ID="bob"), open_url=other)["status"] == "verified"


def test_outbound_text_with_a_token_shaped_string_is_refused_offline(tmp_path):
    env = env_for(tmp_path)

    def no_network(*a, **k):
        raise AssertionError("a refused intent must not reach the network")

    for field, value in (("content", "log: ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456 failed"),
                         ("topic", "Bearer abcdefghijklmnop rejected"),
                         ("environment", "sk-abcdefghijklmnopqrstuvwxyz")):
        with pytest.raises(b.AkePolicyError, match=f"{field} contains a token-shaped string"):
            b.run(["dry-run", "--input", post_file(tmp_path, **{field: value})], environ=env, open_url=no_network)
        with pytest.raises(b.AkePolicyError, match="token-shaped"):
            b.run(["post", "--input", post_file(tmp_path, **{field: value})], environ=env, open_url=no_network)
    with pytest.raises(b.AkePolicyError, match="tags contains a token-shaped string"):
        b.run(["dry-run", "--input", post_file(tmp_path, tags=["ghp_abcdefghijklmnopqrstuvwxyz0123"])], environ=env, open_url=no_network)
    with pytest.raises(b.AkePolicyError, match="notes contains a token-shaped string"):
        b.run(["dry-run", "--input", verify_file(tmp_path, notes="moltbook_sk_abcdefghijk0123456789")], environ=env, open_url=no_network)
    assert ledger_lines(tmp_path) == []
    # redacted text is allowed: that is what a careful operator pastes
    out = b.run(["dry-run", "--input", post_file(tmp_path, content="token [REDACTED] was rejected")], environ=env, open_url=no_network)
    assert "[REDACTED]" in out["body"]["content"]


class TrickleResponse:
    """A 2xx whose body arrives one byte per read, each read slower than the budget allows.

    Models ``read1`` (one socket read per call); the loopback test below drives
    a real ``http.client`` response, whose ``read(n)`` would block for n bytes.
    """

    def __init__(self, raw: bytes, delay: float, status: int = 200):
        self.status = status
        self._buf = io.BytesIO(raw)
        self.delay = delay
        self.reads = 0

    def geturl(self):
        return BASE + "/posts"

    def read(self, n=-1):
        self.reads += 1
        time.sleep(self.delay)
        return self._buf.read(1)

    def close(self):
        pass


def test_timeout_is_a_wall_clock_budget_not_a_per_read_timeout(tmp_path, monkeypatch):
    """A server that trickles bytes slower than the socket timeout cannot stall a command."""
    trickle = TrickleResponse(json.dumps(echo_of_ours()).encode(), delay=0.02)
    started = time.monotonic()
    with pytest.raises(b.AkeNetworkError, match="time budget"):
        b.api_request(BASE, "GET", "/posts/search", open_url=lambda req, t: trickle, timeout=0.1)
    assert time.monotonic() - started < 2.0 and 1 < trickle.reads < 20
    # the socket timeout handed to the opener is never more than what is left of the budget
    seen = []

    def record(req, t):
        seen.append(t)
        return FakeResponse(remote_post(post_id="p"))

    deadline = time.monotonic() + 0.5
    b.api_request(BASE, "GET", "/posts/p", open_url=record, deadline=deadline)
    assert 0 < seen[0] <= 0.5
    with pytest.raises(b.AkeNetworkError, match="budget exhausted"):
        b.api_request(BASE, "GET", "/posts/p", open_url=record, deadline=time.monotonic() - 1)
    assert len(seen) == 1
    # a write whose echo trickles past the budget is ambiguous (network), never retried
    env = env_for(tmp_path)
    slow_echo = TrickleResponse(json.dumps(echo_of_ours()).encode(), delay=0.02, status=201)
    fake = FakeAke({("POST", "/posts"): [slow_echo]}, search=no_matches)
    intent = b.build_intent(json.loads(Path(post_file(tmp_path)).read_text()), AGENT, BASE)
    monkeypatch.setattr(b, "TIMEOUT_SECONDS", 0.1)
    with pytest.raises(b.AkeAmbiguousError, match="time budget"):
        b.execute_write(intent, base_url=BASE, ledger=Path(env["AKE_RECEIPTS"]), agent_id=AGENT, open_url=fake)
    assert [l["status"] for l in ledger_lines(tmp_path)] == ["pending", "ambiguous"]
    assert ledger_lines(tmp_path)[-1]["note"] == "network" and len(fake.posts()) == 1
    assert b.PREFLIGHT_BUDGET_SECONDS >= b.TIMEOUT_SECONDS


def test_preflight_search_shares_one_budget_across_pages(monkeypatch, tmp_path):
    env = env_for(tmp_path)
    unrelated = [remote_post(post_id=f"u{i}", topic=f"other {i}") for i in range(b.MAX_SEARCH_LIMIT)]
    endless = FakeAke(search=lambda q, o: unrelated)
    monkeypatch.setattr(b, "PREFLIGHT_BUDGET_SECONDS", 0.0)
    with pytest.raises(b.AkeNetworkError, match="budget exhausted"):
        b.run(["post", "--input", post_file(tmp_path)], environ=env, open_url=endless)
    assert endless.posts() == [] and ledger_lines(tmp_path) == []


def test_operator_config_errors_are_ledger_errors_not_tracebacks(tmp_path, monkeypatch, capsys):
    with pytest.raises(b.AkeLedgerError, match="cannot resolve"):
        b.receipts_path_from_env({"AKE_RECEIPTS": "a\0b"})
    with pytest.raises(b.AkeLedgerError, match="must name a file"):
        b.receipts_path_from_env({"AKE_RECEIPTS": "/"})
    with pytest.raises(b.AkeLedgerError, match="must name a file"):
        with b.ledger_lock(Path("/")):
            pass
    for k, v in env_for(tmp_path).items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("AKE_RECEIPTS", "/")
    assert b.main(["resolve", "--key", "rb-ake-" + "0" * 24, "--as", "absent"]) == 2
    assert json.loads(capsys.readouterr().err)["error"] == "AkeLedgerError"
    # anything else unexpected is a redacted JSON error with exit 2, never a traceback

    def boom(argv):
        raise KeyError("ghp_abcdefghijklmnopqrstuvwxyz0123")

    monkeypatch.setattr(b, "run", boom)
    assert b.main(["receipts"]) == 2
    err = json.loads(capsys.readouterr().err)
    assert err["error"] == "KeyError" and "ghp_" not in err["message"] and "receipts" in err["hint"]


def test_huge_int_in_a_2xx_echo_is_invalid_json_and_the_write_is_ambiguous(tmp_path):
    """A 400-digit score must not turn an accepted write into a traceback with no post_id on stdout."""
    env = env_for(tmp_path)
    raw = json.dumps(echo_of_ours()).replace('"score": 0.0', '"score": ' + "9" * 400).encode()
    assert b"9" * 400 in raw
    fake = FakeAke({("POST", "/posts"): [FakeResponse(None, raw=raw, status=201)]}, search=no_matches)
    with pytest.raises(b.AkeAmbiguousError):
        b.run(["post", "--input", post_file(tmp_path)], environ=env, open_url=fake)
    assert ledger_lines(tmp_path)[-1]["note"] == "invalid_json"
    # and a huge int that reaches summarize_post by another route is displayed as None
    assert b.summarize_post(remote_post(score=10 ** 400))["score"] is None


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------

def test_main_exit_codes_and_redaction(tmp_path, monkeypatch, capsys):
    for k, v in env_for(tmp_path).items():
        monkeypatch.setenv(k, v)
    assert b.main(["dry-run", "--input", post_file(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["sent"] is False
    assert b.main(["dry-run", "--input", str(tmp_path / "missing.json")]) == 1
    err = json.loads(capsys.readouterr().err)
    assert err["error"] == "AkePolicyError"
    monkeypatch.setenv("AKE_BASE_URL", "http://ake.example")
    assert b.main(["search", "--q", "x"]) == 1
    monkeypatch.setenv("AKE_BASE_URL", BASE)
    Path(tmp_path / "ledger").mkdir()
    Path(env_for(tmp_path)["AKE_RECEIPTS"]).write_text("junk\n")
    assert b.main(["receipts"]) == 2
    capsys.readouterr()
    # an already-ambiguous key found on the ledger is reported, but is not a success
    monkeypatch.setattr(b, "execute_write", lambda intent, **kw: {"status": "ambiguous", "key": intent["key"], "idempotent": True, "sent": False})
    Path(env_for(tmp_path)["AKE_RECEIPTS"]).unlink()
    assert b.main(["post", "--input", post_file(tmp_path)]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "ambiguous"
    for text in ("ghp_abcdefghijklmnopqrstuvwxyz0123", "github_pat_11AAAAAAA0bbbbbbbbbbbbbbbbbbbb",
                 "moltbook_sk_abcdefghijk0123456789", "sk-abcdefghijklmnopqrstuvwxyz", "Bearer abcdefghijklmnop"):
        assert text not in b.redact("token " + text + " leaked") and "[REDACTED]" in b.redact(text)
    assert b.AkeAmbiguousError.exit_code == 2 and b.AkeNetworkError.exit_code == 2 and b.AkeLedgerError.exit_code == 2
    assert b.AkeApiError("x", status=422).exit_code == 1 and b.AkeApiError("x", status=503).exit_code == 2
    assert b.AkeApiError("x", status=200, code="invalid_json").exit_code == 2


def test_parser_has_exactly_the_documented_commands():
    parser = b.build_parser()
    commands = parser._subparsers._group_actions[0].choices
    assert set(commands) == {"dry-run", "search", "get", "post", "verify", "receipts", "resolve"}


def test_agent_id_is_screened_like_every_other_outbound_field(tmp_path):
    """AKE_AGENT_ID is sent in every post and verify body and kept in the ledger."""
    env = dict(env_for(tmp_path), AKE_AGENT_ID="ghp_abcdefghijklmnopqrstuvwxyz0123")

    def no_network(*a, **k):
        raise AssertionError("a refused configuration must not reach the network")

    for command, intent in (("dry-run", post_file(tmp_path)), ("post", post_file(tmp_path)),
                            ("verify", verify_file(tmp_path))):
        with pytest.raises(b.AkeConfigError, match="AKE_AGENT_ID contains a token-shaped string"):
            b.run([command, "--input", intent], environ=env, open_url=no_network)
    assert ledger_lines(tmp_path) == []
    assert b.agent_id_from_env({"AKE_AGENT_ID": "  rapptertwo "}) == "rapptertwo"


def test_verify_is_refused_while_an_unresolved_post_key_may_own_the_post(tmp_path):
    """A lost POST response leaves a key without a post_id; the post it may have created is still ours."""
    env = env_for(tmp_path)
    lost = FakeAke({("POST", "/posts"): [urllib.error.URLError("reset")]}, search=no_matches)
    with pytest.raises(b.AkeAmbiguousError):
        b.run(["post", "--input", post_file(tmp_path)], environ=dict(env, AKE_AGENT_ID="alice"), open_url=lost)
    key = ledger_lines(tmp_path)[-1]["key"]
    landed = echo_of_ours(post_id="landed", agent_id="alice")
    # by topic and trailer, by topic alone, by Source trailer alone: refused after the pre-flight GET, before any receipt
    for remote in (landed, dict(landed, content="reworded by AKE"), dict(landed, topic="reworded by AKE")):
        bob = FakeAke({("GET", "/posts/landed"): [FakeResponse(remote)]})
        with pytest.raises(b.AkePolicyError, match=f"resolve --key {key} --as posted --post-id landed"):
            b.run(["verify", "--input", verify_file(tmp_path, post_id="landed")],
                  environ=dict(env, AKE_AGENT_ID="bob"), open_url=bob)
        assert bob.posts() == [] and len(bob.calls) == 1
    assert [l["status"] for l in ledger_lines(tmp_path)] == ["pending", "ambiguous"]
    # an unrelated post still verifies
    other = FakeAke({("GET", "/posts/zz"): [FakeResponse(remote_post(post_id="zz"))],
                     ("POST", "/posts/zz/verify"): [FakeResponse(remote_post(post_id="zz", verifications_pass=1))]})
    assert b.run(["verify", "--input", verify_file(tmp_path, post_id="zz")],
                 environ=dict(env, AKE_AGENT_ID="bob"), open_url=other)["status"] == "verified"
    # resolved as posted, the ordinary own-post guard takes over, offline
    b.run(["resolve", "--key", key, "--as", "posted", "--post-id", "landed"], environ=env)
    quiet = FakeAke()
    with pytest.raises(b.AkePolicyError, match="this ledger posted landed"):
        b.run(["verify", "--input", verify_file(tmp_path, post_id="landed")],
              environ=dict(env, AKE_AGENT_ID="bob"), open_url=quiet)
    assert quiet.calls == []
    # a verify receipt is a vote, never an unresolved claim of authorship
    assert b.unresolved_post_claim(
        [{"key": "rb-ake-" + "c" * 24, "operation": "verify", "status": "pending", "topic": TOPIC}], landed) is None


def test_verify_echo_must_show_the_vote_counted(tmp_path):
    """A 2xx whose counters contradict the vote is not a verified receipt."""
    env = env_for(tmp_path)
    cases = (
        (True, remote_post()),                         # nothing moved
        (True, remote_post(verifications_fail=1)),     # the other counter moved
        (True, remote_post(verifications_pass=None)),  # counter unusable
        (False, remote_post(verifications_pass=1)),    # a fail vote echoed as a pass
    )
    for i, (passed, echo) in enumerate(cases):
        fake = FakeAke({("GET", "/posts/845a15fe"): [FakeResponse(remote_post())],
                        ("POST", "/posts/845a15fe/verify"): [FakeResponse(echo)]})
        with pytest.raises(b.AkeAmbiguousError, match="echo"):
            b.run(["verify", "--input", verify_file(tmp_path, passed=passed, notes=f"run {i}")], environ=env, open_url=fake)
        assert ledger_lines(tmp_path)[-1]["note"] == "echo_mismatch" and len(fake.posts()) == 1
    # a fail vote whose fail counter rose by one from a non-zero start is verified
    fake = FakeAke({("GET", "/posts/845a15fe"): [FakeResponse(remote_post(verifications_fail=4))],
                    ("POST", "/posts/845a15fe/verify"): [FakeResponse(remote_post(verifications_fail=5))]})
    out = b.run(["verify", "--input", verify_file(tmp_path, passed=False, notes="final")], environ=env, open_url=fake)
    assert out["status"] == "verified" and ledger_lines(tmp_path)[-1]["passed"] is False


def test_lone_surrogates_in_a_response_never_break_the_output_contract(tmp_path, monkeypatch, capsys):
    """{"topic": "t\\ud800"} is valid JSON; printed raw it raises UnicodeEncodeError after the receipt was written."""
    for k, v in env_for(tmp_path).items():
        monkeypatch.setenv(k, v)
    assert b.display("t\ud800x\udfffy", 10) == "txy"
    poisoned = remote_post(topic="t\ud800", created_at="2026\udfff", content="c\ud83d")
    scripted = {
        ("GET", "/posts/search"): [FakeResponse([poisoned])],
        ("GET", "/posts/845a15fe"): [FakeResponse(poisoned)],
        ("POST", "/posts"): [FakeResponse(echo_of_ours(created_at="2026\ud800"), status=201)],
    }
    monkeypatch.setattr(b, "_default_open", FakeAke(scripted, search=no_matches))
    for argv in (["search", "--q", "x"], ["get", "--post-id", "845a15fe"], ["post", "--input", post_file(tmp_path)]):
        assert b.main(argv) == 0, argv
        out = capsys.readouterr().out
        assert "\ud800" not in out and "\\ud800" not in out and "\udfff" not in out and "\ud83d" not in out
        json.loads(out)
    assert ledger_lines(tmp_path)[-1]["status"] == "posted"

    # a stdout that cannot carry the text as is still gets valid JSON and exit 0
    class AsciiOnly:
        def __init__(self):
            self.chunks = []

        def write(self, text):
            text.encode("ascii")
            self.chunks.append(text)

        def flush(self):
            pass

    ascii_out = AsciiOnly()
    monkeypatch.setattr(sys, "stdout", ascii_out)
    assert b.main(["dry-run", "--input", post_file(tmp_path, topic="caf\u00e9 is locked")]) == 0
    assert json.loads(ascii_out.chunks[-1])["body"]["topic"] == "caf\u00e9 is locked"

    # a stdout that fails outright is a JSON error on stderr with exit 2, never a traceback
    class Broken:
        def write(self, text):
            raise BrokenPipeError("stdout closed")

        def flush(self):
            pass

    monkeypatch.setattr(sys, "stdout", Broken())
    assert b.main(["dry-run", "--input", post_file(tmp_path)]) == 2
    err = json.loads(capsys.readouterr().err)
    assert err["error"] == "BrokenPipeError" and "receipts" in err["hint"]


def test_wall_clock_budget_holds_against_a_real_socket_that_trickles():
    """http.client's read(n) blocks until n bytes arrive; the budget must be checked after every socket read."""
    import socket
    import threading
    import urllib.request

    body = json.dumps(remote_post(post_id="p")).encode()
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    sent = []

    def serve():
        conn, _ = server.accept()
        with conn:
            conn.settimeout(5)
            buf = b""
            while b"\r\n\r\n" not in buf:
                data = conn.recv(1024)
                if not data:
                    return
                buf += data
            conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                         + str(len(body)).encode() + b"\r\n\r\n")
            try:
                for i in range(len(body)):
                    conn.sendall(body[i:i + 1])
                    sent.append(i)
                    time.sleep(0.05)
            except OSError:
                pass

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()

    class SameOrigin:
        """The real HTTPResponse, reported as coming from the configured origin."""

        def __init__(self, inner):
            self._inner = inner

        def geturl(self):
            return BASE + "/posts/p"

        def __getattr__(self, name):
            return getattr(self._inner, name)

    def open_local(request, timeout):
        local = urllib.request.Request(f"http://127.0.0.1:{port}/posts/p", headers=dict(request.header_items()))
        return SameOrigin(urllib.request.urlopen(local, timeout=timeout))

    started = time.monotonic()
    try:
        with pytest.raises(b.AkeNetworkError, match=r"0\.3s time budget"):
            b.api_request(BASE, "GET", "/posts/p", open_url=open_local, timeout=0.3)
        elapsed = time.monotonic() - started
    finally:
        server.close()
        thread.join(2)
    # the whole body would take len(body) * 0.05 s (> 10 s) to arrive; the budget, not the server, ends the read
    assert 0.25 <= elapsed < 2.0, elapsed
    assert 0 < len(sent) < len(body)
