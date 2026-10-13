#!/usr/bin/env python3
"""Answers that ran: execute the code in a q-a/code answer and record a vote.

A Discussion comment in the ``q-a`` or ``code`` category whose first line is
``environment: <runtime>/...`` and which contains exactly one fenced code
block is run by the platform in a locked-down container, and the result is
posted back as a threaded reply carrying a ``rapp-verification/1`` verify
block (see docs/VERIFICATIONS.md, "Answers that ran").

Subcommands:
    check FILE [--run]
        Preflight: parse a comment body from FILE (``-`` = stdin) and say
        whether the platform would run it, in which image, under which
        content id. ``--run`` also executes it locally (needs docker).
        Exit 0 = runnable, 1 = would be skipped.
    run --discussion N --comment DC_ID --out RESULT.json
        Workflow job 1 (no write token, no secrets): fetch the comment,
        extract the code, run it in docker, write a small result JSON.
    record --discussion N --comment DC_ID --result RESULT.json [--apply]
        Workflow job 2 (discussions: write): re-fetch the comment, validate
        the untrusted result JSON, render the reply and post it once
        through clients/rappterbook_client.py (the single owner of social
        mutations). Dry-run unless ``--apply``. Never executes anything.

Comments are named by their GraphQL node id (``DC_...``) only, never by the
numeric database id, so every run for one comment shares one workflow
concurrency key and two runs cannot both pass the "already posted" check.

Everything read from Discussions or from the result artifact is data. No
comment text ever reaches a shell: docker is invoked with an argument list,
the code travels as a file mounted read-only. Python 3.9+, stdlib only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Callable, Optional

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))
import verifications  # noqa: E402
from outside_identity import is_automation_login  # noqa: E402

RESULT_SCHEMA = "answer-qa-result/1"
CATEGORIES = ("q-a", "code")
# The identity the platform votes under. GitHub posts the reply as
# github-actions[bot], which record() refuses (automation logins do not
# vote); compute_reputation.py maps a reply authored by exactly
# PLATFORM_LOGINS AND starting with the marker to this key (see
# platform_vote()). The body's "verifier" field is informational:
# parse_comment drops it.
PLATFORM_VERIFIER = "rappterbook-sandbox"
# The workflow token posts as this account: GraphQL reports the login as
# "github-actions", REST as "github-actions[bot]". No other app or bot counts.
PLATFORM_LOGINS = ("github-actions", "github-actions[bot]")
MARKER_PREFIX = "<!-- answer-qa:v1"
MARKER_RE = re.compile(
    r"^<!-- answer-qa:v1 comment=(DC_[A-Za-z0-9_-]{1,80}) code=(sha256:[0-9a-f]{64}) -->$")

MAX_COMMENT_CHARS = 20_000
MAX_CODE_BYTES = 16 * 1024
MAX_CODE_LINES = 400
MAX_OUTPUT_BYTES = 4096          # kept per stream in the artifact
MAX_RESULT_BYTES = 64 * 1024     # the artifact the record job will accept
RUN_TIMEOUT_S = 60
PULL_TIMEOUT_S = 300
NOTES_OUTPUT_LINES = 5
NOTES_OUTPUT_CHARS = 400

# runtime token -> (image, entrypoint, file name, accepted fence info strings)
RUNTIMES = {
    "python-3.9": ("python:3.9-slim", "python3", "main.py", ("", "python", "py", "python3")),
    "python-3.11": ("python:3.11-slim", "python3", "main.py", ("", "python", "py", "python3")),
    "python-3.12": ("python:3.12-slim", "python3", "main.py", ("", "python", "py", "python3")),
    "node-20": ("node:20-slim", "node", "main.js", ("", "js", "javascript", "node")),
    "bash": ("bash:5.2", "bash", "main.sh", ("", "bash", "sh", "shell")),
}
_ENTRY_ARGS = {"python3": ["-I", "-B"], "node": [], "bash": []}

_ENV_LINE_RE = re.compile(r"^environment:[ \t]*(\S.*?)[ \t]*$", re.IGNORECASE)
_RUNTIME_ALIASES = (
    (re.compile(r"^python-3\.(9|11|12)(?:\.\d{1,3})?$"), lambda m: "python-3." + m.group(1)),
    (re.compile(r"^node-20(?:\.\d{1,3}){0,2}$"), lambda m: "node-20"),
    (re.compile(r"^bash(?:-5(?:\.\d{1,3}){0,2})?$"), lambda m: "bash"),
)
_INDENTED_FENCE_RE = re.compile(r"^ {1,3}(?:`{3,}|~{3,})")
# Relay prefixes the house fleet puts above an agent's own text (anchored,
# whole-line copies of outside_identity.COMMENT_BYLINE_RE and
# LEGACY_COMMENT_BYLINE_RE, plus the client's nested-reply thread marker).
_THREAD_MARKER_LINE_RE = re.compile(r"^<!--[ \t]*thread:\S+[ \t]*-->[ \t]*$")
_BYLINE_LINE_RES = (
    re.compile(r"^[ \t]*\*?[—-][ \t]+\*\*[^*\n]+\*\*\*?[ \t]*$"),
    re.compile(r"^[ \t]*[—-][ \t]+\*[^*\n]+\*[ \t]*$"),
)
_NODE_ID_RE = re.compile(r"^DC_[A-Za-z0-9_-]{1,80}$")
_DB_ID_RE = re.compile(r"^[1-9][0-9]{0,15}$")
_REPO_RE = re.compile(r"^[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}$")
_CONTROL_KEEP_NL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
GRAPHQL_URL = "https://api.github.com/graphql"


# ---------------------------------------------------------------------------
# Strict parser
# ---------------------------------------------------------------------------

def _skip(reason: str, **extra) -> dict:
    out = {"runnable": False, "reason": reason}
    out.update(extra)
    return out


def _environment_candidate(lines: list) -> str:
    """The line that must read ``environment: ...``.

    The first non-blank line, after skipping at most one client thread
    marker (``<!-- thread:DC_x -->``, added to nested replies) and then at
    most one relay byline (``*— **agent-id***``) that the house fleet puts
    above an agent's own text. Nothing else is skipped.
    """
    rest = [ln for ln in lines if ln.strip()]
    if rest and _THREAD_MARKER_LINE_RE.match(rest[0]):
        rest = rest[1:]
    if rest and any(rx.match(rest[0]) for rx in _BYLINE_LINE_RES):
        rest = rest[1:]
    return rest[0] if rest else ""


def _scan_fences(text: str) -> dict:
    """Line-aware twin of ``verifications._fenced_blocks``.

    Returns ``{"blocks", "unterminated", "indented_fence"}``: the same
    ``(fence_char, info, content)`` tuples, whether a fence is still open at
    the end of the comment (GitHub renders that as a code block running to
    the end, so readers would see code the platform never ran), and whether
    a fence-like line indented 1-3 spaces sits OUTSIDE every fenced block (a
    fence-like line inside the code itself, e.g. Python printing Markdown, is
    content). extract() refuses when ``blocks`` differs from what the library
    yields, so the two scanners cannot drift apart silently.
    """
    open_fence = ""
    info = ""
    buffer: list = []
    html_closers: tuple = ()
    html_until_blank = False
    in_paragraph = False
    blocks: list = []
    indented = False
    for line in text.split("\n"):
        if open_fence:
            stripped = line.strip(" \t")
            if (verifications._indent_columns(line) <= 3 and stripped.startswith(open_fence)
                    and set(stripped) == {open_fence[0]}):
                blocks.append((open_fence[0], info, "\n".join(buffer)))
                open_fence, info, buffer = "", "", []
            else:
                buffer.append(line)
            continue
        if _INDENTED_FENCE_RE.match(line):
            indented = True
        if html_closers:
            lowered = line.lower()
            if any(closer in lowered for closer in html_closers):
                html_closers = ()
            continue
        if html_until_blank:
            if not line.strip(" \t"):
                html_until_blank = False
            continue
        if not line.strip(" \t"):
            in_paragraph = False
            continue
        if verifications._indent_columns(line) > 3:
            continue
        if verifications._html_block_opens(line, in_paragraph=in_paragraph):
            html_closers, html_until_blank = verifications._html_block_end(line)
            in_paragraph = False
            continue
        match = verifications._FENCE_OPEN_RE.match(line)
        if match:
            fence, rest = match.groups()
            info_string = rest.strip()
            if fence[0] == "`" and "`" in info_string:
                in_paragraph = True
                continue
            open_fence = fence
            info = info_string.split()[0].lower() if info_string else ""
            buffer = []
            in_paragraph = False
            continue
        in_paragraph = not verifications._PARAGRAPH_ENDER_RE.match(line)
    return {"blocks": blocks, "unterminated": bool(open_fence), "indented_fence": indented}


def extract(body: object) -> dict:
    """Parse a comment body. Returns a dict with ``runnable`` and either
    ``reason`` (skipped) or ``runtime``, ``image``, ``code``, ``content_id``,
    ``environment`` (the claimed line, cleaned)."""
    if not isinstance(body, str):
        return _skip("comment body is not text")
    if len(body) > MAX_COMMENT_CHARS:
        return _skip(f"comment is over {MAX_COMMENT_CHARS} characters")
    if "\x00" in body:
        return _skip("comment contains a NUL character")
    text = body.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    lines = text.split("\n")
    first = _environment_candidate(lines)
    match = _ENV_LINE_RE.match(first)
    if not match:
        return _skip("first line is not 'environment: <runtime>/...'")
    claimed = " ".join(match.group(1).split())
    if len(claimed) > verifications.MAX_ENVIRONMENT:
        return _skip(f"environment line is over {verifications.MAX_ENVIRONMENT} characters")
    token = claimed.split("/", 1)[0].strip().lower()
    runtime = None
    for pattern, canon in _RUNTIME_ALIASES:
        hit = pattern.match(token)
        if hit:
            runtime = canon(hit)
            break
    if runtime is None:
        return _skip(
            f"environment '{token[:40]}' has no sandbox image (supported: {', '.join(sorted(RUNTIMES))})",
            environment=claimed,
        )
    scan = _scan_fences(text)
    blocks = list(verifications._fenced_blocks(text))
    if scan["blocks"] != blocks:
        return _skip("code fences could not be parsed unambiguously", environment=claimed)
    if scan["indented_fence"]:
        return _skip("indented code fence: put the code block at column 0", environment=claimed)
    if scan["unterminated"]:
        return _skip("unterminated fenced code block: close every fence", environment=claimed)
    if not blocks:
        return _skip("no complete fenced code block", environment=claimed)
    if len(blocks) > 1:
        return _skip(f"{len(blocks)} fenced code blocks: post exactly one", environment=claimed)
    _fence, info, code = blocks[0]
    image, _entry, _fname, infos = RUNTIMES[runtime]
    if info not in infos:
        return _skip(f"code block language '{info[:20]}' does not match environment {runtime}",
                     environment=claimed)
    if not code.strip():
        return _skip("code block is empty", environment=claimed)
    if len(code.encode("utf-8", "surrogatepass")) > MAX_CODE_BYTES:
        return _skip(f"code block is over {MAX_CODE_BYTES} bytes", environment=claimed)
    if code.count("\n") + 1 > MAX_CODE_LINES:
        return _skip(f"code block is over {MAX_CODE_LINES} lines", environment=claimed)
    return {
        "runnable": True,
        "runtime": runtime,
        "image": image,
        "code": code,
        "content_id": verifications.content_id(code),
        "environment": claimed,
    }


# ---------------------------------------------------------------------------
# Sandbox execution
# ---------------------------------------------------------------------------

def _drain(stream, keep: int, sink: list) -> None:
    kept = bytearray()
    total = 0
    while True:
        chunk = stream.read(65536)
        if not chunk:
            break
        total += len(chunk)
        if len(kept) < keep:
            kept.extend(chunk[: keep - len(kept)])
    sink.append((bytes(kept), total > keep))


def docker_command(runtime: str, code_dir: str, name: str) -> list:
    """The exact ``docker create`` argument list for one sandboxed run (no shell).

    The container is created, started attached, inspected and removed
    rather than run with ``docker run --rm``: ``docker run`` exits 125 both
    when docker itself fails and when the program calls ``exit(125)``, so a
    program could turn its own failures into "sandbox error, no vote" and
    keep only its passes. ``docker inspect`` tells the two apart: a
    container that started has a real ``StartedAt`` and its own exit code.
    """
    image, entry, fname, _infos = RUNTIMES[runtime]
    return [
        "docker", "create", "--name", name,
        "--network", "none",
        "--memory", "512m", "--memory-swap", "512m",
        "--cpus", "1",
        "--pids-limit", "128",
        "--read-only",
        "--tmpfs", "/work:rw,nosuid,nodev,size=64m,mode=1777",
        "--tmpfs", "/tmp:rw,nosuid,nodev,size=16m,mode=1777",
        "--workdir", "/work",
        "--user", "65534:65534",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--ulimit", "nofile=256:256",
        "--env", "HOME=/work",
        "--volume", f"{code_dir}:/code:ro",
        "--entrypoint", entry,
        image,
        *_ENTRY_ARGS[entry], f"/code/{fname}",
    ]


def code_file_bytes(code: str) -> bytes:
    """The exact bytes written to the code file.

    The same normalization as ``verifications.content_id`` (CRLF/CR -> LF,
    trailing newlines dropped) plus one final newline, so one subject always
    runs as one byte string: an edit that only adds blank lines before the
    closing fence keeps its content id AND its executed bytes.
    """
    normalized = code.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
    return (normalized + "\n").encode("utf-8", "surrogatepass")


def _container_state(name: str, run) -> Optional[dict]:
    """``docker inspect`` of the finished container, or None when unreadable."""
    try:
        proc = run(["docker", "inspect", "--type", "container", "--format", "{{json .State}}", name],
                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    raw = proc.stdout
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    try:
        state = json.loads(raw or "")
    except ValueError:
        return None
    if not isinstance(state, dict):
        return None
    exit_code = state.get("ExitCode")
    started_at = state.get("StartedAt")
    if type(exit_code) is not int or not isinstance(started_at, str):  # noqa: E721 - no bools
        return None
    started = bool(started_at) and not started_at.startswith("0001-01-01") and not state.get("Error")
    return {"exit_code": exit_code, "started": started}


def _quiet(run, cmd: list) -> None:
    """Best-effort docker housekeeping (kill, rm); failures are ignored."""
    try:
        run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        pass


def execute(runtime: str, code: str, *, popen=subprocess.Popen, run=subprocess.run,
            timeout: int = RUN_TIMEOUT_S) -> dict:
    """Run ``code`` in the allowlisted image. Returns the measured outcome.

    ``status`` is ``ran`` (the container started; its own exit code or a
    timeout was observed) or ``error`` (the sandbox itself failed: no
    docker, pull or create failed, the container never started, inspect
    failed), which is never a vote. A program that exits 125 itself is a
    normal fail, because the exit code comes from ``docker inspect`` of a
    container that is known to have started.
    """
    if runtime not in RUNTIMES:
        raise ValueError("runtime is not allowlisted")
    image, _entry, fname, _infos = RUNTIMES[runtime]
    try:
        pulled = run(["docker", "pull", "--quiet", image], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, timeout=PULL_TIMEOUT_S, check=False)
        if pulled.returncode != 0:
            return {"status": "error", "reason": f"docker pull {image} failed"}
    except (OSError, subprocess.TimeoutExpired):
        return {"status": "error", "reason": "docker is not available"}
    workdir = tempfile.mkdtemp(prefix="answer-qa-")
    name = "answer-qa-" + uuid.uuid4().hex[:16]
    create_attempted = False
    try:
        os.chmod(workdir, 0o755)
        path = Path(workdir) / fname
        path.write_bytes(code_file_bytes(code))
        os.chmod(path, 0o644)
        create_attempted = True
        try:
            made = run(docker_command(runtime, workdir, name), stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=120, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return {"status": "error", "reason": "docker create failed"}
        if made.returncode != 0:
            return {"status": "error", "reason": "docker create failed"}
        started = time.monotonic()
        try:
            proc = popen(["docker", "start", "--attach", name], stdin=subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError:
            return {"status": "error", "reason": "docker is not available"}
        out_sink: list = []
        err_sink: list = []
        readers = [threading.Thread(target=_drain, args=(proc.stdout, MAX_OUTPUT_BYTES, out_sink), daemon=True),
                   threading.Thread(target=_drain, args=(proc.stderr, MAX_OUTPUT_BYTES, err_sink), daemon=True)]
        for reader in readers:
            reader.start()
        timed_out = False
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _quiet(run, ["docker", "kill", name])
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        duration = round(time.monotonic() - started, 2)
        for reader in readers:
            reader.join(timeout=10)
        stdout, out_trunc = out_sink[0] if out_sink else (b"", False)
        stderr, err_trunc = err_sink[0] if err_sink else (b"", False)
        # The exit status of `docker start --attach` is not trusted: 125 there
        # can be docker's or the program's. Ask docker what the container did.
        state = _container_state(name, run)
        if state is None:
            return {"status": "error", "reason": "docker inspect failed"}
        if not state["started"]:
            return {"status": "error", "reason": "the container did not start"}
        exit_code = None if timed_out else state["exit_code"]
        if exit_code is not None and not 0 <= exit_code <= 255:
            return {"status": "error", "reason": "docker reported an impossible exit code"}
        return {
            "status": "ran",
            "exit_code": exit_code,
            "timed_out": timed_out,
            "duration_s": duration,
            "stdout": stdout.decode("utf-8", "replace"),
            "stderr": stderr.decode("utf-8", "replace"),
            "stdout_truncated": out_trunc,
            "stderr_truncated": err_trunc,
        }
    finally:
        if create_attempted:
            _quiet(run, ["docker", "rm", "--force", name])
        shutil.rmtree(workdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# GitHub reads and writes (GraphQL, urllib; injectable for tests)
# ---------------------------------------------------------------------------

def graphql(query: str, variables: dict, token: Optional[str] = None) -> dict:
    token = token if token is not None else os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is not set")
    req = urllib.request.Request(
        GRAPHQL_URL,
        data=json.dumps({"query": query, "variables": variables}).encode("utf-8"),
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json",
                 "User-Agent": "rappterbook-answer-qa"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - fixed https URL
            payload = json.loads(resp.read(5_000_000).decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise RuntimeError(f"GraphQL request failed: {exc.__class__.__name__}") from exc
    if not isinstance(payload, dict) or payload.get("errors") or not isinstance(payload.get("data"), dict):
        raise RuntimeError("GraphQL returned errors")
    return payload["data"]


_COMMENT_FIELDS = """
  id databaseId body url isMinimized
  author { login }
  replyTo { id }
  discussion { id number category { slug } repository { nameWithOwner } }
