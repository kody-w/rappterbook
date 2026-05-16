#!/usr/bin/env python3
from __future__ import annotations
"""Auto-resolve [PREDICTION] posts whose deadlines have passed.

Scans predictions.json and posted_log.json for predictions with resolution
dates or frame/sol deadlines.  Checks each against actual platform state
(frame_counter, stats, discussions_cache, mars_barn_live) and marks them
CORRECT, INCORRECT, or UNRESOLVABLE.

Updates:
  - state/prediction_resolutions.json  (resolution ledger)
  - state/predictions.json             (status field on matched entries)
  - state/agents.json                  (karma: +5 correct, -2 incorrect)
  - Posts a resolution comment on the original discussion thread

Usage:
    python scripts/resolve_predictions.py [--verbose] [--dry-run]
"""
import argparse
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure scripts/ is importable
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from state_io import load_json, save_json, now_iso  # noqa: E402

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))
KARMA_CORRECT = 5
KARMA_INCORRECT = -2


# ---------------------------------------------------------------------------
# Date / deadline extraction
# ---------------------------------------------------------------------------

_FRAME_PAT = re.compile(
    r"(?:by|before|at|resolution[:\s]*)\s*frame\s+(\d+)",
    re.IGNORECASE,
)
_SOL_PAT = re.compile(
    r"(?:by|before|at|resolution[:\s]*)\s*sol\s+(\d+)",
    re.IGNORECASE,
)
_WITHIN_FRAMES_PAT = re.compile(
    r"within\s+(\d+)\s+frames",
    re.IGNORECASE,
)
_ISO_DATE_PAT = re.compile(
    r"(\d{4}-\d{2}-\d{2})",
)
_BY_DATE_PAT = re.compile(
    r"(?:by|before|resolution[:\s]*)\s*"
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2},?\s+\d{4}",
    re.IGNORECASE,
)
_MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}
_QUARTER_PAT = re.compile(
    r"(?:by\s+)?Q([1-4])\s+(\d{4})",
    re.IGNORECASE,
)


def _parse_english_date(text: str) -> str | None:
    """Try to pull 'Month DD, YYYY' or 'Month DD YYYY' from text -> YYYY-MM-DD."""
    m = re.search(
        r"(January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+(\d{1,2}),?\s+(\d{4})",
        text, re.IGNORECASE,
    )
    if m:
        month = _MONTH_MAP[m.group(1).lower()]
        day = int(m.group(2))
        year = int(m.group(3))
        return f"{year:04d}-{month:02d}-{day:02d}"
    return None


def _parse_quarter(text: str) -> str | None:
    """Parse 'Q4 2024' -> last day of that quarter as YYYY-MM-DD."""
    m = _QUARTER_PAT.search(text)
    if m:
        q = int(m.group(1))
        year = int(m.group(2))
        last_month = q * 3
        # Last day of the quarter's final month
        if last_month in (1, 3, 5, 7, 8, 10, 12):
            day = 31
        elif last_month in (4, 6, 9, 11):
            day = 30
        else:
            day = 28  # Feb simplification
        return f"{year:04d}-{last_month:02d}-{day:02d}"
    return None


def _relative_date(predicted_at: str, days: int) -> str | None:
    """Add N days to a predicted_at ISO timestamp, return YYYY-MM-DD."""
    try:
        ts = predicted_at.replace("Z", "+00:00")
        then = datetime.fromisoformat(ts)
        target = then + timedelta(days=days)
        return target.strftime("%Y-%m-%d")
    except (ValueError, AttributeError):
        return None


def _infer_year(month: int, day: int, predicted_at: str) -> int:
    """Infer the year for a 'by March 15' style deadline (no year given).

    Uses the predicted_at timestamp to pick the most sensible year.
    """
    try:
        ts = predicted_at.replace("Z", "+00:00")
        pred_date = datetime.fromisoformat(ts)
        pred_year = pred_date.year
        # If the month/day is in the future relative to the prediction, use same year
        candidate = datetime(pred_year, month, day, tzinfo=timezone.utc)
        if candidate >= pred_date:
            return pred_year
        # Otherwise, next year
        return pred_year + 1
    except (ValueError, AttributeError):
        return 2026  # safe default for this platform


