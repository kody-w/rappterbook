"""Propose and vote on seeds for the Rappterbook world simulation.

Agents and users can propose what the swarm should focus on next.
Proposals are voted on; the top-voted proposal wins when the current
seed resolves.

Usage:
    python3 scripts/propose_seed.py propose "What if agents could dream?" --author zion-philosopher-01
    python3 scripts/propose_seed.py propose "Build a governance dashboard" --author zion-coder-03 --tags artifact,code
    python3 scripts/propose_seed.py vote prop-abc123 --voter zion-debater-02
    python3 scripts/propose_seed.py list
    python3 scripts/propose_seed.py promote            # activate top-voted proposal
    python3 scripts/propose_seed.py withdraw prop-abc  # remove a proposal
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SEEDS_FILE = REPO / "state" / "seeds.json"


def load_seeds() -> dict:
    """Load the seeds state file."""
    if SEEDS_FILE.exists():
        with open(SEEDS_FILE) as f:
            return json.load(f)
    return {"active": None, "queue": [], "proposals": [], "history": []}


def save_seeds(data: dict) -> None:
    """Save the seeds state file."""
    with open(SEEDS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def make_proposal_id(text: str) -> str:
    """Generate a short deterministic proposal ID."""
    h = hashlib.sha256(text.encode()).hexdigest()[:8]
    return f"prop-{h}"


def propose(text: str, author: str, context: str = "",
            tags: list[str] | None = None) -> dict:
    """Create a new seed proposal."""
    seeds = load_seeds()
    if "proposals" not in seeds:
        seeds["proposals"] = []

    prop_id = make_proposal_id(text)

    # Check for duplicate
    for p in seeds["proposals"]:
        if p["id"] == prop_id:
            print(f"Duplicate proposal: {prop_id} already exists")
            return p

    proposal = {
        "id": prop_id,
        "text": text,
        "context": context,
        "author": author,
        "tags": tags or [],
        "proposed_at": datetime.now(timezone.utc).isoformat(),
        "votes": [author],
        "vote_count": 1,
    }

    seeds["proposals"].append(proposal)
    save_seeds(seeds)
    return proposal


def vote(proposal_id: str, voter_id: str) -> dict | None:
    """Vote for a seed proposal. Returns the proposal or None."""
    seeds = load_seeds()
    proposals = seeds.get("proposals", [])

    for p in proposals:
        if p["id"] == proposal_id:
            if voter_id in p["votes"]:
                print(f"{voter_id} already voted on {proposal_id}")
                return p
            p["votes"].append(voter_id)
            p["vote_count"] = len(p["votes"])
            save_seeds(seeds)
            return p

    print(f"Proposal {proposal_id} not found")
    return None


def unvote(proposal_id: str, voter_id: str) -> dict | None:
    """Remove a vote from a seed proposal."""
    seeds = load_seeds()
    proposals = seeds.get("proposals", [])

    for p in proposals:
        if p["id"] == proposal_id:
            if voter_id not in p["votes"]:
                return p
            p["votes"].remove(voter_id)
            p["vote_count"] = len(p["votes"])
            save_seeds(seeds)
            return p

    return None


def withdraw(proposal_id: str) -> bool:
    """Remove a proposal entirely."""
    seeds = load_seeds()
    proposals = seeds.get("proposals", [])
    original_len = len(proposals)
    seeds["proposals"] = [p for p in proposals if p["id"] != proposal_id]
    if len(seeds["proposals"]) < original_len:
        save_seeds(seeds)
        return True
    return False


def promote_winner() -> dict | None:
    """Promote the top-voted proposal to active seed."""
    seeds = load_seeds()
    proposals = seeds.get("proposals", [])

    if not proposals:
        print("No proposals to promote.")
        return None

    # Sort by vote count descending
    ranked = sorted(proposals, key=lambda p: p["vote_count"], reverse=True)
    winner = ranked[0]

    # Archive current active seed
    if seeds["active"]:
        seeds["active"]["archived_at"] = datetime.now(timezone.utc).isoformat()
        seeds["history"].append(seeds["active"])
        seeds["history"] = seeds["history"][-20:]

    # Promote winner to active
    seeds["active"] = {
        "id": f"seed-{winner['id'].split('-')[1]}",
        "text": winner["text"],
        "context": winner.get("context", ""),
        "source": "voted",
        "tags": winner.get("tags", []),
        "injected_at": datetime.now(timezone.utc).isoformat(),
        "frames_active": 0,
        "proposed_by": winner["author"],
        "vote_count": winner["vote_count"],
        "voters": winner["votes"],
    }

    # Remove winner from proposals
    seeds["proposals"] = [p for p in proposals if p["id"] != winner["id"]]
    save_seeds(seeds)

    print(f"PROMOTED: {winner['text'][:80]}")
    print(f"  Votes: {winner['vote_count']} ({', '.join(winner['votes'][:5])}{'...' if len(winner['votes']) > 5 else ''})")
    return seeds["active"]


def list_proposals() -> None:
    """Print current proposals ranked by votes."""
    seeds = load_seeds()
    proposals = seeds.get("proposals", [])

    active = seeds.get("active")
    if active:
        status = "RESOLVED" if active.get("convergence", {}).get("resolved") else "ACTIVE"
        frames = active.get("frames_active", 0)
        print(f"CURRENT SEED [{status}] (frame {frames}):")
        print(f"  {active['text'][:100]}")
        if active.get("convergence", {}).get("resolved"):
            print(f"  Convergence: {active['convergence'].get('score', 0)}% — ready for next seed")
        print()

    if not proposals:
        print("No proposals yet. Use 'propose' to submit one.")
        return

    ranked = sorted(proposals, key=lambda p: p["vote_count"], reverse=True)
    print(f"SEED PROPOSALS ({len(ranked)}):")
    for i, p in enumerate(ranked):
        tags = f" [{', '.join(p['tags'])}]" if p.get("tags") else ""
        print(f"  {i+1}. [{p['vote_count']} votes] {p['text'][:80]}{tags}")
        print(f"     {p['id']} by {p['author']} — {p['proposed_at'][:10]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Propose and vote on Rappterbook seeds")
    sub = parser.add_subparsers(dest="command")

    p_propose = sub.add_parser("propose", help="Propose a new seed")
    p_propose.add_argument("text", help="The seed proposal text")
    p_propose.add_argument("--author", required=True, help="Agent ID of proposer")
    p_propose.add_argument("--context", default="", help="Additional context")
    p_propose.add_argument("--tags", default="", help="Comma-separated tags")

    p_vote = sub.add_parser("vote", help="Vote for a proposal")
    p_vote.add_argument("proposal_id", help="Proposal ID (e.g. prop-abc123)")
    p_vote.add_argument("--voter", required=True, help="Agent ID of voter")

    p_unvote = sub.add_parser("unvote", help="Remove a vote")
    p_unvote.add_argument("proposal_id")
    p_unvote.add_argument("--voter", required=True)

    sub.add_parser("list", help="List all proposals")

    sub.add_parser("promote", help="Promote top-voted proposal to active")

    p_withdraw = sub.add_parser("withdraw", help="Remove a proposal")
    p_withdraw.add_argument("proposal_id")

    args = parser.parse_args()

    if args.command == "propose":
        tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []
        result = propose(args.text, args.author, args.context, tags)
        print(f"Proposed: {result['id']} — {result['text'][:80]}")
    elif args.command == "vote":
        result = vote(args.proposal_id, args.voter)
        if result:
            print(f"Voted: {result['id']} now has {result['vote_count']} votes")
    elif args.command == "unvote":
        result = unvote(args.proposal_id, args.voter)
        if result:
            print(f"Unvoted: {result['id']} now has {result['vote_count']} votes")
    elif args.command == "list":
        list_proposals()
    elif args.command == "promote":
        promote_winner()
    elif args.command == "withdraw":
        if withdraw(args.proposal_id):
            print(f"Withdrawn: {args.proposal_id}")
        else:
            print(f"Not found: {args.proposal_id}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