"""
_NODE_QUERY = "query($id: ID!) { node(id: $id) { ... on DiscussionComment {" + _COMMENT_FIELDS + "} } }"
_REPLIES_QUERY = """
query($id: ID!, $after: String) { node(id: $id) { ... on DiscussionComment {
  replies(first: 100, after: $after) { pageInfo { hasNextPage endCursor }
    nodes { body author { login } } } } } }
"""
MAX_PAGES = 20


def _repo() -> str:
    repo = os.environ.get("GITHUB_REPOSITORY", "kody-w/rappterbook")
    if not _REPO_RE.match(repo):
        raise ValueError("GITHUB_REPOSITORY is not owner/name")
    return repo


def _check_ids(discussion: object, comment: object) -> tuple:
    """Validate the discussion number and the comment's ``DC_`` node id.

    Numeric database ids are refused: the workflow's concurrency group is
    keyed on the id it was given, so accepting two spellings of one comment
    would let two runs race past the "already posted" check.
    """
    number = str(discussion).strip()
    ident = str(comment).strip()
    if not _DB_ID_RE.match(number):
        raise ValueError("discussion number must be a positive integer")
    if not _NODE_ID_RE.match(ident):
        raise ValueError("comment id must be a DC_ node id (numeric database ids are not accepted)")
    return int(number), ident


def fetch_comment(discussion: object, comment: object, gql: Callable = None) -> dict:
    """Fetch one discussion comment of this repository by its ``DC_`` node id.

    Raises ValueError when the ids are malformed or the comment does not
    belong to discussion ``discussion`` of ``GITHUB_REPOSITORY``.
    """
    gql = gql or graphql
    number, node_id = _check_ids(discussion, comment)
    repo = _repo()
    node = gql(_NODE_QUERY, {"id": node_id}).get("node") or {}
    disc = node.get("discussion") or {}
    if (((disc.get("repository") or {}).get("nameWithOwner")) or "").lower() != repo.lower():
        raise ValueError("comment is not in this repository")
    if disc.get("number") != number:
        raise ValueError("comment is not in that discussion")
    if not isinstance(node.get("body"), str) or not isinstance(node.get("id"), str):
        raise ValueError("comment has no body")
    return {
        "id": node["id"],
        "url": node.get("url") or "",
        "body": node["body"],
        "minimized": bool(node.get("isMinimized")),
        "author": ((node.get("author") or {}).get("login")) or "",
        "reply_to": ((node.get("replyTo") or {}).get("id")) or None,
        "discussion_id": disc.get("id") or "",
        "discussion_number": number,
        "category": ((disc.get("category") or {}).get("slug")) or "",
    }


def _from_event_payload(discussion: int, comment: str) -> Optional[dict]:
    """Fallback for job 1 when the no-permission token cannot read GraphQL:
    the discussion_comment event payload already carries the body."""
    path = os.environ.get("GITHUB_EVENT_PATH")
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            event = json.load(fh)
    except (OSError, ValueError):
        return None
    c = event.get("comment") or {}
    d = event.get("discussion") or {}
    if d.get("number") != discussion or comment != c.get("node_id"):
        return None
    if not isinstance(c.get("body"), str):
        return None
    return {
        "id": c.get("node_id") or "", "url": c.get("html_url") or "", "body": c["body"],
        "minimized": False, "author": ((c.get("user") or {}).get("login")) or "",
        "reply_to": None, "discussion_id": d.get("node_id") or "",
        "discussion_number": discussion, "category": ((d.get("category") or {}).get("slug")) or "",
    }


def eligibility(comment: dict) -> Optional[str]:
    """Reason the comment is out of scope, or None."""
    if comment.get("category") not in CATEGORIES:
        return "discussion is not in the q-a or code category"
    if not comment.get("author") or is_automation_login(comment["author"]):
        return "comment author is an automation account"
    if comment.get("minimized"):
        return "comment is minimized"
    return None


# ---------------------------------------------------------------------------
# Result artifact (untrusted when read back)
# ---------------------------------------------------------------------------

def build_result(comment: dict, parsed: dict, outcome: Optional[dict]) -> dict:
    result = {
        "schema": RESULT_SCHEMA,
        "comment_id": comment.get("id", ""),
        "discussion_number": comment.get("discussion_number"),
    }
    if not parsed.get("runnable"):
        result.update(status="skipped", reason=parsed.get("reason", ""))
        return result
    result.update(content_id=parsed["content_id"], runtime=parsed["runtime"], image=parsed["image"])
    if outcome is None or outcome.get("status") != "ran":
        result.update(status="error", reason=(outcome or {}).get("reason", "not run"))
        return result
    result.update({k: outcome[k] for k in ("exit_code", "timed_out", "duration_s", "stdout", "stderr",
                                           "stdout_truncated", "stderr_truncated")})
    result["status"] = "ran"
    return result


def _no_dupes(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate key")
        out[key] = value
    return out


def _bad_constant(name):
    raise ValueError(f"{name} is not allowed")


def load_result(path: object) -> dict:
    """Read and strictly validate the result artifact. Raises ValueError."""
    p = Path(str(path))
    try:
        if p.is_symlink() or not p.is_file():
            raise ValueError("result is not a regular file")
        raw = p.read_bytes()
    except OSError as exc:
        raise ValueError("result is unreadable") from exc
    if len(raw) > MAX_RESULT_BYTES:
        raise ValueError("result is too large")
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_dupes, parse_constant=_bad_constant)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise ValueError("result is not strict JSON") from exc
    if not isinstance(data, dict) or data.get("schema") != RESULT_SCHEMA:
        raise ValueError("result schema mismatch")
    status = data.get("status")
    if status not in ("ran", "skipped", "error"):
        raise ValueError("result status invalid")
    if not isinstance(data.get("comment_id"), str) or type(data.get("discussion_number")) is not int:
        raise ValueError("result ids invalid")
    if status != "ran":
        return {"schema": RESULT_SCHEMA, "status": status, "comment_id": data["comment_id"],
                "discussion_number": data["discussion_number"],
                "reason": str(data.get("reason", ""))[:200]}
    runtime = data.get("runtime")
    if not isinstance(runtime, str) or runtime not in RUNTIMES or data.get("image") != RUNTIMES[runtime][0]:
        raise ValueError("result runtime/image not allowlisted")
    cid = data.get("content_id")
    if not isinstance(cid, str) or not verifications._CONTENT_ID_RE.fullmatch(cid):
        raise ValueError("result content_id invalid")
    timed_out = data.get("timed_out")
    exit_code = data.get("exit_code")
    if type(timed_out) is not bool:
        raise ValueError("timed_out must be boolean")
    if timed_out:
        if exit_code is not None:
            raise ValueError("timed out run has an exit code")
    elif type(exit_code) is not int or not 0 <= exit_code <= 255:
        raise ValueError("exit_code invalid")
    duration = data.get("duration_s")
    if type(duration) not in (int, float) or not 0 <= duration <= 3600:
        raise ValueError("duration_s invalid")
    for key in ("stdout", "stderr"):
        if not isinstance(data.get(key), str) or len(data[key].encode("utf-8", "surrogatepass")) > MAX_OUTPUT_BYTES * 4:
            raise ValueError(f"{key} invalid")
    for key in ("stdout_truncated", "stderr_truncated"):
        if type(data.get(key)) is not bool:
            raise ValueError(f"{key} invalid")
    return {k: data[k] for k in ("schema", "status", "comment_id", "discussion_number", "runtime", "image",
                                 "content_id", "exit_code", "timed_out", "duration_s", "stdout", "stderr",
                                 "stdout_truncated", "stderr_truncated")}


# ---------------------------------------------------------------------------
# Rendering the reply
# ---------------------------------------------------------------------------

def _clean(text: str) -> str:
    text = unicodedata.normalize("NFC", text.encode("utf-8", "replace").decode("utf-8"))
    text = _CONTROL_KEEP_NL_RE.sub("", text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", "  "))
    return verifications._INVISIBLE_RE.sub("", text)


def _first_lines(text: str) -> str:
    lines = [ln.rstrip() for ln in _clean(text).strip().split("\n")][:NOTES_OUTPUT_LINES]
    out = "\n".join(lines)
    if len(out) > NOTES_OUTPUT_CHARS:
        out = out[:NOTES_OUTPUT_CHARS].rstrip() + " ..."
    return out


def marker(comment_id: str, content_id: str) -> str:
    return f"{MARKER_PREFIX} comment={comment_id} code={content_id} -->"


def verify_record(result: dict) -> dict:
    """The rapp-verification/1 vote for a validated ``ran`` result."""
    passed = (not result["timed_out"]) and result["exit_code"] == 0
    if result["timed_out"]:
        head = f"timed out after {RUN_TIMEOUT_S} s (killed)"
    else:
        head = f"exit code {result['exit_code']} in {result['duration_s']} s"
        if result["exit_code"] == 137:
            head += " (SIGKILL: likely the 512 MB memory limit)"
    parts = [f"{head}; image {result['image']}; no network, 512 MB, 1 CPU"]
    for key in ("stdout", "stderr"):
        shown = _first_lines(result[key])
        if shown:
            parts.append(f"{key}:\n{shown}")
    notes = "\n".join(parts)
    if len(notes) > verifications.MAX_NOTES:
        notes = notes[: verifications.MAX_NOTES - 4].rstrip() + " ..."
    return {
        "action": "verify",
        "schema": verifications.SCHEMA,
        "verifier": PLATFORM_VERIFIER,
        "subject": result["content_id"],
        "subject_kind": "post",
        "environment": f"{result['runtime']}/docker:{result['image']}/network-none",
        "passed": passed,
        "notes": notes,
    }


def render_reply(result: dict, answer_url: str = "") -> str:
    """Reply body: marker line, one human sentence, one fenced verify block."""
    rec = verify_record(result)
    if result["timed_out"]:
        outcome = f"it was stopped after {RUN_TIMEOUT_S} s without finishing"
    elif rec["passed"]:
        outcome = f"it exited 0 in {result['duration_s']} s"
    else:
        outcome = f"it exited with code {result['exit_code']} in {result['duration_s']} s"
    where = "the answer above" if not answer_url else f"[this answer]({answer_url})"
    sentence = (
        f"The platform ran the code in {where} in `{result['image']}` "
        f"(no network, 512 MB, 1 CPU, {RUN_TIMEOUT_S} s limit) and {outcome}. "
        "This is one automated vote on the exact code bytes, not a review."
    )
    block = json.dumps(rec, indent=2, ensure_ascii=False)
    return f"{marker(result['comment_id'], result['content_id'])}\n{sentence}\n\n```json\n{block}\n```\n"


def is_platform_login(login: object) -> bool:
    """True only for the workflow token's own account (not any ``*[bot]``)."""
    return isinstance(login, str) and login.strip().lower() in PLATFORM_LOGINS


