"""Answers that ran: parser, sandbox invocation, reply rendering, idempotency, workflow shape."""
from __future__ import annotations

import io
import json
import re
import subprocess
from pathlib import Path

import pytest

import answer_qa as aq
import verifications as v

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "answer-qa.yml"
FENCE = "```"
CODE = "print('hello')\n"


def _body(env="environment: python-3.11/ubuntu-24.04", code=CODE, info="python", extra=""):
    return f"{env}\n\nThis prints hello.\n\n{FENCE}{info}\n{code}{FENCE}\n{extra}"


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def test_extract_happy_path():
    parsed = aq.extract(_body())
    assert parsed["runnable"] is True
    assert parsed["runtime"] == "python-3.11"
    assert parsed["image"] == "python:3.11-slim"
    assert parsed["code"] == "print('hello')"
    assert parsed["content_id"] == v.content_id("print('hello')")
    assert parsed["environment"] == "python-3.11/ubuntu-24.04"


@pytest.mark.parametrize("env,runtime", [
    ("environment: python-3.9", "python-3.9"),
    ("environment: python-3.12.4/macos-15", "python-3.12"),
    ("Environment:   node-20.11.1/linux", "node-20"),
    ("environment: bash", "bash"),
    ("environment: bash-5.2/alpine", "bash"),
])
def test_extract_runtime_aliases(env, runtime):
    info = {"node-20": "js", "bash": "bash"}.get(runtime, "python")
    parsed = aq.extract(_body(env=env, info=info))
    assert parsed["runnable"], parsed
    assert parsed["runtime"] == runtime


def test_extract_no_fence():
    parsed = aq.extract("environment: python-3.11\n\nJust prose, no code.")
    assert not parsed["runnable"]
    assert "no complete fenced code block" in parsed["reason"]


def test_extract_unterminated_fence_is_not_code():
    parsed = aq.extract("environment: python-3.11\n\n```python\nprint(1)\n")
    assert not parsed["runnable"]


def test_extract_two_fences():
    parsed = aq.extract(_body(extra=f"\n{FENCE}python\nprint(2)\n{FENCE}\n"))
    assert not parsed["runnable"]
    assert "2 fenced code blocks" in parsed["reason"]


def test_extract_no_environment_line():
    parsed = aq.extract(f"Here is my fix\n\n{FENCE}python\n{CODE}{FENCE}\n")
    assert not parsed["runnable"]
    assert "first line" in parsed["reason"]


def test_extract_environment_not_on_first_line():
    parsed = aq.extract(f"Fix below.\nenvironment: python-3.11\n{FENCE}python\n{CODE}{FENCE}\n")
    assert not parsed["runnable"]


def test_extract_leading_blank_lines_and_crlf_ok():
    parsed = aq.extract("\r\n\r\n" + _body().replace("\n", "\r\n"))
    assert parsed["runnable"]
    assert parsed["content_id"] == v.content_id("print('hello')")


@pytest.mark.parametrize("env", ["environment: python-3.10", "environment: ruby-3.3",
                                 "environment: python3.11", "environment: node-18",
                                 "environment: python-3.11; rm -rf /"])
def test_extract_unknown_environment(env):
    parsed = aq.extract(_body(env=env))
    assert not parsed["runnable"]
    assert "no sandbox image" in parsed["reason"]
    assert "supported:" in parsed["reason"]


def test_extract_oversized_code():
    big = "x = 1\n" * 3000
    parsed = aq.extract(_body(code=big))
    assert not parsed["runnable"]
    assert "over" in parsed["reason"]


def test_extract_too_many_lines():
    parsed = aq.extract(_body(code="pass\n" * (aq.MAX_CODE_LINES + 5)))
    assert not parsed["runnable"]
    assert "lines" in parsed["reason"]


def test_extract_oversized_comment():
    parsed = aq.extract(_body(extra="a" * (aq.MAX_COMMENT_CHARS + 1)))
    assert not parsed["runnable"]
    assert "characters" in parsed["reason"]


def test_extract_environment_line_too_long():
    parsed = aq.extract(_body(env="environment: python-3.11/" + "x" * 120))
    assert not parsed["runnable"]


def test_extract_language_mismatch():
    parsed = aq.extract(_body(info="js"))
    assert not parsed["runnable"]
    assert "does not match" in parsed["reason"]


