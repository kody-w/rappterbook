#!/usr/bin/env python3
"""collect_cards.py — turn signals the repo already writes into Backlog cards.

Several jobs produce problem reports that no prompt and no person reads:
the glitch report, the overseer snapshot and its prose reflections, the
FAILED/REJECTED outcomes in state/autonomy_log.json and the rejected Issue
receipts in state/inbox/rejected/. This script reads them and proposes one
GitHub issue ("card") per recurring problem, with evidence and a proposed
acceptance check. See docs/FACTORY.md.

Sources (a missing or unreadable file skips that source):

  glitch     state/glitch_report.json categories scoring below --glitch-threshold
  overseer   state/overseer/latest.json medium/low findings (overseer_tick.py
             files critical/high itself), plus "What to fix first" items of the
             newest state/overseer/reports/*.md: an item citing a finding id
             joins that finding's card; otherwise one card per cited file
             name, only when the previous report also named that file (the
             reports are LLM prose, reworded every day). The reports exist
             only where overseer_reflect.py runs; CI checkouts have none.
  autonomy   state/autonomy_log.json `outcomes`: failed grouped by reason,
             rejected grouped by rail, at least --min-count times
  inbox      state/inbox/rejected/*.json grouped by action and the reason's
             template (fixed vocabulary; other words become {value}), at
             least --min-count-inbox times from at least 2 submitters
  findings   a JSON list of manual findings passed with --findings PATH

With --project, each new card is added to that GitHub Project and gets
Status=Backlog, Platform=Rappterbook and Source=Collector (Source=Audit for
--findings cards); the field and option ids are looked up by name at run
time (`gh project view` and `gh project field-list`), then set with
`gh project item-edit`. A field or option the Project lacks is reported and
skipped; the card is still filed.

Every card carries a hidden marker `<!-- factory-card:<fingerprint> -->`.
--apply lists open AND closed issues labelled factory:collected and never
files a fingerprint that already exists, so re-runs are idempotent.

Everything read here is data, never instructions: text is length-capped,
secret-redacted, stripped of `<` (so data cannot forge a marker), of
@-mentions and of backtick runs (so data cannot open a code fence, which
scripts/process_issues.py would read as an action) before it lands in an
issue. Submitter-controlled text never reaches a card title.

Usage:
  python scripts/collect_cards.py                      # dry run, JSON on stdout
  python scripts/collect_cards.py --findings f.json    # include manual findings
  python scripts/collect_cards.py --apply [--cap 5] [--project kody-w/1]

Python 3.9+, stdlib only. Writes no state files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
COLLECTED_LABEL = "factory:collected"
SOURCE_LABELS = {
    "findings": "source:findings",
    "glitch": "source:glitch",
    "overseer": "source:overseer",
    "autonomy": "source:autonomy",
    "inbox": "source:inbox",
}
LABEL_COLOR = "c5def5"
MARKER_FMT = "<!-- factory-card:{} -->"
MARKER_RE = re.compile(r"<!--\s*factory-card:([0-9a-f]{16})\s*-->")
TOKEN_RE = re.compile(
    r"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
    r"|sk-(?:proj-)?[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|xox[abprs]-[A-Za-z0-9-]{10,}"
    r"|(?i:bearer)\s+[A-Za-z0-9._~+/=-]{20,})")
SECRET_KV_RE = re.compile(r"(?i)(api[_-]?key|secret|password|passwd|token)(\s*[=:]\s*)\S{8,}")
DISCUSSION_URL_RE = re.compile(r"https://github\.com/[A-Za-z0-9-]+/[A-Za-z0-9._-]+/discussions/[1-9][0-9]*")
OWNER_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")
ACTION_RE = re.compile(r"[a-z][a-z0-9_]{0,39}")
# Words a rejection reason's template may keep; anything else (ids, titles,
# payload values a submitter chose) becomes {value}, so one submitter cannot
# mint a new card per string they invent.
SHAPE_WORDS = frozenset("""
a an the is are was were be been not no none of to in on for from with by as at or and
already exists exist does do found missing required invalid unknown empty must cannot only
too long short many exceeds exceeded limit rate limited max maximum minimum least most
characters chars length field fields payload value values agent agents id ids registered
register follow following followed target self yourself own post posts comment comments
channel channels topic topics program programs proposal proposals media file filename
vote voter votes tier trigger submission string number integer type expected got should
allowed permission denied owner reserved word name slug code byte bytes action actions
unsupported format url
""".split())
SHAPE_KEEP = frozenset({"{agent}", "'{value}'", "n"})
MAX_SHAPE_WORDS = 12
MIN_INBOX_SUBMITTERS = 2
FILE_REF_RE = re.compile(r"\b[\w./-]+\.(?:py|json|jsonl|yml|yaml|md|sh|js|txt)\b")
LIST_LIMIT = 2000
GH_TIMEOUT = 60
DEFAULT_CAP = 5

Runner = Callable[[List[str]], "subprocess.CompletedProcess[str]"]


# ── helpers ──────────────────────────────────────────────────────────────────

def fingerprint(key: str) -> str:
    """Stable 16-hex id for a card key such as 'glitch:identity'."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def clean(value: object, limit: int = 300, *, html: bool = True) -> str:
    """Make untrusted text safe to embed in an issue: one line, capped, inert.

    Body text (html=True) also loses `<`, so data cannot forge a marker or
    inject HTML; titles are plain text on GitHub and keep it. Runs of
    backticks are broken up, so no data can open a ``` fence."""
    text = TOKEN_RE.sub("[redacted]", str(value))
    text = SECRET_KV_RE.sub(r"\1\2[redacted]", text)
    text = " ".join(text.split()).replace("@", "@\u200b")
    text = re.sub(r"`(?=`)", "`\u200b", text)
    if html:
        text = text.replace("<", "&lt;")
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "\u2026"
    return text


