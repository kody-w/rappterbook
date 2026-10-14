#!/usr/bin/env python3
"""Export a GitHub Project (v2) to docs/board.json for the public board page.

Schema ``rappterbook-board/1``::

    {
      "_schema": "rappterbook-board/1",
      "project": {"owner": "kody-w", "number": 1, "title": "...", "url": "..."},
      "generated_at": "2026-10-13T12:00:00Z",   # last time the board CHANGED
      "columns": [
        {"name": "Backlog", "count": 2, "items": [
          {"title": "...", "url": "https://github.com/o/r/issues/1",
           "repo": "o/r", "number": 1, "kind": "issue", "status": "Backlog",
           "project_status": "Todo", "labels": ["bug"], "assignee": "alice",
           "updated_at": "2026-10-12T09:00:00Z"}
        ]},
        ... Ready, Building, QA, Review, Blocked, Done (always all seven, in order)
      ],
      "total": 2,
      "truncated": false,      # true when the project has more items than were read
      "source_total": 2        # gh's totalCount for the project
    }

Usage::

    python3 scripts/export_board.py                      # project from $FACTORY_PROJECT
    python3 scripts/export_board.py kody-w/1             # owner/number
    python3 scripts/export_board.py --owner kody-w --number 1
    python3 scripts/export_board.py https://github.com/users/kody-w/projects/1

Data comes from ``gh project item-list --format json``, ``gh project
field-list --format json`` and one read-only ``gh api graphql`` lookup
(``nodes(ids:)``, batches of 100, request on stdin) that adds each item's
``updatedAt`` and its repository's visibility, which item-list does not
report. Everything in the project is treated as untrusted data: it is never
passed to a shell, links are kept only when they point at https://github.com/,
and the page renders it with textContent.

What is published (fail closed): only issues and pull requests whose
repository is in the allowlist (``--repos`` / ``$FACTORY_BOARD_REPOS``,
comma-separated; default ``$GITHUB_REPOSITORY``, else kody-w/rappterbook)
AND that GraphQL reports as public. A private repository, or an item whose
visibility could not be read, is dropped. Drafts stay out unless
``--include-drafts``.

Exit codes: 0 on success, and also 0 (printing ``skipped: ...``) when no
project is configured, no token is available in Actions, or the token lacks
the ``read:project`` scope -- in those cases any existing board.json is left
byte-for-byte untouched. A FACTORY_PROJECT that is set but malformed exits 2.
Any other gh failure exits 1 and leaves the file untouched too.

The file is rewritten only when the board content changed, so a scheduled
re-export of an unchanged board produces no diff and no commit.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

SCHEMA = "rappterbook-board/1"
COLUMNS: Tuple[str, ...] = ("Backlog", "Ready", "Building", "QA", "Review", "Blocked", "Done")
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "docs" / "board.json"
DEFAULT_REPO = "kody-w/rappterbook"
ITEM_LIMIT = 1000
NODE_BATCH = 100
MAX_TITLE = 300
MAX_LABELS = 20

# Project status names that mean one of the super-board columns. Keys are
# normalized (lowercase, alphanumerics only). Anything else lands in Backlog.
_ALIASES = {
    "backlog": "Backlog", "todo": "Backlog", "nostatus": "Backlog", "triage": "Backlog",
    "ready": "Ready", "readyfordev": "Ready", "upnext": "Ready", "readytostart": "Ready",
    "building": "Building", "inprogress": "Building", "doing": "Building", "wip": "Building",
    "qa": "QA", "testing": "QA", "intesting": "QA", "inqa": "QA", "qareview": "QA",
    "review": "Review", "inreview": "Review", "needsreview": "Review", "readyforreview": "Review",
    "blocked": "Blocked", "onhold": "Blocked",
    "done": "Done", "closed": "Done", "shipped": "Done", "merged": "Done",
    "complete": "Done", "completed": "Done",
}

_SCOPE_MARKERS = (
    "read:project",
    "missing required scope",
    "insufficient_scopes",
    # GitHub App tokens say "... by integration", fine-grained PATs "... by personal access token"
    "resource not accessible by",
)
# gh has no credentials at all (exit 4): nothing to export, not a failure.
_NO_TOKEN_MARKERS = (
    "gh auth login",
    "set the gh_token environment variable",
)
_GH_URL = re.compile(r"^https://github\.com/([A-Za-z0-9-]+)/([A-Za-z0-9._-]+)/(issues|pull)/([0-9]{1,9})$")
_PROJECT_URL = re.compile(r"^https://github\.com/(?:users|orgs)/([A-Za-z0-9-]+)/projects/([0-9]{1,9})/?$")
_OWNER = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
_NUMBER = re.compile(r"[0-9]{1,9}")
_REPO = re.compile(r"[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}")
_NODE_ID = re.compile(r"[A-Za-z0-9_=-]{1,200}")
# C0/C1 controls and DEL, zero-width and bidi controls (U+200B-U+200F,
# U+202A-U+202E, U+2066-U+2069), line/paragraph separators (U+2028/9) and
# the BOM: none belongs in a one-line public title, and bidi overrides can
# make a card display spoofed text order.
_UNSAFE_CHARS = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f\u200b-\u200f\u2028-\u202e\u2066-\u2069\ufeff]")

_NODES_QUERY = """
query($ids: [ID!]!) {
  nodes(ids: $ids) {
    ... on ProjectV2Item {
      id
      updatedAt
      content {
        ... on Issue { updatedAt url repository { nameWithOwner isPrivate } }
        ... on PullRequest { updatedAt url repository { nameWithOwner isPrivate } }
      }
    }
  }
}
"""


class ScopeError(Exception):
    """gh says the token cannot read projects."""


class NoTokenError(ScopeError):
    """gh has no credentials at all."""


class GhError(Exception):
    """Any other gh failure."""


# ---------------------------------------------------------------------------
# Project reference parsing
# ---------------------------------------------------------------------------

def parse_project(ref: Optional[str], default_owner: Optional[str] = None) -> Optional[Tuple[str, int]]:
    """Parse 'owner/number', a project URL, or a bare number. None if unset/invalid.

    Only ASCII digits count (``str.isdigit`` would accept '³', which ``int``
    rejects). main() tells "unset" from "set but invalid".
    """
    ref = (ref or "").strip()
    if not ref:
        return None
    m = _PROJECT_URL.match(ref)
    if m:
        return (m.group(1), int(m.group(2))) if int(m.group(2)) > 0 else None
    if "/" in ref:
        owner, _, num = ref.partition("/")
    else:
        owner, num = (default_owner or ""), ref
    owner = owner.strip()
    num = num.strip()
    if not _OWNER.match(owner) or not _NUMBER.fullmatch(num) or int(num) <= 0:
        return None
    return owner, int(num)


def parse_repos(raw: Optional[str]) -> List[str]:
    """Comma-separated owner/name list, lowercased; malformed entries dropped."""
    out = []
    for part in (raw or "").split(","):
        part = part.strip()
        if _REPO.fullmatch(part) and part.lower() not in out:
            out.append(part.lower())
    return out


# ---------------------------------------------------------------------------
# gh
# ---------------------------------------------------------------------------

def run_gh(args: Sequence[str], input_text: Optional[str] = None) -> Any:
    """Run gh with an argv list (never a shell) and return parsed JSON stdout.

    ``input_text`` is sent on stdin (``gh api graphql --input -``), so no
    project data ever appears in argv.
    """
    try:
        proc = subprocess.run(
            ["gh", *args], capture_output=True, text=True, timeout=120, check=False,
            input=input_text,
        )
    except FileNotFoundError as exc:
        raise GhError("gh CLI not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise GhError("gh timed out") from exc
    if proc.returncode != 0:
        err = (proc.stderr or "") + (proc.stdout or "")
        lowered = err.lower()
        if any(marker in lowered for marker in _NO_TOKEN_MARKERS):
            raise NoTokenError(err.strip()[:300])
        if any(marker in lowered for marker in _SCOPE_MARKERS):
            raise ScopeError(err.strip()[:300])
        raise GhError(err.strip()[:500] or "gh exited %d" % proc.returncode)
    try:
        return json.loads(proc.stdout or "null")
    except ValueError as exc:
        raise GhError("gh returned non-JSON output") from exc


def _raw_items(items: Any) -> List[Any]:
    raw = items.get("items") if isinstance(items, dict) else items
    return raw if isinstance(raw, list) else []


def fetch_details(item_ids: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    """Item id -> {updated_at, private, repo} from GraphQL ``nodes(ids:)``.

    Read-only. Ids that are not plain GraphQL ids are never sent. A failed
    query raises GhError (the caller fails closed and writes nothing); a
    node that comes back null or without repository data is simply absent,
    which normalize() treats as "visibility unknown" and drops.
    """
    ids = [i for i in item_ids if isinstance(i, str) and _NODE_ID.fullmatch(i)]
    details: Dict[str, Dict[str, Any]] = {}
    for start in range(0, len(ids), NODE_BATCH):
        batch = ids[start:start + NODE_BATCH]
        request = json.dumps({"query": _NODES_QUERY, "variables": {"ids": batch}})
        # gh exits non-zero on GraphQL errors, which run_gh raises.
        data = run_gh(["api", "graphql", "--input", "-"], input_text=request)
        payload = data.get("data") if isinstance(data, dict) else None
        nodes = payload.get("nodes") if isinstance(payload, dict) else None
        if not isinstance(nodes, list):
            raise GhError("graphql nodes query returned no nodes")
        for node in nodes:
            if not isinstance(node, dict) or node.get("id") not in batch:
                continue
            content = node.get("content") if isinstance(node.get("content"), dict) else {}
            repo = content.get("repository") if isinstance(content.get("repository"), dict) else {}
            private = repo.get("isPrivate")
            stamps = [s for s in (node.get("updatedAt"), content.get("updatedAt"))
                      if isinstance(s, str) and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", s)]
            details[node["id"]] = {
                "private": private if isinstance(private, bool) else None,
                "repo": repo.get("nameWithOwner") if isinstance(repo.get("nameWithOwner"), str) else None,
                "updated_at": max(stamps) if stamps else None,
            }
    return details


def fetch(owner: str, number: int) -> Tuple[Any, Any, Any, Dict[str, Dict[str, Any]]]:
    """Return (fields, items, project_view, details) raw JSON from gh."""
    num = str(number)
    fields = run_gh(["project", "field-list", num, "--owner", owner, "--format", "json", "--limit", "100"])
    items = run_gh(["project", "item-list", num, "--owner", owner, "--format", "json", "--limit", str(ITEM_LIMIT)])
    try:
        view = run_gh(["project", "view", num, "--owner", owner, "--format", "json"])
    except GhError:
        view = None  # title/url are cosmetic; never fail the export for them
    ids = [it.get("id") for it in _raw_items(items) if isinstance(it, dict)]
    details = fetch_details(ids)
    return fields, items, view, details


# ---------------------------------------------------------------------------
# Normalization (pure)
# ---------------------------------------------------------------------------

def _norm(name: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


def map_status(raw: Any) -> str:
    """Map a project Status value to a super-board column; unknown -> Backlog."""
    if not isinstance(raw, str):
        return "Backlog"
    key = _norm(raw)
    for col in COLUMNS:
        if key == _norm(col):
            return col
    return _ALIASES.get(key, "Backlog")


def _clean_text(value: Any, limit: int) -> str:
    text = value if isinstance(value, str) else ("" if value is None else str(value))
    text = _UNSAFE_CHARS.sub("", text).strip()
    return text[:limit]


def _field_names(fields: Any) -> List[str]:
    if isinstance(fields, dict):
        fields = fields.get("fields")
    out = []
    for f in fields or []:
        if isinstance(f, dict) and isinstance(f.get("name"), str):
            out.append(f["name"])
    return out


def _lookup(item: Dict[str, Any], field_name: str) -> Any:
    """Find a field value on an item; gh camelCases custom field keys."""
    if field_name in item:
        return item[field_name]
    want = _norm(field_name)
    for key, value in item.items():
        if _norm(key) == want:
            return value
    return None


def _safe_url(url: Any) -> Optional[str]:
    if isinstance(url, str) and _GH_URL.match(url.strip()):
        return url.strip()
    return None


def _string_list(value: Any) -> List[str]:
    if isinstance(value, str):
        value = [value]
    out = []
    for v in value or []:
        if isinstance(v, dict):
            v = v.get("name") or v.get("login")
        text = _clean_text(v, 80)
        if text:
            out.append(text)
    return out[:MAX_LABELS]


def normalize_item(item: Dict[str, Any], status_field: str = "Status",
                   agent_field: Optional[str] = None,
                   include_drafts: bool = False,
                   details: Optional[Dict[str, Dict[str, Any]]] = None,
                   repos: Optional[Sequence[str]] = None) -> Optional[Dict[str, Any]]:
    """One gh item -> one board card, or None if it should not be published.

    Fail closed: an issue or PR is published only when its repository is in
    ``repos`` and ``details`` (from fetch_details) says it is public.
    ``details=None`` means nothing is known, so every issue/PR is dropped.
    """
    if not isinstance(item, dict):
        return None
    content = item.get("content") if isinstance(item.get("content"), dict) else {}
    ctype = str(content.get("type") or "")
    if ctype == "DraftIssue" and not include_drafts:
        return None
    url = _safe_url(content.get("url"))
    repo = None
    number = None
    kind = "draft" if ctype == "DraftIssue" else ("pr" if ctype == "PullRequest" else "issue")
    if url:
        m = _GH_URL.match(url)
        repo = "%s/%s" % (m.group(1), m.group(2))
        number = int(m.group(4))
        kind = "pr" if m.group(3) == "pull" else "issue"
    elif ctype != "DraftIssue":
        return None  # an issue/PR we cannot link is not worth a public card
    info: Dict[str, Any] = {}
    if repo is not None:
        if repos is None or repo.lower() not in {r.lower() for r in repos}:
            return None  # not an allowlisted repository
        info = (details or {}).get(item.get("id")) if isinstance(item.get("id"), str) else None
        if not isinstance(info, dict) or info.get("private") is not False:
            return None  # private, or visibility unknown
        if isinstance(info.get("repo"), str) and info["repo"].lower() != repo.lower():
            return None  # GraphQL and item-list disagree about the item
    raw_status = _lookup(item, status_field)
    assignee = None
    if agent_field:
        agent = _lookup(item, agent_field)
        agent_list = _string_list(agent)
        assignee = agent_list[0] if agent_list else None
    if not assignee:
        people = _string_list(item.get("assignees") or content.get("assignees"))
        assignee = people[0] if people else None
    updated = info.get("updated_at")
    return {
        "title": _clean_text(item.get("title") or content.get("title"), MAX_TITLE) or "(untitled)",
        "url": url,
        "repo": repo,
        "number": number,
        "kind": kind,
        "status": map_status(raw_status),
        "project_status": _clean_text(raw_status, 60) or None,
        "labels": _string_list(item.get("labels") or content.get("labels")),
        "assignee": assignee,
        "updated_at": updated if isinstance(updated, str) else None,
    }


def normalize(fields: Any, items: Any, view: Any = None, owner: str = "",
              number: int = 0, include_drafts: bool = False,
              details: Optional[Dict[str, Dict[str, Any]]] = None,
              repos: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """Raw gh JSON -> rappterbook-board/1 document (without generated_at)."""
    names = _field_names(fields)
    status_field = next((n for n in names if _norm(n) == "status"), "Status")
    agent_field = next((n for n in names if _norm(n) == "agent"), None)
    raw_items = _raw_items(items)
    buckets: Dict[str, List[Dict[str, Any]]] = {c: [] for c in COLUMNS}
    for raw in raw_items:
        card = normalize_item(raw, status_field, agent_field, include_drafts, details, repos)
        if card is not None:
            buckets[card["status"]].append(card)
    reported = items.get("totalCount") if isinstance(items, dict) else None
    source_total = reported if type(reported) is int and reported >= 0 else len(raw_items)  # noqa: E721
    for col in COLUMNS:
        # Stable, content-derived order so unchanged boards export identically.
        buckets[col].sort(key=lambda c: (c["updated_at"] or "", c["repo"] or "", c["number"] or 0, c["title"]),
                          reverse=True)
    project: Dict[str, Any] = {"owner": owner, "number": number, "title": None, "url": None}
    if isinstance(view, dict):
        project["title"] = _clean_text(view.get("title"), 200) or None
        purl = view.get("url")
        if isinstance(purl, str) and _PROJECT_URL.match(purl):
            project["url"] = purl
    return {
        "_schema": SCHEMA,
        "project": project,
        "columns": [{"name": c, "count": len(buckets[c]), "items": buckets[c]} for c in COLUMNS],
        "total": sum(len(v) for v in buckets.values()),
        # gh item-list stops at ITEM_LIMIT; say so instead of looking complete
        "truncated": source_total > len(raw_items),
        "source_total": max(source_total, len(raw_items)),
    }


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_if_changed(doc: Dict[str, Any], out: Path, now: Optional[str] = None) -> bool:
    """Write doc (stamping generated_at) unless the board content is unchanged."""
    try:
        old = json.loads(out.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old = None
    if isinstance(old, dict):
        old_body = {k: v for k, v in old.items() if k != "generated_at"}
        if old_body == doc:
            return False
    full = dict(doc)
    full["generated_at"] = now or _now()
    ordered = {k: full[k] for k in ("_schema", "project", "generated_at", "columns", "total",
                                    "truncated", "source_total") if k in full}
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".board.", suffix=".json", dir=str(out.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(ordered, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, str(out))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return True


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("project", nargs="?", help="owner/number, project URL, or number (default $FACTORY_PROJECT)")
    ap.add_argument("--owner", help="project owner (user or org)")
    ap.add_argument("--number", type=int, help="project number")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="output path (default docs/board.json)")
    ap.add_argument("--include-drafts", action="store_true", help="also publish draft items (off: drafts may be private notes)")
    ap.add_argument("--repos", help="comma-separated owner/name allowlist (default $FACTORY_BOARD_REPOS, "
                                    "else $GITHUB_REPOSITORY, else %s)" % DEFAULT_REPO)
    args = ap.parse_args(argv)

    default_owner = args.owner or os.environ.get("GITHUB_REPOSITORY_OWNER")
    if args.number is not None:
        raw_ref = "%s/%d" % (args.owner or default_owner or "", args.number)
    else:
        raw_ref = (args.project or os.environ.get("FACTORY_PROJECT") or "").strip()
    if not raw_ref:
        print("skipped: no project configured (set FACTORY_PROJECT=owner/number)")
        return 0
    ref = parse_project(raw_ref, default_owner)
    if ref is None:
        # Set but unusable: say so loudly rather than look unconfigured.
        print("error: project %r is not owner/number or a users/orgs project URL" % raw_ref[:100],
              file=sys.stderr)
        return 2
    repos = parse_repos(args.repos or os.environ.get("FACTORY_BOARD_REPOS")
                        or os.environ.get("GITHUB_REPOSITORY") or DEFAULT_REPO)
    if not repos:
        print("error: no valid owner/name in the repository allowlist", file=sys.stderr)
        return 2
    owner, number = ref
    out = Path(args.out)
    if os.environ.get("GITHUB_ACTIONS") == "true" and not (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")):
        print("skipped: no token (set the FACTORY_PROJECT_TOKEN secret); %s left untouched" % out)
        return 0
    try:
        fields, items, view, details = fetch(owner, number)
    except NoTokenError:
        print("skipped: gh has no token; %s left untouched" % out)
        return 0
    except ScopeError:
        print("skipped: token lacks project scope (needs read:project); %s left untouched" % out)
        return 0
    except GhError as exc:
        print("error: gh project export failed: %s" % exc, file=sys.stderr)
        return 1
    doc = normalize(fields, items, view, owner, number, args.include_drafts, details, repos)
    if doc["truncated"]:
        print("warning: project has %d items, only %d were read; board.json marks itself truncated"
              % (doc["source_total"], len(_raw_items(items))), file=sys.stderr)
    changed = write_if_changed(doc, out)
    print("%s %s: %d items from %s/%d" % ("wrote" if changed else "unchanged", out, doc["total"], owner, number))
    return 0


if __name__ == "__main__":
    sys.exit(main())