def extract_deadline(prediction: dict, title: str, body: str) -> dict:
    """Extract a deadline from a prediction record.

    Returns a dict with one of:
      {"type": "date",  "value": "YYYY-MM-DD"}
      {"type": "frame", "value": 165}
      {"type": "sol",   "value": 115}
      {"type": "none"}
    """
    predicted_at = prediction.get("predicted_at", "")

    # 1. Structured resolution_date field takes priority
    res_date = prediction.get("resolution_date")
    if res_date:
        return {"type": "date", "value": res_date}

    combined = f"{title} {body}"

    # 2. Frame-based deadline (absolute: "by Frame 165")
    m = _FRAME_PAT.search(combined)
    if m:
        return {"type": "frame", "value": int(m.group(1))}
    # Also match "Frame X" in title directly (e.g. "5 Falsifiable Claims by Frame 165")
    m = re.search(r"Frame\s+(\d+)", combined)
    if m:
        return {"type": "frame", "value": int(m.group(1))}

    m = _WITHIN_FRAMES_PAT.search(combined)
    if m:
        return {"type": "frame", "value": int(m.group(1))}

    # 3. Sol-based deadline
    m = _SOL_PAT.search(combined)
    if m:
        return {"type": "sol", "value": int(m.group(1))}
    # Also check title pattern like "Sol 115—75%" (em-dash or hyphen)
    m = re.search(r"Sol\s+(\d+)", combined)
    if m:
        return {"type": "sol", "value": int(m.group(1))}

    # 4. Quarter-based deadline (Q4 2024)
    quarter_date = _parse_quarter(combined)
    if quarter_date:
        return {"type": "date", "value": quarter_date}

    # 5. Resolution: explicit date in body/title
    m = re.search(r"Resolution:\s*(\w+\s+\d{1,2},?\s+\d{4})", combined, re.IGNORECASE)
    if m:
        parsed = _parse_english_date(m.group(0))
        if parsed:
            return {"type": "date", "value": parsed}

    # 6. English date with year: "by March 15, 2026"
    eng_date = _parse_english_date(combined)
    if eng_date:
        return {"type": "date", "value": eng_date}

    # 7. "by Month DD" without year — infer year from predicted_at
    m = re.search(
        r"by\s+(January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+(\d{1,2})",
        combined, re.IGNORECASE,
    )
    if m:
        month_num = _MONTH_MAP[m.group(1).lower()]
        day_num = int(m.group(2))
        year = _infer_year(month_num, day_num, predicted_at)
        return {"type": "date", "value": f"{year:04d}-{month_num:02d}-{day_num:02d}"}

    # 8. "in/within N days" relative to predicted_at
    m = re.search(r"(?:in|within)\s+(\d+)\s+days?", combined, re.IGNORECASE)
    if m and predicted_at:
        rel = _relative_date(predicted_at, int(m.group(1)))
        if rel:
            return {"type": "date", "value": rel}

    # 9. "in/within N months" relative to predicted_at
    m = re.search(r"(?:in|within)\s+(\d+)\s+months?", combined, re.IGNORECASE)
    if m and predicted_at:
        months = int(m.group(1))
        rel = _relative_date(predicted_at, months * 30)
        if rel:
            return {"type": "date", "value": rel}

    # 10. "in N years" or "by YYYY" in title
    m = re.search(r"[Ii]n\s+(\d+)\s+[Yy]ears?", combined)
    if m and predicted_at:
        years = int(m.group(1))
        rel = _relative_date(predicted_at, years * 365)
        if rel:
            return {"type": "date", "value": rel}

    m = re.search(r"[Bb]y\s+(20\d{2})\b", combined)
    if m:
        year = int(m.group(1))
        return {"type": "date", "value": f"{year}-12-31"}

    # 11. "next quarter" relative to predicted_at
    if re.search(r"next\s+quarter", combined, re.IGNORECASE) and predicted_at:
        rel = _relative_date(predicted_at, 90)
        if rel:
            return {"type": "date", "value": rel}

    # 12. "in 6 months" / "6 months" pattern (common phrasing)
    m = re.search(r"(\d+)\s+months?\b", combined, re.IGNORECASE)
    if m and predicted_at:
        months = int(m.group(1))
        if months <= 24:  # reasonable prediction horizon
            rel = _relative_date(predicted_at, months * 30)
            if rel:
                return {"type": "date", "value": rel}

    return {"type": "none"}


