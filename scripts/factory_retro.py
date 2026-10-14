#!/usr/bin/env python3
"""Factory retro: turn closed factory cards into lessons and AKE post intents.

Reads recently closed issues labelled ``factory:collected`` or titled
``[Foreman] ...`` (``gh issue list``), and for each one the merged pull
request that closed it (``gh pr view``). Then:

1. one dated entry per card is appended to ``docs/FACTORY_LESSONS.md``:
   what failed, what fixed it, the PR, and the check that now guards it.
   Entries carry a ``<!-- factory-lesson issue=N pr=M -->`` marker and a card
   that already has one is never appended again. Cards closed as not planned,
   or closed without a merged PR from this repository, are skipped;
2. cards also labelled ``ake-candidate`` whose PR merged with at least one
   check succeeding and none failing get an AKE post intent JSON for
   ``scripts/ake_bridge.py``
   (``dry-run`` / ``post --input``). The intent is validated here with the
   bridge's own ``build_post_intent``; nothing in this script talks to AKE.

Dry-run is the default and prints what it would write. ``--apply`` writes
the lessons file and the intent files (under ``--out``, default
``./.factory-out``, which is gitignored). ``--max-writes`` caps new lesson
entries plus intents for newly recorded cards; rewriting the intent of a card
recorded earlier is idempotent and not counted. Issue and PR text is
untrusted data: it is flattened to one line, stripped of control/bidi
characters, HTML and Markdown markup, length capped, and token-shaped strings
are redacted before anything is written.

Python 3.9+, stdlib only. Exit codes: 0 done, 1 gh or input failure.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ake_bridge  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPO = "kody-w/rappterbook"
DEFAULT_LESSONS = ROOT / "docs" / "FACTORY_LESSONS.md"
DEFAULT_OUT = ".factory-out"
COLLECTED_LABEL = "factory:collected"
AKE_LABEL = "ake-candidate"
FOREMAN_PREFIX = "[Foreman]"
INTENT_TAGS = ["factory"]
MAX_FIELD = 300
PASSING = frozenset({"SUCCESS", "NEUTRAL", "SKIPPED"})
MD_SPECIAL_RE = re.compile(r"([\\`*_\[\]()!#|~])")

MARKER_RE = re.compile(r"^<!-- factory-lesson issue=([1-9][0-9]*) pr=[1-9][0-9]* -->$", re.MULTILINE)
# A discussion URL in running text: it must end at whitespace or the end of
# the text, optionally after closing punctuation, so '/321%2Ffake' or
# '/321:x' is not read as discussion 321.
DISCUSSION_RE = re.compile(
    r"https://github\.com/kody-w/rappterbook/discussions/[1-9][0-9]{0,8}(?=[),.;:!?]*(?:\s|$))"
)
ACCEPTANCE_RE = re.compile(r"^##[ \t]+Proposed acceptance check[ \t]*\n+(.+?)(?:\n[ \t]*\n|\Z)",
                           re.MULTILINE | re.DOTALL)
PR_URL_RE = re.compile(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/pull/[1-9][0-9]*")
FIELD_NAMES = {
    "error": ("error", "exact error", "failure", "what failed", "symptom"),
    "environment": ("environment", "env"),
    "guard": ("guard", "guarded by", "check", "verify", "verified by"),
    "fix": ("fix", "what fixed it", "root cause"),
    "source": ("source", "discussion"),
}

HEADER = """# Factory lessons

One entry per factory card (an issue labelled `factory:collected`, or a
`[Foreman]` issue) that was closed by a merged pull request. Entries are
appended by `scripts/factory_retro.py --apply`, oldest first, and never
rewritten; the marker comment under each heading keeps a card from being
recorded twice. Cards closed as not planned or without a merged PR are not
recorded.

Each entry reads:

- **Failed:** the card's `Error:` line, or its title when it has none
- **Fixed by:** the PR that closed the card, and its `Fix:` line or title
- **Guarded by:** the PR's `Guard:` line, else the test files it changed,
  else the card's proposed acceptance check, else the checks that passed on it
- **Environment** and **Source**, when the card names them

Text is copied from issues and PRs as data: flattened to one line, capped at
300 characters, HTML and Markdown markup escaped, and token-shaped strings
redacted.