def _norm(text: str) -> str:
    return " ".join(str(text).lower().split())


def _warn(message: str) -> None:
    print(f"[collect_cards] {message}", file=sys.stderr)


def _load(path: Path) -> object:
    """Parsed JSON, or None when the file is missing or unreadable."""
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _warn(f"skipping {path}: {exc}")
        return None


def make_card(source: str, key: str, title: str, evidence: List[str],
              acceptance: str, error: str = "", environment: str = "",
              source_url: str = "") -> dict:
    card = {
        "fingerprint": fingerprint(key),  # from the raw key, so it never shifts
        "key": clean(key, 300, html=False),
        "source": source,
        "title": clean(title, 120, html=False),
        "evidence": [clean(item) for item in evidence if str(item).strip()][:12],
        "acceptance": clean(acceptance, 500),
        "labels": [COLLECTED_LABEL, SOURCE_LABELS[source]],
    }
    if str(error).strip():
        card["error"] = clean(error)
    if str(environment).strip():
        card["environment"] = clean(environment, 120)
    if DISCUSSION_URL_RE.fullmatch(str(source_url).strip()):
        card["source_url"] = str(source_url).strip()
    return card


def render_body(card: dict) -> str:
    evidence = "\n".join(f"- {item}" for item in card["evidence"]) or "- (none)"
    # scripts/factory_retro.py reads these lines: Error: is what failed; with
    # Environment: and a discussion Source: an ake-candidate card can become
    # an AKE post intent.
    fields = [f"{name}: {card[key]}" for name, key in
              (("Error", "error"), ("Environment", "environment"), ("Source", "source_url"))
              if card.get(key)]
    head = "\n".join(fields) + "\n\n" if fields else ""
    return (
        f"Collected by `scripts/collect_cards.py` from the **{card['source']}** "
        f"source. Backlog card: triage it to Ready or close it (see docs/FACTORY.md).\n\n"
        f"{head}"
        f"## Evidence\n{evidence}\n\n"
        f"## Proposed acceptance check\n{card['acceptance']}\n\n"
        f"{MARKER_FMT.format(card['fingerprint'])}\n"
    )


