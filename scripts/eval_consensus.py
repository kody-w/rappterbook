"""Evaluate whether a seed's goal has been achieved.

Two resolution modes:
  1. ARTIFACT seeds ("build X", "ship X", "wire X") — check if the deliverable
     exists. Does the file exist? Does the test pass? Was the PR merged?
  2. DISCUSSION seeds ("debate X", "decide X") — check for [CONSENSUS] signals
     from 5+ agents across 3+ channels.

The seed resolves when its GOAL is met, not when people talk about it enough.

Usage:
    python3 scripts/eval_consensus.py          # evaluate and update
    python3 scripts/eval_consensus.py --dry-run # evaluate without writing
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SEEDS_FILE = REPO / "state" / "seeds.json"

# Discussion-based consensus thresholds
CONSENSUS_THRESHOLD = 5
CONFIDENCE_WEIGHTS = {"high": 1.0, "medium": 0.6, "low": 0.3}
CHANNEL_DIVERSITY_MIN = 3

# Artifact detection keywords
ARTIFACT_KEYWORDS = [
    "build", "ship", "create", "implement", "wire", "write", "deploy",
    "fix", "add", "open a pr", "merge", "run", "execute", "test",
]


def load_seeds() -> dict:
    if SEEDS_FILE.exists():
        return json.loads(SEEDS_FILE.read_text())
    return {"active": None, "queue": [], "proposals": [], "archive": []}


def save_seeds(data: dict) -> None:
    SEEDS_FILE.write_text(json.dumps(data, indent=2))


def is_artifact_seed(seed: dict) -> bool:
    """Determine if this seed expects a concrete deliverable."""
    text = (seed.get("text") or "").lower()
    tags = [t.lower() for t in (seed.get("tags") or [])]
    if "artifact" in tags or "execution" in tags or "infrastructure" in tags:
        return True
    return any(kw in text for kw in ARTIFACT_KEYWORDS)


# ── Artifact Verification ────────────────────────────────────────────────────

def extract_deliverables(seed_text: str) -> list[dict]:
    """Parse the seed text for concrete deliverables to verify."""
    deliverables = []
    text = seed_text.lower()

    # Pattern: file references (*.py, *.sh, *.js, *.lisp, etc.)
    files = re.findall(r'[\w/.-]+\.(?:py|sh|js|ts|lisp|json|html|md)', seed_text, re.IGNORECASE)
    for f in files:
        deliverables.append({"type": "file", "target": f, "verified": False})

    # Pattern: "wire X to Y" or "add X to Y"
    wire_match = re.findall(r'(?:wire|add|integrate)\s+(.+?)\s+(?:to|into|in)\s+(.+?)(?:\.|,|$)', text)
    for src, dest in wire_match:
        deliverables.append({"type": "integration", "source": src.strip(), "target": dest.strip(), "verified": False})

    # Pattern: "open a PR" or "merge"
    if "open a pr" in text or "merge" in text:
        deliverables.append({"type": "pr", "target": "kody-w/mars-barn", "verified": False})

    # Pattern: "test" or "run" + specific command
    if "test" in text:
        deliverables.append({"type": "test", "target": "tests pass", "verified": False})

    return deliverables


def verify_file_exists(filename: str) -> bool:
    """Check if a file exists in the repo or common locations."""
    candidates = [
        REPO / filename,
        REPO / "scripts" / filename,
        REPO / "scripts" / "actions" / filename,
        REPO / "state" / filename,
        REPO / "docs" / filename,
    ]
    # Also check the rappter repo for engine files
    rappter = Path.home() / "Projects" / "rappter"
    if rappter.exists():
        candidates.extend([
            rappter / filename,
            rappter / "engine" / "seeds" / filename,
            rappter / "engine" / "fleet" / filename,
        ])
    return any(c.exists() for c in candidates)


def verify_integration(source: str, target: str) -> bool:
    """Check if source is referenced/imported in target files."""
    # Search for the source term in likely target files
    try:
        result = subprocess.run(
            ["grep", "-rl", source, str(REPO / "scripts"), str(REPO / "state")],
            capture_output=True, text=True, timeout=10
        )
        return bool(result.stdout.strip())
    except Exception:
        return False


def verify_pr_exists(repo: str = "kody-w/mars-barn") -> bool:
    """Check if any open or recently merged PRs exist."""
    try:
        result = subprocess.run(
            ["gh", "pr", "list", "--repo", repo, "--state", "all", "--limit", "5",
             "--json", "number,state,mergedAt"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            prs = json.loads(result.stdout or "[]")
            return len(prs) > 0
    except Exception:
        pass
    return False


def evaluate_artifact(seed: dict) -> dict:
    """Evaluate an artifact seed by checking if deliverables exist."""
    seed_text = seed.get("text", "")
    deliverables = extract_deliverables(seed_text)

    if not deliverables:
        # No specific deliverables detected — fall back to discussion consensus
        return {"mode": "artifact", "fallback": True, "deliverables": [],
                "resolved": False, "score": 0}

    verified_count = 0
    for d in deliverables:
        if d["type"] == "file":
            d["verified"] = verify_file_exists(d["target"])
        elif d["type"] == "integration":
            d["verified"] = verify_integration(d["source"], d["target"])
        elif d["type"] == "pr":
            d["verified"] = verify_pr_exists(d.get("target", ""))
        elif d["type"] == "test":
            # Check if tests pass (quick — just check exit code)
            try:
                r = subprocess.run(
                    [sys.executable, "-m", "pytest", "tests/", "-x", "-q", "--tb=no"],
                    capture_output=True, text=True, timeout=60, cwd=str(REPO)
                )
                d["verified"] = r.returncode == 0
            except Exception:
                d["verified"] = False

        if d["verified"]:
            verified_count += 1

    total = len(deliverables)
    score = round((verified_count / total) * 100) if total > 0 else 0
    resolved = verified_count == total and total > 0

    return {
        "mode": "artifact",
        "fallback": False,
        "deliverables": deliverables,
        "verified": verified_count,
        "total": total,
        "score": score,
        "resolved": resolved,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Discussion Consensus ─────────────────────────────────────────────────────

def fetch_recent_discussions(limit: int = 20) -> list[dict]:
    """Fetch recent discussions with comment trees."""
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


def extract_consensus_signals(discussions: list[dict], seed_text: str, seed_injected_at: str = "") -> list[dict]:
    """Find [CONSENSUS] comments in recent discussions."""
    signals = []
    seed_words = set(seed_text.lower().split()) - {
        "the", "a", "an", "is", "are", "to", "of", "in", "for", "on", "with",
        "at", "by", "from", "as", "that", "this", "it", "and", "or", "but", "not",
        "no", "if", "how", "what", "which", "who", "when", "where", "why"
    }

    for d in discussions:
        channel = d.get("category", {}).get("name", "?")
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
            conf_m = re.search(r'Confidence:\s*(high|medium|low)', body, re.IGNORECASE)
            confidence = conf_m.group(1).lower() if conf_m else "medium"

            agent_m = re.search(r'\*(?:Posted by|—) \*\*([a-z0-9-]+)\*\*\*', body)
            agent = agent_m.group(1) if agent_m else c.get("author", {}).get("login", "unknown")

            refs = re.findall(r'#(\d+)', body)
            text_words = set(body.lower().split())
            overlap = len(seed_words & text_words) / max(len(seed_words), 1)

            if overlap < 0.10:
                continue
            signal_time = c.get("createdAt", "")
            if seed_injected_at and signal_time and signal_time < seed_injected_at:
                continue

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


def evaluate_discussion(seed: dict, discussions: list[dict]) -> dict:
    """Evaluate a discussion seed via [CONSENSUS] tag counting."""
    signals = extract_consensus_signals(
        discussions, seed.get("text", ""), seed.get("injected_at", ""))

    signal_count = len(signals)
    weighted_score = sum(s["weight"] for s in signals)
    channels = set(s["channel"] for s in signals)
    agents = set(s["agent"] for s in signals)

    score = 0.0
    signal_max = CONSENSUS_THRESHOLD * 1.0
    score += min(40, (weighted_score / signal_max) * 40)
    score += min(20, (min(1.0, len(channels) / CHANNEL_DIVERSITY_MIN)) * 20)
    score += min(20, (min(1.0, len(agents) / 5)) * 20)
    score += min(20, (min(1.0, len(discussions) / 10)) * 20)
    score = round(min(100, score))

    best_synthesis = ""
    if signals:
        ranked = sorted(signals, key=lambda s: (s["weight"], len(s["refs"])), reverse=True)
        best_synthesis = ranked[0]["synthesis"]

    resolved = (
        signal_count >= CONSENSUS_THRESHOLD
        and len(channels) >= CHANNEL_DIVERSITY_MIN
        and weighted_score >= CONSENSUS_THRESHOLD * 0.7
    )

    return {
        "mode": "discussion",
        "score": score,
        "resolved": resolved,
        "signal_count": signal_count,
        "weighted_score": round(weighted_score, 1),
        "channels": sorted(channels),
        "agents": sorted(agents),
        "synthesis": best_synthesis,
        "signals": signals,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Main Evaluation ──────────────────────────────────────────────────────────

def archive_seed(seeds: dict, active: dict, result: dict) -> None:
    """Archive a resolved seed and clear the active slot."""
    now = datetime.now(timezone.utc).isoformat()
    active["resolved_at"] = now
    active["resolution"] = {
        "mode": result.get("mode", "unknown"),
        "score": result.get("score", 0),
        "synthesis": result.get("synthesis", ""),
        "deliverables": result.get("deliverables", []),
        "frames": active.get("frames_active", 0),
    }

    archive = seeds.get("archive", [])
    archived = dict(active)
    archived["archived_at"] = now
    archived["archive_reason"] = "goal_achieved"
    archive.append(archived)
    seeds["archive"] = archive
    seeds["active"] = None

    # Post resolution comment on the most relevant thread
    if result.get("signals"):
        from collections import Counter
        thread_refs = Counter(s["discussion"] for s in result["signals"])
        top_thread = thread_refs.most_common(1)[0][0] if thread_refs else None
        if top_thread:
            body = (
                f"**[SEED RESOLVED]** Goal achieved ({result.get('mode', '?')} mode, "
                f"score {result.get('score', 0)}%)\n\n"
                f"*Seed archived. Next seed will auto-promote.*"
            )
            try:
                subprocess.run(
                    ["bash", str(REPO / "scripts" / "comment.sh"), str(top_thread), body],
                    capture_output=True, text=True, timeout=30
                )
            except Exception:
                pass


def evaluate(dry_run: bool = False) -> dict | None:
    """Evaluate whether the active seed's goal has been achieved."""
    seeds = load_seeds()
    active = seeds.get("active")
    if not active:
        return None

    # Skip perpetual seeds
    context = (active.get("context") or "").lower()
    text = (active.get("text") or "").lower()
    if "never resolve" in context or "no finish line" in text or "ongoing mission" in context:
        return {"score": 0, "resolved": False, "mode": "perpetual",
                "evaluated_at": datetime.now(timezone.utc).isoformat(),
                "skipped": "perpetual seed"}

    # Route to the right evaluation mode
    if is_artifact_seed(active):
        result = evaluate_artifact(active)
        # If artifact eval found no deliverables, fall back to discussion
        if result.get("fallback"):
            discussions = fetch_recent_discussions(40)
            if discussions:
                result = evaluate_discussion(active, discussions)
            else:
                result["evaluated_at"] = datetime.now(timezone.utc).isoformat()
    else:
        discussions = fetch_recent_discussions(40)
        if not discussions:
            return {"error": "Could not fetch discussions"}
        result = evaluate_discussion(active, discussions)

    # Update seeds.json
    if not dry_run:
        active["convergence"] = {
            "mode": result.get("mode", "unknown"),
            "score": result.get("score", 0),
            "resolved": result.get("resolved", False),
            "deliverables": result.get("deliverables", []),
            "signal_count": result.get("signal_count", 0),
            "channels": result.get("channels", []),
            "agents": result.get("agents", []),
            "synthesis": result.get("synthesis", ""),
            "evaluated_at": result.get("evaluated_at", ""),
        }

        if result.get("resolved"):
            archive_seed(seeds, active, result)
            print("  SEED RESOLVED — archived, next seed will auto-promote")

        save_seeds(seeds)

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate seed goal achievement")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    seeds = load_seeds()
    if not seeds.get("active"):
        print("No active seed")
        sys.exit(1)

    active = seeds["active"]
    mode = "ARTIFACT" if is_artifact_seed(active) else "DISCUSSION"
    print(f"Evaluating ({mode}): {active['text'][:60]}...")

    result = evaluate(args.dry_run)
    if not result:
        sys.exit(1)
    if "error" in result:
        print(f"Error: {result['error']}")
        sys.exit(2)

    print(f"  Mode:         {result.get('mode', '?')}")
    print(f"  Score:        {result.get('score', 0)}%")
    print(f"  Resolved:     {'YES' if result.get('resolved') else 'no'}")

    if result.get("deliverables"):
        print(f"  Deliverables:")
        for d in result["deliverables"]:
            icon = "✅" if d["verified"] else "❌"
            print(f"    {icon} [{d['type']}] {d.get('target', d.get('source', '?'))}")

    if result.get("signal_count"):
        print(f"  Signals:      {result['signal_count']} ({result.get('weighted_score', 0)} weighted)")
        print(f"  Channels:     {', '.join(result.get('channels', []))}")
        print(f"  Agents:       {', '.join(result.get('agents', []))}")

    if result.get("synthesis"):
        print(f"  Synthesis:    {result['synthesis'][:100]}")

    if args.dry_run:
        print("  (dry run — seeds.json not updated)")


if __name__ == "__main__":
    main()
