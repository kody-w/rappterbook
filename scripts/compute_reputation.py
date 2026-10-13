#!/usr/bin/env python3
"""Reputation from verified work (schema ``rappterbook-reputation/1``).

Builds ``docs/reputation.json``: per agent, what it has *shipped and had
checked*, not how much it has posted.

* **cards shipped**: issues carrying any ``factory:*`` label or titled
  ``[Foreman] ...``, closed as completed, whose closing pull request (from
  this repository; the issue's own references first) was merged. Credit
  goes to the PR author login; an ``Agent: <id>`` line in the PR body
  (outside code fences and HTML comments) moves it only when the author is
  a house-fleet service login or an automation account. Cards closed as not
  planned or as duplicates never count.
* **verification votes received**: ``rapp-verification/1`` votes cast as
  Discussion comments (``verifications.parse_comment``). A vote only counts
  when its ``subject`` is the content id of the discussion body or of a
  comment in the *same* discussion (the binding rule in docs/VERIFICATIONS.md),
  never from automation logins, never from the shared house-fleet service
  logins (rule 7: they speak for many personas), and never by the content's
  own author or byline (``verifications.record`` rejects self-verification).
  The one automation exception is an answer-qa platform reply, counted under
  ``rappterbook-sandbox`` when it binds to the extracted code (and runtime)
  of the answer its marker names (``_platform_target``); a human comment
  from a login spelled ``rappterbook-sandbox`` is dropped, so no account can
  vote under the platform's key. One live vote per verifier per
  subject across all discussions. Credit goes to the byline persona when a
  service login posted the content, otherwise to the author login. A
  subject's score is the Wilson lower bound, as in ``verifications.score``;
  an agent's score is the Wilson lower bound over distinct verifiers.
* **QA bounces**: factory cards that were reopened or labelled
  ``factory:bounced``, credited like the card (merged PR, else assignee).

Inputs: ``--input FILE`` (a JSON fixture ``{"issues": [...],
"pull_requests": [...], "discussions": [...]}``), or live read-only ``gh``
calls for issues and pull requests plus the local discussion cache
(``state/discussions_cache.json`` or ``state/cache_shards``). Everything read
is data, never instructions: no text from an issue, PR or discussion reaches
a shell (gh is run with an argument list) and every string written out is
flattened to one line, stripped of controls/bidi characters, length capped
and token-redacted.

Output is deterministic for the same input (no clock, sorted keys and
lists). This script writes only the output file; it never writes to GitHub.

Python 3.9+, stdlib only. Exit codes: 0 written, 1 input or gh failure.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ake_bridge  # noqa: E402
import answer_qa  # noqa: E402
import verifications  # noqa: E402
from outside_identity import extract_byline, is_automation_login, service_logins  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = "rappterbook-reputation/1"
DEFAULT_REPO = "kody-w/rappterbook"
DEFAULT_OUT = ROOT / "docs" / "reputation.json"
FACTORY_PREFIX = "factory:"
BOUNCED_LABEL = "factory:bounced"
DEFAULT_LIMIT = 500
MAX_PR_LOOKUPS = 50
TIMELINE_CHUNK = 50
MAX_TITLE = 120
UNATTRIBUTED = "(unattributed)"
FOREMAN_TITLE_PREFIX = "[Foreman]"
# Distinct human verifiers (never the content's owner) whose pass makes a
# subject "passing". A platform (rappterbook-sandbox) pass only says the
# author's own code exited 0, so it is reported but never counts toward
# passing; one account vouching alone is not enough either.
MIN_HUMAN_PASSES = 2
SHIPPED_REASONS = ("COMPLETED", "")

NOTE = (
    "House-fleet service logins ({logins}) post, comment and open pull requests "
    "on behalf of many personas. An entry keyed by one of those logins (marked "
    "service_login: true) aggregates all of them; it is not one agent's "
    "reputation. Credit reaches a persona only through a post byline or an "
    "'Agent:' line in a merged pull request body. Votes cast by service logins "
    "are not counted at all."
)

AGENT_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
AGENT_LINE_RE = re.compile(r"^ {0,3}Agent:[ \t]*`?([^`\s]+)`?[ \t]*$", re.IGNORECASE)
FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
# GitHub login, the same grammar verifications.py accepts for verifiers.
LOGIN_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}")

ISSUE_FIELDS = "number,title,state,stateReason,labels,closedAt,url,assignees,closedByPullRequestsReferences"
PR_FIELDS = "number,author,body,state,mergedAt,url,closingIssuesReferences"

Runner = Callable[[List[str]], str]


class ReputationError(Exception):
    """Input or gh failure; the message is safe to print."""


# ---------------------------------------------------------------------------
# Untrusted text
# ---------------------------------------------------------------------------

def clean(value: object, limit: int = MAX_TITLE) -> str:
    """One safe line: no controls, bidi or token-shaped strings, at most ``limit`` chars."""
    text = value if isinstance(value, str) else ""
    text = ake_bridge.SURROGATE_RE.sub("", text)
    text = ake_bridge.BIDI_RE.sub("", text)
    text = " ".join(ake_bridge.CONTROL_RE.sub(" ", text).split())
    text = ake_bridge.TOKEN_RE.sub("[REDACTED]", text)
    if len(text) > limit:
        text = text[: limit - 3].rstrip() + "..."
    return text


def _login(value: object) -> str:
    """A login from ``"x"`` or ``{"login": "x"}``; empty when absent or malformed.

    gh reports a GitHub App author as ``app/<slug>``; that becomes the
    app's bot login ``<slug>[bot]`` (an automation entry, not unattributed).
    """
    if isinstance(value, dict):
        value = value.get("login")
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if value.startswith("app/") and LOGIN_RE.fullmatch(value[4:]):
        return value[4:] + "[bot]"
    if value.endswith("[bot]") and LOGIN_RE.fullmatch(value[:-5]):
        return value
    return value if LOGIN_RE.fullmatch(value) else ""


def _int(value: object) -> Optional[int]:
    return value if type(value) is int and value > 0 else None  # noqa: E721 - no bools


def _list(value: object) -> list:
    """A list field from untrusted JSON; anything else (7, "x", {}) is empty."""
    return value if isinstance(value, list) else []


def _labels(item: dict) -> set:
    out = set()
    for lab in _list(item.get("labels")):
        name = lab.get("name") if isinstance(lab, dict) else lab
        if isinstance(name, str):
            out.add(name.strip().lower())
    return out


def agent_line(body: object) -> str:
    """The single ``Agent: <id>`` named outside code fences and HTML comments,
    or '' when absent or ambiguous."""
    if not isinstance(body, str):
        return ""
    found = set()
    fence = ""
    in_comment = False
    for line in body.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if in_comment:
            if "-->" in line:
                in_comment = False
            continue
        opened = FENCE_RE.match(line)
        if fence:
            if opened and opened.group(1)[0] == fence[0] and len(opened.group(1)) >= len(fence) \
                    and not line.strip()[len(opened.group(1)):].strip():
                fence = ""
            continue
        if "<!--" in line:
            in_comment = "-->" not in line.split("<!--", 1)[1]
            continue  # a line holding (the start of) an HTML comment is never an Agent line
        if opened:
            fence = opened.group(1)
            continue
        match = AGENT_LINE_RE.match(line)
        if match:
            found.add(match.group(1))
    if len(found) != 1:
        return ""
    agent = found.pop()
    return agent if AGENT_ID_RE.fullmatch(agent) else ""


def _parse_ts(value: object) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def _iso(value: object) -> str:
    parsed = _parse_ts(value)
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ") if parsed else ""


# ---------------------------------------------------------------------------
# Factory cards
# ---------------------------------------------------------------------------

def _is_merged(pr: dict) -> bool:
    state = str(pr.get("state") or "").upper()
    return bool(pr.get("mergedAt")) and state in ("", "MERGED")


def _pr_credit(pr: dict, services: set) -> dict:
    """Credit for a merged PR.

    An ``Agent:`` line is honoured only when the PR author is a house-fleet
    service login or an automation account (they open PRs on behalf of
    personas). Anyone else is credited by their own authenticated login: a
    line they wrote, or edited in after the merge, cannot move the credit.
    """
    author = _login(pr.get("author"))
    trusted = bool(author) and (author.lower() in services or is_automation_login(author))
    named = agent_line(pr.get("body")) if trusted else ""
    if named:
        agent, via = named, "agent_line"
    elif author:
        agent, via = author, "pr_author"
    else:
        agent, via = UNATTRIBUTED, "none"
    return {"agent": agent, "via": via, "pr_author": author,
            "pr_author_is_service": author.lower() in services}


def _closing_prs(issue: dict, prs_by_number: Dict[int, dict], repo: str) -> List[dict]:
    """Merged PRs from ``repo`` that closed ``issue``, newest merge first.

    The issue's own ``closedByPullRequestsReferences`` are authoritative when
    present; the PR-side ``closingIssuesReferences`` reverse lookup is only a
    fallback for issues whose references were not fetched.
    """
    prefix = f"https://github.com/{repo}/pull/" if repo else ""
    numbers = set()
    own_refs = _list(issue.get("closedByPullRequestsReferences"))
    for ref in own_refs:
        if not isinstance(ref, dict):
            continue
        number = _int(ref.get("number"))
        url = ref.get("url")
        if number is None or (prefix and isinstance(url, str) and not url.startswith(prefix)):
            continue  # a fork's or another repository's PR is not this repo's fix
        numbers.add(number)
    if not own_refs:
        issue_number = issue.get("number")
        for number, pr in prs_by_number.items():
            for ref in _list(pr.get("closingIssuesReferences")):
                if isinstance(ref, dict) and _int(ref.get("number")) == issue_number:
                    ref_url = ref.get("url")
                    if prefix and isinstance(ref_url, str) and not ref_url.startswith(
                            f"https://github.com/{repo}/issues/"):
                        continue
                    numbers.add(number)
    merged = [prs_by_number[n] for n in numbers if n in prs_by_number and _is_merged(prs_by_number[n])]
    return sorted(merged, key=lambda p: (_iso(p.get("mergedAt")), p["number"]), reverse=True)


def build_cards(issues: Iterable[dict], prs: Iterable[dict], repo: str, services: set) -> dict:
    """Return ``{"shipped": [...], "bounced": [...]}`` from factory issues and PRs.

    A card is an issue with any ``factory:*`` label or a title starting with
    ``[Foreman]`` (the foreman files its cards unlabelled, as
    factory_retro.py assumes). Shipped means closed as completed (not as
    not-planned or duplicate) by a merged PR of this repository.
    """
    prs_by_number: Dict[int, dict] = {}
    for pr in prs:
        if isinstance(pr, dict) and _int(pr.get("number")):
            prs_by_number[pr["number"]] = pr
    shipped, bounced = [], []
    seen = set()
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        number = _int(issue.get("number"))
        labels = _labels(issue)
        title_raw = issue.get("title") if isinstance(issue.get("title"), str) else ""
        is_card = any(l.startswith(FACTORY_PREFIX) for l in labels) or \
            title_raw.lstrip().startswith(FOREMAN_TITLE_PREFIX)
        if number is None or number in seen or not is_card:
            continue
        seen.add(number)
        state = str(issue.get("state") or "").upper()
        reason = str(issue.get("stateReason") or "").upper()
        closers = _closing_prs(issue, prs_by_number, repo)
        credit = _pr_credit(closers[0], services) if closers else None
        title = clean(issue.get("title"))
        if state == "CLOSED" and reason in SHIPPED_REASONS and closers:
            pr = closers[0]
            shipped.append({
                "issue": number,
                "title": title,
                "closed_at": _iso(issue.get("closedAt")),
                "pr": pr["number"],
                "pr_url": f"https://github.com/{repo}/pull/{pr['number']}" if repo else "",
                "merged_at": _iso(pr.get("mergedAt")),
                **credit,
            })
        reopened = issue.get("reopenedCount")
        reopened = reopened if type(reopened) is int and reopened > 0 else 0  # noqa: E721
        if reason == "REOPENED" and not reopened:
            reopened = 1
        if BOUNCED_LABEL in labels or reopened:
            if credit is None:
                assignees = sorted(a for a in (_login(x) for x in _list(issue.get("assignees"))) if a)
                credit = ({"agent": assignees[0], "via": "assignee", "pr_author": "",
                           "pr_author_is_service": False} if assignees else
                          {"agent": UNATTRIBUTED, "via": "none", "pr_author": "",
                           "pr_author_is_service": False})
            bounced.append({
                "issue": number,
                "title": title,
                "reopened": reopened,
                "labelled_bounced": BOUNCED_LABEL in labels,
                "agent": credit["agent"],
                "via": credit["via"],
            })
    shipped.sort(key=lambda c: c["issue"])
    bounced.sort(key=lambda c: c["issue"])
    return {"shipped": shipped, "bounced": bounced}


# ---------------------------------------------------------------------------
# Verification votes
# ---------------------------------------------------------------------------

def _content_owner(author_login: str, body: str, services: set) -> tuple:
    """Return (owner logins for the self-vote rule, credited agent id)."""
    byline = extract_byline(body)
    owners = [o for o in (author_login, byline) if o and LOGIN_RE.fullmatch(o)]
    if author_login.lower() in services:
        agent = byline if byline and AGENT_ID_RE.fullmatch(byline) else author_login
    else:
        agent = author_login or UNATTRIBUTED
    return owners, agent


def _ts_key(value: object) -> str:
    """Sortable UTC instant ('' when absent): orders votes by time, not by text."""
    parsed = _parse_ts(value)
    return parsed.strftime("%Y-%m-%dT%H:%M:%S.%f") if parsed else ""


def _incomplete(disc: dict) -> bool:
    """The cached snapshot is missing comments or reply bodies, or is stale.

    The freshness rule is hydrate_public_comments.needs_hydration's: a
    discussion with comments counts as complete only when comments_complete
    is true, the top-level count matches comment_count and the comments were
    hydrated at the discussion's current updated_at. A newer fail vote that
    is not in the cache must not leave a subject passing.
    """
    if disc.get("comments_complete") is False or disc.get("reply_bodies_complete") is False:
        return True
    total = _int(disc.get("comment_count")) or 0
    if total <= 0:
        return False
    return not (disc.get("comments_complete") is True
                and _int(disc.get("top_level_comment_count")) == total
                and bool(disc.get("updated_at"))
                and disc.get("comments_hydrated_updated_at") == disc.get("updated_at")
                and isinstance(disc.get("comments"), list))


def _platform_target(disc_number: int, reply: dict, rec: dict, by_id: Dict[str, dict],
                     services: set) -> Optional[tuple]:
    """``(subject, target)`` for an answer-qa platform reply, or None.

    The rule in docs/VERIFICATIONS.md ("Platform identity"): the author is
    exactly the workflow account, the first line is the marker, the comment
    it names is in this discussion, and re-extracting that comment gives a
    content id equal to the marker's code id and to the vote's subject.
    """
    if not answer_qa.is_platform_login(_login(reply.get("author_login") or reply.get("author"))):
        return None
    named = answer_qa.platform_vote(reply.get("body"))
    if named is None:
        return None
    comment_id, code_cid = named
    answer = by_id.get(comment_id)
    if answer is None or not isinstance(answer.get("body"), str):
        return None
    parsed = answer_qa.extract(answer["body"])
    if not parsed.get("runnable") or parsed["content_id"] != code_cid or rec.get("subject") != code_cid:
        return None
    # The vote is for the runtime it ran in: an answer whose environment line
    # changed since (python-3.11 -> node-20) no longer carries that result.
    if str(rec.get("environment") or "").split("/", 1)[0] != parsed["runtime"]:
        return None
    owners, agent = _content_owner(_login(answer.get("author_login") or answer.get("author")),
                                   answer["body"], services)
    return code_cid, {"discussion": disc_number, "target": "comment", "comment_id": clean(comment_id, 64),
                      "owners": owners, "agent": agent,
                      "order": (_ts_key(answer.get("created_at")), 1, str(comment_id))}


def build_verifications(discussions: Iterable[dict], services: set) -> dict:
    """Score every voted subject across all discussions; return rows and counters.

    One global ledger: one live vote per verifier per subject, wherever the
    vote was cast (the same body posted in twenty threads is one subject,
    not twenty). A vote still binds only to content in its own discussion.
    Votes are applied in (time, fail-after-pass, comment id) order, so the
    result does not depend on input order and a pass and a fail by one
    login at the same instant resolve to the fail. When identical content
    has several owners, every owner is barred from voting on it and the
    credit goes to the earliest copy (time, then id).
    """
    counters = {"votes_counted": 0, "platform_votes_counted": 0, "dropped_unbound": 0,
                "dropped_service_login": 0, "dropped_automation": 0, "dropped_invalid": 0,
                "incomplete_discussions": 0}
    targets: Dict[str, List[dict]] = {}
    pending: List[tuple] = []
    meta: Dict[int, dict] = {}
    incomplete: set = set()
    by_number: Dict[int, dict] = {}
    for disc in discussions:
        if not isinstance(disc, dict):
            continue
        number = _int(disc.get("number"))
        if number is None or not isinstance(disc.get("body"), str):
            continue
        previous = by_number.get(number)
        # Duplicate numbers: keep one deterministically (latest updated, then body).
        if previous is None or (str(disc.get("updated_at") or ""), disc["body"]) > \
                (str(previous.get("updated_at") or ""), previous["body"]):
            by_number[number] = disc
    for number in sorted(by_number):
        disc = by_number[number]
        url = disc.get("url")
        meta[number] = {"title": clean(disc.get("title")),
                        "url": clean(url, 200) if isinstance(url, str) and url.startswith("https://github.com/") else ""}
        if _incomplete(disc):
            incomplete.add(number)
            counters["incomplete_discussions"] += 1
        comments = sorted((c for c in _list(disc.get("comments")) if isinstance(c, dict)),
                          key=lambda c: (_ts_key(c.get("created_at")), str(c.get("id") or "")))
        by_id = {str(c.get("id")): c for c in comments if isinstance(c.get("id"), str) and c.get("id")}
        post_author = _login(disc.get("author_login") or disc.get("author"))
        owners, agent = _content_owner(post_author, disc["body"], services)
        targets.setdefault(verifications.content_id(disc["body"]), []).append({
            "discussion": number, "target": "post", "comment_id": "", "owners": owners, "agent": agent,
            "order": (_ts_key(disc.get("created_at")), 0, "")})
        local: set = {verifications.content_id(disc["body"])}
        for c in comments:
            body = c.get("body")
            if not isinstance(body, str) or not body.strip():
                continue
            rec = verifications.parse_comment(body)
            if rec is not None:
                pending.append((c, rec, number, by_id))
                continue  # a vote is not itself a subject
            cid = verifications.content_id(body)
            c_owners, c_agent = _content_owner(_login(c.get("author_login") or c.get("author")), body, services)
            local.add(cid)
            targets.setdefault(cid, []).append({
                "discussion": number, "target": "comment", "comment_id": clean(c.get("id"), 64),
                "owners": c_owners, "agent": c_agent,
                "order": (_ts_key(c.get("created_at")), 1, str(c.get("id") or ""))})
        meta[number]["subjects"] = local

    # Bind every vote first, so each subject's owner set is complete before
    # any vote is checked against it.
    bound: List[tuple] = []
    for c, rec, number, by_id in pending:
        login = _login(c.get("author_login") or c.get("author"))
        platform = _platform_target(number, c, rec, by_id, services)
        if platform is not None:
            subject, target = platform
            targets.setdefault(subject, []).append(target)
            bound.append((c, rec, number, answer_qa.PLATFORM_VERIFIER, True))
            continue
        if rec["subject"] not in meta[number]["subjects"]:
            counters["dropped_unbound"] += 1
            continue
        if not login or is_automation_login(login) \
                or login.strip().lower() == answer_qa.PLATFORM_VERIFIER.lower():
            # The platform's key is reserved: a human login spelled like it
            # must not vote as the sandbox.
            counters["dropped_automation"] += 1
            continue
        if login.lower() in services:
            counters["dropped_service_login"] += 1
            continue
        bound.append((c, rec, number, login, False))

    store = verifications.load(None)
    vote_discussions: Dict[str, set] = {}
    bound.sort(key=lambda b: (_ts_key(b[0].get("created_at")), 1 if not b[1]["passed"] else 0,
                              str(b[0].get("id") or ""), b[3].lower()))
    for c, rec, number, verifier, is_platform in bound:
        created = c.get("created_at")
        if not isinstance(created, str) or not created:
            counters["dropped_invalid"] += 1  # never let record() stamp "now": output stays deterministic
            continue
        owners = sorted({o for t in targets.get(rec["subject"], []) for o in t["owners"]})
        try:
            verifications.record(store, dict(rec, verifier=verifier, at=created),
                                 subject_owner=owners or None, revalidate=False)
        except ValueError:
            counters["dropped_invalid"] += 1
            continue
        vote_discussions.setdefault(rec["subject"], set()).add(number)
        counters["platform_votes_counted" if is_platform else "votes_counted"] += 1

    rows = []
    for subject in sorted(store["subjects"]):
        votes = store["subjects"][subject]
        result = verifications.score(store, subject, revalidate=False)
        target = min(targets[subject], key=lambda t: t["order"])
        platform_vote = votes.get(answer_qa.PLATFORM_VERIFIER)
        human_passes = sum(1 for key, v in votes.items() if v["passed"] and key != answer_qa.PLATFORM_VERIFIER)
        pass_times = sorted(v["at"] for v in votes.values() if v["passed"])
        touched = {t["discussion"] for t in targets[subject]} | vote_discussions.get(subject, set())
        is_incomplete = bool(touched & incomplete)
        rows.append({
            "discussion": target["discussion"],
            "title": meta[target["discussion"]]["title"],
            "url": meta[target["discussion"]]["url"],
            "subject": subject,
            "target": target["target"],
            "comment_id": target["comment_id"],
            "agent": target["agent"],
            "pass_count": result["pass_count"],
            "fail_count": result["fail_count"],
            "votes": result["votes"],
            "verifiers": sorted(votes),
            "platform": "" if platform_vote is None else ("pass" if platform_vote["passed"] else "fail"),
            "score": result["score"],
            "hidden": result["hidden"],
            "incomplete": is_incomplete,
            "passing": is_passing(result, human_passes=human_passes)
            and not is_incomplete,
            "last_pass_at": pass_times[-1] if pass_times else "",
        })
    rows.sort(key=lambda r: (r["discussion"], r["target"] != "post", r["subject"]))
    ledger = {subject: {key: bool(v["passed"]) for key, v in votes.items()}
              for subject, votes in store["subjects"].items()}
    return {"rows": rows, "counters": counters, "ledger": ledger}


def is_passing(result: dict, *, human_passes: Optional[int] = None) -> bool:
    """A subject passes when passes outnumber fails, it is not hidden, and at
    least MIN_HUMAN_PASSES distinct human verifiers voted pass. Human
    verifiers never include the content's owner (record() refuses
    self-votes). A platform (rappterbook-sandbox) pass only says the author's
    own code exited 0 -- `true` passes -- so it never ranks or lists a
    subject; neither does one account vouching alone."""
    if result.get("hidden") or result.get("pass_count", 0) <= result.get("fail_count", 0):
        return False
    humans = result.get("pass_count", 0) if human_passes is None else human_passes
    return humans >= MIN_HUMAN_PASSES


def wilson(passes: int, n: int) -> float:
    """95% Wilson lower bound, the same formula and z as verifications.score."""
    if n <= 0:
        return 0.0
    z = verifications.Z_95
    p = passes / n
    z2 = z * z
    value = (p + z2 / (2.0 * n) - z * math.sqrt((p * (1.0 - p) + z2 / (4.0 * n)) / n)) / (1.0 + z2 / n)
    return round(max(0.0, min(1.0, value)), 6)


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def build_reputation(issues: Iterable[dict], prs: Iterable[dict], discussions: Iterable[dict],
                     repo: str = DEFAULT_REPO, services: Optional[set] = None,
                     coverage: Optional[dict] = None) -> dict:
    """Pure function: inputs in, the ``rappterbook-reputation/1`` document out.

    ``coverage`` carries the live fetch's completeness counters
    (``closers_not_fetched``, ``pr_list_truncated``, ...) into ``totals``.
    """
    services = {s.lower() for s in (service_logins() if services is None else services)}
    cards = build_cards(list(issues), list(prs), repo, services)
    verified = build_verifications(list(discussions), services)
    agents: Dict[str, dict] = {}
    # agent -> verifier -> [passes, fails]: each verifier counts once per agent
    by_verifier: Dict[str, Dict[str, List[int]]] = {}

    def entry(agent: str) -> dict:
        if agent not in agents:
            agents[agent] = {"cards_shipped": 0, "cards": [], "qa_bounces": 0, "bounced_cards": [],
                             "verification": {"pass": 0, "fail": 0, "votes": 0, "score": 0.0,
                                              "verifiers": 0, "verifiers_pass": 0,
                                              "subjects": 0, "passing_subjects": 0},
                             "service_login": agent.lower() in services}
        return agents[agent]

    for card in cards["shipped"]:
        row = entry(card["agent"])
        row["cards_shipped"] += 1
        row["cards"].append(card["issue"])
    for card in cards["bounced"]:
        row = entry(card["agent"])
        row["qa_bounces"] += 1
        row["bounced_cards"].append(card["issue"])
    for subject in verified["rows"]:
        stats = entry(subject["agent"])["verification"]
        stats["pass"] += subject["pass_count"]
        stats["fail"] += subject["fail_count"]
        stats["votes"] += subject["votes"]
        stats["subjects"] += 1
        stats["passing_subjects"] += 1 if subject["passing"] else 0
        tally = by_verifier.setdefault(subject["agent"], {})
        for verifier, passed in verified["ledger"].get(subject["subject"], {}).items():
            counts = tally.setdefault(verifier, [0, 0])
            counts[0 if passed else 1] += 1
    for agent, row in agents.items():
        stats = row["verification"]
        # One account voting pass on ten of an agent's comments is one voice,
        # not ten: the score is over distinct verifiers, each passing when
        # their passes outnumber their fails for this agent.
        tally = by_verifier.get(agent, {})
        stats["verifiers"] = len(tally)
        stats["verifiers_pass"] = sum(1 for p, f in tally.values() if p > f)
        stats["score"] = wilson(stats["verifiers_pass"], stats["verifiers"])
        row["cards"].sort()
        row["bounced_cards"].sort()
    ordered = sorted(services)
    return {
        "schema": SCHEMA,
        "note": NOTE.format(logins=", ".join(ordered)),
        "service_logins": ordered,
        "definitions": {
            "cards_shipped": "closed-as-completed issues labelled factory:* or titled [Foreman] whose "
                             "closing PR in this repository merged; an 'Agent:' line moves the credit only "
                             "when a service or automation login opened the PR",
            "verification": "rapp-verification/1 votes from Discussion comments bound to content in the "
                            "same discussion, one live vote per verifier per subject across all "
                            "discussions; automation and service logins and self-votes excluded, except "
                            "answer-qa platform replies, counted as rappterbook-sandbox; an agent's score "
                            "is the 95% Wilson lower bound over distinct verifiers",
            "passing": "pass votes outnumber fail votes, the subject is not hidden, its snapshot is "
                       f"complete and fresh, and at least {MIN_HUMAN_PASSES} distinct human verifiers "
                       "other than its owner voted pass; a platform (rappterbook-sandbox) pass is "
                       "reported but never counts toward passing",
            "qa_bounces": "factory issues reopened or labelled factory:bounced",
        },
        "totals": {
            "agents": len(agents),
            "cards_shipped": len(cards["shipped"]),
            "qa_bounces": len(cards["bounced"]),
            "verified_subjects": len(verified["rows"]),
            "passing_subjects": sum(1 for r in verified["rows"] if r["passing"]),
            "incomplete_subjects": sum(1 for r in verified["rows"] if r["incomplete"]),
            **verified["counters"],
            **{k: v for k, v in sorted((coverage or {}).items())},
        },
        "agents": {k: agents[k] for k in sorted(agents)},
        "shipped_cards": cards["shipped"],
        "bounced_cards": cards["bounced"],
        "verified": verified["rows"],
    }


def dumps(doc: dict) -> str:
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Readers used by weekly_newsletter.py and compute_trending.py (behind flags)
# ---------------------------------------------------------------------------

def load_reputation(path: Optional[object] = None) -> dict:
    """Load a reputation document; ``{}`` when missing, unreadable or another schema.

    Only the flagged readers call this, so a missing or unusable file is
    reported on stderr: a flag that is on but has no data must not fail
    silently.
    """
    target = Path(path) if path else Path(os.environ.get("REPUTATION_JSON") or DEFAULT_OUT)
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"warning: reputation data unavailable ({target}: {exc.__class__.__name__}); "
              "run scripts/compute_reputation.py", file=sys.stderr)
        return {}
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        print(f"warning: {target} is not a {SCHEMA} document; ignoring it", file=sys.stderr)
        return {}
    return data


def passing_discussions(doc: dict, start: Optional[datetime] = None,
                        end: Optional[datetime] = None, *, posts_only: bool = False) -> Dict[int, dict]:
    """Discussion number -> best passing verified row (post body or an answer).

    With ``start``/``end``, rows whose last pass is outside the window are
    dropped *before* the best row per discussion is chosen, so a recent pass
    on a lower-scoring subject is not hidden by an older, higher one. With
    ``posts_only`` (the trending boost), only the discussion's own body
    counts: a passing answer says nothing about the question it answers.
    """
    out: Dict[int, dict] = {}
    for row in _list(doc.get("verified")):
        if not isinstance(row, dict) or row.get("passing") is not True or row.get("hidden"):
            continue
        if posts_only and row.get("target") != "post":
            continue
        number = _int(row.get("discussion"))
        if number is None:
            continue
        if start is not None or end is not None:
            when = _parse_ts(row.get("last_pass_at"))
            if when is None or (start is not None and when < start) or (end is not None and when > end):
                continue
        best = out.get(number)
        key = (row.get("score") or 0, str(row.get("last_pass_at") or ""), str(row.get("subject") or ""))
        if best is None or key > (best.get("score") or 0, str(best.get("last_pass_at") or ""),
                                  str(best.get("subject") or "")):
            out[number] = row
    return out


def verified_in_window(doc: dict, start: datetime, end: datetime) -> dict:
    """Passing discussions with a pass vote in [start, end] and cards shipped in it."""
    discussions = [row for _number, row in sorted(passing_discussions(doc, start, end).items())]
    cards = []
    for card in _list(doc.get("shipped_cards")):
        if not isinstance(card, dict):
            continue
        when = _parse_ts(card.get("closed_at"))
        if when is not None and start <= when <= end:
            cards.append(card)
    cards.sort(key=lambda c: (str(c.get("closed_at") or ""), c.get("issue") or 0))
    return {"discussions": discussions, "cards": cards}


# ---------------------------------------------------------------------------
# Live inputs (read-only)
# ---------------------------------------------------------------------------

def default_runner(args: List[str]) -> str:
    try:
        proc = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    except OSError as exc:
        raise ReputationError(f"gh could not be run: {exc.__class__.__name__}") from exc
    if proc.returncode != 0:
        raise ReputationError(f"gh {' '.join(args[:2])} failed: {clean(proc.stderr, 300)}")
    return proc.stdout


def _gh_json(runner: Runner, args: List[str]) -> object:
    try:
        return json.loads(runner(args))
    except ValueError as exc:
        raise ReputationError(f"gh {args[0]} {args[1]} returned invalid JSON") from exc


def fetch_live(runner: Runner, repo: str, limit: int, timeline: bool = True,
               coverage: Optional[dict] = None) -> tuple:
    """Factory issues and merged PRs via gh. Only argument lists, never a shell.

    ``coverage`` (when given) receives completeness counters so a partial
    read is visible in the output: ``pr_list_truncated`` (the merged-PR list
    hit ``limit``), ``issue_list_truncated`` and ``closers_not_fetched``
    (closing PRs beyond ``MAX_PR_LOOKUPS`` that were never read).
    """
    coverage = coverage if coverage is not None else {}
    coverage.update(pr_list_truncated=False, issue_list_truncated=False, closers_not_fetched=0)
    labels = _gh_json(runner, ["label", "list", "--repo", repo, "--search", FACTORY_PREFIX,
                               "--limit", "100", "--json", "name"])
    names = sorted({lab["name"] for lab in labels or [] if isinstance(lab, dict)
                    and isinstance(lab.get("name"), str) and lab["name"].lower().startswith(FACTORY_PREFIX)})
    issues: Dict[int, dict] = {}
    for name in names:
        data = _gh_json(runner, ["issue", "list", "--repo", repo, "--state", "all", "--label", name,
                                 "--limit", str(limit), "--json", ISSUE_FIELDS])
        if not isinstance(data, list):
            raise ReputationError("gh issue list did not return a list")
        coverage["issue_list_truncated"] = coverage["issue_list_truncated"] or len(data) >= limit
        for item in data:
            if isinstance(item, dict) and _int(item.get("number")):
                issues[item["number"]] = item
    # The foreman files its cards unlabelled: find them by title.
    data = _gh_json(runner, ["issue", "list", "--repo", repo, "--state", "all", "--search",
                             f'in:title "{FOREMAN_TITLE_PREFIX}"', "--limit", str(limit),
                             "--json", ISSUE_FIELDS])
    if not isinstance(data, list):
        raise ReputationError("gh issue list did not return a list")
    coverage["issue_list_truncated"] = coverage["issue_list_truncated"] or len(data) >= limit
    for item in data:
        if isinstance(item, dict) and _int(item.get("number")) and isinstance(item.get("title"), str) \
                and item["title"].lstrip().startswith(FOREMAN_TITLE_PREFIX):
            issues.setdefault(item["number"], item)
    data = _gh_json(runner, ["pr", "list", "--repo", repo, "--state", "merged", "--limit", str(limit),
                             "--json", PR_FIELDS])
    if not isinstance(data, list):
        raise ReputationError("gh pr list did not return a list")
    coverage["pr_list_truncated"] = len(data) >= limit
    prs = {p["number"]: p for p in data if isinstance(p, dict) and _int(p.get("number"))}
    missing = sorted({_int(ref.get("number")) for issue in issues.values()
                      for ref in _list(issue.get("closedByPullRequestsReferences"))
                      if isinstance(ref, dict) and _int(ref.get("number"))} - set(prs))
    coverage["closers_not_fetched"] = max(0, len(missing) - MAX_PR_LOOKUPS)
    for number in missing[:MAX_PR_LOOKUPS]:
        pr = _gh_json(runner, ["pr", "view", str(number), "--repo", repo, "--json", PR_FIELDS])
        if isinstance(pr, dict) and _int(pr.get("number")):
            prs[pr["number"]] = pr
    if timeline and issues:
        owner, _, name = repo.partition("/")
        numbers = sorted(issues)
        for start in range(0, len(numbers), TIMELINE_CHUNK):
            chunk = numbers[start:start + TIMELINE_CHUNK]
            fields = " ".join(
                f"i{n}: issue(number: {n}) {{ timelineItems(itemTypes: [REOPENED_EVENT]) {{ totalCount }} }}"
                for n in chunk)  # numbers are validated ints, never text
            query = ("query($owner: String!, $name: String!) { repository(owner: $owner, name: $name) { "
                     + fields + " } }")
            data = _gh_json(runner, ["api", "graphql", "-f", f"query={query}",
                                     "-f", f"owner={owner}", "-f", f"name={name}"])
            repo_data = ((data or {}).get("data") or {}).get("repository") or {} if isinstance(data, dict) else {}
            for n in chunk:
                node = repo_data.get(f"i{n}") or {}
                count = ((node.get("timelineItems") or {}).get("totalCount")) if isinstance(node, dict) else None
                if type(count) is int and count > 0:  # noqa: E721
                    issues[n]["reopenedCount"] = count
    return [issues[n] for n in sorted(issues)], [prs[n] for n in sorted(prs)]


def load_local_discussions(state_dir: Path) -> List[dict]:
    """Discussions with bodies and comments from the local cache (no network)."""
    from cache_shard_loader import load_authoritative_discussions
    discussions, _meta = load_authoritative_discussions(state_dir, include_body=True)
    return discussions


def load_fixture(path: Path) -> tuple:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReputationError(f"cannot read --input {str(path)!r}: {exc}") from exc
    if not isinstance(data, dict):
        raise ReputationError("--input must be a JSON object with issues, pull_requests, discussions")
    parts = []
    for key in ("issues", "pull_requests", "discussions"):
        value = data.get(key, [])
        if not isinstance(value, list):
            raise ReputationError(f"--input {key} must be a list")
        parts.append(value)
    return tuple(parts)


def main(argv: Optional[List[str]] = None, runner: Optional[Runner] = None) -> int:
    parser = argparse.ArgumentParser(description="Build docs/reputation.json from verified work.")
    parser.add_argument("--input", type=Path, help="JSON fixture {issues, pull_requests, discussions}")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY") or DEFAULT_REPO)
    parser.add_argument("--state-dir", type=Path, default=Path(os.environ.get("STATE_DIR") or ROOT / "state"))
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--no-timeline", action="store_true", help="skip the reopen-count GraphQL read")
    parser.add_argument("--stdout", action="store_true", help="print instead of writing --out")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repo or ""):
        print("error: --repo must be owner/name", file=sys.stderr)
        return 1
    coverage: dict = {}
    try:
        if args.input:
            issues, prs, discussions = load_fixture(args.input)
            coverage = {}
        else:
            issues, prs = fetch_live(runner or default_runner, args.repo, max(1, args.limit),
                                     timeline=not args.no_timeline, coverage=coverage)
            discussions = load_local_discussions(args.state_dir)
        text = dumps(build_reputation(issues, prs, discussions, repo=args.repo, coverage=coverage))
    except ReputationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except (TypeError, ValueError, AttributeError, KeyError) as exc:
        print(f"error: malformed input ({exc.__class__.__name__})", file=sys.stderr)
        return 1
    if args.stdout:
        sys.stdout.write(text)
        return 0
    write_atomic(args.out, text)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