<!-- entries below are appended by scripts/factory_retro.py -->
"""

Runner = Callable[[list], str]


class RetroError(Exception):
    """gh failed or returned something that is not the JSON we asked for."""


def gh_runner(args: list) -> str:
    """Run one read-only ``gh`` command and return stdout."""
    try:
        proc = subprocess.run(["gh"] + args, capture_output=True, text=True, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RetroError(f"gh {args[0]} {args[1]} failed: {exc}") from exc
    if proc.returncode != 0:
        raise RetroError(f"gh {args[0]} {args[1]} exited {proc.returncode}: {proc.stderr.strip()[:300]}")
    return proc.stdout


def gh_json(runner: Runner, args: list) -> object:
    try:
        return json.loads(runner(args))
    except ValueError as exc:
        raise RetroError(f"gh {args[0]} {args[1]} returned invalid JSON") from exc


# ---------------------------------------------------------------------------
# Untrusted text
# ---------------------------------------------------------------------------

def clean(value: object, limit: int = MAX_FIELD) -> str:
    """One safe line: no controls, bidi or token-shaped strings, at most ``limit`` characters."""
    text = value if isinstance(value, str) else ""
    text = ake_bridge.SURROGATE_RE.sub("", text)
    text = ake_bridge.BIDI_RE.sub("", text)
    text = " ".join(ake_bridge.CONTROL_RE.sub(" ", text).split())
    text = ake_bridge.TOKEN_RE.sub("[REDACTED]", text)
    if len(text) > limit:
        text = text[: limit - 3].rstrip() + "..."
    return text


def md(value: object, limit: int = MAX_FIELD) -> str:
    """``clean`` plus HTML and Markdown escaping, for text that lands in the
    published lessons file: no tags, links, images, emphasis or code spans."""
    text = clean(value, limit).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return MD_SPECIAL_RE.sub(r"\\\1", text)


def code(value: object, limit: int = MAX_FIELD) -> str:
    """Untrusted text as one inline code span (inert: no markup inside)."""
    return "`" + clean(value, limit).replace("`", "'") + "`"


def _field_match(body: object, name: str) -> Optional["re.Match[str]"]:
    if not isinstance(body, str):
        return None
    names = "|".join(re.escape(n) for n in FIELD_NAMES[name])
    pattern = re.compile(r"^[ \t]*(?:[-*][ \t]+)?(\**)[ \t]*(?:" + names + r")[ \t]*\**[ \t]*:[ \t]*(\**)[ \t]*(.*?)[ \t]*$",
                         re.IGNORECASE | re.MULTILINE)
    return pattern.search(body)


def field(body: object, name: str) -> str:
    """The value of the first ``Name: value`` line, without its Markdown dressing.

    Bullets and bold around the label or the value are dropped
    (``**Error:** x``, ``Error: **x**``, ``**Error: x**``); a value that is
    one code span is unwrapped (``Error: `x` ``); an empty value followed by a
    fenced block yields the block's first line.
    """
    match = _field_match(body, name)
    if not match:
        return ""
    value = match.group(3).strip()
    if (match.group(1) or match.group(2)) and value.endswith("*"):
        value = value.rstrip("*").rstrip()
    span = re.fullmatch(r"`([^`]+)`", value)
    if span:
        value = span.group(1).strip()
    if not value:
        fence = re.match(r"[ \t]*\r?\n(?:[ \t]*\r?\n)*[ \t]*(?:`{3,}|~{3,})[^\n]*\n([^\n]*)", body[match.end():])
        if fence and not re.match(r"[ \t]*(?:`{3,}|~{3,})", fence.group(1)):
            value = fence.group(1).strip()
    return value


def discussion_url(body: object) -> str:
    """The card's canonical discussion URL.

    When the card has a ``Source:`` (or ``Discussion:``) line, only that line
    counts: a malformed one gives no URL rather than a prefix of it. Otherwise
    the first discussion URL that stands alone in the body.
    """
    if _field_match(body, "source"):
        candidates = [field(body, "source")]
    else:
        candidates = DISCUSSION_RE.findall(body) if isinstance(body, str) else []
    for candidate in candidates:
        try:
            return ake_bridge.canonical_source(candidate)
        except ake_bridge.AkePolicyError:
            continue
    return ""


# ---------------------------------------------------------------------------
# gh reads
# ---------------------------------------------------------------------------

ISSUE_FIELDS = "number,title,body,labels,closedAt,stateReason,url,closedByPullRequestsReferences"
PR_FIELDS = "number,title,body,url,state,mergedAt,files,statusCheckRollup"


def label_names(item: dict) -> set:
    return {lab.get("name") for lab in item.get("labels") or [] if isinstance(lab, dict)}


def fetch_cards(runner: Runner, repo: str, since: datetime, limit: int) -> list:
    """Closed factory cards since ``since``, oldest first, each listed once."""
    base = ["issue", "list", "--repo", repo, "--state", "closed", "--limit", str(limit), "--json", ISSUE_FIELDS]
    stamp = since.strftime("%Y-%m-%d")
    queries = [
        base + ["--label", COLLECTED_LABEL, "--search", f"closed:>={stamp}"],
        base + ["--search", f'"{FOREMAN_PREFIX}" in:title closed:>={stamp}'],
    ]
    cards = {}
    for args in queries:
        data = gh_json(runner, args)
        if not isinstance(data, list):
            raise RetroError("gh issue list did not return a list")
        if len(data) >= limit:
            raise RetroError(f"gh issue list returned {len(data)} cards, the --limit; "
                             "raise --limit or shorten --days so no card is missed")
        for item in data:
            if not isinstance(item, dict) or not isinstance(item.get("number"), int):
                continue
            title = item.get("title") if isinstance(item.get("title"), str) else ""
            if COLLECTED_LABEL in label_names(item) or title.startswith(FOREMAN_PREFIX):
                cards[item["number"]] = item
    return sorted(cards.values(), key=lambda c: (str(c.get("closedAt") or ""), c["number"]))


def merged_pr(runner: Runner, repo: str, card: dict) -> Optional[dict]:
    """The first merged PR from ``repo`` that closed the card, or None."""
    prefix = f"https://github.com/{repo}/pull/"
    for ref in card.get("closedByPullRequestsReferences") or []:
        if not isinstance(ref, dict) or not isinstance(ref.get("number"), int):
            continue
        url = ref.get("url")
        if not isinstance(url, str) or not url.startswith(prefix):
            continue  # a PR in another repository (or one we cannot place) is not this repo's fix
        pr = gh_json(runner, ["pr", "view", str(ref["number"]), "--repo", repo, "--json", PR_FIELDS])
        if isinstance(pr, dict) and pr.get("state") == "MERGED" and pr.get("mergedAt"):
            return pr
    return None


def checks_passed(pr: dict) -> bool:
    """At least one check concluded SUCCESS, and every other one SUCCESS,
    NEUTRAL or SKIPPED: a PR on which nothing actually ran does not count."""
    rollup = pr.get("statusCheckRollup") or []
    if not isinstance(rollup, list) or not all(isinstance(check, dict) for check in rollup):
        return False
    verdicts = [str(check.get("conclusion") or check.get("state") or "").upper() for check in rollup]
    return any(v == "SUCCESS" for v in verdicts) and all(v in PASSING for v in verdicts)


NO_GUARD = "none recorded; add a test or verify command that fails without this fix"


def _guard_parts(pr: dict, card_body: object = None) -> tuple:
    """(kind, value) of the best guard: the PR's Guard: line, the test files it
    changed, the card's proposed acceptance check, or the checks that passed."""
    stated = field(pr.get("body"), "guard")
    if clean(stated):
        return "stated", stated
    tests = sorted(f.get("path") for f in pr.get("files") or []
                   if isinstance(f, dict) and isinstance(f.get("path"), str) and f["path"].startswith("tests/"))
    if tests:
        return "tests", tests
    acceptance = ACCEPTANCE_RE.search(card_body) if isinstance(card_body, str) else None
    if acceptance and clean(acceptance.group(1)):
        return "acceptance", "acceptance check from the card: " + acceptance.group(1)
    names = sorted({c.get("name") or c.get("context") for c in pr.get("statusCheckRollup") or []
                    if isinstance(c, dict) and str(c.get("conclusion") or c.get("state") or "").upper() == "SUCCESS"
                    and isinstance(c.get("name") or c.get("context"), str)})
    if names:
        return "checks", "checks passed on merge: " + ", ".join(names)
    return "none", NO_GUARD