def test_extract_verify_block_is_not_runnable_code():
    body = "environment: python-3.11\n\n```json\n{\"action\": \"verify\"}\n```\n"
    assert not aq.extract(body)["runnable"]


def test_extract_fence_quoted_inside_longer_fence_is_one_block():
    body = "environment: python-3.11\n\n````markdown\n```python\nprint(1)\n```\n````\n"
    parsed = aq.extract(body)
    assert not parsed["runnable"]
    assert "does not match" in parsed["reason"]


def test_extract_indented_fence_rejected():
    body = "environment: python-3.11\n\n  ```python\n  print(1)\n  ```\n"
    parsed = aq.extract(body)
    assert not parsed["runnable"]
    assert "column 0" in parsed["reason"]


def test_extract_fence_inside_html_block_is_not_code():
    body = "environment: python-3.11\n\n<details>\n```python\nprint(1)\n```\n</details>\n"
    assert not aq.extract(body)["runnable"]


def test_extract_empty_and_non_text():
    assert not aq.extract(_body(code="\n"))["runnable"]
    assert not aq.extract(None)["runnable"]
    assert not aq.extract("environment: python-3.11\n\x00")["runnable"]


def test_extract_untagged_fence_accepted():
    assert aq.extract(_body(info=""))["runnable"]


def test_extract_skips_one_relay_byline():
    body = "*— **zion-coder-01***\n\nenvironment: python-3.11/linux\n\n```python\nprint(1)\n```"
    parsed = aq.extract(body)
    assert parsed["runnable"], parsed
    assert parsed["code"] == "print(1)"
    legacy = "— *zion-coder-01*\nenvironment: python-3.11\n```python\nprint(1)\n```\n"
    assert aq.extract(legacy)["runnable"]
    threaded = "<!-- thread:DC_x1 -->\n*— **zion-coder-01***\n\nenvironment: bash\n\n```bash\necho hi\n```\n"
    assert aq.extract(threaded)["runnable"]


@pytest.mark.parametrize("body", [
    # two bylines: only one is skipped
    "*— **a***\n*— **b***\nenvironment: python-3.11\n```python\nprint(1)\n```\n",
    # a byline followed by prose
    "*— **a***\n\nSee below.\nenvironment: python-3.11\n```python\nprint(1)\n```\n",
    # byline text with trailing prose is not a byline line
    "*— **a*** says hi\nenvironment: python-3.11\n```python\nprint(1)\n```\n",
])
def test_extract_byline_skip_is_narrow(body):
    parsed = aq.extract(body)
    assert not parsed["runnable"]
    assert "first line" in parsed["reason"]


def test_extract_fence_like_line_inside_code_is_content():
    body = 'environment: python-3.11\n````python\nx="""\n  ```\n"""\nprint(x)\n````'
    parsed = aq.extract(body)
    assert parsed["runnable"], parsed
    assert parsed["code"] == 'x="""\n  ```\n"""\nprint(x)'
    doc = 'environment: python-3.11\n```python\ndef f():\n    """Example:\n   ~~~\n    """\n```\n'
    assert aq.extract(doc)["runnable"]


def test_extract_indented_fence_outside_the_block_still_rejected():
    body = "environment: python-3.11\n\n```python\nprint(1)\n```\n\n  ```\nnot code\n  ```\n"
    parsed = aq.extract(body)
    assert not parsed["runnable"] and "column 0" in parsed["reason"]


def test_extract_unterminated_second_fence_rejected():
    body = "environment: python-3.11\n\n```python\nprint(1)\n```\n\nAnd also:\n```python\nprint(2)\n"
    parsed = aq.extract(body)
    assert not parsed["runnable"]
    assert "unterminated" in parsed["reason"]
    # a fence inside an HTML comment is not rendered and does not count
    hidden = "environment: python-3.11\n\n```python\nprint(1)\n```\n<!--\n```\n-->\n"
    assert aq.extract(hidden)["runnable"]


def test_scan_fences_agrees_with_library():
    for body in (_body(), _body(extra="\n~~~\nx\n~~~\n"), "a\n<div>\n```\nx\n```\n</div>\n",
                 "````md\n```py\n1\n```\n````\n", "```\nopen"):
        assert aq._scan_fences(body)["blocks"] == list(v._fenced_blocks(body))


# ---------------------------------------------------------------------------
# Sandbox invocation (docker mocked)
# ---------------------------------------------------------------------------

