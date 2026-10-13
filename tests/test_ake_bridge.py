"""Contracts for the fail-closed Rappterbook -> Agentic Knowledge Exchange bridge."""
from __future__ import annotations

import hashlib
import io
import json
import os
import sys
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
    "https://ake.example#f", "ake.example", "https://[::1", "",
])
def test_base_url_must_be_a_bare_https_origin(raw):
    with pytest.raises(b.AkeConfigError):
        b.validate_base_url(raw) if raw else b.base_url_from_env({"AKE_BASE_URL": raw})
    assert b.validate_base_url("https://AKE.example:8443/") == "https://ake.example:8443"


def test_strict_json_rejects_nan_overflow_duplicates_and_depth():
    for bad in (b'{"a": NaN}', b'{"a": Infinity}', b'{"a": 1e309}', b'{"a": -1e999}', b'{"a": 1, "a": 2}'):
        with pytest.raises(ValueError):
            b.loads_strict(bad)
    with pytest.raises(ValueError, match="deeply"):
        b.loads_strict(b"[" * 100000 + b"]" * 100000)
    assert b.loads_strict(b'{"a": [1, 2.5]}') == {"a": [1, 2.5]}


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
        remote_post(topic="hi\x1b[31m there‮", content="x" * 900, tags=["a", {"b": 1}], score="9", extra="dropped"),
        "not-an-object",
    ])]})
    out = b.run(["search", "--q", "sqlite", "--limit", "5"], environ=env_for(tmp_path), open_url=fake)
    assert out["untrusted"] is True and out["count"] == 2 and len(out["results"]) == 1
    row = out["results"][0]
    assert row["topic"] == "hi[31m there" and row["content"].endswith("...[truncated]")
    assert row["score"] is None and "extra" not in row
    assert fake.calls[0][3] == {"q": "sqlite", "limit": "5", "offset": "0"}
    assert not (tmp_path / "ledger").exists()
    with pytest.raises(b.AkePolicyError):
        b.run(["search", "--limit", "51"], environ=env_for(tmp_path), open_url=fake)


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
        return [remote_post(post_id="dup2", topic="different", content="see " + SOURCE + " for details")] if q == SOURCE else []

    fake2 = FakeAke(search=by_source)
    with pytest.raises(b.AkePolicyError, match="dup2"):
        b.run(["post", "--input", post_file(tmp_path)], environ=env, open_url=fake2)
    assert [s["q"] for s in fake2.searches()] == [TOPIC, SOURCE]
    assert fake2.posts() == [] and ledger_lines(tmp_path) == []
    # a longer discussion number is a different discussion, not a substring match
    neighbour = remote_post(post_id="n", topic="other", content="see " + SOURCE + "4")
    fake3 = FakeAke({("POST", "/posts"): [FakeResponse(echo_of_ours(), status=201)]}, search=lambda q, o: [neighbour])
    assert b.run(["post", "--input", post_file(tmp_path)], environ=env, open_url=fake3)["status"] == "posted"


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
    assert b.display("line\nbreak\ttab", 20) == "line\nbreak\ttab"


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