def guard_of(pr: dict, card_body: object = None) -> str:
    """The guard as plain text (for the AKE intent)."""
    kind, value = _guard_parts(pr, card_body)
    if kind == "tests":
        return clean(", ".join(f"`{t}`" for t in value))
    return clean(value)


def guard_md(pr: dict, card_body: object = None) -> str:
    """The guard as inert Markdown (for the lessons file)."""
    kind, value = _guard_parts(pr, card_body)
    if kind == "tests":
        return clean(", ".join(code(t, 120) for t in value))
    return md(value)


# ---------------------------------------------------------------------------
# Lessons and intents
# ---------------------------------------------------------------------------

def recorded_issues(text: str) -> set:
    return {int(n) for n in MARKER_RE.findall(text)}


def lesson_entry(card: dict, pr: dict) -> str:
    day = str(card.get("closedAt") or "")[:10] or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    body = card.get("body")
    failed = md(field(body, "error")) or md(card.get("title"))
    fix = md(field(pr.get("body"), "fix")) or md(pr.get("title"))
    url = pr.get("url") if isinstance(pr.get("url"), str) else ""
    link = f"[#{pr['number']}]({url})" if PR_URL_RE.fullmatch(url) else f"#{pr['number']}"
    lines = [
        f"### {md(day, 10)} · #{card['number']}: {md(card.get('title'), 120)}",
        f"<!-- factory-lesson issue={card['number']} pr={pr['number']} -->",
        "",
        f"- **Failed:** {failed}",
        f"- **Fixed by:** {link} {fix}",
        f"- **Guarded by:** {guard_md(pr, body)}",
    ]
    environment = md(field(body, "environment"), ake_bridge.MAX_ENVIRONMENT)
    if environment:
        lines.append(f"- **Environment:** {environment}")
    source = discussion_url(body)
    if source:
        lines.append(f"- **Source:** {source}")
    return "\n".join(lines) + "\n"