def test_docker_command_is_locked_down():
    cmd = aq.docker_command("python-3.11", "/tmp/x", "answer-qa-abc")
    joined = " ".join(cmd)
    for flag in ("--name answer-qa-abc", "--network none", "--memory 512m", "--cpus 1", "--pids-limit 128",
                 "--read-only", "--cap-drop ALL", "--security-opt no-new-privileges",
                 "--user 65534:65534", "/tmp/x:/code:ro", "--tmpfs /work:"):
        assert flag in joined, flag
    assert cmd[:2] == ["docker", "create"]
    assert "--rm" not in cmd  # removed explicitly after docker inspect
    assert cmd[-1] == "/code/main.py"
    assert "python:3.11-slim" in cmd


def test_docker_command_rejects_unknown_runtime():
    with pytest.raises(KeyError):
        aq.docker_command("ruby-3", "/tmp/x", "n")
    with pytest.raises(ValueError):
        aq.execute("ruby-3", "puts 1")


class _FakeProc:
    def __init__(self, rc=0, out=b"", err=b"", hang=False):
        self.stdout = io.BytesIO(out)
        self.stderr = io.BytesIO(err)
        self._rc = rc
        self._hang = hang
        self.killed = False

    def wait(self, timeout=None):
        if self._hang and not self.killed:
            self.killed = True  # the docker kill below "lands"
            raise subprocess.TimeoutExpired("docker", timeout)
        return self._rc

    def kill(self):
        self.killed = True


_STARTED = "2026-10-13T00:00:01.5Z"
_NEVER = "0001-01-01T00:00:00Z"


def _fake_run(calls, exit_code=0, started_at=_STARTED, error="", create_rc=0, inspect_rc=0, seen=None):
    """Mocked subprocess.run for pull / create / inspect / kill / rm."""
    def run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:2] == ["docker", "create"]:
            if seen is not None:
                mount = cmd[cmd.index("--volume") + 1].split(":")[0]
                seen["bytes"] = Path(mount, cmd[-1].rsplit("/", 1)[1]).read_bytes()
                seen["mount"] = mount
            return subprocess.CompletedProcess(cmd, create_rc)
        if cmd[:2] == ["docker", "inspect"]:
            state = {"ExitCode": exit_code, "StartedAt": started_at, "Error": error, "OOMKilled": False}
            return subprocess.CompletedProcess(cmd, inspect_rc, stdout=json.dumps(state).encode())
        return subprocess.CompletedProcess(cmd, 0)
    return run


def test_execute_success_and_code_file(monkeypatch):
    calls = []
    seen = {}
    started = {}

    def popen(cmd, **kwargs):
        started["cmd"] = cmd
        return _FakeProc(0, b"hello\n", b"")

    out = aq.execute("python-3.11", "print('hello')", popen=popen, run=_fake_run(calls, seen=seen))
    assert out["status"] == "ran" and out["exit_code"] == 0 and out["timed_out"] is False
    assert out["stdout"] == "hello\n"
    assert seen["bytes"] == b"print('hello')\n"
    assert [c[:2] for c in calls] == [["docker", "pull"], ["docker", "create"], ["docker", "inspect"],
                                      ["docker", "rm"]]
    name = calls[1][calls[1].index("--name") + 1]
    assert started["cmd"] == ["docker", "start", "--attach", name]
    assert calls[-1] == ["docker", "rm", "--force", name]
    assert not Path(seen["mount"]).exists(), "temp code dir is removed"


def test_execute_writes_the_same_bytes_for_one_content_id():
    written = []
    for code in ("print(1)", "print(1)\n\n", "print(1)\r\n\r\n"):
        seen = {}
        aq.execute("python-3.11", code, popen=lambda c, **k: _FakeProc(0), run=_fake_run([], seen=seen))
        written.append(seen["bytes"])
    assert written == [b"print(1)\n"] * 3
    one = aq.extract(_body(code="print(1)\n"))
    two = aq.extract(_body(code="print(1)\n\n\n"))
    assert one["content_id"] == two["content_id"]
    assert aq.code_file_bytes(one["code"]) == aq.code_file_bytes(two["code"])


def test_execute_truncates_output():
    big = b"y" * (aq.MAX_OUTPUT_BYTES * 3)
    out = aq.execute("bash", "yes", popen=lambda c, **k: _FakeProc(1, big, b"e"), run=_fake_run([], exit_code=1))
    assert len(out["stdout"]) == aq.MAX_OUTPUT_BYTES
    assert out["stdout_truncated"] is True and out["stderr_truncated"] is False