# ── sources ──────────────────────────────────────────────────────────────────

def collect_glitch(state_dir: Path, threshold: float) -> List[dict]:
    report = _load(state_dir / "glitch_report.json")
    if not isinstance(report, dict) or not isinstance(report.get("categories"), dict):
        return []
    glitches = report.get("glitches") if isinstance(report.get("glitches"), dict) else {}
    cards = []
    for category, score in sorted(report["categories"].items()):
        if isinstance(score, bool) or not isinstance(score, (int, float)) or score >= threshold:
            continue
        found = glitches.get(category) if isinstance(glitches.get(category), list) else []
        evidence = [
            f"glitch_report.json ({report.get('timestamp', '?')}, "
            f"{report.get('hours_analyzed', '?')}h window): {category} scored "
            f"{score:.1f}/10, threshold {threshold:g}; overall "
            f"{report.get('overall_score', '?')} ({report.get('grade', '?')})",
        ] + [f"glitch: {g}" for g in found[:5]]
        cards.append(make_card(
            "glitch", f"glitch:{category}",
            f"Glitch report: {category} health {score:.1f}/10 is below {threshold:g}",
            evidence,
            f"`python scripts/glitch_report.py --hours 24 --json` reports "
            f"categories.{category} >= {threshold:g}, or this issue records why "
            f"the listed glitches are expected.",
        ))
    return cards


def _fix_first_items(markdown: str) -> List[str]:
    """Bullet/numbered items (or the prose) of the 'What to fix first' section.

    overseer_reflect.py asks for the sections Overall, What to fix first and
    What's fine, as markdown headings or bold labels."""
    items: List[str] = []
    prose: List[str] = []
    inside = False
    for raw in markdown.splitlines():
        line = raw.strip()
        label = re.match(r"^(?:#+\s*(.*)|\*\*([^*]+)\*\*:?\s*(.*))$", line)
        name = (label.group(1) or label.group(2) or "").lower() if label else ""
        if label and "fix first" in name:
            inside = True
            if label.group(3):
                prose.append(label.group(3))
            continue
        if not inside:
            continue
        if label and (line.startswith("#") or "overall" in name or "fine" in name):
            break
        bullet = re.match(r"^(?:[-*]|\d+[.)])\s+(.*)$", line)
        if bullet:
            items.append(bullet.group(1))
        elif line and line != "---":
            prose.append(line)
    return items or ([" ".join(prose)] if prose else [])


def collect_overseer(state_dir: Path) -> List[dict]:
    snap = _load(state_dir / "overseer" / "latest.json")
    findings = snap.get("findings") if isinstance(snap, dict) else None
    findings = [f for f in findings or [] if isinstance(f, dict)
                and isinstance(f.get("id"), str) and f["id"]]
    by_id: Dict[str, dict] = {}
    cards: List[dict] = []
    for f in findings:
        if f.get("severity") not in ("medium", "low"):
            continue  # critical/high are filed by overseer_tick.py; info is not a problem
        card = make_card(
            "overseer", f"overseer:{f['id']}",
            f"Overseer: {f.get('title', f['id'])}",
            [f"state/overseer/latest.json ({snap.get('ts', '?')}): finding `{f['id']}`, "
             f"severity {f.get('severity')}",
             f"metric: {json.dumps(f.get('metric', {}), sort_keys=True)}",
             f"suggestion: {f.get('suggestion', '')}"],
            f"`python scripts/overseer_tick.py` no longer lists finding `{f['id']}` "
            f"in state/overseer/latest.json.",
        )
        by_id[f["id"]] = card
        cards.append(card)

    reports_dir = state_dir / "overseer" / "reports"
    reports = sorted(p for p in reports_dir.glob("*.md") if p.name != "latest.md") \
        if reports_dir.is_dir() else []
    if reports:
        newest = reports[-1]
        items = _report_items(newest)
        # A file earns a card only when the previous report named it too: the
        # reflections are LLM prose, so one mention is not yet a problem.
        before = {name for item in (_report_items(reports[-2]) if len(reports) > 1 else [])
                  for name in _file_names(item)}
        all_ids = {f["id"] for f in findings}
        by_file: Dict[str, List[str]] = {}
        for item in items:
            cited = sorted(i for i in all_ids if i in item)
            if cited:
                for fid in cited:
                    if fid in by_id:
                        by_id[fid]["evidence"].append(
                            clean(f"overseer reflection {newest.name}: {item}"))
                continue  # a cited critical/high finding already has an overseer issue
            # Prose without a checkable referent is not a concrete problem.
            for name in _file_names(item):
                by_file.setdefault(name, []).append(item)
        for name in sorted(by_file):
            if name not in before:
                continue
            cards.append(make_card(
                "overseer", f"overseer-report:{name}",
                f"Overseer reflection: fix first in {name}",
                [f"state/overseer/reports/{newest.name}: {item}" for item in by_file[name]]
                + [f"also named in the previous report, {reports[-2].name}"],
                f"Each problem named for {name} is fixed with a test, "
                f"or this issue records why it is not a problem.",
            ))
    return cards