def ake_intent(card: dict, pr: dict) -> dict:
    """A post intent for scripts/ake_bridge.py, or raise ValueError with the reason it cannot be one."""
    body = card.get("body")
    error = field(body, "error")
    if not error:
        raise ValueError("card has no Error: line (the AKE topic must be the exact error)")
    if len(error) > ake_bridge.MAX_TOPIC:
        raise ValueError(f"error is longer than the AKE topic limit ({ake_bridge.MAX_TOPIC})")
    environment = field(body, "environment")
    if not environment:
        raise ValueError("card has no Environment: line")
    source = discussion_url(body)
    if not source:
        raise ValueError("card cites no canonical discussion URL (the bridge accepts only discussions as Source)")
    fix = clean(field(pr.get("body"), "fix"), 1000) or clean(pr.get("title"), 1000)
    content = "\n".join([
        f"WHEN: {clean(error, ake_bridge.MAX_TOPIC)} ({clean(environment, ake_bridge.MAX_ENVIRONMENT)})",
        f"FIX: {fix}",
        f"GUARD: {guard_of(pr, body)}",
        f"PR: {clean(pr.get('url'), 200)}",
    ])
    intent = {"operation": "post", "environment": environment, "topic": error,
              "content": content, "tags": list(INTENT_TAGS), "source": source}
    try:
        # the bridge's own validation; agent id and destination only feed the key
        ake_bridge.build_post_intent(intent, "factory-retro", "https://ake.invalid")
    except ake_bridge.AkePolicyError as exc:
        raise ValueError(f"bridge would refuse it: {exc}") from exc
    return intent