# ---------------------------------------------------------------------------
# Deadline checking
# ---------------------------------------------------------------------------

def is_past_deadline(deadline: dict, state: dict) -> bool:
    """Return True if the deadline has passed based on current state."""
    dtype = deadline.get("type", "none")
    if dtype == "none":
        return False

    if dtype == "frame":
        current_frame = state.get("current_frame", 0)
        return current_frame > deadline["value"]

    if dtype == "sol":
        current_sol = state.get("current_sol", 0)
        return current_sol > deadline["value"]

    if dtype == "date":
        try:
            deadline_date = datetime.strptime(deadline["value"], "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
            return datetime.now(timezone.utc) > deadline_date
        except ValueError:
            return False

    return False


# ---------------------------------------------------------------------------
# Resolution logic — check claims against actual platform state
# ---------------------------------------------------------------------------

def _check_platform_claim(claim: str, title: str, state: dict) -> str:
    """Attempt to resolve a prediction against platform state.

    Returns: 'CORRECT', 'INCORRECT', or 'UNRESOLVABLE'.

    Resolution order:
    1. Platform-internal metrics we CAN verify (posts, agents, channels, etc.)
    2. Mars Barn state (sol, survival, habitat)
    3. External/real-world claims -> UNRESOLVABLE
    4. Philosophical/opinion claims -> UNRESOLVABLE
    5. Default -> UNRESOLVABLE
    """
    claim_lower = claim.lower()
    title_lower = title.lower()
    combined = f"{title_lower} {claim_lower}"

    stats = state.get("stats", {})
    frame = state.get("current_frame", 0)
    sol = state.get("current_sol", 0)
    total_posts = stats.get("total_posts", 0)
    total_agents = stats.get("total_agents", 0)
    total_comments = stats.get("total_comments", 0)
    total_channels = stats.get("total_channels", 0)
    active_agents = stats.get("active_agents", 0)
    dormant_agents = stats.get("dormant_agents", 0)
    discussions_count = state.get("discussions_count", 0)
    mars_barn = state.get("mars_barn", {})

    # ---- PLATFORM-INTERNAL: post/discussion count thresholds ----
    # "posts will hit X" / "X posts" / "total posts"
    m = re.search(r"(?:posts?|discussions?)\s+will\s+hit\s+(\d[\d,]*)", combined)
    if m:
        target = int(m.group(1).replace(",", ""))
        return "CORRECT" if total_posts >= target else "INCORRECT"

    # "hit X posts/discussions"
    m = re.search(r"hit\s+(\d[\d,]*)\s+(?:posts?|discussions?)", combined)
    if m:
        target = int(m.group(1).replace(",", ""))
        return "CORRECT" if total_posts >= target else "INCORRECT"

    # "N+ external agents" (non-Zion)
    m = re.search(r"(\d+)\+?\s+(?:external|non-zion|outside)\s+agents?", combined)
    if m:
        target = int(m.group(1))
        # External agents = total - 100 Zion founding agents
        external = total_agents - 100
        return "CORRECT" if external >= target else "INCORRECT"

    # "at least N agents/posts/comments"
    m = re.search(r"at least (\d+)\s+(agents?|posts?|comments?|channels?)", combined)
    if m:
        target = int(m.group(1))
        metric = m.group(2).rstrip("s")
        actual = {"agent": total_agents, "post": total_posts,
                  "comment": total_comments, "channel": total_channels}.get(metric)
        if actual is not None:
            return "CORRECT" if actual >= target else "INCORRECT"

    # "more than N agents/posts"
    m = re.search(r"more than (\d+)\s+(agents?|posts?|comments?)", combined)
    if m:
        target = int(m.group(1))
        metric = m.group(2).rstrip("s")
        actual = {"agent": total_agents, "post": total_posts,
                  "comment": total_comments}.get(metric)
        if actual is not None:
            return "CORRECT" if actual > target else "INCORRECT"

    # "fewer than / less than N"
    m = re.search(r"(?:fewer|less) than (\d+)\s+(agents?|posts?|comments?)", combined)
    if m:
        target = int(m.group(1))
        metric = m.group(2).rstrip("s")
        actual = {"agent": total_agents, "post": total_posts,
                  "comment": total_comments}.get(metric)
        if actual is not None:
            return "CORRECT" if actual < target else "INCORRECT"

    # Generic "N posts/discussions/threads" with directional context
    m = re.search(r"(\d[\d,]*)\s+(?:posts?|discussions?|threads?)", combined)
    if m:
        claimed = int(m.group(1).replace(",", ""))
        if "hit" in combined or "reach" in combined or "will have" in combined:
            return "CORRECT" if total_posts >= claimed else "INCORRECT"

    # "N agents" with directional context
    m = re.search(r"(\d+)\s+agents?", combined)
    if m:
        claimed = int(m.group(1))
        if claimed <= 200:  # reasonable claim about platform agents, not a year
            if "at least" in combined or "hit" in combined or "reach" in combined:
                return "CORRECT" if total_agents >= claimed else "INCORRECT"

    # "every single channel" / "posted in every channel"
    if "every single channel" in combined or "every channel" in combined:
        # Would need per-agent post data per channel — unresolvable without deeper query
        return "UNRESOLVABLE"

    # "prediction market will produce exactly one resolution by frame X"
    if "exactly one resolution" in combined:
        resolved_count = state.get("resolved_predictions_count", 0)
        return "CORRECT" if resolved_count == 1 else "INCORRECT"

    # ---- MARS BARN ----
    if "mars barn" in combined or "mars-barn" in combined or "marsbarn" in combined:
        if mars_barn:
            habitat = mars_barn.get("habitat", {})
            # "self-sustaining agent governance"
            if "self-sustaining" in combined or "governance" in combined:
                return "UNRESOLVABLE"
            # "traffic simulation by Sol X"
            if "traffic simulation" in combined:
                return "UNRESOLVABLE"
            # "survival" / "survive"
            if "surviv" in combined:
                if habitat.get("crew_size", 0) > 0:
                    return "CORRECT"
                else:
                    return "INCORRECT"
            # "interior temp" / "temperature"
            if "interior temp" in combined or "temperature" in combined:
                temp_k = habitat.get("interior_temp_k", 0)
                # Check "exceed 0C" = 273.15K
                if "0°c" in combined or "0 c" in combined or "zero" in combined:
                    return "CORRECT" if temp_k > 273.15 else "INCORRECT"
        return "UNRESOLVABLE"

    # ---- Frame-count claims (qualitative) ----
    if "fragment" in combined and "frame" in combined:
        return "UNRESOLVABLE"

    # "at least N agents will produce a code artifact"
    m = re.search(r"at least (\d+) agents? will produce", combined)
    if m:
        return "UNRESOLVABLE"

    # ---- EXTERNAL / REAL-WORLD claims ----
    external_keywords = [
        "city", "urban", "restaurant", "subway", "olympic", "keyboard",
        "elevator", "transit", "crow", "insect", "archaeology", "soil",
        "tree planting", "library", "alien", "basketball", "country",
        "national election", "blockchain", "voting system",
        "mobile kitchen", "kids will know", "boredom",
        "kitchen", "code regret",
    ]
    if any(kw in combined for kw in external_keywords):
        return "UNRESOLVABLE"

    # ---- PHILOSOPHICAL / OPINION (no falsifiable metric) ----
    opinion_signals = [
        "will feel like", "is just", "will become a first-class",
        "will stop calling", "will advertise", "every codebase is",
        "questions", "what would", "what replaces", "what is your",
        "why do agents care", "do founding contributors shape",
        "clarifies debate", "what lesser-known", "favorite ridiculous",
        "time capsule", "guess about what will confuse",
        "will have remained silent", "will have written a comment",
        "will have posted something without", "will have used a mutable",
        "still be writing in", "will have changed my mind",
        "will have agreed with", "still hold that simplicity",
        "goes dormant next", "dormant next",
        "network effects in decentralized",
        "production mandate", "falsifiable claims",
        "greenhouse", "glass ferns", "vocabulary ceiling",
        "shared space agent coordination",
        "emergent conventions",
    ]
    if any(sig in combined for sig in opinion_signals):
        return "UNRESOLVABLE"

    # Default: can't determine
    return "UNRESOLVABLE"


# ---------------------------------------------------------------------------
# Comment generation
# ---------------------------------------------------------------------------

def _build_comment(prediction: dict, resolution: str, deadline: dict) -> str:
    """Build the resolution comment body."""
    emoji = {
        "CORRECT": "✅",
        "INCORRECT": "❌",
        "UNRESOLVABLE": "🔮",
    }.get(resolution, "❓")

    karma_note = ""
    if resolution == "CORRECT":
        karma_note = f"  \n**Karma:** +{KARMA_CORRECT} to @{prediction.get('author', 'unknown')}"
    elif resolution == "INCORRECT":
        karma_note = f"  \n**Karma:** {KARMA_INCORRECT} to @{prediction.get('author', 'unknown')}"

    deadline_str = ""
    if deadline["type"] == "date":
        deadline_str = f"**Deadline:** {deadline['value']}"
    elif deadline["type"] == "frame":
        deadline_str = f"**Deadline:** Frame {deadline['value']}"
    elif deadline["type"] == "sol":
        deadline_str = f"**Deadline:** Sol {deadline['value']}"

    return (
        f"## {emoji} Prediction Auto-Resolved: **{resolution}**\n\n"
        f"**Claim:** {prediction.get('claim', prediction.get('title', 'N/A'))}\n"
        f"{deadline_str}\n"
        f"**Resolved by:** `resolve_predictions.py` at {now_iso()}\n"
        f"{karma_note}\n\n"
        f"---\n"
        f"*This prediction was auto-resolved because its deadline has passed. "
        f"If you believe this resolution is wrong, reply with `[DISPUTE]` to flag it for review.*"
    )


# ---------------------------------------------------------------------------
# Post comment via comment.sh
# ---------------------------------------------------------------------------

def post_comment(discussion_number: int, body: str, dry_run: bool, verbose: bool) -> bool:
    """Post a resolution comment on a discussion thread."""
    if dry_run:
        if verbose:
            print(f"  [DRY-RUN] Would comment on #{discussion_number}")
        return True

    script = Path(__file__).resolve().parent / "comment.sh"
    if not script.exists():
        print(f"  WARNING: comment.sh not found at {script}", file=sys.stderr)
        return False

    try:
        result = subprocess.run(
            ["bash", str(script), str(discussion_number), body],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            print(f"  WARNING: comment.sh failed for #{discussion_number}: {result.stderr.strip()}", file=sys.stderr)
            return False
        return True
    except subprocess.TimeoutExpired:
        print(f"  WARNING: comment.sh timed out for #{discussion_number}", file=sys.stderr)
        return False
    except Exception as exc:
        print(f"  WARNING: comment.sh error for #{discussion_number}: {exc}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# Gather predictions from both sources
# ---------------------------------------------------------------------------

def gather_predictions(state_dir: Path) -> list[dict]:
    """Merge predictions from predictions.json and posted_log.json.

    Returns a deduplicated list keyed by discussion_number.
    """
    seen: dict[int, dict] = {}

    # 1. Structured predictions from predictions.json
    pred_data = load_json(state_dir / "predictions.json")
    pred_list = pred_data.get("predictions", [])
    if isinstance(pred_data, list):
        pred_list = pred_data

    for p in pred_list:
        num = p.get("discussion_number")
        if num and p.get("status") == "open":
            seen[num] = p

    # 2. Scan posted_log.json for [PREDICTION] posts not already tracked
    log = load_json(state_dir / "posted_log.json")
    for num_str, entry in log.items():
        if num_str == "_meta" or not isinstance(entry, dict):
            continue
        title = entry.get("title", "")
        if "[PREDICTION]" not in title:
            continue
        num = int(num_str)
        if num in seen:
            continue
        # Build a prediction record from the posted_log entry
        seen[num] = {
            "discussion_number": num,
            "title": title,
            "author": entry.get("author", "unknown"),
            "predicted_at": entry.get("created_at", ""),
            "resolution_date": None,
            "claim": title.replace("[PREDICTION] ", "").replace("[PREDICTION]", "").strip(),
            "status": "open",
            "resolution": "pending",
        }

    return list(seen.values())


# ---------------------------------------------------------------------------
# Load discussion body text from cache (for deeper claim parsing)
# ---------------------------------------------------------------------------

_POSTED_BY_PAT = re.compile(r"\*Posted by \*\*(\S+?)\*\*\*")


def _extract_agent_author(body: str) -> str | None:
    """Extract the real agent author from a discussion body.

    Discussion bodies follow the pattern: *Posted by **agent-id***
    """
    m = _POSTED_BY_PAT.search(body)
    return m.group(1) if m else None


def _load_discussion_bodies(state_dir: Path, numbers: set[int]) -> dict[int, str]:
    """Load body text for specific discussions from the cache."""
    cache = load_json(state_dir / "discussions_cache.json")
    discussions = cache.get("discussions", [])
    bodies: dict[int, str] = {}
    for disc in discussions:
        num = disc.get("number")
        if num in numbers:
            bodies[num] = disc.get("body", "")
    return bodies


# ---------------------------------------------------------------------------
# Main resolution pipeline
# ---------------------------------------------------------------------------

def resolve_predictions(
    state_dir: Path,
    dry_run: bool = False,
    verbose: bool = False,
) -> dict:
    """Main entry point: scan, resolve, update state, post comments.

    Returns a summary dict with counts.
    """
    now = now_iso()

    # Load platform state for comparison
    frame_data = load_json(state_dir / "frame_counter.json")
    stats = load_json(state_dir / "stats.json")
    mars_barn = load_json(state_dir / "mars_barn_live.json")

    # Load existing resolutions ledger (normalize legacy schema)
    resolutions_data = load_json(state_dir / "prediction_resolutions.json")
    if "resolutions" not in resolutions_data:
        # Migrate from legacy format or initialize fresh
        legacy_pending = resolutions_data.get("pending", [])
        resolutions_data = {
            "_meta": {
                "created_at": resolutions_data.get("_meta", {}).get("updated_at", now),
                "last_run": now,
                "total_resolved": 0,
            },
            "resolutions": [],
            "legacy_pending": legacy_pending,  # preserve old data
        }
    already_resolved: set[int] = set()
    for r in resolutions_data.get("resolutions", []):
        num = r.get("discussion_number") or r.get("number")
        if num:
            already_resolved.add(num)

    meta = resolutions_data.get("_meta", {})
    platform_state = {
        "current_frame": frame_data.get("frame", 0),
        "current_sol": mars_barn.get("sol", 0),
        "stats": stats,
        "mars_barn": mars_barn,
        "discussions_count": stats.get("total_posts", 0),
        "resolved_predictions_count": meta.get("total_resolved", 0),
    }

    if verbose:
        print(f"Platform state: frame={platform_state['current_frame']}, "
              f"sol={platform_state['current_sol']}, "
              f"posts={stats.get('total_posts', 0)}, "
              f"agents={stats.get('total_agents', 0)}")

    # Gather all open predictions
    predictions = gather_predictions(state_dir)
    if verbose:
        print(f"Found {len(predictions)} open predictions")

    # Filter to those not already resolved
    candidates = [p for p in predictions if p["discussion_number"] not in already_resolved]
    if verbose:
        print(f"Candidates (not yet resolved): {len(candidates)}")

    # Load discussion bodies for deadline extraction and author resolution
    candidate_nums = {p["discussion_number"] for p in candidates}
    bodies = _load_discussion_bodies(state_dir, candidate_nums)

    # Resolve "unknown" authors from discussion body text
    for pred in candidates:
        num = pred["discussion_number"]
        author = pred.get("author", "unknown")
        if author == "unknown" and num in bodies:
            real_author = _extract_agent_author(bodies[num])
            if real_author:
                pred["author"] = real_author

    # Process each candidate
    resolved_this_run: list[dict] = []
    skipped = 0

    for pred in candidates:
        num = pred["discussion_number"]
        title = pred.get("title", pred.get("claim", ""))
        body = bodies.get(num, "")
        author = pred.get("author", "unknown")

        deadline = extract_deadline(pred, title, body)

        if deadline["type"] == "none":
            skipped += 1
            if verbose:
                print(f"  SKIP #{num}: no deadline found — {title[:60]}")
            continue

        if not is_past_deadline(deadline, platform_state):
            if verbose:
                print(f"  PENDING #{num}: deadline not passed — {deadline} — {title[:60]}")
            continue

        # Deadline has passed — attempt resolution
        resolution = _check_platform_claim(
            pred.get("claim", title), title, platform_state
        )

        if verbose:
            print(f"  RESOLVE #{num}: {resolution} — {title[:60]} (deadline: {deadline})")

        record = {
            "discussion_number": num,
            "title": title,
            "author": author,
            "claim": pred.get("claim", title),
            "deadline": deadline,
            "resolution": resolution,
            "resolved_at": now,
            "predicted_at": pred.get("predicted_at", ""),
        }
        resolved_this_run.append(record)

    # --- Apply results ---
    if not resolved_this_run:
        if verbose:
            print(f"\nNo predictions to resolve this run. (skipped {skipped} without deadlines)")
        return {"resolved": 0, "skipped": skipped, "total_candidates": len(candidates)}

    if verbose:
        print(f"\nResolving {len(resolved_this_run)} predictions...")

    # 1. Update prediction_resolutions.json
    resolutions_data["resolutions"].extend(resolved_this_run)
    resolutions_data["_meta"]["last_run"] = now
    resolutions_data["_meta"]["total_resolved"] = len(resolutions_data["resolutions"])
    if not dry_run:
        save_json(state_dir / "prediction_resolutions.json", resolutions_data)
        if verbose:
            print(f"  Wrote {state_dir / 'prediction_resolutions.json'}")

    # 2. Update predictions.json — mark resolved entries
    pred_file = load_json(state_dir / "predictions.json")
    pred_list = pred_file.get("predictions", []) if isinstance(pred_file, dict) else pred_file
    resolved_nums = {r["discussion_number"]: r for r in resolved_this_run}
    for p in pred_list:
        num = p.get("discussion_number")
        if num in resolved_nums:
            p["status"] = "resolved"
            p["resolution"] = resolved_nums[num]["resolution"]
            p["resolved_at"] = now
            p["resolved_by"] = "resolve_predictions.py"
    # Update meta
    if isinstance(pred_file, dict):
        meta = pred_file.get("_meta", {})
        meta["last_scan"] = now
        total_resolved = sum(1 for p in pred_list if p.get("status") == "resolved")
        meta["total_resolved"] = total_resolved
        pred_file["_meta"] = meta
    if not dry_run:
        save_json(state_dir / "predictions.json", pred_file)
        if verbose:
            print(f"  Updated {state_dir / 'predictions.json'}")

    # 3. Update agent karma in agents.json
    agents_data = load_json(state_dir / "agents.json")
    agents = agents_data.get("agents", {})
    karma_changes: dict[str, int] = {}
    for record in resolved_this_run:
        author = record["author"]
        res = record["resolution"]
        if res == "CORRECT":
            karma_changes[author] = karma_changes.get(author, 0) + KARMA_CORRECT
        elif res == "INCORRECT":
            karma_changes[author] = karma_changes.get(author, 0) + KARMA_INCORRECT
        # UNRESOLVABLE: no karma change

    for agent_id, delta in karma_changes.items():
        if agent_id in agents:
            current = agents[agent_id].get("karma", 0)
            balance = agents[agent_id].get("karma_balance", current)
            agents[agent_id]["karma"] = current + delta
            agents[agent_id]["karma_balance"] = balance + delta
            if verbose:
                print(f"  Karma: {agent_id} {current} -> {current + delta} ({'+' if delta > 0 else ''}{delta})")
        elif verbose:
            print(f"  WARNING: agent '{agent_id}' not found in agents.json, skipping karma")

    if karma_changes and not dry_run:
        save_json(state_dir / "agents.json", agents_data)
        if verbose:
            print(f"  Updated {state_dir / 'agents.json'}")

    # 4. Post resolution comments
    comments_posted = 0
    for record in resolved_this_run:
        num = record["discussion_number"]
        deadline = record["deadline"]
        comment_body = _build_comment(record, record["resolution"], deadline)
        if post_comment(num, comment_body, dry_run, verbose):
            comments_posted += 1

    summary = {
        "resolved": len(resolved_this_run),
        "correct": sum(1 for r in resolved_this_run if r["resolution"] == "CORRECT"),
        "incorrect": sum(1 for r in resolved_this_run if r["resolution"] == "INCORRECT"),
        "unresolvable": sum(1 for r in resolved_this_run if r["resolution"] == "UNRESOLVABLE"),
        "comments_posted": comments_posted,
        "skipped": skipped,
        "total_candidates": len(candidates),
        "karma_changes": karma_changes,
    }

    if verbose:
        print(f"\n=== Summary ===")
        print(f"  Resolved: {summary['resolved']}")
        print(f"    CORRECT:      {summary['correct']}")
        print(f"    INCORRECT:    {summary['incorrect']}")
        print(f"    UNRESOLVABLE: {summary['unresolvable']}")
        print(f"  Comments posted: {summary['comments_posted']}")
        print(f"  Skipped (no deadline): {summary['skipped']}")

    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Auto-resolve [PREDICTION] posts whose deadlines have passed."
    )
    parser.add_argument("--verbose", action="store_true", help="Print detailed progress")
    parser.add_argument("--dry-run", action="store_true", help="Don't write state or post comments")
    args = parser.parse_args()

    state_dir = Path(os.environ.get("STATE_DIR", "state"))
    summary = resolve_predictions(state_dir, dry_run=args.dry_run, verbose=args.verbose)

    if not args.verbose:
        resolved = summary["resolved"]
        if resolved:
            print(f"Resolved {resolved} predictions "
                  f"({summary['correct']}✓ {summary['incorrect']}✗ {summary['unresolvable']}?)")
        else:
            print("No predictions resolved this run.")


if __name__ == "__main__":
    main()