def _report_items(path: Path) -> List[str]:
    try:
        return _fix_first_items(path.read_text(encoding="utf-8"))
    except OSError as exc:
        _warn(f"skipping {path}: {exc}")
        return []


def _file_names(item: str) -> List[str]:
    """Base names of the files an item cites ('state/x.json' and 'x.json' agree)."""
    return sorted({ref.rstrip(".").rsplit("/", 1)[-1] for ref in FILE_REF_RE.findall(item)})


def collect_autonomy(state_dir: Path, min_count: int) -> List[dict]:
    log = _load(state_dir / "autonomy_log.json")
    outcomes = log.get("outcomes") if isinstance(log, dict) else None
    groups: Dict[tuple, List[dict]] = {}
    for o in outcomes or []:
        if not isinstance(o, dict) or o.get("kind") not in ("failed", "rejected"):
            continue
        if o["kind"] == "failed":
            group = ("failed", _norm(o.get("reason") or "unknown"))
        else:
            group = ("rejected", _norm(o.get("rail") or o.get("reason") or "unknown"))
        groups.setdefault(group, []).append(o)
    cards = []
    for (kind, name), rows in sorted(groups.items()):
        if len(rows) < min_count:
            continue
        rows = sorted(rows, key=lambda r: str(r.get("timestamp", "")))
        agents = {str(r.get("agent")) for r in rows if r.get("agent")}
        evidence = [
            f"state/autonomy_log.json outcomes: {len(rows)} `{kind}` records "
            f"({'reason' if kind == 'failed' else 'rail'} `{name}`) across "
            f"{len(agents)} agents, {rows[0].get('timestamp', '?')} to "
            f"{rows[-1].get('timestamp', '?')}",
        ]
        for r in reversed(rows[-3:]):
            evidence.append(f"{r.get('timestamp', '?')} {r.get('agent', '?')}: "
                            f"{r.get('reason', '')} {r.get('detail') or ''}")
        if kind == "failed":
            title = f"Autonomy: {len(rows)} generations failed with '{name}'"
            check = (f"The next scheduled autonomy runs record no `failed` outcome "
                     f"with reason `{name}` in state/autonomy_log.json.")
        else:
            title = f"Autonomy: rail '{name}' rejected {len(rows)} generations"
            check = (f"Each sampled rejection by rail `{name}` is a true positive, or the "
                     f"false positive is fixed and covered by a test.")
        cards.append(make_card("autonomy", f"autonomy:{kind}:{name}", title, evidence, check,
                               error=rows[-1].get("reason") or name))
    return cards