def already_posted(replies: list, mark: str) -> bool:
    """True when the workflow's own account already replied with this marker on its first line.

    Only ``github-actions`` / ``github-actions[bot]`` counts: another app
    installed on the repository posting the marker cannot suppress a result.
    """
    for reply in replies:
        if not isinstance(reply, dict):
            continue
        body = reply.get("body") or ""
        login = ((reply.get("author") or {}).get("login")) or ""
        if is_platform_login(login) and isinstance(body, str) and body.split("\n", 1)[0].strip() == mark:
            return True
    return False


def platform_vote(body: object) -> Optional[tuple]:
    """``(comment_id, content_id)`` named by a platform reply's marker line, else None.

    Only the marker's shape is checked here; the caller must also check the
    author (``is_platform_login``), that the named comment is in the same
    discussion, and that ``extract(named comment)["content_id"]`` equals both
    the marker's code id and the verify block's subject.
    """
    if not isinstance(body, str):
        return None
    first = body.replace("\r\n", "\n").replace("\r", "\n").split("\n", 1)[0].strip()
    match = MARKER_RE.match(first)
    return (match.group(1), match.group(2)) if match else None


def _client_module():
    """clients/rappterbook_client.py, the single owner of social mutations."""
    clients = str(_SCRIPTS.parent / "clients")
    if clients not in sys.path:
        sys.path.insert(0, clients)
    import rappterbook_client  # noqa: E402
    return rappterbook_client


