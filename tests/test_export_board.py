"""scripts/export_board.py and docs/board.html: the public factory board."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from unittest import mock

import pytest

import export_board as eb

ROOT = Path(__file__).resolve().parent.parent
BOARD_HTML = ROOT / "docs" / "board.html"
WORKFLOW = ROOT / ".github" / "workflows" / "static-api.yml"

FIELDS = {
    "fields": [
        {"id": "F1", "name": "Title", "type": "ProjectV2Field"},
        {"id": "F2", "name": "Status", "type": "ProjectV2SingleSelectField",
         "options": [{"id": "a", "name": "Todo"}, {"id": "b", "name": "In Progress"}]},
        {"id": "F3", "name": "Agent", "type": "ProjectV2Field"},
    ],
    "totalCount": 3,
}


def _issue(n, status, *, repo="kody-w/rappterbook", kind="Issue", agent=None, **extra):
    path = "pull" if kind == "PullRequest" else "issues"
    item = {
        "id": "PVTI_%d" % n,
        "title": "Item %d" % n,
        "content": {
            "type": kind, "number": n, "title": "Item %d" % n, "repository": repo,
            "url": "https://github.com/%s/%s/%d" % (repo, path, n), "body": "x",
        },
        "repository": "https://github.com/" + repo,
        "labels": ["factory"],
        "assignees": ["human-%d" % n],
    }
    if status is not None:
        item["status"] = status
    if agent is not None:
        item["agent"] = agent
    item.update(extra)
    return item


# The real `gh project item-list --format json` shape: no updatedAt anywhere
# (it comes from the GraphQL nodes() lookup, DETAILS below).
ITEMS = {
    "items": [
        _issue(1, "Done", agent="zion-coder-01"),
        _issue(2, "Building", kind="PullRequest"),
        _issue(3, "Waiting on Godot"),          # unknown -> Backlog
        _issue(4, None),                         # no status -> Backlog
        _issue(5, "In Review"),                  # alias -> Review
        _issue(6, "qa"),                         # case-insensitive -> QA
        _issue(7, "Blocked"),
        _issue(8, "Ready"),
        {"id": "PVTI_D", "title": "secret draft", "status": "Ready",
         "content": {"type": "DraftIssue", "title": "secret draft", "body": "private"}},
        {"id": "PVTI_X", "title": "<img src=x onerror=alert(1)>", "status": "Ready",
         "content": {"type": "Issue", "url": "javascript:alert(1)", "number": 9}},
    ],
    "totalCount": 10,
}
VIEW = {"title": "Factory", "url": "https://github.com/users/kody-w/projects/3", "number": 3}
REPOS = ["kody-w/rappterbook"]


def _node(item_id, *, private=False, repo="kody-w/rappterbook", updated=None, content_updated=None):
    return {"id": item_id, "updatedAt": updated or "2026-09-01T00:00:00Z",
            "content": {"updatedAt": content_updated or "2026-09-01T00:00:00Z",
                        "url": "https://github.com/x", "repository": {"nameWithOwner": repo, "isPrivate": private}}}


GRAPHQL_NODES = [_node("PVTI_%d" % n) for n in range(2, 9)] + [
    _node("PVTI_1", updated="2026-09-20T00:00:00Z", content_updated="2026-10-01T00:00:00Z")]


def _details(nodes=None):
    return {n["id"]: {"private": n["content"]["repository"]["isPrivate"],
                      "repo": n["content"]["repository"]["nameWithOwner"],
                      "updated_at": max(n["updatedAt"], n["content"]["updatedAt"])}
            for n in (GRAPHQL_NODES if nodes is None else nodes)}


DETAILS = _details()


def _doc(**kw):
    kw.setdefault("details", DETAILS)
    kw.setdefault("repos", REPOS)
    return eb.normalize(FIELDS, ITEMS, VIEW, "kody-w", 3, **kw)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "test-token")  # CI sets GITHUB_ACTIONS; never skip for "no token"
    for name in ("FACTORY_BOARD_REPOS", "GITHUB_REPOSITORY", "GITHUB_REPOSITORY_OWNER", "FACTORY_PROJECT"):
        monkeypatch.delenv(name, raising=False)


def _col(doc, name):
    return next(c for c in doc["columns"] if c["name"] == name)


# ---------------------------------------------------------------------------
# normalization
# ---------------------------------------------------------------------------

def test_columns_are_super_board_order_and_always_present():
    doc = eb.normalize(FIELDS, {"items": []}, None, "kody-w", 3)
    assert [c["name"] for c in doc["columns"]] == [
        "Backlog", "Ready", "Building", "QA", "Review", "Blocked", "Done"]
    assert all(c["count"] == 0 and c["items"] == [] for c in doc["columns"])
    assert doc["_schema"] == "rappterbook-board/1" and doc["total"] == 0
    assert (doc["truncated"], doc["source_total"]) == (False, 0)


def test_normalizes_fixture_items():
    doc = _doc()
    done = _col(doc, "Done")["items"]
    assert done == [{
        "title": "Item 1",
        "url": "https://github.com/kody-w/rappterbook/issues/1",
        "repo": "kody-w/rappterbook",
        "number": 1,
        "kind": "issue",
        "status": "Done",
        "project_status": "Done",
        "labels": ["factory"],
        "assignee": "zion-coder-01",          # Agent field wins over assignees
        "updated_at": "2026-10-01T00:00:00Z",  # the later of item and content updatedAt
    }]
    pr = _col(doc, "Building")["items"][0]
    assert pr["kind"] == "pr" and pr["url"].endswith("/pull/2") and pr["number"] == 2
    assert pr["assignee"] == "human-2"        # no Agent value -> first assignee
    assert pr["updated_at"] == "2026-09-01T00:00:00Z"
    assert doc["project"] == {"owner": "kody-w", "number": 3, "title": "Factory",
                              "url": "https://github.com/users/kody-w/projects/3"}
    assert {c["name"]: c["count"] for c in doc["columns"]} == {
        "Backlog": 2, "Ready": 1, "Building": 1, "QA": 1, "Review": 1, "Blocked": 1, "Done": 1}
    assert doc["total"] == 8
    assert (doc["truncated"], doc["source_total"]) == (False, 10)
    for col in doc["columns"]:
        assert col["count"] == len(col["items"])
        assert all(item["status"] == col["name"] for item in col["items"])


def test_private_unknown_and_foreign_repo_items_are_never_published():
    nodes = [n for n in GRAPHQL_NODES if n["id"] not in ("PVTI_2", "PVTI_3")]
    nodes.append(_node("PVTI_2", private=True))           # private repository
    details = _details(nodes)                              # PVTI_3: visibility unknown
    items = dict(ITEMS, items=ITEMS["items"] + [_issue(20, "Ready", repo="someone/else")])
    details["PVTI_20"] = {"private": False, "repo": "someone/else", "updated_at": None}
    doc = eb.normalize(FIELDS, items, VIEW, "kody-w", 3, details=details, repos=REPOS)
    numbers = {i["number"] for c in doc["columns"] for i in c["items"]}
    assert numbers == {1, 4, 5, 6, 7, 8}
    widened = eb.normalize(FIELDS, items, VIEW, "kody-w", 3, details=details,
                           repos=REPOS + ["someone/else"])
    assert 20 in {i["number"] for c in widened["columns"] for i in c["items"]}
    # no visibility data at all: nothing is published
    assert eb.normalize(FIELDS, ITEMS, VIEW, "kody-w", 3, details=None, repos=REPOS)["total"] == 0
    # GraphQL naming another repository than item-list is not trusted
    mismatch = _details([_node("PVTI_1", repo="evil/other")])
    assert eb.normalize(FIELDS, ITEMS, VIEW, "kody-w", 3, details=mismatch, repos=REPOS)["total"] == 0


def test_truncated_project_says_so():
    items = {"items": [_issue(1, "Done"), _issue(2, "Ready")], "totalCount": 3}
    doc = eb.normalize(FIELDS, items, None, "kody-w", 3, details=DETAILS, repos=REPOS)
    assert (doc["truncated"], doc["source_total"], doc["total"]) == (True, 3, 2)


def test_clean_text_strips_bidi_zero_width_and_separators():
    hostile = "a‮b​c d⁦e﻿f\x85g\x9fh"
    assert eb._clean_text(hostile, 100) == "abcdefgh"


@pytest.mark.parametrize("raw,col", [
    ("Ready to Start", "Ready"), ("Ready for review", "Review"), ("In QA", "QA"),
    ("QA Review", "QA"), ("Complete", "Done"), ("Completed", "Done"), ("Done", "Done"),
])
def test_common_template_status_names(raw, col):
    assert eb.map_status(raw) == col


def test_unknown_or_missing_status_goes_to_backlog():
    backlog = _col(_doc(), "Backlog")["items"]
    assert sorted(i["number"] for i in backlog) == [3, 4]
    raw = {i["number"]: i["project_status"] for i in backlog}
    assert raw == {3: "Waiting on Godot", 4: None}
    for odd in (None, 7, "", "   ", "Doneish", ["Done"]):
        assert eb.map_status(odd) == "Backlog"
    assert eb.map_status("In Progress") == "Building"
    assert eb.map_status("REVIEW") == "Review"


def test_drafts_and_unlinkable_items_are_not_published_by_default():
    doc = _doc()
    titles = [i["title"] for c in doc["columns"] for i in c["items"]]
    assert "secret draft" not in titles
    assert not any("onerror" in t for t in titles)   # javascript: url dropped
    with_drafts = _doc(include_drafts=True)
    draft = _col(with_drafts, "Ready")["items"]
    assert any(i["kind"] == "draft" and i["url"] is None for i in draft)


def test_custom_field_names_are_matched_loosely():
    fields = {"fields": [{"name": "Status"}, {"name": "Agent"}]}
    items = [_issue(1, None, Status="Review", **{"Agent": "worker-1"})]
    doc = eb.normalize(fields, items, None, "o", 1, details=DETAILS, repos=REPOS)
    item = _col(doc, "Review")["items"][0]
    assert item["assignee"] == "worker-1"


def test_parse_project_forms():
    assert eb.parse_project("kody-w/3") == ("kody-w", 3)
    assert eb.parse_project("https://github.com/orgs/acme/projects/12") == ("acme", 12)
    assert eb.parse_project("7", default_owner="kody-w") == ("kody-w", 7)
    for bad in (None, "", "7", "kody-w/x", "a b/3", "kody-w/0", "; rm -rf /", "kody-w/³",
                "kody-w/abc", "https://github.com/orgs/acme/projects/0"):
        assert eb.parse_project(bad) is None
    assert eb.parse_repos(" Kody-W/RappterBook, bad repo, a/b ,a/b") == ["kody-w/rappterbook", "a/b"]


@pytest.mark.parametrize("argv,env", [
    (["--out", "{out}"], {"FACTORY_PROJECT": "kody-w/abc"}),
    (["https://github.com/kody-w/rappterbook/projects/3", "--out", "{out}"], {}),
    (["--number", "3", "--out", "{out}"], {}),
    (["kody-w/³", "--out", "{out}"], {}),
])
def test_set_but_invalid_project_is_an_error_not_a_skip(argv, env, tmp_path, monkeypatch, capsys):
    for k, val in env.items():
        monkeypatch.setenv(k, val)
    out = tmp_path / "board.json"
    with mock.patch.object(eb.subprocess, "run") as run:
        assert eb.main([a.replace("{out}", str(out)) for a in argv]) == 2
    run.assert_not_called()
    assert "error:" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# gh / main
# ---------------------------------------------------------------------------

def _proc(rc=0, out="", err=""):
    return subprocess.CompletedProcess(["gh"], rc, stdout=out, stderr=err)


def _fake_gh(calls, nodes=None, graphql_rc=0, requests=None):
    def run(argv, **kw):
        calls.append(list(argv))
        assert "shell" not in kw
        if argv[1:3] == ["api", "graphql"]:
            assert argv[3:] == ["--input", "-"]
            request = json.loads(kw["input"])
            if requests is not None:
                requests.append(request)
            if graphql_rc:
                return _proc(graphql_rc, err="gh: HTTP 502")
            pool = {n["id"]: n for n in (GRAPHQL_NODES if nodes is None else nodes)}
            return _proc(out=json.dumps({"data": {"nodes": [pool.get(i) for i in request["variables"]["ids"]]}}))
        sub = argv[2]
        payload = {"field-list": FIELDS, "item-list": ITEMS, "view": VIEW}[sub]
        return _proc(out=json.dumps(payload))
    return run


def test_main_writes_board_json_from_mocked_gh(tmp_path, monkeypatch, capsys):
    out = tmp_path / "board.json"
    calls = []
    monkeypatch.setenv("FACTORY_PROJECT", "kody-w/3")
    with mock.patch.object(eb.subprocess, "run", side_effect=_fake_gh(calls)):
        assert eb.main(["--out", str(out)]) == 0
    doc = json.loads(out.read_text())
    assert doc["_schema"] == "rappterbook-board/1" and doc["total"] == 8
    assert re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$", doc["generated_at"])
    item_list = next(c for c in calls if c[2] == "item-list")
    assert item_list[:6] == ["gh", "project", "item-list", "3", "--owner", "kody-w"]
    assert "--format" in item_list and "json" in item_list and "--limit" in item_list
    assert "wrote" in capsys.readouterr().out
    assert _col(doc, "Done")["items"][0]["updated_at"] == "2026-10-01T00:00:00Z"


def test_main_sends_only_valid_ids_on_stdin(tmp_path, monkeypatch):
    items = dict(ITEMS, items=ITEMS["items"] + [dict(_issue(30, "Ready"), id="PVTI_$(id)")])
    calls, requests = [], []
    run = _fake_gh(calls, requests=requests)

    def wrapped(argv, **kw):
        if argv[1:3] == ["project", "item-list"]:
            return _proc(out=json.dumps(items))
        return run(argv, **kw)

    with mock.patch.object(eb.subprocess, "run", side_effect=wrapped):
        assert eb.main(["kody-w/3", "--out", str(tmp_path / "b.json")]) == 0
    sent = [i for r in requests for i in r["variables"]["ids"]]
    assert "PVTI_$(id)" not in sent and "PVTI_1" in sent
    assert all("PVTI" not in " ".join(c) for c in calls if c[1:3] == ["api", "graphql"])


def test_failed_visibility_lookup_fails_closed(tmp_path):
    out = tmp_path / "board.json"
    out.write_text("{}\n")
    with mock.patch.object(eb.subprocess, "run", side_effect=_fake_gh([], graphql_rc=1)):
        assert eb.main(["kody-w/3", "--out", str(out)]) == 1
    assert out.read_text() == "{}\n"


def test_private_item_is_dropped_end_to_end(tmp_path):
    out = tmp_path / "board.json"
    nodes = [n for n in GRAPHQL_NODES if n["id"] != "PVTI_5"] + [_node("PVTI_5", private=True)]
    with mock.patch.object(eb.subprocess, "run", side_effect=_fake_gh([], nodes=nodes)):
        assert eb.main(["kody-w/3", "--out", str(out)]) == 0
    doc = json.loads(out.read_text())
    assert 5 not in {i["number"] for c in doc["columns"] for i in c["items"]}
    assert doc["total"] == 7


def test_unchanged_board_is_not_rewritten(tmp_path):
    out = tmp_path / "board.json"
    doc = _doc()
    assert eb.write_if_changed(doc, out, now="2026-10-01T00:00:00Z") is True
    before = out.read_bytes()
    assert eb.write_if_changed(_doc(), out, now="2026-10-13T00:00:00Z") is False
    assert out.read_bytes() == before
    changed = _doc()
    changed["columns"][0]["items"] = []
    assert eb.write_if_changed(changed, out, now="2026-10-13T00:00:00Z") is True
    assert json.loads(out.read_text())["generated_at"] == "2026-10-13T00:00:00Z"


def test_missing_scope_skips_and_leaves_file_untouched(tmp_path, capsys):
    out = tmp_path / "board.json"
    out.write_bytes(b'{"_schema": "rappterbook-board/1", "keep": "me"}\n')
    before = out.read_bytes()
    err = ("error: your authentication token is missing required scopes [read:project]\n"
           "To request it, run:  gh auth refresh -s read:project")
    with mock.patch.object(eb.subprocess, "run", return_value=_proc(1, err=err)):
        assert eb.main(["kody-w/3", "--out", str(out)]) == 0
    assert out.read_bytes() == before
    assert "skipped: token lacks project scope" in capsys.readouterr().out


@pytest.mark.parametrize("err", [
    "GraphQL: Resource not accessible by personal access token (user.projectV2)",
    "GraphQL: Resource not accessible by integration (user.projectV2)",
    "gh: To use GitHub CLI in a GitHub Actions workflow, set the GH_TOKEN environment variable.",
    "To get started with GitHub CLI, please run:  gh auth login",
])
def test_permission_and_missing_token_messages_skip(err, tmp_path, capsys):
    out = tmp_path / "board.json"
    with mock.patch.object(eb.subprocess, "run", return_value=_proc(4 if "GH_TOKEN" in err else 1, err=err)):
        assert eb.main(["kody-w/3", "--out", str(out)]) == 0
    assert not out.exists()
    assert "skipped:" in capsys.readouterr().out


def test_actions_without_token_skips_without_calling_gh(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GH_TOKEN", "")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with mock.patch.object(eb.subprocess, "run") as run:
        assert eb.main(["kody-w/3", "--out", str(tmp_path / "b.json")]) == 0
    run.assert_not_called()
    assert "skipped: no token" in capsys.readouterr().out


def test_no_project_configured_skips_without_calling_gh(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("FACTORY_PROJECT", raising=False)
    out = tmp_path / "board.json"
    with mock.patch.object(eb.subprocess, "run") as run:
        assert eb.main(["--out", str(out)]) == 0
    run.assert_not_called()
    assert not out.exists()
    assert "skipped: no project configured" in capsys.readouterr().out


def test_other_gh_failure_exits_nonzero_and_leaves_file(tmp_path):
    out = tmp_path / "board.json"
    out.write_text("{}\n")
    with mock.patch.object(eb.subprocess, "run", return_value=_proc(1, err="HTTP 502")):
        assert eb.main(["kody-w/3", "--out", str(out)]) == 1
    assert out.read_text() == "{}\n"


# ---------------------------------------------------------------------------
# page + workflow
# ---------------------------------------------------------------------------

def test_board_html_never_uses_innerhtml_or_external_scripts():
    html = BOARD_HTML.read_text(encoding="utf-8")
    assert not re.search(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|eval\(", html)
    assert not re.search(r"<script[^>]+src=", html, re.I)
    assert not re.search(r"<link[^>]+href=[\"']?https?:", html, re.I)
    assert "fetch('board.json'" in html
    assert "textContent" in html
    assert 'name="viewport"' in html
    for col in eb.COLUMNS:
        assert "'%s'" % col in html


def test_board_html_keeps_header_on_empty_board_and_handles_null_json():
    html = BOARD_HTML.read_text(encoding="utf-8")
    assert "showState('The board is empty', 'No issues or pull requests are on the project yet.', true)" in html
    assert "if (!keepMeta)" in html
    assert "doc !== NOT_PUBLISHED" in html and "doc !== null" not in html
    assert "doc.truncated === true" in html


def test_static_api_runs_exporter_only_when_variable_set():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert text.count("scripts/export_board.py") == 1
    step = text[text.index("- name: Export the factory board"):]
    assert "vars.FACTORY_PROJECT != ''" in step
    assert "docs/board.json" in step
    assert "continue-on-error: true" in step
    assert "github.token" not in step  # it can never read Projects v2