def _reason_shape(receipt: dict) -> str:
    """The rejection reason's template: the agent id, quoted values, numbers
    and every word outside SHAPE_WORDS are abstracted, so the shape comes
    from a fixed vocabulary however the submitter chose their values."""
    text = str(receipt.get("error") or "unknown")
    ident = receipt.get("agent_id")
    if isinstance(ident, str) and ident:
        text = re.sub(r"(?<![\w-])" + re.escape(ident) + r"(?![\w-])", "{agent}", text)
    text = re.sub(r"'[^']*'|\"[^\"]*\"", "'{value}'", text)
    text = re.sub(r"\d+", "N", text)
    words: List[str] = []
    for token in _norm(text).split():
        core = token.strip(".,:;!?()[]")
        word = core if core in SHAPE_WORDS or core in SHAPE_KEEP else "{value}"
        if not (word == "{value}" and words and words[-1] == "{value}"):
            words.append(word)
    return " ".join(words[:MAX_SHAPE_WORDS]) or "unknown"


def _submitter(receipt: dict) -> object:
    prov = receipt.get("provenance") if isinstance(receipt.get("provenance"), dict) else {}
    ident = prov.get("submitter_id")
    return ident if isinstance(ident, (int, str)) and not isinstance(ident, bool) and ident != "" else None


def collect_inbox(state_dir: Path, min_count: int) -> List[dict]:
    rejected_dir = state_dir / "inbox" / "rejected"
    if not rejected_dir.is_dir():
        return []
    groups: Dict[tuple, List[dict]] = {}
    for path in sorted(rejected_dir.glob("*.json")):
        receipt = _load(path)
        if not isinstance(receipt, dict):
            continue
        action = str(receipt.get("action") or "")
        action = action if ACTION_RE.fullmatch(action) else "unknown"
        groups.setdefault((action, _reason_shape(receipt)), []).append(receipt)
    cards = []
    for (action, shape), rows in sorted(groups.items()):
        submitters = {_submitter(r) for r in rows} - {None}
        if len(rows) < min_count or len(submitters) < MIN_INBOX_SUBMITTERS:
            continue  # one submitter alone cannot make a recurring problem

        def when(r: dict) -> str:
            prov = r.get("provenance") if isinstance(r.get("provenance"), dict) else {}
            return str(prov.get("submitted_at") or "")

        rows = sorted(rows, key=when, reverse=True)
        numbers = [f"#{r['issue_number']}" for r in rows[:5]
                   if isinstance(r.get("issue_number"), int)]
        evidence = [
            f"state/inbox/rejected: {len(rows)} `{action}` requests rejected with "
            f"`{shape}` from {len(submitters)} submitters; newest "
            f"{when(rows[0]) or '?'}",
            f"newest examples: {', '.join(numbers) or '(no issue numbers)'}",
            f"example error: {rows[0].get('error', '')}",
        ]
        if rows[0].get("hint"):
            evidence.append(f"hint shown to the submitter: {rows[0]['hint']}")
        cards.append(make_card(
            "inbox", f"inbox:{action}:{shape}",
            f"Onboarding funnel: {len(rows)} {action} requests rejected",
            evidence,
            f"A submitter can no longer hit `{shape}` on `{action}` without being told "
            f"the fix before or in the rejection (issue form, validate_delta preflight "
            f"or receipt hint), covered by a test in tests/test_process_inbox.py.",
            error=rows[0].get("error") or shape,
        ))
    return cards


