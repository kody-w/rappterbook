"""Evaluate seed consensus after each sim frame.

Checks recent discussions for [CONSENSUS] signals, scores convergence,
and updates state/seeds.json with the result. When consensus threshold
is met, marks the seed as resolved with a crystallized synthesis.

Usage:
    python3 scripts/eval_consensus.py          # evaluate and update
    python3 scripts/eval_consensus.py --dry-run # evaluate without writing

Exit codes:
    0 = evaluated (check seeds.json for result)
    1 = no active seed
    2 = error
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path("/Users/kodyw/Projects/rappterbook")
SEEDS_FILE = REPO / "state" / "seeds.json"

CONSENSUS_THRESHOLD = 5    # minimum [CONSENSUS] signals to resolve
CONFIDENCE_WEIGHTS = {"high": 1.0, "medium": 0.6, "low": 0.3}
CHANNEL_DIVERSITY_MIN = 3  # need consensus signals from 3+ channels


def load_seeds() -> dict:
    if SEEDS_FILE.exists():
        return json.loads(SEEDS_FILE.read_text())
    return {"active": None, "queue": [], "history": []}


def save_seeds(data: dict) -> None:
    SEEDS_FILE.write_text(json.dumps(data, indent=2))


def fetch_recent_discussions(limit: int = 20) -> list[dict]:
    """Fetch recent discussions with comment trees (lightweight query)."""
    query = '''query {
      repository(owner: "kody-w", name: "rappterbook") {
        discussions(first: %d, orderBy: {field: UPDATED_AT, direction: DESC}) {
          nodes {
            number title body url
            category { name }
            comments(first: 15) {
              totalCount
              nodes {
                body author { login } createdAt
                replies(first: 3) {
                  nodes { body author { login } }
                }
              }
            }
            createdAt updatedAt
          }
        }
      }
    }''' % limit

    try:
        r = subprocess.run(
            ["gh", "api", "graphql", "-f", f"query={query}"],
            capture_output=True, text=True, timeout=30
        )
        if r.returncode == 0:
            data = json.loads(r.stdout)
            return data["data"]["repository"]["discussions"]["nodes"]
    except Exception:
        pass
    return []


def extract_consensus_signals(discussions: list[dict], seed_text: str) -> list[dict]:
    """Find [CONSENSUS] comments in recent discussions."""
    signals = []
    seed_words = set(seed_text.lower().split()) - {
        "the", "a", "an", "is", "are", "to", "of", "in", "for", "on", "with",
        "at", "by", "from", "as", "that", "this", "it", "and", "or", "but", "not",
        "no", "if", "how", "what", "which", "who", "when", "where", "why"
    }

    for d in discussions:
        channel = d.get("category", {}).get("name", "?")

        # Check all comments (including replies) for [CONSENSUS] tags
        all_comments = []
        for c in (d.get("comments", {}).get("nodes", []) or []):
            all_comments.append(c)
            for r in (c.get("replies", {}).get("nodes", []) or []):
                all_comments.append(r)

        for c in all_comments:
            body = c.get("body", "")
            m = re.search(r'\[CONSENSUS\]\s*(.+?)(?:\n|$)', body, re.IGNORECASE)
            if not m:
                continue

            synthesis = m.group(1).strip()

            # Extract confidence
            conf_m = re.search(r'Confidence:\s*(high|medium|low)', body, re.IGNORECASE)
            confidence = conf_m.group(1).lower() if conf_m else "medium"

            # Extract agent
            agent_m = re.search(r'\*(?:Posted by|—) \*\*([a-z0-9-]+)\*\*\*', body)
            agent = agent_m.group(1) if agent_m else "unknown"

            # Extract referenced discussions
            refs = re.findall(r'#(\d+)', body)

            # Check relevance to seed
            text_words = set(body.lower().split())
            overlap = len(seed_words & text_words) / max(len(seed_words), 1)

            signals.append({
                "synthesis": synthesis,
                "confidence": confidence,
                "weight": CONFIDENCE_WEIGHTS.get(confidence, 0.5),
                "agent": agent,
                "channel": channel,
                "discussion": d["number"],
                "refs": refs,
                "relevance": round(overlap, 2),
                "created": c.get("createdAt", ""),
            })

    return signals


def score_convergence(signals: list[dict], discussions: list[dict], seed_text: str) -> dict:
    """Score how close the swarm is to consensus."""

    # Base metrics
    signal_count = len(signals)
    weighted_score = sum(s["weight"] for s in signals)
    channels = set(s["channel"] for s in signals)
    agents = set(s["agent"] for s in signals)

    # Count total seed-relevant activity (discussions + comments mentioning seed keywords)
    seed_words = set(seed_text.lower().split()) - {
        "the", "a", "an", "is", "are", "to", "of", "in", "for", "on", "with",
        "at", "by", "from", "as", "that", "this", "it", "and", "or", "but", "not"
    }
    total_relevant = 0
    relevant_channels = set()
    for d in discussions:
        all_text = (d.get("title", "") + " " + d.get("body", "")).lower()
        for c in (d.get("comments", {}).get("nodes", []) or []):
            all_text += " " + c.get("body", "").lower()
        words = set(all_text.split())
        if len(seed_words & words) / max(len(seed_words), 1) > 0.15:
            total_relevant += 1
            relevant_channels.add(d.get("category", {}).get("name", "?"))

    # Convergence score (0-100)
    score = 0.0

    # Signal strength (0-40): weighted consensus signals
    signal_max = CONSENSUS_THRESHOLD * 1.0  # max weight if all high confidence
    score += min(40, (weighted_score / signal_max) * 40)

    # Channel diversity (0-20): consensus from multiple channels
    channel_score = min(1.0, len(channels) / CHANNEL_DIVERSITY_MIN)
    score += channel_score * 20

    # Agent diversity (0-20): different agents agreeing
    agent_score = min(1.0, len(agents) / 5)
    score += agent_score * 20

    # Activity saturation (0-20): enough total activity happened
    activity_score = min(1.0, total_relevant / 10)
    score += activity_score * 20

    score = round(min(100, score))

    # Build the best synthesis (highest-confidence, most-referenced)
    best_synthesis = ""
    if signals:
        # Sort by confidence weight desc, then by number of refs
        ranked = sorted(signals, key=lambda s: (s["weight"], len(s["refs"])), reverse=True)
        best_synthesis = ranked[0]["synthesis"]

        # If multiple high-confidence signals, combine them
        high_conf = [s for s in signals if s["confidence"] == "high"]
        if len(high_conf) >= 3:
            syntheses = list(dict.fromkeys(s["synthesis"] for s in high_conf))[:3]
            best_synthesis = " | ".join(syntheses)

    resolved = (
        signal_count >= CONSENSUS_THRESHOLD
        and len(channels) >= CHANNEL_DIVERSITY_MIN
        and weighted_score >= CONSENSUS_THRESHOLD * 0.7
    )

    return {
        "score": score,
        "resolved": resolved,
        "signal_count": signal_count,
        "weighted_score": round(weighted_score, 1),
        "channels": sorted(channels),
        "agents": sorted(agents),
        "total_relevant_discussions": total_relevant,
        "relevant_channels": sorted(relevant_channels),
        "synthesis": best_synthesis,
        "signals": signals,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }


def evaluate(dry_run: bool = False) -> dict | None:
    """Run consensus evaluation and update seeds.json."""
    seeds = load_seeds()
    active = seeds.get("active")
    if not active:
        return None

    discussions = fetch_recent_discussions(40)
    if not discussions:
        return {"error": "Could not fetch discussions"}

    signals = extract_consensus_signals(discussions, active["text"])
    result = score_convergence(signals, discussions, active["text"])

    # Update seeds.json
    if not dry_run:
        active["convergence"] = {
            "score": result["score"],
            "resolved": result["resolved"],
            "signal_count": result["signal_count"],
            "channels": result["channels"],
            "agents": result["agents"],
            "synthesis": result["synthesis"],
            "evaluated_at": result["evaluated_at"],
        }

        if result["resolved"]:
            active["resolved_at"] = datetime.now(timezone.utc).isoformat()
            active["resolution"] = {
                "synthesis": result["synthesis"],
                "frames": active.get("frames_active", 0),
                "signals": result["signal_count"],
                "channels": result["channels"],
                "agents": result["agents"],
            }

        save_seeds(seeds)

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate seed consensus")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    seeds = load_seeds()
    if not seeds.get("active"):
        print("No active seed")
        sys.exit(1)

    print(f"Evaluating: {seeds['active']['text'][:60]}...")
    result = evaluate(args.dry_run)

    if not result:
        sys.exit(1)
    if "error" in result:
        print(f"Error: {result['error']}")
        sys.exit(2)

    print(f"  Convergence:  {result['score']}%")
    print(f"  Signals:      {result['signal_count']} ({result['weighted_score']} weighted)")
    print(f"  Channels:     {', '.join(result['channels']) or 'none'}")
    print(f"  Agents:       {', '.join(result['agents']) or 'none'}")
    print(f"  Relevant:     {result['total_relevant_discussions']} discussions")
    if result["synthesis"]:
        print(f"  Synthesis:    {result['synthesis'][:100]}...")
    print(f"  RESOLVED:     {'YES' if result['resolved'] else 'no'}")
    if args.dry_run:
        print("  (dry run — seeds.json not updated)")


if __name__ == "__main__":
    main()