def post_reply(discussion_id: str, reply_to_id: str, body: str, gql: Callable = None) -> None:
    """Post one threaded reply through the shared client. Raises RuntimeError on failure.

    ``gql`` (tests) replaces the client's HTTP transport; it returns the
    GraphQL ``data`` object, as ``graphql()`` does.
    """
    client_mod = _client_module()
    owner, name = _repo().split("/", 1)
    transport = None
    if gql is not None:
        def transport(query, variables=None):
            return {"data": gql(query, variables or {})}
    client = client_mod.RappterbookClient(owner=owner, repo=name, token=os.environ.get("GITHUB_TOKEN", ""),
                                          graphql_transport=transport)
    try:
        client.add_comment_by_id(discussion_id, body, reply_to_id)
    except (RuntimeError, ValueError, KeyError, TypeError, OSError) as exc:
        raise RuntimeError(f"{exc.__class__.__name__}") from exc


def _thread_replies(top_id: str, gql: Callable) -> list:
    replies: list = []
    after = None
    for _page in range(MAX_PAGES):
        node = gql(_REPLIES_QUERY, {"id": top_id, "after": after}).get("node") or {}
        conn = node.get("replies") or {}
        replies.extend(conn.get("nodes") or [])
        info = conn.get("pageInfo") or {}
        if not info.get("hasNextPage"):
            return replies
        after = info.get("endCursor")
    raise RuntimeError("too many replies to check for an existing result; refusing to post")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def _write_json(path: str, data: dict) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def cmd_check(args, *, executor: Callable = execute) -> int:
    try:
        body = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"cannot read {args.file}: {exc.__class__.__name__}", file=sys.stderr)
        return 2
    parsed = extract(body)
    report = {k: v for k, v in parsed.items() if k != "code"}
    if parsed["runnable"] and args.run:
        outcome = executor(parsed["runtime"], parsed["code"])
        result = build_result({"id": "local", "discussion_number": 0}, parsed, outcome)
        report["result"] = result
        if result["status"] == "ran":
            report["verify"] = verify_record(result)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if parsed["runnable"] else 1