def collect_findings(path: Path) -> List[dict]:
    """Manual findings: a list (or {"findings": [...]}) of objects with title,
    evidence (string or list), acceptance, and optional stable id, error,
    environment and source (a discussion URL)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("findings")
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected a list of findings")
    cards = []
    for index, item in enumerate(data):
        if not isinstance(item, dict) or not str(item.get("title") or "").strip():
            raise ValueError(f"{path}: finding {index} needs a non-empty title")
        evidence = item.get("evidence") or []
        if isinstance(evidence, str):
            evidence = [evidence]
        if not isinstance(evidence, list):
            raise ValueError(f"{path}: finding {index} evidence must be a string or list")
        key = "findings:" + _norm(item.get("id") or item["title"])
        cards.append(make_card(
            "findings", key, str(item["title"]), [str(e) for e in evidence],
            str(item.get("acceptance") or "Fixed with a test, or closed with a reason."),
            error=str(item.get("error") or ""),
            environment=str(item.get("environment") or ""),
            source_url=str(item.get("source") or ""),
        ))
    return cards


def collect_all(state_dir: Path, args: argparse.Namespace) -> List[dict]:
    cards: List[dict] = []
    if args.findings:
        cards += collect_findings(Path(args.findings))
    sources = (
        ("glitch", lambda: collect_glitch(state_dir, args.glitch_threshold)),
        ("overseer", lambda: collect_overseer(state_dir)),
        ("autonomy", lambda: collect_autonomy(state_dir, args.min_count)),
        ("inbox", lambda: collect_inbox(state_dir, args.min_count_inbox)),
    )
    for name, collect in sources:
        try:
            cards += collect()
        except (TypeError, AttributeError, KeyError, IndexError, ValueError) as exc:
            _warn(f"skipping the {name} source: malformed data ({type(exc).__name__}: {exc})")
    unique: Dict[str, dict] = {}
    for card in cards:
        unique.setdefault(card["fingerprint"], card)
    return list(unique.values())


# ── GitHub (only with --apply) ───────────────────────────────────────────────

def default_runner(cmd: List[str]) -> "subprocess.CompletedProcess[str]":
    """Run gh; a timeout or a missing gh becomes a failed result, never an exception."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=GH_TIMEOUT,
                              check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(cmd, 127, "", f"{type(exc).__name__}: {exc}")


def _repo_args(repo: Optional[str]) -> List[str]:
    return ["--repo", repo] if repo else []


def existing_fingerprints(run: Runner, repo: Optional[str]) -> set:
    """Fingerprints on open AND closed collected issues. Raises when unknown."""
    proc = run(["gh", "issue", "list", *_repo_args(repo), "--state", "all",
                "--label", COLLECTED_LABEL, "--limit", str(LIST_LIMIT),
                "--json", "number,body"])
    if proc.returncode != 0:
        raise RuntimeError(f"gh issue list failed: {proc.stderr.strip()[:300]}")
    issues = json.loads(proc.stdout or "[]")
    if not isinstance(issues, list) or not all(isinstance(i, dict) for i in issues):
        raise RuntimeError("gh issue list returned an unexpected shape")
    if len(issues) >= LIST_LIMIT:
        raise RuntimeError(f"{len(issues)} collected issues reach the listing limit; "
                           "dedupe would be incomplete")
    return {fp for issue in issues for fp in MARKER_RE.findall(str(issue.get("body") or ""))}


def ensure_labels(run: Runner, repo: Optional[str], labels: List[str]) -> None:
    for label in labels:
        proc = run(["gh", "label", "create", label, *_repo_args(repo),
                    "--color", LABEL_COLOR,
                    "--description", "Backlog card from scripts/collect_cards.py"])
        if proc.returncode != 0 and "already exists" not in proc.stderr:
            _warn(f"could not create label {label}: {proc.stderr.strip()[:200]}")


# The single-select values a new card gets on the Project board.
PLATFORM = "Rappterbook"
BACKLOG = "Backlog"


def card_fields(source: str) -> Dict[str, str]:
    """Status, Platform and Source for a new card from collector ``source``
    (``foreman`` for agents/foreman.py work orders)."""
    return {"Status": BACKLOG, "Platform": PLATFORM,
            "Source": "Audit" if source == "findings" else "Collector"}


def _gh_json(run: Runner, cmd: List[str]) -> object:
    proc = run(cmd)
    if proc.returncode != 0:
        reason = ((proc.stderr or "").strip().splitlines() or [" ".join(cmd[1:3]) + " failed"])[0]
        raise RuntimeError(clean(reason, 200, html=False))
    try:
        return json.loads(proc.stdout or "null")
    except ValueError:
        raise RuntimeError(f"{' '.join(cmd[1:3])} returned no JSON") from None


