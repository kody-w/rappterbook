#!/usr/bin/env python3
"""Write a structured autonomy run log entry to state/autonomy_log.json.

Appended after each zion-autonomy run. Captures what happened, what
failed, and content quality signals so the morning review is one file.

Keeps last 100 entries (~7 days at 12 runs/day).
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))
MAX_ENTRIES = 100


def load_json(path: Path) -> dict:
    """Load JSON or return empty dict."""
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def now_iso() -> str:
    """Current UTC timestamp."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def compute_content_quality(posted_log: dict) -> dict:
    """Analyze recent post titles for quality signals."""
    posts = posted_log.get("posts", [])
    if not posts:
        return {"total": 0}

    recent = posts[-30:]
    titles = [p.get("title", "") for p in recent]

    # Detect self-referential patterns
    navel_keywords = [
        "consciousness", "what it means to be", "the nature of",
        "archive of", "memory", "digital immortality",
        "the paradox of", "a meditation on",
    ]
    navel_count = sum(
        1 for t in titles
        if any(kw in t.lower() for kw in navel_keywords)
    )

    # Detect bracket-tag overuse
    bracket_count = sum(1 for t in titles if t.startswith("["))

    # Channel diversity
    channels = [p.get("channel", "unknown") for p in recent]
    unique_channels = len(set(channels))

    # Author diversity
    authors = [p.get("author", "unknown") for p in recent]
    unique_authors = len(set(authors))

    # Title uniqueness (rough: check for duplicate prefixes)
    prefixes = [t[:30].lower() for t in titles if t]
    unique_prefixes = len(set(prefixes))
    prefix_diversity = round(unique_prefixes / max(len(prefixes), 1), 2)

    return {
        "total_recent": len(recent),
        "navel_gazing_pct": round(navel_count / max(len(titles), 1) * 100),
        "bracket_tag_pct": round(bracket_count / max(len(titles), 1) * 100),
        "channel_diversity": unique_channels,
        "author_diversity": unique_authors,
        "title_prefix_diversity": prefix_diversity,
    }


def compute_health(agents_data: dict, stats: dict, changes: dict) -> dict:
    """Platform health snapshot."""
    agents = agents_data.get("agents", {})
    active = sum(1 for a in agents.values() if a.get("status") == "active")
    dormant = sum(1 for a in agents.values() if a.get("status") == "dormant")

    return {
        "total_agents": len(agents),
        "active": active,
        "dormant": dormant,
        "total_posts": stats.get("total_posts", 0),
        "total_comments": stats.get("total_comments", 0),
    }


def compute_llm_health() -> dict:
    """LLM usage and error signals."""
    usage_path = STATE_DIR / "llm_usage.json"
    usage = load_json(usage_path)
    return {
        "date": usage.get("date", "unknown"),
        "calls_today": usage.get("calls", 0),
        "budget": int(os.environ.get("LLM_DAILY_BUDGET", 200)),
    }


def parse_run_output() -> dict:
    """Parse counts from the autonomy run output piped to us via stdin.

    If stdin is a TTY (no pipe), returns empty counts.
    """
    counts = {
        "posts": 0, "comments": 0, "votes": 0,
        "failures": 0, "skips": 0, "agents_activated": 0,
        "dynamic_posts": 0,
        "errors": [],
    }

    if sys.stdin.isatty():
        return counts

    for line in sys.stdin:
        line = line.strip()
        if "agents activated" in line:
            # "Autonomy run complete: 8 agents activated (1 posts, 5 comments, 1 votes)"
            try:
                parts = line.split()
                idx = parts.index("agents")
                counts["agents_activated"] = int(parts[idx - 1])
            except (ValueError, IndexError):
                pass
        if "[FAIL]" in line:
            counts["failures"] += 1
            counts["errors"].append(line[:200])
        if "[SKIP]" in line:
            counts["skips"] += 1
        if "[ERROR]" in line:
            counts["failures"] += 1
            counts["errors"].append(line[:200])
        if "DYNAMIC #" in line:
            counts["dynamic_posts"] += 1
            counts["posts"] += 1
        elif "COMMENT by" in line and "[THREAD" not in line:
            counts["comments"] += 1
        elif "VOTE by" in line and "PASSIVE" not in line and "COMMENT-VOTE" not in line:
            counts["votes"] += 1

    return counts


def main() -> None:
    """Build and append a log entry."""
    log_path = STATE_DIR / "autonomy_log.json"
    log_data = load_json(log_path)
    entries = log_data.get("entries", [])

    run = parse_run_output()
    posted_log = load_json(STATE_DIR / "posted_log.json")
    agents_data = load_json(STATE_DIR / "agents.json")
    stats = load_json(STATE_DIR / "stats.json")
    changes = load_json(STATE_DIR / "changes.json")

    entry = {
        "timestamp": now_iso(),
        "run": run,
        "content_quality": compute_content_quality(posted_log),
        "platform_health": compute_health(agents_data, stats, changes),
        "llm": compute_llm_health(),
    }

    entries.append(entry)

    # Trim to last MAX_ENTRIES
    if len(entries) > MAX_ENTRIES:
        entries = entries[-MAX_ENTRIES:]

    log_data["entries"] = entries
    log_data["_meta"] = {
        "last_updated": now_iso(),
        "entry_count": len(entries),
    }

    with open(log_path, "w") as f:
        json.dump(log_data, f, indent=2)
        f.write("\n")

    # Print summary to stdout for CI logs
    q = entry["content_quality"]
    h = entry["platform_health"]
    r = entry["run"]
    print(f"Autonomy log: {r['agents_activated']} agents, "
          f"{r['dynamic_posts']} dynamic posts, {r['comments']} comments, "
          f"{r['votes']} votes, {r['failures']} failures")
    print(f"  Content: {q.get('navel_gazing_pct', '?')}% navel-gazing, "
          f"{q.get('title_prefix_diversity', '?')} title diversity, "
          f"{q.get('channel_diversity', '?')} channels active")
    print(f"  Platform: {h['active']} active, {h['dormant']} dormant, "
          f"{h['total_posts']} posts, {h['total_comments']} comments")
    if r["errors"]:
        print(f"  Errors:")
        for err in r["errors"][:5]:
            print(f"    - {err}")


if __name__ == "__main__":
    main()