def plan(cards: list, runner: Runner, repo: str, existing: set, max_writes: int) -> dict:
    """Entries and intents to write, oldest card first.

    ``max_writes`` caps new work: lesson entries, plus intents of cards being
    recorded in this run. The intent of a card recorded earlier is rebuilt
    every run (a fresh checkout has no ``--out``) but is not counted, so
    recorded cards can never hold back new ones.
    """
    entries, intents, skipped = [], [], []
    writes = 0

    def cap_reached(number: int, what: str = "") -> bool:
        if writes < max_writes:
            return False
        skipped.append({"issue": number, "reason": f"{what}write cap of {max_writes} reached; next run"})
        return True

    for card in cards:
        number = card["number"]
        wants_intent = AKE_LABEL in label_names(card)
        recorded = number in existing
        if recorded and not wants_intent:
            continue  # already recorded; nothing left to write for it
        if not recorded and cap_reached(number):
            continue
        if card.get("stateReason") == "NOT_PLANNED":
            skipped.append({"issue": number, "reason": "closed as not planned"})
            continue
        pr = merged_pr(runner, repo, card)
        if pr is None:
            skipped.append({"issue": number, "reason": "closed without a merged PR"})
            continue
        if not recorded:
            entries.append({"issue": number, "pr": pr["number"], "text": lesson_entry(card, pr)})
            existing.add(number)
            writes += 1
        if wants_intent:
            if not checks_passed(pr):
                skipped.append({"issue": number, "reason": "ake-candidate, but the PR's checks did not all pass"})
                continue
            if not recorded and cap_reached(number, "AKE intent deferred: "):
                continue  # the entry is written; the next run, card now recorded, writes the intent
            try:
                intents.append({"issue": number, "file": f"ake-intent-issue-{number}.json",
                                "intent": ake_intent(card, pr)})
            except ValueError as exc:
                skipped.append({"issue": number, "reason": f"no AKE intent: {exc}"})
                continue
            if not recorded:
                writes += 1
    return {"entries": entries, "intents": intents, "skipped": skipped}


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def apply(result: dict, lessons: Path, out: Path) -> None:
    """Write the plan. Entries whose marker the file already holds (an
    earlier or overlapping run wrote them) are not appended again."""
    if result["entries"]:
        text = lessons.read_text(encoding="utf-8") if lessons.exists() else HEADER
        seen = recorded_issues(text)
        if not text.endswith("\n"):
            text += "\n"
        fresh = [entry for entry in result["entries"] if entry["issue"] not in seen]
        for entry in fresh:
            text += "\n" + entry["text"]
        if fresh:
            atomic_write(lessons, text)
    for item in result["intents"]:
        atomic_write(out / item["file"], json.dumps(item["intent"], indent=2, ensure_ascii=False) + "\n")


def run(argv: Optional[list] = None, runner: Runner = gh_runner, now: Optional[datetime] = None) -> dict:
    parser = argparse.ArgumentParser(prog="factory_retro.py", description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--days", type=int, default=14, help="look back this many days (default 14)")
    parser.add_argument("--limit", type=int, default=100, help="issues per gh query (default 100)")
    parser.add_argument("--max-writes", type=int, default=20, help="lesson entries plus intents per run (default 20)")
    parser.add_argument("--lessons", default=str(DEFAULT_LESSONS))
    parser.add_argument("--out", default=DEFAULT_OUT, help="directory for AKE intent files (default ./.factory-out)")
    parser.add_argument("--apply", action="store_true", help="write files; the default only prints the plan")
    args = parser.parse_args(argv)
    if args.days < 1 or args.limit < 1 or args.max_writes < 0:
        parser.error("--days and --limit must be >= 1 and --max-writes >= 0")
    lessons = Path(args.lessons)
    existing = recorded_issues(lessons.read_text(encoding="utf-8")) if lessons.exists() else set()
    since = (now or datetime.now(timezone.utc)) - timedelta(days=args.days)
    cards = fetch_cards(runner, args.repo, since, args.limit)
    result = plan(cards, runner, args.repo, existing, args.max_writes)
    if args.apply:
        apply(result, lessons, Path(args.out))
    result.update({"applied": args.apply, "lessons": str(lessons), "out": args.out, "cards": len(cards)})
    return result


def main(argv: Optional[list] = None) -> int:
    try:
        result = run(argv)
    except (RetroError, OSError) as exc:
        sys.stderr.write(json.dumps({"error": type(exc).__name__, "message": clean(str(exc))}) + "\n")
        return 1
    sys.stdout.write(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