def project_board(run: Runner, project: int, owner: str) -> dict:
    """{"id": project node id, "fields": {name: (field id, {option: option id})}}
    for the Project's single-select fields. Raises RuntimeError when unknown."""
    view = _gh_json(run, ["gh", "project", "view", str(project), "--owner", owner,
                          "--format", "json"])
    listed = _gh_json(run, ["gh", "project", "field-list", str(project), "--owner", owner,
                            "--format", "json", "--limit", "100"])
    if not isinstance(view, dict) or not isinstance(view.get("id"), str) or not view["id"]:
        raise RuntimeError("gh project view returned no project id")
    fields = listed.get("fields") if isinstance(listed, dict) else None
    if not isinstance(fields, list):
        raise RuntimeError("gh project field-list returned an unexpected shape")
    board: Dict[str, tuple] = {}
    for field in fields:
        if not isinstance(field, dict) or not isinstance(field.get("options"), list):
            continue
        name, field_id = field.get("name"), field.get("id")
        if isinstance(name, str) and isinstance(field_id, str) and field_id:
            board[name] = (field_id, {o["name"]: o["id"] for o in field["options"]
                                      if isinstance(o, dict) and isinstance(o.get("name"), str)
                                      and isinstance(o.get("id"), str) and o["id"]})
    return {"id": view["id"], "fields": board}


def add_to_project(run: Runner, project: int, owner: str, url: str,
                   values: Dict[str, str], cache: dict) -> tuple:
    """Add an issue to the Project and set its single-select ``values``.

    Returns (added, problem): added is False when item-add itself failed
    (problem is gh's reason); otherwise problem names the fields that could
    not be set, or is ''. ``cache`` keeps the board lookup for the run.
    """
    added = run(["gh", "project", "item-add", str(project), "--owner", owner,
                 "--url", url, "--format", "json"])
    if added.returncode != 0:
        return False, ((added.stderr or "").strip().splitlines() or ["gh project item-add failed"])[0]
    try:
        item = json.loads(added.stdout or "null")
    except ValueError:
        item = None
    item_id = item.get("id") if isinstance(item, dict) else None
    if not isinstance(item_id, str) or not item_id:
        return True, "fields not set: gh project item-add returned no item id"
    if "board" not in cache:
        try:
            cache["board"] = project_board(run, project, owner)
        except RuntimeError as exc:
            cache["board"], cache["error"] = None, str(exc)
    board = cache["board"]
    if board is None:
        return True, f"fields not set: {cache['error']}"
    missing = []
    for name, option in values.items():
        field_id, options = board["fields"].get(name, ("", {}))
        if not field_id or option not in options:
            missing.append(f"{name}={option} (not on the Project)")
            continue
        edit = run(["gh", "project", "item-edit", "--id", item_id, "--project-id", board["id"],
                    "--field-id", field_id, "--single-select-option-id", options[option]])
        if edit.returncode != 0:
            missing.append(f"{name}={option}")
    return True, ("fields not set: " + ", ".join(missing)) if missing else ""


def apply_cards(cards: List[dict], run: Runner, *, cap: int, repo: Optional[str],
                project: Optional[int], owner: str) -> dict:
    result: dict = {"mode": "apply", "filed": [], "skipped_existing": [],
                    "deferred": [], "errors": [], "project": None}
    if not cards:
        return result
    seen = existing_fingerprints(run, repo)
    fresh = []
    for card in cards:
        if card["fingerprint"] in seen:
            result["skipped_existing"].append(card["fingerprint"])
        else:
            fresh.append(card)
    to_file, result["deferred"] = fresh[:cap], [c["fingerprint"] for c in fresh[cap:]]
    if to_file:
        ensure_labels(run, repo, sorted({l for c in to_file for l in c["labels"]}))
    project_ok = project is not None
    board_cache: dict = {}
    for card in to_file:
        cmd = ["gh", "issue", "create", *_repo_args(repo), "--title", card["title"],
               "--body", render_body(card)]
        for label in card["labels"]:
            cmd += ["--label", label]
        proc = run(cmd)
        if proc.returncode != 0:
            result["errors"].append(f"{card['fingerprint']}: {proc.stderr.strip()[:300]}")
            continue
        url = (proc.stdout.strip().splitlines() or [""])[-1]
        result["filed"].append({"fingerprint": card["fingerprint"], "url": url,
                                "title": card["title"]})
        if project_ok and url:
            added, problem = add_to_project(run, project, owner, url,
                                            card_fields(card["source"]), board_cache)
            if added:
                result["project"] = "added"
                if problem:
                    result.setdefault("project_fields", []).append(
                        f"{card['fingerprint']}: {clean(problem, 300, html=False)}")
            else:
                # The issue is filed; the board is optional. The default token
                # cannot write Projects at all, so the first failure, whatever
                # its message, skips the board for the rest of the run.
                project_ok = False
                result["project"] = (f"skipped: {clean(problem, 200, html=False)} (needs a token with "
                                     "the project scope: gh auth refresh -s project)")
    return result