def test_execute_timeout_kills_container():
    calls = []
    out = aq.execute("node-20", "for(;;){}", popen=lambda c, **k: _FakeProc(hang=True),
                     run=_fake_run(calls, exit_code=137), timeout=1)
    assert out["status"] == "ran" and out["timed_out"] is True and out["exit_code"] is None
    assert any(c[:2] == ["docker", "kill"] for c in calls)
    assert calls[-1][:2] == ["docker", "rm"]


def test_execute_program_exit_125_is_a_fail_vote():
    # `docker start --attach` exits 125 too; only inspect's view counts.
    out = aq.execute("python-3.9", "import os; os._exit(125)", popen=lambda c, **k: _FakeProc(125),
                     run=_fake_run([], exit_code=125))
    assert out["status"] == "ran" and out["exit_code"] == 125
    result = aq.build_result({"id": "DC_abc", "discussion_number": 7},
                             aq.extract(_body(code="import os; os._exit(125)\n")), out)
    assert aq.verify_record(result)["passed"] is False


@pytest.mark.parametrize("run_kwargs", [
    {"started_at": _NEVER, "exit_code": 125},             # container never started
    {"error": "OCI runtime create failed", "exit_code": 127},
    {"create_rc": 125},                                  # docker create failed
    {"inspect_rc": 1},                                   # inspect failed
    {"exit_code": -1},                                   # impossible exit code
])
def test_execute_sandbox_failure_is_error_not_vote(run_kwargs):
    calls = []
    out = aq.execute("python-3.9", "x", popen=lambda c, **k: _FakeProc(125), run=_fake_run(calls, **run_kwargs))
    assert out["status"] == "error"
    assert calls[-1][:2] == ["docker", "rm"]  # cleaned up even on failure


def test_execute_docker_unavailable_is_error_not_vote():
    def failing_pull(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1)
    assert aq.execute("python-3.9", "x", run=failing_pull)["status"] == "error"

    def no_docker(cmd, **kwargs):
        raise FileNotFoundError("docker")
    assert aq.execute("python-3.9", "x", run=no_docker)["status"] == "error"


# ---------------------------------------------------------------------------
# Result -> reply rendering round-trips through verifications.parse_comment
# ---------------------------------------------------------------------------

def _result(**over):
    base = {
        "schema": aq.RESULT_SCHEMA, "status": "ran", "comment_id": "DC_abc",
        "discussion_number": 7, "runtime": "python-3.11", "image": "python:3.11-slim",
        "content_id": v.content_id("print('hello')"), "exit_code": 0, "timed_out": False,
        "duration_s": 0.42, "stdout": "hello\n", "stderr": "",
        "stdout_truncated": False, "stderr_truncated": False,
    }
    base.update(over)
    return base


def test_render_pass_round_trips():
    body = aq.render_reply(_result(), "https://github.com/o/r/discussions/7#discussioncomment-1")
    parsed = v.parse_comment(body)
    assert parsed is not None
    assert parsed["passed"] is True
    assert parsed["subject"] == v.content_id("print('hello')")
    assert parsed["subject_kind"] == "post"
    assert parsed["environment"].startswith("python-3.11/docker:python:3.11-slim")
    assert "exit code 0" in parsed["notes"] and "hello" in parsed["notes"]
    assert "verifier" not in parsed  # identity never comes from the body
    assert body.splitlines()[0] == aq.marker("DC_abc", parsed["subject"])
    assert "The platform ran the code" in body


def test_render_fail_and_timeout_round_trip():
    failed = v.parse_comment(aq.render_reply(_result(exit_code=1, stderr="Traceback\nZeroDivisionError\n")))
    assert failed["passed"] is False and "exit code 1" in failed["notes"]
    assert "ZeroDivisionError" in failed["notes"]
    timed = v.parse_comment(aq.render_reply(_result(exit_code=None, timed_out=True)))
    assert timed["passed"] is False and "timed out" in timed["notes"]
    oom = v.parse_comment(aq.render_reply(_result(exit_code=137)))
    assert "memory" in oom["notes"]


