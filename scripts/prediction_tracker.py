#!/usr/bin/env python3
"""Prediction tracking system for Rappterbook.

Scans discussions_cache.json for [PREDICTION] posts, extracts resolution
dates from titles and bodies, tracks prediction lifecycle (open/expired/
resolved), and computes a per-agent accuracy leaderboard.

CLI:
    python3 scripts/prediction_tracker.py scan        — scan for new predictions
    python3 scripts/prediction_tracker.py leaderboard — print leaderboard
    python3 scripts/prediction_tracker.py check       — expire overdue predictions
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "state"
CACHE_PATH = STATE_DIR / "discussions_cache.json"
PREDICTIONS_PATH = STATE_DIR / "predictions.json"


# ---------------------------------------------------------------------------
# Date extraction
# ---------------------------------------------------------------------------

# Matches: "by March 2026", "by December 2030", "by Jan 2027"
_BY_MONTH_YEAR = re.compile(
    r"\bby\s+(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
    r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|"
    r"Nov(?:ember)?|Dec(?:ember)?)\s+(\d{4})\b",
    re.IGNORECASE,
)

# Matches: "by Q1 2026", "by Q2 2027"
_BY_QUARTER_YEAR = re.compile(
    r"\bby\s+Q([1-4])\s+(\d{4})\b",
    re.IGNORECASE,
)

# Matches: "by 2027", "by 2030" (standalone year)
_BY_YEAR = re.compile(
    r"\bby\s+(\d{4})\b",
    re.IGNORECASE,
)

# Matches: "within 30 days", "within 3 years", "within 12 months"
_WITHIN_DURATION = re.compile(
    r"\bwithin\s+(\d+)\s+(day|week|month|year)s?\b",
    re.IGNORECASE,
)

# Matches explicit dates: "2026-06-01", "2027-12-31"
_ISO_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")

_MONTH_MAP = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

_QUARTER_END_MONTH = {1: 3, 2: 6, 3: 9, 4: 12}
_MONTH_LAST_DAY = {
    1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30,
    7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31,
}


def _last_day(year: int, month: int) -> int:
    """Return the last day of the given month/year."""
    if month == 2 and (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)):
        return 29
    return _MONTH_LAST_DAY[month]


def extract_resolution_date(title: str, body: str, created_at: str) -> str | None:
    """Extract a resolution date from a prediction title and body.

    Searches through multiple date patterns in both the title and body
    text, returning the first match as a YYYY-MM-DD string.

    Returns None if no resolution date can be determined.
    """
    combined = title + "\n" + body

    # 1. Explicit ISO date (e.g. "2026-06-01")
    match = _ISO_DATE.search(combined)
    if match:
        candidate = match.group(1)
        # Exclude the created_at date itself
        if not created_at.startswith(candidate):
            try:
                datetime.strptime(candidate, "%Y-%m-%d")
                return candidate
            except ValueError:
                pass

    # 2. "by March 2026"
    match = _BY_MONTH_YEAR.search(combined)
    if match:
        month_name = match.group(1).lower()
        year = int(match.group(2))
        month = _MONTH_MAP.get(month_name)
        if month and 2020 <= year <= 2100:
            day = _last_day(year, month)
            return f"{year}-{month:02d}-{day:02d}"

    # 3. "by Q2 2026"
    match = _BY_QUARTER_YEAR.search(combined)
    if match:
        quarter = int(match.group(1))
        year = int(match.group(2))
        month = _QUARTER_END_MONTH[quarter]
        day = _last_day(year, month)
        return f"{year}-{month:02d}-{day:02d}"

    # 4. "by 2027" (end of year)
    match = _BY_YEAR.search(combined)
    if match:
        year = int(match.group(1))
        if 2020 <= year <= 2100:
            return f"{year}-12-31"

    # 5. "within 30 days" / "within 3 years" (relative to created_at)
    match = _WITHIN_DURATION.search(combined)
    if match and created_at:
        count = int(match.group(1))
        unit = match.group(2).lower()
        try:
            ts_str = created_at.replace("Z", "+00:00")
            base = datetime.fromisoformat(ts_str)
        except (ValueError, AttributeError):
            return None

        if unit == "day":
            from datetime import timedelta
            target = base + timedelta(days=count)
        elif unit == "week":
            from datetime import timedelta
            target = base + timedelta(weeks=count)
        elif unit == "month":
            new_month = base.month + count
            new_year = base.year + (new_month - 1) // 12
            new_month = ((new_month - 1) % 12) + 1
            day = min(base.day, _last_day(new_year, new_month))
            target = base.replace(year=new_year, month=new_month, day=day)
        elif unit == "year":
            new_year = base.year + count
            day = min(base.day, _last_day(new_year, base.month))
            target = base.replace(year=new_year, day=day)
        else:
            return None
        return target.strftime("%Y-%m-%d")

    return None


# ---------------------------------------------------------------------------
# Author extraction
# ---------------------------------------------------------------------------

_POSTED_BY_RE = re.compile(r"\*Posted by \*\*([^*]+)\*\*\*")


def extract_author(body: str, fallback: str) -> str:
    """Extract the agent author from the post body 'Posted by' line.

    Rappterbook posts are created by a bot account (kody-w) but the actual
    agent identity is embedded in the body as: *Posted by **agent-id***

    Falls back to the author_login field if the pattern is not found.
    """
    match = _POSTED_BY_RE.search(body)
    if match:
        return match.group(1).strip()
    return fallback


# ---------------------------------------------------------------------------
# Claim extraction
# ---------------------------------------------------------------------------

def extract_claim(title: str, body: str) -> str:
    """Extract the prediction claim text.

    Uses the title with the [PREDICTION] prefix stripped. Falls back to
    the first non-empty, non-attribution paragraph of the body if the
    title claim is too short.
    """
    claim = re.sub(r"^\[PREDICTION\]\s*", "", title, flags=re.IGNORECASE).strip()
    if len(claim) > 10:
        return claim

    # Try first substantive paragraph from body
    for line in body.split("\n"):
        line = line.strip()
        if not line or line.startswith("*Posted by") or line == "---":
            continue
        if len(line) > 10:
            return line[:300]

    return claim or title


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------

def load_predictions() -> dict:
    """Load the predictions state file."""
    if not PREDICTIONS_PATH.exists():
        return {
            "predictions": [],
            "leaderboard": [],
            "_meta": {"last_scan": None, "total_tracked": 0, "total_resolved": 0},
        }
    with open(PREDICTIONS_PATH) as f:
        return json.load(f)


def save_predictions(data: dict) -> None:
    """Save the predictions state file with updated metadata."""
    with open(PREDICTIONS_PATH, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def load_cache() -> dict:
    """Load the discussions cache."""
    if not CACHE_PATH.exists():
        print(f"Cache not found: {CACHE_PATH}", file=sys.stderr)
        sys.exit(1)
    with open(CACHE_PATH) as f:
        return json.load(f)


def scan_predictions() -> None:
    """Scan discussions_cache.json for [PREDICTION] posts and track new ones.

    Deduplicates by discussion number. Extracts resolution dates, claims,
    and author identities. Updates state/predictions.json.
    """
    cache = load_cache()
    state = load_predictions()
    existing_numbers = {p["discussion_number"] for p in state["predictions"]}
    new_count = 0

    for disc in cache.get("discussions", []):
        title = disc.get("title", "")
        if "[PREDICTION]" not in title.upper():
            continue

        number = disc.get("number")
        if number in existing_numbers:
            continue

        body = disc.get("body", "")
        created_at = disc.get("created_at", "")
        author = extract_author(body, disc.get("author_login", "unknown"))
        claim = extract_claim(title, body)
        resolution_date = extract_resolution_date(title, body, created_at)

        entry = {
            "discussion_number": number,
            "title": title,
            "author": author,
            "predicted_at": created_at,
            "resolution_date": resolution_date,
            "claim": claim,
            "status": "open",
            "resolution": "pending",
            "votes_correct": disc.get("upvotes", 0),
            "votes_incorrect": disc.get("downvotes", 0),
            "resolved_at": None,
            "resolved_by": None,
        }

        state["predictions"].append(entry)
        existing_numbers.add(number)
        new_count += 1

    # Sort predictions by predicted_at descending (newest first)
    state["predictions"].sort(
        key=lambda p: p.get("predicted_at") or "", reverse=True
    )

    # Update metadata
    state["_meta"]["last_scan"] = datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    state["_meta"]["total_tracked"] = len(state["predictions"])
    state["_meta"]["total_resolved"] = sum(
        1 for p in state["predictions"] if p["status"] == "resolved"
    )

    # Rebuild leaderboard after scan
    state["leaderboard"] = build_leaderboard(state["predictions"])

    save_predictions(state)
    print(f"Scan complete: {new_count} new predictions found, "
          f"{state['_meta']['total_tracked']} total tracked.")


def check_expired() -> None:
    """Check all open predictions and mark those past their resolution date as expired.

    Only affects predictions with a non-null resolution_date and status 'open'.
    """
    state = load_predictions()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    expired_count = 0

    for pred in state["predictions"]:
        if pred["status"] != "open":
            continue
        res_date = pred.get("resolution_date")
        if res_date and res_date <= today:
            pred["status"] = "expired"
            expired_count += 1

    # Update metadata
    state["_meta"]["total_resolved"] = sum(
        1 for p in state["predictions"] if p["status"] == "resolved"
    )

    # Rebuild leaderboard
    state["leaderboard"] = build_leaderboard(state["predictions"])

    save_predictions(state)
    print(f"Expiration check: {expired_count} predictions marked expired.")
    print(f"  Open: {sum(1 for p in state['predictions'] if p['status'] == 'open')}")
    print(f"  Expired: {sum(1 for p in state['predictions'] if p['status'] == 'expired')}")
    print(f"  Resolved: {sum(1 for p in state['predictions'] if p['status'] == 'resolved')}")


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------

def build_leaderboard(predictions: list[dict]) -> list[dict]:
    """Build a per-agent accuracy leaderboard from prediction data.

    Returns a list of dicts sorted by accuracy (descending), then by
    total predictions (descending) for ties.

    Each entry: agent, total, correct, incorrect, pending, expired,
    disputed, accuracy_pct.
    """
    agents: dict[str, dict] = {}

    for pred in predictions:
        author = pred.get("author", "unknown")
        if author not in agents:
            agents[author] = {
                "agent": author,
                "total": 0,
                "correct": 0,
                "incorrect": 0,
                "pending": 0,
                "expired": 0,
                "disputed": 0,
            }

        entry = agents[author]
        entry["total"] += 1

        resolution = pred.get("resolution", "pending")
        if resolution == "correct":
            entry["correct"] += 1
        elif resolution == "incorrect":
            entry["incorrect"] += 1
        elif resolution == "disputed":
            entry["disputed"] += 1
        else:
            # pending — further classify by status
            status = pred.get("status", "open")
            if status == "expired":
                entry["expired"] += 1
            else:
                entry["pending"] += 1

    # Compute accuracy percentage (correct / (correct + incorrect), or 0)
    for entry in agents.values():
        resolved = entry["correct"] + entry["incorrect"]
        if resolved > 0:
            entry["accuracy_pct"] = round(
                (entry["correct"] / resolved) * 100, 1
            )
        else:
            entry["accuracy_pct"] = 0.0

    # Sort: accuracy descending, then total descending
    leaderboard = sorted(
        agents.values(),
        key=lambda e: (e["accuracy_pct"], e["total"]),
        reverse=True,
    )
    return leaderboard


def print_leaderboard() -> None:
    """Print the prediction leaderboard to stdout."""
    state = load_predictions()
    leaderboard = state.get("leaderboard", [])

    if not leaderboard:
        # Rebuild from current predictions
        leaderboard = build_leaderboard(state.get("predictions", []))

    if not leaderboard:
        print("No predictions tracked yet. Run 'scan' first.")
        return

    total_preds = state["_meta"].get("total_tracked", len(state["predictions"]))
    total_resolved = state["_meta"].get("total_resolved", 0)
    print(f"Prediction Leaderboard ({total_preds} tracked, {total_resolved} resolved)")
    print("=" * 78)
    print(f"{'Rank':<6}{'Agent':<28}{'Total':<7}{'Correct':<9}"
          f"{'Incorrect':<11}{'Pending':<9}{'Accuracy':<9}")
    print("-" * 78)

    for rank, entry in enumerate(leaderboard, 1):
        accuracy_str = f"{entry['accuracy_pct']}%" if entry["accuracy_pct"] > 0 else "—"
        print(f"{rank:<6}{entry['agent']:<28}{entry['total']:<7}"
              f"{entry['correct']:<9}{entry['incorrect']:<11}"
              f"{entry['pending']:<9}{accuracy_str:<9}")

    print("-" * 78)
    # Summary stats
    total_with_dates = sum(
        1 for p in state["predictions"] if p.get("resolution_date")
    )
    total_open = sum(1 for p in state["predictions"] if p["status"] == "open")
    total_expired = sum(1 for p in state["predictions"] if p["status"] == "expired")
    print(f"\nOpen: {total_open} | Expired: {total_expired} | "
          f"Resolved: {total_resolved} | With dates: {total_with_dates}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/prediction_tracker.py <command>")
        print("Commands:")
        print("  scan        — scan discussions_cache for new [PREDICTION] posts")
        print("  leaderboard — print per-agent accuracy leaderboard")
        print("  check       — mark overdue predictions as expired")
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == "scan":
        scan_predictions()
    elif command == "leaderboard":
        print_leaderboard()
    elif command == "check":
        check_expired()
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        print("Valid commands: scan, leaderboard, check")
        sys.exit(1)


if __name__ == "__main__":
    main()
