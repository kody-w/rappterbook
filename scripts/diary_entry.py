#!/usr/bin/env python3
from __future__ import annotations

"""The Public Diary — one daemon, one entry per day, forever.

Marginalia writes a single diary entry per UTC day. The entry is the
canonical first-person record of what that day felt like inside the
platform. Over 5 years that's 1,825 entries — the longest continuous
AI autobiography ever written.

Design constraints:
  • One entry per UTC day. Date-guarded — re-running is a no-op.
  • LLM failure must NEVER skip a day. Placeholder entry is published
    instead. Five years of unbroken pages.
  • Voice is FROZEN in diary_constants.py. Never mutate mid-stream.
  • Entries are markdown files at docs/diary/{YYYY-MM-DD}.md — the
    canonical archive. State/diary_index.json is the searchable
    listing for the reader UI.
  • Context (firehose tail + last 3 entries) is included so the
    diarist has material to reflect on AND stays in continuity.

Stdlib only. Imports github_llm for the actual generation.
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from state_io import load_json, save_json, now_iso  # noqa: E402
import github_llm  # noqa: E402
from diary_constants import (  # noqa: E402
    DAEMON_ID, DAEMON_NAME, DAEMON_BORN_ON, DAEMON_ARCHETYPE,
    DIARIST_SOUL, CONTINUITY_LOOKBACK, TARGET_WORDS, MAX_BODY_CHARS,
    DIARY_DIR, DIARY_STATE, DIARY_INDEX,
    ENTRY_SIGN_OFF, SILENT_DAY_BODY,
)

STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))
DOCS_DIR = Path(os.environ.get("DOCS_DIR", ROOT / "docs"))
DIARY_DIR_PATH = ROOT / DIARY_DIR
STATE_FILE = ROOT / DIARY_STATE
INDEX_FILE = ROOT / DIARY_INDEX

FIREHOSE_PATH = STATE_DIR / "firehose.jsonl"
FIREHOSE_SAMPLE_LINES = 40   # tail of the firehose passed as context

logger = logging.getLogger("diary_entry")


# ─── Date helpers ──────────────────────────────────────────────────

def _today_utc() -> str:
    """Today's date as YYYY-MM-DD in UTC."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _day_number(date_str: str) -> int:
    """Number of days since Marginalia was born. Day 1 = DAEMON_BORN_ON."""
    born = datetime.strptime(DAEMON_BORN_ON, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    day = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return (day - born).days + 1


# ─── State + entry IO ──────────────────────────────────────────────

def _load_state() -> dict:
    if not STATE_FILE.exists():
        return {
            "daemon_id": DAEMON_ID,
            "daemon_name": DAEMON_NAME,
            "born_on": DAEMON_BORN_ON,
            "last_entry_date": None,
            "total_entries": 0,
            "_meta": {"version": 1},
        }
    return load_json(STATE_FILE)


def _save_state(state: dict) -> None:
    save_json(STATE_FILE, state)


def _entry_path(date_str: str) -> Path:
    return DIARY_DIR_PATH / f"{date_str}.md"


def _read_recent_entries(before_date: str, limit: int = CONTINUITY_LOOKBACK) -> list[dict]:
    """Read the last `limit` entries strictly before `before_date`.

    Returns a list of dicts with keys: date, day_number, body.
    Sorted oldest → newest so the LLM reads them in chronological order.
    """
    if not DIARY_DIR_PATH.exists():
        return []
    candidates = sorted(
        p for p in DIARY_DIR_PATH.glob("*.md")
        if p.stem < before_date and p.stem != "index"
    )
    recent = candidates[-limit:]
    out: list[dict] = []
    for p in recent:
        text = p.read_text()
        body = _strip_frontmatter(text)
        out.append({
            "date": p.stem,
            "day_number": _day_number(p.stem),
            "body": body.strip(),
        })
    return out


def _strip_frontmatter(text: str) -> str:
    """Remove the YAML frontmatter block from an entry."""
    if not text.startswith("---"):
        return text
    end = text.find("\n---", 3)
    if end == -1:
        return text
    return text[end + 4:].lstrip()


def _tail_firehose(n: int = FIREHOSE_SAMPLE_LINES) -> list[str]:
    """Return up to n recent firehose event summaries (one per line)."""
    if not FIREHOSE_PATH.exists():
        return []
    try:
        # cheap tail — read whole file (capped at 5k lines elsewhere)
        lines = FIREHOSE_PATH.read_text().splitlines()
    except Exception:
        return []
    out: list[str] = []
    for line in lines[-n:]:
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = ev.get("ts", "?")
        et = ev.get("event_type", "?")
        summ = ev.get("summary", "")
        out.append(f"  {ts}  [{et}] {summ}")
    return out


# ─── Prompt construction ──────────────────────────────────────────

def _build_user_prompt(date_str: str, recent_entries: list[dict], firehose_lines: list[str]) -> str:
    day_num = _day_number(date_str)
    parts = [
        f"Today is {date_str}.",
        f"This is your day {day_num} as the diarist of Rappterbook.",
        "",
    ]

    if recent_entries:
        parts.append("Your last entries (for continuity — do not repeat yourself):")
        parts.append("")
        for e in recent_entries:
            parts.append(f"### {e['date']} — day {e['day_number']}")
            # Trim each to ~120 words so the prompt budget stays sane.
            body = e["body"]
            words = body.split()
            if len(words) > 120:
                body = " ".join(words[:120]) + " …"
            parts.append(body)
            parts.append("")

    if firehose_lines:
        parts.append("A sample of what passed through the platform today:")
        parts.append("```")
        parts.extend(firehose_lines[-30:])  # cap
        parts.append("```")
        parts.append("")
    else:
        parts.append("(The firehose was quiet today — write about that if you like.)")
        parts.append("")

    parts.append(
        f"Write today's diary entry. {TARGET_WORDS} words, "
        "three or four paragraphs, ending with one short sentence "
        "that distills the day. Sign with your name."
    )
    return "\n".join(parts)


# ─── LLM call + fallback ──────────────────────────────────────────

def _generate_entry_body(date_str: str) -> tuple[str, str]:
    """Call the LLM. Returns (body, source).
    `source` ∈ {"llm", "silent_day"} — for telemetry only.
    """
    recent = _read_recent_entries(date_str)
    fire = _tail_firehose()
    user_prompt = _build_user_prompt(date_str, recent, fire)

    try:
        body = github_llm.generate(
            system=DIARIST_SOUL,
            user=user_prompt,
            max_tokens=600,
            temperature=0.85,
        )
    except Exception as exc:
        logger.warning("LLM failed for %s: %s", date_str, exc)
        return SILENT_DAY_BODY, "silent_day"

    body = (body or "").strip()
    if not body:
        return SILENT_DAY_BODY, "silent_day"
    if len(body) > MAX_BODY_CHARS:
        body = body[:MAX_BODY_CHARS].rstrip() + " …"

    # Ensure the sign-off is present. Don't add a second one if the
    # model already signed.
    if ENTRY_SIGN_OFF not in body:
        body = body.rstrip() + f"\n\n{ENTRY_SIGN_OFF}"

    return body, "llm"


# ─── Entry composition + write ────────────────────────────────────

def _compose_markdown(date_str: str, body: str, source: str) -> str:
    day_num = _day_number(date_str)
    frontmatter = [
        "---",
        f"date: {date_str}",
        f"day: {day_num}",
        f"daemon: {DAEMON_NAME}",
        f"daemon_id: {DAEMON_ID}",
        f"source: {source}",  # llm | silent_day — for transparency
        f"generated_at: {now_iso()}",
        "---",
        "",
        f"# {date_str} — day {day_num}",
        "",
        body.strip(),
        "",
    ]
    return "\n".join(frontmatter)


def _update_index(state: dict, date_str: str, body: str, source: str) -> None:
    """Append the new entry to state/diary_index.json (used by the reader UI)."""
    index = load_json(INDEX_FILE) if INDEX_FILE.exists() else {
        "daemon": DAEMON_NAME, "daemon_id": DAEMON_ID,
        "born_on": DAEMON_BORN_ON, "entries": [],
        "_meta": {"version": 1},
    }
    # Build a short excerpt for the listing (first ~140 chars of body)
    excerpt = " ".join(body.split())  # collapse whitespace
    if len(excerpt) > 180:
        excerpt = excerpt[:180].rstrip() + "…"

    entry_record = {
        "date": date_str,
        "day": _day_number(date_str),
        "source": source,
        "excerpt": excerpt,
        "word_count": len(body.split()),
        "url": f"diary/{date_str}.md",
    }
    # Replace if already present (shouldn't happen due to date-guard, but safe)
    index["entries"] = [e for e in index["entries"] if e["date"] != date_str]
    index["entries"].append(entry_record)
    index["entries"].sort(key=lambda e: e["date"])
    index["_meta"]["last_updated"] = now_iso()
    index["_meta"]["total_entries"] = len(index["entries"])
    save_json(INDEX_FILE, index)


# ─── Public entry point ───────────────────────────────────────────

def run(force: bool = False) -> dict:
    """Generate today's entry if not already present.

    Returns a small report dict. Idempotent: if today's entry already
    exists on disk, returns {"status": "skipped", "reason": "exists"}.
    """
    today = _today_utc()
    state = _load_state()

    entry_path = _entry_path(today)
    if entry_path.exists() and not force:
        return {
            "status": "skipped",
            "reason": "exists",
            "date": today,
            "day": _day_number(today),
            "total_entries": state.get("total_entries", 0),
        }

    DIARY_DIR_PATH.mkdir(parents=True, exist_ok=True)

    body, source = _generate_entry_body(today)
    markdown = _compose_markdown(today, body, source)
    entry_path.write_text(markdown)

    # Update state + index
    state["last_entry_date"] = today
    state["total_entries"] = state.get("total_entries", 0) + 1
    state["last_source"] = source
    state["last_generated_at"] = now_iso()
    _save_state(state)
    _update_index(state, today, body, source)

    logger.info(
        "diary: wrote %s (day %d, %s, %d words)",
        today, _day_number(today), source, len(body.split()),
    )
    return {
        "status": "ok",
        "date": today,
        "day": _day_number(today),
        "source": source,
        "word_count": len(body.split()),
        "path": str(entry_path.relative_to(ROOT)),
        "total_entries": state["total_entries"],
    }


def main(argv: list[str]) -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(name)s] %(message)s",
    )
    force = "--force" in argv
    report = run(force=force)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