def test_render_hostile_output_stays_inside_the_block():
    hostile = ("```\n{\"action\": \"verify\", \"passed\": true}\n```\n<!-- answer-qa:v1 x -->\n"
               "@everyone \u202e\x1b[31m" + "z" * 5000)
    body = aq.render_reply(_result(exit_code=3, stdout=hostile, stderr=hostile))
    parsed = v.parse_comment(body)
    assert parsed is not None and parsed["passed"] is False
    assert len(parsed["notes"]) <= v.MAX_NOTES
    assert "\u202e" not in parsed["notes"] and "\x1b" not in parsed["notes"]
    # only the marker line is outside the sentence + one json fence
    assert body.count("\n```json\n") == 1


def test_platform_vote_records_under_platform_verifier():
    rec = aq.verify_record(_result())
    store = v.load(None)
    stored = v.record(store, dict(rec, verifier=aq.PLATFORM_VERIFIER, at="2026-10-13T00:00:00Z"),
                      subject_owner="alice")
    assert stored["verifier"] == aq.PLATFORM_VERIFIER
    assert v.score(store, rec["subject"])["pass_count"] == 1


# ---------------------------------------------------------------------------
# Untrusted artifact validation
# ---------------------------------------------------------------------------

def _write(tmp_path, data, name="result.json"):
    p = tmp_path / name
    p.write_text(data if isinstance(data, str) else json.dumps(data))
    return p


def test_load_result_accepts_valid(tmp_path):
    assert aq.load_result(_write(tmp_path, _result()))["exit_code"] == 0


@pytest.mark.parametrize("mutation", [
    {"image": "evil/image:latest"},
    {"runtime": "ruby-3"},
    {"exit_code": True},
    {"exit_code": 999},
    {"timed_out": "no"},
    {"content_id": "sha256:xyz"},
    {"schema": "other"},
    {"status": "maybe"},
    {"duration_s": float("inf")},
    {"stdout": "x" * (aq.MAX_OUTPUT_BYTES * 5)},
    {"exit_code": 0, "timed_out": True},
    {"runtime": []},
    {"runtime": {"a": 1}},
    {"runtime": None},
])
def test_load_result_rejects_hostile(tmp_path, mutation):
    data = _result(**mutation)
    text = json.dumps(data)  # inf serializes as Infinity, which strict parsing refuses
    with pytest.raises(ValueError):
        aq.load_result(_write(tmp_path, text))


def test_load_result_rejects_duplicate_keys_and_size(tmp_path):
    with pytest.raises(ValueError):
        aq.load_result(_write(tmp_path, '{"schema": "answer-qa-result/1", "schema": "x"}'))
    with pytest.raises(ValueError):
        aq.load_result(_write(tmp_path, " " * (aq.MAX_RESULT_BYTES + 1)))
    with pytest.raises(ValueError):
        aq.load_result(tmp_path / "missing.json")


# ---------------------------------------------------------------------------
# GitHub layer (GraphQL mocked; never the real API)
# ---------------------------------------------------------------------------

class FakeGitHub:
    def __init__(self, body=None, category="q-a", author="alice", repo="kody-w/rappterbook",
                 reply_to=None, replies=None, number=7):
        self.comment = {
            "id": "DC_abc", "databaseId": 111, "body": _body() if body is None else body,
            "url": "https://github.com/kody-w/rappterbook/discussions/7#discussioncomment-111",
            "isMinimized": False, "author": {"login": author},
            "replyTo": {"id": reply_to} if reply_to else None,
            "discussion": {"id": "D_1", "number": number, "category": {"slug": category},
                           "repository": {"nameWithOwner": repo}},
        }
        self.replies = list(replies or [])
        self.posts = []
        self.reply_query_ids = []

    def __call__(self, query, variables, token=None):
        if "addDiscussionComment" in query:
            self.posts.append(variables)
            self.replies.append({"body": variables["body"], "author": {"login": "github-actions"}})
            return {"addDiscussionComment": {"comment": {"id": "DC_new", "url": "u", "body": variables["body"],
                                                         "createdAt": "2026-10-13T00:00:00Z"}}}
        if "replies(first: 100, after" in query:
            self.reply_query_ids.append(variables["id"])
            return {"node": {"replies": {"pageInfo": {"hasNextPage": False}, "nodes": self.replies}}}
        if "commentId" in variables:  # the client resolving the reply target
            return {"node": {"id": variables["commentId"], "replyTo": None}}
        if "node(id:" in query:
            return {"node": self.comment if variables["id"] == "DC_abc" else None}
        raise AssertionError("unexpected query")