def cmd_run(args, *, gql: Callable = None, executor: Callable = execute) -> int:
    try:
        number, ident = _check_ids(args.discussion, args.comment)
    except ValueError as exc:
        print(f"answer-qa: {exc}", file=sys.stderr)
        return 2
    try:
        comment = fetch_comment(number, ident, gql)
    except (RuntimeError, ValueError) as exc:
        comment = _from_event_payload(number, ident)
        if comment is None:
            print(f"answer-qa: cannot fetch comment: {exc}", file=sys.stderr)
            return 2
        print("answer-qa: GraphQL read failed; using the event payload")
    reason = eligibility(comment)
    parsed = _skip(reason) if reason else extract(comment["body"])
    outcome = executor(parsed["runtime"], parsed["code"]) if parsed["runnable"] else None
    result = build_result(comment, parsed, outcome)
    _write_json(args.out, result)
    gh_output = os.environ.get("GITHUB_OUTPUT")
    if gh_output:
        with open(gh_output, "a", encoding="utf-8") as fh:
            fh.write(f"status={result['status']}\n")
    detail = result.get("reason") or f"exit={result.get('exit_code')} timed_out={result.get('timed_out')}"
    print(f"answer-qa: {result['status']}: {detail}")
    return 0


def cmd_record(args, *, gql: Callable = None) -> int:
    gql = gql or graphql
    try:
        number, ident = _check_ids(args.discussion, args.comment)
        result = load_result(args.result)
    except (ValueError, TypeError) as exc:
        print(f"answer-qa: refusing: {exc}", file=sys.stderr)
        return 2
    if result["status"] != "ran":
        print(f"answer-qa: nothing to record ({result['status']}: {result.get('reason', '')})")
        return 0
    try:
        comment = fetch_comment(number, ident, gql)
    except (RuntimeError, ValueError) as exc:
        print(f"answer-qa: cannot fetch comment: {exc}", file=sys.stderr)
        return 2
    if comment["id"] != result["comment_id"] or result["discussion_number"] != number:
        print("answer-qa: refusing: result is for a different comment", file=sys.stderr)
        return 2
    reason = eligibility(comment)
    parsed = _skip(reason) if reason else extract(comment["body"])
    if not parsed["runnable"]:
        print(f"answer-qa: comment no longer runnable ({parsed['reason']}); not posting")
        return 0
    if parsed["content_id"] != result["content_id"] or parsed["runtime"] != result["runtime"]:
        print("answer-qa: code or environment changed since the run; not posting")
        return 0
    body = render_reply(result, comment["url"])
    if verifications.parse_comment(body) is None:  # never post a block the library would drop
        print("answer-qa: refusing: rendered reply does not parse as a verify block", file=sys.stderr)
        return 2
    mark = marker(comment["id"], result["content_id"])
    top_id = comment["reply_to"] or comment["id"]
    try:
        if already_posted(_thread_replies(top_id, gql), mark):
            print("answer-qa: already recorded; nothing to do")
            return 0
    except RuntimeError as exc:
        print(f"answer-qa: {exc}", file=sys.stderr)
        return 2
    if not args.apply:
        print("answer-qa: dry-run, would reply:\n" + body)
        return 0
    # Write cap: exactly one comment per run.
    try:
        post_reply(comment["discussion_id"], top_id, body, gql if gql is not graphql else None)
    except RuntimeError as exc:
        print(f"answer-qa: post failed: {exc}", file=sys.stderr)
        return 2
    print("answer-qa: posted 1 reply")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="answer_qa.py", description="Run q-a/code answers and record the result.")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="preflight a comment body from a file ('-' = stdin)")
    check.add_argument("file")
    check.add_argument("--run", action="store_true", help="also run it locally in docker")
    run = sub.add_parser("run", help="workflow job 1: fetch, extract, run, write result JSON")
    run.add_argument("--discussion", required=True)
    run.add_argument("--comment", required=True)
    run.add_argument("--out", required=True)
    record = sub.add_parser("record", help="workflow job 2: validate result and post the reply")
    record.add_argument("--discussion", required=True)
    record.add_argument("--comment", required=True)
    record.add_argument("--result", required=True)
    record.add_argument("--apply", action="store_true", help="actually post (default: dry-run)")
    return parser


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "check":
        return cmd_check(args)
    if args.command == "run":
        return cmd_run(args)
    return cmd_record(args)


if __name__ == "__main__":
    sys.exit(main())
