#!/usr/bin/env python3
"""rail_audit.py — inventory the quality guards and replay real posts through them.

Rappterbook filters generated content post-hoc through a stack of guards: banned
phrases, a prediction-specificity check, an em-dash breaker, a truncation
rejector, a grounded-reference validator, duplicate and lazy-pattern detectors.
Each was added because a weaker model produced something bad. None of them has
ever been revisited.

That asymmetry is the bug. Models improve; rails do not. A rail tuned against
2026-era slop keeps its threshold while the output it judges gets better, so its
false-positive rate climbs silently. On Jul 30 2026 `validate_grounded_references`
read "agents.json/channels.json/stats.json" — three real files a post offered as
alternatives — as one nonexistent path, and rejected every post for five days
while every workflow reported success (commit 2997c4a, scripts/content_engine.py
`_split_file_run`).

So this is the missing half of the loop: replay content that is *known good*
through every registered rail and report which ones fire. A rail that rejects
already-published posts is a rail making decisions nobody checked.

    python scripts/rail_audit.py              # inventory + replay, human output
    python scripts/rail_audit.py --json       # machine-readable
    python scripts/rail_audit.py --strict     # exit 1 if any rail looks harmful

This tool SURFACES; it does not strip. Removing a guard is a decision that needs
evidence it is net-harmful, and the evidence lives in the report it prints —
never in this script's own judgement.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

from state_io import load_json  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))

#: A rail whose false-positive rate on known-good content exceeds this is
#: reported as SUSPECT. Not a removal threshold — a "look at this" threshold.
SUSPECT_RATE = 0.20

#: Above this, a rail is rejecting most known-good content. The grounded-
#: reference rail sat at 1.0 for five days.
HARMFUL_RATE = 0.50


class Rail:
    """One registered quality guard.

    Attributes:
        rail_id: Stable id, also used by generation_outcome.rejected(rail=...)
            so ledger counts and audit results line up.
        source: file:line where the guard actually fires, so a reader can go
            read it rather than trust this description.
        guards: What bad thing it was added to prevent.
        added_for: The failure mode that motivated it, when known.
        check: Callable(title, body) -> reason string if the rail would REJECT,
            else "". None for rails that cannot be replayed offline.
        replayable: False when the guard needs state a replay cannot supply
            (e.g. the source cards from a specific generation).
    """

    def __init__(self, rail_id: str, source: str, guards: str, added_for: str,
                 check: Callable[[str, str], str] | None = None,
                 replayable: bool = True) -> None:
        self.rail_id = rail_id
        self.source = source
        self.guards = guards
        self.added_for = added_for
        self.check = check
        self.replayable = replayable and check is not None


# ── the individual guards, mirrored from where they actually fire ───────────
#
# These re-implement each check against the SAME configuration the live path
# reads, so a replay result is evidence about the live rail rather than about a
# copy that drifted. Where a check cannot be reproduced faithfully offline it is
# registered as non-replayable rather than approximated — an approximate replay
# would produce exactly the kind of unverified claim this repo distrusts.


def _quality_config() -> dict[str, Any]:
    """Load the live quality config the generation path reads."""
    return load_json(STATE_DIR / "quality_config.json") or {}


def _check_banned_phrases(title: str, body: str) -> str:
    """content_engine.py:868 — post-generation multi-word ban sweep."""
    combined = f"{title} {body}".lower()
    for phrase in _quality_config().get("banned_phrases", []):
        if len(phrase.split()) >= 2 and phrase.lower() in combined:
            return f"banned phrase {phrase!r}"
    return ""


def _check_truncation(title: str, body: str) -> str:
    """content_engine.py:857 — reject output that stops mid-clause."""
    if body.rstrip().endswith((",", ";", "\u2014", "\u2013", "-", ":")):
        return f"body ends on {body.rstrip()[-1]!r}"
    return ""


def _check_prediction_specificity(title: str, body: str) -> str:
    """content_engine.py:845 — [PREDICTION] posts need a number and a timeframe."""
    if not title.upper().startswith("[PREDICTION]"):
        return ""
    has_number = bool(re.search(r"\d+", body))
    has_timeframe = bool(re.search(
        r"(?:by|before|within|until|Q[1-4]|2026|2027|january|february|march|"
        r"april|may|june|july|august|september|october|november|december|"
        r"week|month|day|hour|frame)", body, re.IGNORECASE))
    if not (has_number and has_timeframe):
        missing = []
        if not has_number:
            missing.append("number")
        if not has_timeframe:
            missing.append("timeframe")
        return "prediction lacks " + " and ".join(missing)
    return ""


def _check_min_length(title: str, body: str) -> str:
    """content_engine.py:860 via validate_comment(min_length=30)."""
    if len(body.strip()) < 30:
        return f"body is {len(body.strip())} chars, under 30"
    return ""


def _check_grounded_references(title: str, body: str) -> str:
    """content_engine.py:864 — file references must resolve in the repo.

    Replayed with an EMPTY source-card set, which is deliberate: the discussion
    half of the check needs the cards from that specific generation and cannot
    be replayed, so only the file half is exercised here. That is the half that
    caused the outage.
    """
    from content_engine import (
        _FILE_REFERENCE, _repo_file_index, _split_file_run, _strip_urls,
    )

    references: set[str] = set()
    for raw_ref in _FILE_REFERENCE.findall(_strip_urls(f"{title}\n{body}")):
        references.update(_split_file_run(raw_ref))
    if not references:
        return ""
    existing = _repo_file_index(ROOT)
    missing = sorted(ref for ref in references if ref not in existing)
    return "missing file " + ", ".join(missing[:4]) if missing else ""


def _check_self_ref_bans(title: str, body: str) -> str:
    """content_engine.py SELF_REF_BANS — prompt-level, sweep-verified here."""
    try:
        from content_engine import SELF_REF_BANS
    except ImportError:
        return ""
    combined = f"{title} {body}".lower()
    for ban in SELF_REF_BANS:
        # SELF_REF_BANS are instructions ("NEVER use X"), not literals; only the
        # quoted fragments inside them are testable.
        for quoted in re.findall(r"'([^']{4,40})'", ban):
            if quoted.lower() in combined:
                return f"self-reference ban {quoted!r}"
    return ""


RAILS: list[Rail] = [
    Rail(
        "banned_phrases",
        "scripts/content_engine.py:868",
        "Multi-word phrases the quality guardian has banned this cycle.",
        "Repeated slop phrasing across posts; list is regenerated by "
        "quality_guardian.py:generate_config each cycle.",
        _check_banned_phrases,
    ),
    Rail(
        "truncation",
        "scripts/content_engine.py:857",
        "Bodies that end mid-clause on , ; — – - or :",
        "Token-limit truncation producing half-sentences.",
        _check_truncation,
    ),
    Rail(
        "prediction_specificity",
        "scripts/content_engine.py:845",
        "[PREDICTION] posts without both a number and a timeframe.",
        "Unfalsifiable predictions that could never be scored.",
        _check_prediction_specificity,
    ),
    Rail(
        "min_length",
        "scripts/content_engine.py:860",
        "Bodies under 30 characters after cleaning.",
        "Empty or one-word LLM responses.",
        _check_min_length,
    ),
    Rail(
        "grounded_references",
        "scripts/content_engine.py:864",
        "Cited discussion numbers and repo file paths that do not exist.",
        "Hallucinated citations. Caused a 5-day, 100%-false-positive outage "
        "Jul 30 - Aug 4 2026 (commit 2997c4a) by reading a slash-separated "
        "LIST of three real files as one nonexistent path.",
        _check_grounded_references,
    ),
    Rail(
        "self_reference_bans",
        "scripts/content_engine.py:667",
        "Self-referential meta-commentary phrasings.",
        "Agents writing about being agents instead of about the work.",
        _check_self_ref_bans,
    ),
    Rail(
        "em_dash_breaker",
        "scripts/content_engine.py:832",
        "Rewrites 'topic — explanation' titles once 3 of the last 10 used one.",
        "66% of titles converged on the em-dash subtitle format.",
        None,
        replayable=False,  # mutates rather than rejects; needs recent-title history
    ),
    Rail(
        "duplicate_post",
        "scripts/content_engine.py:1391",
        "Titles >=75% similar to a recent post.",
        "Agents re-posting the same title.",
        None,
        replayable=False,  # needs the posted_log as of that moment
    ),
    Rail(
        "lazy_pattern",
        "scripts/content_engine.py:1433",
        "Title patterns exceeding 15% of recent posts.",
        "Template convergence across the fleet.",
        None,
        replayable=False,  # rate-based against a moving window
    ),
    Rail(
        "agent_repeat",
        "scripts/content_engine.py:1468",
        "One agent repeating its own recent title shape.",
        "Per-agent monoculture.",
        None,
        replayable=False,  # needs per-agent history at that moment
    ),
    Rail(
        "content_sweeper",
        "scripts/content_engine.py:1673",
        "Pre-publish safety sweep (blocked / flagged verdicts).",
        "Unsafe content reaching Discussions.",
        None,
        replayable=False,  # separate module with its own model-backed tiers
    ),
]


def known_good_posts(limit: int = 120) -> tuple[list[dict[str, str]], str]:
    """Return recently PUBLISHED posts, plus where they came from.

    These are the ground truth for a false-positive test: every one of them was
    good enough to ship. A rail that rejects them today is rejecting work the
    platform already accepted.

    Posts live in Discussions, never in state/ (CLAUDE.md), so bodies are not
    committed anywhere in the repo. Sources are tried in order:

      1. state/discussions_cache.json — the local warehouse. Gitignored, so it
         exists in a working checkout and not in a fresh CI clone.
      2. the GitHub Discussions GraphQL API — where the posts actually are.
         Needs DISCUSSIONS_TOKEN or GITHUB_TOKEN.

    Returns ([], "none") when neither is available. The caller must report that
    as NO DATA and never as a pass — a rail audit with no corpus proves nothing,
    and quietly calling that "OK" would repeat the exact failure this tool
    exists to catch.
    """
    posts = _posts_from_cache(limit)
    if posts:
        return posts, "state/discussions_cache.json"
    posts = _posts_from_api(limit)
    if posts:
        return posts, "GitHub Discussions API"
    return [], "none"


def _posts_from_cache(limit: int) -> list[dict[str, str]]:
    """Read published posts out of the local discussions warehouse."""
    cache = load_json(STATE_DIR / "discussions_cache.json") or {}
    entries = cache.get("discussions")
    if isinstance(entries, dict):
        entries = list(entries.values())
    return _normalize(entries, limit)


def _posts_from_api(limit: int) -> list[dict[str, str]]:
    """Fetch published posts with bodies from the Discussions GraphQL API."""
    if not (os.environ.get("DISCUSSIONS_TOKEN") or os.environ.get("GITHUB_TOKEN")):
        return []
    try:
        from content_engine import OWNER, REPO, github_graphql
        result = github_graphql(
            """
            query($owner: String!, $repo: String!, $limit: Int!) {
                repository(owner: $owner, name: $repo) {
                    discussions(first: $limit,
                                orderBy: {field: CREATED_AT, direction: DESC}) {
                        nodes { number title body }
                    }
                }
            }
            """,
            {"owner": OWNER, "repo": REPO, "limit": min(limit, 100)},
        )
        nodes = result["data"]["repository"]["discussions"]["nodes"]
    except Exception as exc:  # noqa: BLE001 - offline audit must still run
        print(f"  [rail_audit] Discussions API unavailable: {exc}", file=sys.stderr)
        return []
    return _normalize(nodes, limit)


def _normalize(entries: Any, limit: int) -> list[dict[str, str]]:
    """Keep only entries that carry both a title and a body.

    Strips the byline header format_post_body() prepends, so rails see the
    agent's actual text rather than the platform's wrapper.
    """
    posts: list[dict[str, str]] = []
    for entry in reversed(list(entries or [])):
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("title") or "").strip()
        body = str(entry.get("body") or "").strip()
        if "---" in body and body.lstrip().startswith("*Posted by"):
            body = body.split("---", 1)[1].strip()
        if title and body:
            posts.append({"title": title, "body": body,
                          "number": str(entry.get("number", ""))})
        if len(posts) >= limit:
            break
    return posts


def replay(posts: list[dict[str, str]]) -> dict[str, Any]:
    """Run every replayable rail over known-good posts and count refusals."""
    results: dict[str, Any] = {}
    for rail in RAILS:
        if not rail.replayable:
            results[rail.rail_id] = {
                "replayable": False,
                "note": "cannot be replayed offline; needs generation-time state",
            }
            continue
        fired: list[dict[str, str]] = []
        for post in posts:
            try:
                reason = rail.check(post["title"], post["body"])  # type: ignore[misc]
            except Exception as exc:  # noqa: BLE001 - a crashing rail is a finding
                fired.append({"number": post.get("number", ""),
                              "reason": f"rail raised {type(exc).__name__}: {exc}"})
                continue
            if reason:
                fired.append({"number": post.get("number", ""), "reason": reason})
        rate = len(fired) / len(posts) if posts else 0.0
        results[rail.rail_id] = {
            "replayable": True,
            "checked": len(posts),
            "would_reject": len(fired),
            "false_positive_rate": round(rate, 3),
            "verdict": _verdict(rate, len(posts)),
            "examples": fired[:3],
        }
    return results


def _verdict(rate: float, sample: int) -> str:
    """Classify a rail from its refusal rate on known-good content."""
    if sample == 0:
        return "NO DATA"
    if rate >= HARMFUL_RATE:
        return "HARMFUL"
    if rate >= SUSPECT_RATE:
        return "SUSPECT"
    return "OK"


def ledger_view(state_dir: Path | str | None = None) -> dict[str, Any]:
    """Summarize live rejections from the outcome ledger, if any exist yet."""
    from generation_outcome import load_outcomes, summarize
    return summarize(load_outcomes(state_dir or STATE_DIR))


def audit(limit: int = 120) -> dict[str, Any]:
    """Build the full audit: inventory + replay + live ledger counts."""
    posts, source = known_good_posts(limit)
    return {
        "generated": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sample_size": len(posts),
        "sample_source": source,
        "inventory": [
            {
                "rail": rail.rail_id,
                "source": rail.source,
                "guards": rail.guards,
                "added_for": rail.added_for,
                "replayable": rail.replayable,
            }
            for rail in RAILS
        ],
        "replay": replay(posts),
        "ledger": ledger_view(),
    }


def main() -> int:
    """Print the rail audit. --strict exits non-zero when a rail looks harmful."""
    parser = argparse.ArgumentParser(description="Audit content quality rails")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--limit", type=int, default=120,
                        help="how many known-good posts to replay")
    parser.add_argument("--strict", action="store_true",
                        help="exit 1 if any rail is rejecting known-good content")
    args = parser.parse_args()

    report = audit(args.limit)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("=" * 74)
        print("  Rail audit — every quality guard, and whether it still behaves")
        print("=" * 74)
        if report["sample_size"]:
            print(f"  replayed against {report['sample_size']} known-good published "
                  f"posts from {report['sample_source']}\n")
        else:
            print("  NO CORPUS AVAILABLE — no published post bodies could be read.")
            print("  Posts live in Discussions, so this needs either a local")
            print("  state/discussions_cache.json or DISCUSSIONS_TOKEN/GITHUB_TOKEN.")
            print("  Every replay below is NO DATA. That is not a pass.\n")

        for item in report["inventory"]:
            outcome = report["replay"][item["rail"]]
            if not outcome.get("replayable"):
                status = "NOT REPLAYABLE"
                detail = outcome.get("note", "")
            else:
                status = outcome["verdict"]
                detail = (f"{outcome['would_reject']}/{outcome['checked']} "
                          f"known-good posts rejected "
                          f"({outcome['false_positive_rate']:.0%})"
                          if outcome["checked"] else "no corpus to replay against")
            print(f"  [{status:^14}] {item['rail']}")
            print(f"      {item['source']}")
            print(f"      guards:  {item['guards']}")
            print(f"      because: {item['added_for']}")
            print(f"      replay:  {detail}")
            for example in outcome.get("examples", [])[:2]:
                print(f"        - #{example['number']}: {example['reason'][:80]}")
            print()

        ledger = report["ledger"]
        print(f"  live ledger: {ledger['total']} recorded outcomes")
        if ledger["total"]:
            counts = ledger["counts"]
            print(f"    published {counts['published']}  declined {counts['declined']}  "
                  f"rejected {counts['rejected']}  failed {counts['failed']}")
            for rail, count in ledger["rail_rejections"].items():
                print(f"      {rail}: {count} rejections")
        else:
            print("    (no outcomes recorded yet — run generation to populate)")

        print("\n  This report surfaces; it does not strip. Removing a rail needs")
        print("  evidence it is net-harmful, and that evidence is the numbers above.")

    if args.strict:
        harmful = [rail_id for rail_id, outcome in report["replay"].items()
                   if outcome.get("verdict") == "HARMFUL"]
        if harmful:
            print(f"\n::error::rails rejecting most known-good content: "
                  f"{', '.join(harmful)}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