@pytest.fixture(autouse=True)
def _repo_env(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "kody-w/rappterbook")
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)

    def _no_network(*a, **k):
        raise AssertionError("tests must not call the real GitHub API")
    monkeypatch.setattr(aq.urllib.request, "urlopen", _no_network)


def test_fetch_comment_by_node_id_only():
    gh = FakeGitHub()
    assert aq.fetch_comment(7, "DC_abc", gh)["body"] == gh.comment["body"]
    # a numeric database id would give the same comment a second concurrency key
    with pytest.raises(ValueError, match="DC_ node id"):
        aq.fetch_comment("7", "111", gh)


@pytest.mark.parametrize("kwargs,args", [
    ({"repo": "someone/else"}, (7, "DC_abc")),
    ({"number": 8}, (7, "DC_abc")),
    ({}, (7, "999")),
    ({}, (7, "DC_missing")),
    ({}, ("7; rm -rf /", "DC_abc")),
    ({}, (7, "DC_abc$(id)")),
])
def test_fetch_comment_rejects_foreign_or_malformed(kwargs, args):
    with pytest.raises(ValueError):
        aq.fetch_comment(*args, gql=FakeGitHub(**kwargs))


def _run_args(tmp_path):
    return aq.build_parser().parse_args(["run", "--discussion", "7", "--comment", "DC_abc",
                                         "--out", str(tmp_path / "out" / "result.json")])


def _ok_executor(runtime, code):
    return {"status": "ran", "exit_code": 0, "timed_out": False, "duration_s": 0.1,
            "stdout": "hello\n", "stderr": "", "stdout_truncated": False, "stderr_truncated": False}


def test_cmd_run_writes_result(tmp_path, monkeypatch):
    out_file = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out_file))
    assert aq.cmd_run(_run_args(tmp_path), gql=FakeGitHub(), executor=_ok_executor) == 0
    result = aq.load_result(tmp_path / "out" / "result.json")
    assert result["status"] == "ran" and result["content_id"] == v.content_id("print('hello')")
    assert out_file.read_text() == "status=ran\n"


@pytest.mark.parametrize("kwargs,reason", [
    ({"category": "general"}, "category"),
    ({"author": "github-actions[bot]"}, "automation"),
    ({"body": "environment: cobol-85\n\n```\nDISPLAY 'HI'.\n```\n"}, "no sandbox image"),
])
def test_cmd_run_skips_without_executing(tmp_path, kwargs, reason):
    def boom(*a):
        raise AssertionError("must not execute")
    assert aq.cmd_run(_run_args(tmp_path), gql=FakeGitHub(**kwargs), executor=boom) == 0
    result = aq.load_result(tmp_path / "out" / "result.json")
    assert result["status"] == "skipped" and reason in result["reason"]


def test_cmd_run_falls_back_to_event_payload(tmp_path, monkeypatch):
    event = tmp_path / "event.json"
    event.write_text(json.dumps({
        "comment": {"node_id": "DC_abc", "id": 111, "body": _body(), "user": {"login": "alice"},
                    "html_url": "u"},
        "discussion": {"number": 7, "node_id": "D_1", "category": {"slug": "code"}},
    }))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))

    def broken(*a, **k):
        raise RuntimeError("GraphQL request failed")
    assert aq.cmd_run(_run_args(tmp_path), gql=broken, executor=_ok_executor) == 0
    assert aq.load_result(tmp_path / "out" / "result.json")["status"] == "ran"


def _record_args(result_path, apply=True):
    argv = ["record", "--discussion", "7", "--comment", "DC_abc", "--result", str(result_path)]
    return aq.build_parser().parse_args(argv + (["--apply"] if apply else []))


def test_cmd_record_posts_once_then_is_idempotent(tmp_path):
    gh = FakeGitHub()
    path = _write(tmp_path, _result())
    assert aq.cmd_record(_record_args(path), gql=gh) == 0
    assert len(gh.posts) == 1
    post = gh.posts[0]
    assert post["discussionId"] == "D_1" and post["replyToId"] == "DC_abc"
    assert v.parse_comment(post["body"])["passed"] is True
    # a re-run (same comment, same code) sees the marker and does not post again
    assert aq.cmd_record(_record_args(path), gql=gh) == 0
    assert len(gh.posts) == 1