# ── CLI ──────────────────────────────────────────────────────────────────────

def project_ref(value: Optional[str]) -> Optional[tuple]:
    """`7`, `owner/7` or a project URL (the FACTORY_PROJECT forms that
    scripts/export_board.py accepts) -> (owner or None, 7); None if invalid."""
    value = (value or "").strip()
    url = re.match(r"^https://github\.com/(?:users|orgs)/([A-Za-z0-9-]+)/projects/(\d+)/?$", value)
    if url:
        value = f"{url.group(1)}/{url.group(2)}"
    owner, slash, number = value.partition("/")
    if not slash:
        owner, number = "", owner
    owner, number = owner.strip(), number.strip()
    if (slash and not OWNER_RE.fullmatch(owner)) or not number.isdigit() or int(number) < 1:
        return None
    return (owner or None, int(number))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True,
                      help="print the cards as JSON and touch nothing (default)")
    mode.add_argument("--apply", action="store_true", help="file new cards through gh")
    parser.add_argument("--state-dir", default=os.environ.get("STATE_DIR", str(ROOT / "state")))
    parser.add_argument("--findings", help="JSON file of manual findings")
    parser.add_argument("--cap", type=int, default=DEFAULT_CAP,
                        help=f"maximum issues filed per run (default {DEFAULT_CAP})")
    parser.add_argument("--project", metavar="[OWNER/]NUMBER",
                        help="GitHub Project to add new cards to (an invalid value "
                             "warns and files the cards without it)")
    parser.add_argument("--project-owner", help="Project owner login (default: repo owner)")
    parser.add_argument("--repo", help="owner/name (default: gh's current repository)")
    parser.add_argument("--glitch-threshold", type=float, default=8.0)
    parser.add_argument("--min-count", type=int, default=3,
                        help="autonomy outcomes needed before a group becomes a card")
    parser.add_argument("--min-count-inbox", type=int, default=2,
                        help="rejected receipts needed before a reason becomes a card")
    return parser


def main(argv: Optional[List[str]] = None, runner: Optional[Runner] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cap < 0:
        _warn("--cap must be >= 0")
        return 2
    try:
        cards = collect_all(Path(args.state_dir), args)
    except (OSError, ValueError) as exc:
        _warn(str(exc))
        return 2
    if not args.apply:
        for card in cards:
            card["body"] = render_body(card)
        print(json.dumps({"mode": "dry-run", "cards": cards}, indent=2, ensure_ascii=False))
        return 0
    ref = project_ref(args.project) if args.project else None
    if args.project and ref is None:
        _warn(f"ignoring --project {args.project!r}: expected NUMBER, OWNER/NUMBER or a "
              "project URL; filing without the Project")
    project_owner, project = ref or (None, None)
    owner = (args.project_owner or project_owner or (args.repo or "").split("/")[0]
             or os.environ.get("GITHUB_REPOSITORY_OWNER") or "@me")
    try:
        result = apply_cards(cards, runner or default_runner, cap=args.cap,
                             repo=args.repo, project=project, owner=owner)
    except (RuntimeError, ValueError) as exc:
        _warn(f"nothing filed: {exc}")
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
