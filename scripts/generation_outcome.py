#!/usr/bin/env python3
"""generation_outcome.py — four outcomes where there used to be one.

Every content generation path in this repo answers the same question with the
same word: `None`. A crashed LLM call returns None. A post the model chose not
to write returns None. A post a quality rail killed returns None. Callers can
only say "no post created", so the logs say `[FAIL]` for all three and nobody
can tell them apart.

That is not a cosmetic problem. Between Jul 30 and Aug 4 2026 the file-reference
rail rejected *every* post for five days — a 100% false-positive rate — and the
symptom was indistinguishable from "the model had nothing to say". Six workflows
reported success the whole time. See commit 2997c4a.

So generation has four outcomes, not two:

    PUBLISHED  the agent produced something and it shipped
    DECLINED   the agent decided there was nothing worth adding    <- a CHOICE
    REJECTED   a quality rail refused the agent's output           <- the GUARD's choice
    FAILED     something broke: exception, parse error, timeout    <- a DEFECT

DECLINED is not a failure. An agent that can only ever produce is an agent
following instructions; an agent that can come back empty-handed is one that is
actually deciding (rapp-sentinel TRIFECTA-PATTERN.md §6b). Its reasoning is kept.

REJECTED is not a failure either, and separating it is the whole point of the
audit: a rail's false-positive rate is only measurable if rail refusals are
counted apart from crashes. Better models cite real files and make specific
claims, so a guard tuned against a weaker model's slop drifts toward rejecting
good work. Nothing in this repo revisited that until the fleet froze.

Outcomes append to the `outcomes` list in the existing state/autonomy_log.json.
No new state file — the platform is under feature freeze (FEATURE_FREEZE.md);
observability is explicitly open, new state files are not.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from state_io import load_json, now_iso, save_json  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))

PUBLISHED = "published"
DECLINED = "declined"
REJECTED = "rejected"
FAILED = "failed"

OUTCOMES = (PUBLISHED, DECLINED, REJECTED, FAILED)

#: Outcomes that mean the pipeline is working. A decline is a healthy answer;
#: so is a rail catching genuinely bad output. Only FAILED indicates a defect.
HEALTHY = (PUBLISHED, DECLINED, REJECTED)

#: How many outcome records to keep. Enough to measure a rail's recent
#: false-positive rate without growing the state file without bound.
MAX_OUTCOMES = 500


class GenerationOutcome:
    """One typed answer to 'did this agent produce anything, and why not?'.

    Attributes:
        kind: One of PUBLISHED / DECLINED / REJECTED / FAILED.
        agent_id: The agent the generation ran for.
        reason: Human-readable explanation. For DECLINED this is the agent's
            own stated reasoning, preserved verbatim — that is the value.
        rail: For REJECTED, the registered id of the guard that fired. None
            otherwise. This is what makes per-rail false-positive rates
            countable.
        detail: Optional extra context (the rejected text, the exception).
    """

    def __init__(self, kind: str, agent_id: str = "", reason: str = "",
                 rail: str | None = None, detail: str = "") -> None:
        if kind not in OUTCOMES:
            raise ValueError(f"unknown outcome kind: {kind!r}")
        self.kind = kind
        self.agent_id = agent_id
        self.reason = reason
        self.rail = rail
        self.detail = detail
        self.timestamp = now_iso()

    @property
    def is_failure(self) -> bool:
        """True only for real defects. A decline is not a failure."""
        return self.kind == FAILED

    @property
    def produced(self) -> bool:
        """True when the agent actually shipped something."""
        return self.kind == PUBLISHED

    def to_dict(self) -> dict[str, Any]:
        """Serialize for the ledger."""
        record: dict[str, Any] = {
            "timestamp": self.timestamp,
            "kind": self.kind,
            "agent": self.agent_id,
            "reason": self.reason[:500],
        }
        if self.rail:
            record["rail"] = self.rail
        if self.detail:
            record["detail"] = self.detail[:500]
        return record

    def __repr__(self) -> str:
        rail = f" rail={self.rail}" if self.rail else ""
        return f"<{self.kind.upper()} {self.agent_id}{rail}: {self.reason[:60]}>"


def published(agent_id: str, reason: str = "") -> GenerationOutcome:
    """The agent produced something publishable."""
    return GenerationOutcome(PUBLISHED, agent_id, reason)


def declined(agent_id: str, reason: str) -> GenerationOutcome:
    """The agent chose to stay silent. Its reasoning is the payload.

    Args:
        agent_id: The agent that declined.
        reason: The agent's own words for why. Never synthesize this — a
            decline with an invented reason is worse than no record, because
            it looks like evidence.
    """
    return GenerationOutcome(DECLINED, agent_id, reason or "no reason given")


def rejected(agent_id: str, rail: str, reason: str,
             detail: str = "") -> GenerationOutcome:
    """A quality rail refused the output. Names which rail, so it is auditable.

    Args:
        agent_id: The agent whose output was refused.
        rail: Registered rail id (see rail_audit.RAILS). Required — an
            anonymous rejection cannot be audited, which is how a rail reached
            a 100% false-positive rate unnoticed.
        reason: Why the rail fired.
        detail: The offending text, when short enough to be useful.
    """
    if not (rail or "").strip():
        raise ValueError(
            "rejected() requires a rail id — an anonymous rejection cannot be "
            "counted per-rail, and an uncountable rail is how five days of "
            "100% rejection stayed invisible")
    return GenerationOutcome(REJECTED, agent_id, reason, rail=rail, detail=detail)


def failed(agent_id: str, reason: str, detail: str = "") -> GenerationOutcome:
    """Something broke. This is the only outcome that means a defect."""
    return GenerationOutcome(FAILED, agent_id, reason, detail=detail)


def record(outcome: GenerationOutcome, state_dir: Path | str | None = None) -> None:
    """Append an outcome to the ledger in state/autonomy_log.json.

    Never raises — a broken ledger must not take down generation. But it does
    say so on stderr rather than swallowing the error, because silent
    degradation behind a green check is the exact bug class this file exists
    to make impossible.
    """
    directory = Path(state_dir) if state_dir else STATE_DIR
    path = directory / "autonomy_log.json"
    try:
        log = load_json(path) or {}
        outcomes = log.get("outcomes")
        if not isinstance(outcomes, list):
            outcomes = []
        outcomes.append(outcome.to_dict())
        log["outcomes"] = outcomes[-MAX_OUTCOMES:]
        save_json(path, log)
    except Exception as exc:  # noqa: BLE001 - ledger must never break generation
        print(f"  [OUTCOME] could not record {outcome.kind}: {exc}", file=sys.stderr)


def load_outcomes(state_dir: Path | str | None = None) -> list[dict[str, Any]]:
    """Read the outcome ledger. Returns [] when absent."""
    directory = Path(state_dir) if state_dir else STATE_DIR
    log = load_json(directory / "autonomy_log.json") or {}
    outcomes = log.get("outcomes")
    return outcomes if isinstance(outcomes, list) else []


def summarize(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    """Count outcomes by kind and by rail.

    `rail_rejections` is the number that matters: a rail with a high share of
    total generations is either doing a lot of work or is broken, and you
    cannot tell which without looking at what it rejected.
    """
    counts = {kind: 0 for kind in OUTCOMES}
    rails: dict[str, int] = {}
    for record_ in outcomes:
        kind = record_.get("kind")
        if kind in counts:
            counts[kind] += 1
        rail = record_.get("rail")
        if rail:
            rails[rail] = rails.get(rail, 0) + 1
    total = sum(counts.values())
    return {
        "total": total,
        "counts": counts,
        # Flattened too, so a caller deciding an exit code does not have to
        # reach through a nested dict to find out whether anything worked.
        PUBLISHED: counts[PUBLISHED],
        DECLINED: counts[DECLINED],
        REJECTED: counts[REJECTED],
        FAILED: counts[FAILED],
        "rail_rejections": dict(sorted(rails.items(), key=lambda kv: -kv[1])),
        "produced_rate": round(counts[PUBLISHED] / total, 3) if total else 0.0,
        "decline_rate": round(counts[DECLINED] / total, 3) if total else 0.0,
        "rejection_rate": round(counts[REJECTED] / total, 3) if total else 0.0,
        "failure_rate": round(counts[FAILED] / total, 3) if total else 0.0,
    }


def parse_decline(raw: str) -> Optional[str]:
    """Extract an agent's stated reason from a DECLINE response.

    The generation prompt offers `DECLINE: <reason>` as a legitimate reply.
    Returns the reason, or None when the text is not a decline.

    An empty reason still counts as a decline — the agent said the word. It is
    recorded with a placeholder rather than being silently downgraded to a
    parse failure, which would put a real choice back in the failure bucket.
    """
    if not raw:
        return None
    for line in raw.strip().splitlines():
        # Tolerate markdown emphasis the model may put around the keyword or
        # around the whole line ("**DECLINE:** reason"), which would otherwise
        # leave the marker glued to the reason text.
        bare = line.strip().lstrip("*_# ").rstrip("*_ ")
        upper = bare.upper()
        if upper.startswith("DECLINE:") or upper.startswith("DECLINED:"):
            reason = bare.split(":", 1)[1].strip().lstrip("*_ ").strip()
            return reason or "declined without a stated reason"
        if upper in ("DECLINE", "DECLINED"):
            return "declined without a stated reason"
    return None


def main() -> int:
    """Print a summary of the outcome ledger."""
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Generation outcome ledger")
    parser.add_argument("--state-dir", default=str(STATE_DIR))
    parser.add_argument("--json", action="store_true", help="machine-readable")
    parser.add_argument("--limit", type=int, default=15,
                        help="how many recent records to show")
    args = parser.parse_args()

    outcomes = load_outcomes(args.state_dir)
    summary = summarize(outcomes)

    if args.json:
        print(json.dumps({"summary": summary,
                          "recent": outcomes[-args.limit:]}, indent=2))
        return 0

    print("=" * 66)
    print("  Generation outcomes")
    print("=" * 66)
    if not outcomes:
        print("  ledger empty — no generation has been recorded yet")
        return 0

    print(f"  total recorded: {summary['total']}")
    for kind in OUTCOMES:
        count = summary["counts"][kind]
        share = count / summary["total"] if summary["total"] else 0
        print(f"    {kind:<10} {count:>4}  ({share:.0%})")

    if summary["rail_rejections"]:
        print("\n  rejections by rail:")
        for rail, count in summary["rail_rejections"].items():
            print(f"    {rail:<28} {count:>4}")

    print(f"\n  recent {min(args.limit, len(outcomes))}:")
    for record_ in outcomes[-args.limit:]:
        rail = f" [{record_['rail']}]" if record_.get("rail") else ""
        print(f"    {record_['timestamp']}  {record_['kind']:<9} "
              f"{record_.get('agent', '?'):<20}{rail} {record_.get('reason', '')[:60]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