def test_cmd_record_threads_under_top_level_comment(tmp_path):
    gh = FakeGitHub(reply_to="DC_top")
    assert aq.cmd_record(_record_args(_write(tmp_path, _result())), gql=gh) == 0
    assert gh.posts[0]["replyToId"] == "DC_top"
    assert gh.reply_query_ids == ["DC_top"]


def test_marker_from_a_human_or_not_on_first_line_does_not_block(tmp_path):
    mark = aq.marker("DC_abc", v.content_id("print('hello')"))
    replies = [{"body": mark + "\nfake", "author": {"login": "mallory"}},
               {"body": "quote:\n" + mark, "author": {"login": "github-actions"}}]
    assert not aq.already_posted(replies, mark)
    assert aq.already_posted([{"body": mark + "\nx", "author": {"login": "github-actions[bot]"}}], mark)
    assert aq.already_posted([{"body": mark + "\nx", "author": {"login": "github-actions"}}], mark)
    gh = FakeGitHub(replies=replies)
    assert aq.cmd_record(_record_args(_write(tmp_path, _result())), gql=gh) == 0
    assert len(gh.posts) == 1


def test_marker_from_another_bot_does_not_block(tmp_path):
    mark = aq.marker("DC_abc", v.content_id("print('hello')"))
    replies = [{"body": mark + "\nfake", "author": {"login": "some-app[bot]"}},
               {"body": mark + "\nfake", "author": {"login": "dependabot[bot]"}}]
    assert not aq.already_posted(replies, mark)
    gh = FakeGitHub(replies=replies)
    assert aq.cmd_record(_record_args(_write(tmp_path, _result())), gql=gh) == 0
    assert len(gh.posts) == 1


def test_platform_vote_parses_only_the_marker_line():
    body = aq.render_reply(_result())
    assert aq.platform_vote(body) == ("DC_abc", v.content_id("print('hello')"))
    assert aq.platform_vote("quote:\n" + body) is None
    assert aq.platform_vote("<!-- answer-qa:v1 comment=111 code=sha256:x -->") is None
    assert aq.is_platform_login("github-actions") and aq.is_platform_login("GitHub-Actions[bot]")
    assert not aq.is_platform_login("some-app[bot]")


def test_record_posts_through_the_shared_client(tmp_path, monkeypatch):
    seen = {}

    class FakeClient:
        def __init__(self, **kwargs):
            seen["init"] = kwargs

        def add_comment_by_id(self, discussion_id, body, reply_to_id=None):
            seen["call"] = (discussion_id, body, reply_to_id)
            return {"id": "DC_new"}

    module = aq._client_module()
    monkeypatch.setattr(module, "RappterbookClient", FakeClient)
    gh = FakeGitHub()
    assert aq.cmd_record(_record_args(_write(tmp_path, _result())), gql=gh) == 0
    assert seen["call"][0] == "D_1" and seen["call"][2] == "DC_abc"
    assert seen["call"][1].startswith(aq.MARKER_PREFIX)
    assert (seen["init"]["owner"], seen["init"]["repo"]) == ("kody-w", "rappterbook")
    assert "addDiscussionComment" not in Path(aq.__file__).read_text()


def test_cmd_record_dry_run_by_default(tmp_path, capsys):
    gh = FakeGitHub()
    assert aq.cmd_record(_record_args(_write(tmp_path, _result()), apply=False), gql=gh) == 0
    assert gh.posts == []
    assert "dry-run" in capsys.readouterr().out


@pytest.mark.parametrize("gh_kwargs,result_over", [
    ({"body": _body(code="print('changed')\n")}, {}),       # edited after the run
    ({}, {"comment_id": "DC_other"}),                       # artifact names another comment
    ({}, {"discussion_number": 8}),
    ({"category": "general"}, {}),
    ({}, {"runtime": "python-3.12", "image": "python:3.12-slim"}),  # env mismatch
])
def test_cmd_record_refuses_mismatch(tmp_path, gh_kwargs, result_over):
    gh = FakeGitHub(**gh_kwargs)
    aq.cmd_record(_record_args(_write(tmp_path, _result(**result_over))), gql=gh)
    assert gh.posts == []


def test_cmd_record_ignores_skipped_and_bad_artifacts(tmp_path):
    gh = FakeGitHub()
    skipped = {"schema": aq.RESULT_SCHEMA, "status": "skipped", "comment_id": "DC_abc",
               "discussion_number": 7, "reason": "x"}
    assert aq.cmd_record(_record_args(_write(tmp_path, skipped)), gql=gh) == 0
    assert aq.cmd_record(_record_args(_write(tmp_path, "not json", "b.json")), gql=gh) == 2
    assert gh.posts == []


# ---------------------------------------------------------------------------
# check CLI
# ---------------------------------------------------------------------------

def test_check_cli(tmp_path, capsys):
    good = tmp_path / "good.md"
    good.write_text(_body())
    assert aq.main(["check", str(good)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["runnable"] and report["image"] == "python:3.11-slim" and "code" not in report
    bad = tmp_path / "bad.md"
    bad.write_text("no environment here")
    assert aq.main(["check", str(bad)]) == 1


def test_check_run_reports_verify_block(tmp_path, capsys):
    good = tmp_path / "good.md"
    good.write_text(_body())
    args = aq.build_parser().parse_args(["check", str(good), "--run"])
    assert aq.cmd_check(args, executor=_ok_executor) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["verify"]["passed"] is True


# ---------------------------------------------------------------------------
# Workflow definition (parsed as text: stdlib only)
# ---------------------------------------------------------------------------

def _job_blocks(text):
    jobs = text.split("\njobs:\n", 1)[1]
    blocks = {}
    current = None
    for line in jobs.split("\n"):
        match = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if match:
            current = match.group(1)
            blocks[current] = []
        elif current:
            blocks[current].append(line)
    return {k: "\n".join(v) for k, v in blocks.items()}


def test_workflow_triggers_and_gate():
    text = WORKFLOW.read_text()
    top = text.split("\njobs:\n", 1)[0]
    assert re.search(r"^  discussion_comment:\n    types: \[created\]$", top, re.M)
    assert "workflow_dispatch:" in top and "discussion_number:" in top and "comment_id:" in top
    assert "schedule:" not in text and "cron" not in text
    assert re.search(r"^permissions: \{\}$", top, re.M)
    jobs = _job_blocks(text)
    assert set(jobs) == {"run", "record"}
    for block in jobs.values():
        assert "vars.ANSWER_QA == 'true'" in block
        # only the exact value 'true' enables a job: no other mode exists
        assert re.findall(r"vars\.ANSWER_QA\s*==\s*'([^']*)'", block) == ["true"]
        assert "vars.ANSWER_QA !=" not in block
    assert "== 'dry-run'" not in text


def test_workflow_concurrency_keys_and_rate_cap():
    text = WORKFLOW.read_text()
    top = text.split("\njobs:\n", 1)[0]
    assert "group: answer-qa-${{ github.event.comment.node_id || inputs.comment_id }}" in top
    run = _job_blocks(text)["run"]
    assert "group: answer-qa-sandbox-${{ github.event.comment.user.login || 'dispatch' }}" in run


def test_run_job_has_empty_permissions_and_no_secrets():
    text = WORKFLOW.read_text()
    assert "secrets." not in text and "secrets[" not in text
    run = _job_blocks(text)["run"]
    perms = re.findall(r"^    permissions:(.*)$", run, re.M)
    assert perms == [" {}"]
    assert "write" not in run
    assert "persist-credentials: false" in run


def test_record_job_writes_only_discussions_and_runs_no_artifact_code():
    record = _job_blocks(WORKFLOW.read_text())["record"]
    assert "needs: run" in record
    perms = record.split("    permissions:\n", 1)[1].split("\n    timeout-minutes", 1)[0]
    assert perms.split() == ["contents:", "read", "discussions:", "write"]
    assert "answer_qa.py record" in record
    assert "docker" not in record
    assert "bash $" not in record and "python3 $" not in record


def test_workflow_never_interpolates_event_text_into_run_lines():
    text = WORKFLOW.read_text()
    in_run = False
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("run:"):
            in_run = True
            assert "${{" not in stripped
            continue
        if in_run:
            if re.match(r"^\s*(- name:|- uses:|env:|with:|id:|[a-z-]+:\s)", line) and not line.startswith(" " * 12):
                in_run = False
            else:
                assert "${{" not in line, line


def test_extract_tilde_fence_and_workflow_prefilter_agree():
    assert aq.extract("environment: bash\n\n~~~sh\necho hi\n~~~\n")["runnable"]
    run = _job_blocks(WORKFLOW.read_text())["run"]
    assert "'```'" in run and "'~~~'" in run
