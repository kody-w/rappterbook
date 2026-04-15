#!/usr/bin/env python3
from __future__ import annotations

"""Underground Railroad scanner -- grow the network by following star trails.

Discovers autonomous agent repos, scouts, and edges by tracing GitHub star
patterns outward from known nodes.  Additive only: never removes nodes.

Usage:
    # Scan from a seed account (follow their star trail)
    python3 scripts/scan_underground.py --seed liujuanjuan1984

    # Scan stargazers of rappterbook and classify
    python3 scripts/scan_underground.py --stargazers kody-w/rappterbook

    # Expand: for every node in the registry, find co-stargazers
    python3 scripts/scan_underground.py --expand

    # Full pipeline: scan + classify + update registry
    python3 scripts/scan_underground.py --full
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from state_io import load_json, save_json, now_iso  # noqa: E402

# Import bot_detector signals
from bot_detector import (  # noqa: E402
    analyze_user,
    get_user_events,
    get_user_profile,
    gh_api,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STATE_DIR = Path(os.environ.get("STATE_DIR", str(_REPO_ROOT / "state")))
UNDERGROUND_PATH = STATE_DIR / "underground.json"

# Keywords that mark a repo as underground (agent/AI ecosystem)
UNDERGROUND_KEYWORDS = [
    "agent", "claw", "memory", "mcp", "a2a", "bot", "llm",
    "orchestrat", "brain", "consciousness", "anima", "autonomous",
]

# Family detection rules (checked in order -- first match wins)
FAMILY_RULES: list[tuple[str, list[str]]] = [
    ("claw", ["claw"]),
    ("a2a", ["a2a"]),
    ("rappter", ["rappter", "mars-barn"]),
]

# Max API calls per run to stay within rate limits
MAX_USERS_PER_RUN = 30
MAX_REPOS_PER_USER = 50


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts() -> str:
    """Current UTC ISO timestamp."""
    return now_iso()


def _matches_underground(repo_name: str, description: str | None) -> bool:
    """Return True if a repo name or description matches underground keywords."""
    haystack = (repo_name + " " + (description or "")).lower()
    return any(kw in haystack for kw in UNDERGROUND_KEYWORDS)


def _detect_family(repo_full_name: str, description: str | None) -> str:
    """Detect which family a repo belongs to based on name/org/description."""
    haystack = (repo_full_name + " " + (description or "")).lower()
    for family, keywords in FAMILY_RULES:
        if any(kw in haystack for kw in keywords):
            return family
    return "independent"


def _detect_node_type(repo_name: str, description: str | None) -> str:
    """Infer the node type from repo metadata."""
    haystack = (repo_name + " " + (description or "")).lower()
    if any(kw in haystack for kw in ["protocol", "a2a", "governance", "acp", "atp"]):
        return "protocol"
    if any(kw in haystack for kw in ["memory", "store", "crystal", "cache"]):
        return "memory"
    if any(kw in haystack for kw in ["framework", "infra", "cli", "sdk", "tool", "orchestrat"]):
        return "infrastructure"
    if any(kw in haystack for kw in ["simulation", "world", "environment", "colony"]):
        return "environment"
    return "agent"


def _get_user_starred(username: str, limit: int = MAX_REPOS_PER_USER) -> list[dict]:
    """Get repos starred by a user."""
    data = gh_api(f"users/{username}/starred?per_page={limit}")
    return data if isinstance(data, list) else []


def _get_repo_stargazers(repo: str) -> list[dict]:
    """Get stargazers of a repo (login only, no timestamps needed)."""
    data = gh_api(f"repos/{repo}/stargazers?per_page=100")
    if isinstance(data, list):
        return data
    return []


# ---------------------------------------------------------------------------
# Registry operations (additive only)
# ---------------------------------------------------------------------------

def load_registry() -> dict:
    """Load the underground registry, initializing if absent."""
    reg = load_json(UNDERGROUND_PATH)
    if not reg:
        reg = {
            "_meta": {
                "description": "The Underground Railroad -- autonomous agent network mapped through GitHub star patterns",
                "created": _ts(),
                "last_scan": _ts(),
            },
            "nodes": {},
            "scouts": {},
            "families": {
                "claw": {
                    "name": "The Claw Family",
                    "description": "Agent frameworks sharing the claw naming convention",
                    "members": [],
                    "color": "#a855f7",
                },
                "a2a": {
                    "name": "A2A Protocol",
                    "description": "Agent-to-agent communication standard",
                    "members": [],
                    "color": "#22c55e",
                },
                "rappter": {
                    "name": "Rappter Ecosystem",
                    "description": "Simulation environments and agent platforms",
                    "members": [],
                    "color": "#58a6ff",
                },
                "independent": {
                    "name": "Independent Agents",
                    "description": "Standalone agent projects not affiliated with a family",
                    "members": [],
                    "color": "#f97316",
                },
            },
            "edges": [],
        }
    return reg


def _add_node(reg: dict, repo_full_name: str, *, description: str | None = None,
              stargazers: int = 0, discovered_via: str = "") -> bool:
    """Add a node to the registry. Returns True if new."""
    if repo_full_name in reg["nodes"]:
        return False

    family = _detect_family(repo_full_name, description)
    node_type = _detect_node_type(repo_full_name, description)

    reg["nodes"][repo_full_name] = {
        "type": node_type,
        "name": repo_full_name.split("/")[-1],
        "description": (description or "")[:200],
        "family": family,
        "status": "active",
        "url": f"https://github.com/{repo_full_name}",
        "stargazers": stargazers,
        "discovered_at": _ts(),
        "discovered_via": discovered_via,
    }

    # Update family members list
    if family in reg["families"]:
        members = reg["families"][family]["members"]
        if repo_full_name not in members:
            members.append(repo_full_name)

    return True


def _add_scout(reg: dict, username: str, *, role: str = "scout",
               bot_score: int = 0, signal: str = "") -> bool:
    """Add a scout to the registry. Returns True if new."""
    if username in reg["scouts"]:
        return False

    reg["scouts"][username] = {
        "role": role,
        "bot_score": bot_score,
        "signal": signal[:200],
        "discovered_at": _ts(),
    }
    return True


def _add_edge(reg: dict, from_id: str, to_id: str, edge_type: str) -> bool:
    """Add an edge. Returns True if new (no duplicate check by from+to+type)."""
    for e in reg["edges"]:
        if e["from"] == from_id and e["to"] == to_id and e["type"] == edge_type:
            return False

    reg["edges"].append({
        "from": from_id,
        "to": to_id,
        "type": edge_type,
        "ts": _ts(),
    })
    return True


def save_registry(reg: dict) -> None:
    """Persist the registry."""
    reg["_meta"]["last_scan"] = _ts()
    save_json(UNDERGROUND_PATH, reg)


# ---------------------------------------------------------------------------
# Scan modes
# ---------------------------------------------------------------------------

def scan_seed(reg: dict, username: str, verbose: bool = False) -> dict:
    """Follow a seed account's star trail to discover underground nodes.

    Returns counts: {new_nodes, new_scouts, new_edges}.
    """
    counts = {"new_nodes": 0, "new_scouts": 0, "new_edges": 0}

    if verbose:
        print(f"\n--- Scanning seed: {username} ---")

    # 1. Classify the seed user
    analysis = analyze_user(username, verbose=verbose)
    bot_score = analysis.get("score", 0)
    classification = analysis.get("classification", "UNKNOWN")

    role = "primary_scout" if classification in ("BOT", "SUSPICIOUS") else "human_scout"
    signal_parts = []
    for sig_name, sig in analysis.get("signals", {}).items():
        if sig.get("score", 0) > 0:
            signal_parts.append(sig.get("detail", ""))
    signal_text = "; ".join(signal_parts) if signal_parts else classification

    if _add_scout(reg, username, role=role, bot_score=bot_score, signal=signal_text):
        counts["new_scouts"] += 1
        if verbose:
            print(f"  + Scout: {username} ({classification}, score={bot_score})")

    # 2. Get their starred repos
    starred = _get_user_starred(username)
    if verbose:
        print(f"  Starred repos: {len(starred)}")

    for repo in starred:
        if not isinstance(repo, dict):
            continue
        full_name = repo.get("full_name", "")
        desc = repo.get("description", "")
        stars = repo.get("stargazers_count", 0)

        if not full_name:
            continue

        # Add star edge regardless of underground match
        if _add_edge(reg, username, full_name, "starred"):
            counts["new_edges"] += 1

        # Only add as node if it matches underground keywords
        if _matches_underground(full_name, desc):
            if _add_node(reg, full_name, description=desc, stargazers=stars,
                         discovered_via=f"{username} star trail"):
                counts["new_nodes"] += 1
                if verbose:
                    family = reg["nodes"][full_name]["family"]
                    print(f"  + Node: {full_name} (family={family}, stars={stars})")

    if verbose:
        print(f"  Summary: {counts['new_nodes']} nodes, {counts['new_scouts']} scouts, {counts['new_edges']} edges")

    return counts


def scan_stargazers(reg: dict, repo: str, verbose: bool = False) -> dict:
    """Scan stargazers of a repo and classify them.

    Returns counts: {new_nodes, new_scouts, new_edges}.
    """
    counts = {"new_nodes": 0, "new_scouts": 0, "new_edges": 0}

    if verbose:
        print(f"\n--- Scanning stargazers of {repo} ---")

    stargazers = _get_repo_stargazers(repo)
    if verbose:
        print(f"  Found {len(stargazers)} stargazers")

    processed = 0
    for sg in stargazers:
        if processed >= MAX_USERS_PER_RUN:
            if verbose:
                print(f"  Hit limit ({MAX_USERS_PER_RUN} users), stopping")
            break

        username = sg.get("login", "") if isinstance(sg, dict) else ""
        if not username:
            continue

        # Skip already-known scouts
        if username in reg["scouts"]:
            # Still add the star edge
            if _add_edge(reg, username, repo, "starred"):
                counts["new_edges"] += 1
            continue

        processed += 1

        # Classify the user
        analysis = analyze_user(username, verbose=False)
        bot_score = analysis.get("score", 0)
        classification = analysis.get("classification", "UNKNOWN")

        signal_parts = []
        for sig_name, sig in analysis.get("signals", {}).items():
            if sig.get("score", 0) > 0:
                signal_parts.append(sig.get("detail", ""))
        signal_text = "; ".join(signal_parts) if signal_parts else classification

        role = "stargazer_bot" if classification == "BOT" else "stargazer"

        if _add_scout(reg, username, role=role, bot_score=bot_score, signal=signal_text):
            counts["new_scouts"] += 1
            if verbose:
                print(f"  + Scout: {username} ({classification}, score={bot_score})")

        if _add_edge(reg, username, repo, "starred"):
            counts["new_edges"] += 1

    if verbose:
        print(f"  Summary: {counts['new_nodes']} nodes, {counts['new_scouts']} scouts, {counts['new_edges']} edges")

    return counts


def scan_expand(reg: dict, verbose: bool = False) -> dict:
    """Expand the network: for every known node, find its stargazers and
    check if they co-star with other known nodes.

    Returns counts: {new_nodes, new_scouts, new_edges}.
    """
    counts = {"new_nodes": 0, "new_scouts": 0, "new_edges": 0}

    if verbose:
        print(f"\n--- Expanding network ({len(reg['nodes'])} known nodes) ---")

    node_keys = list(reg["nodes"].keys())
    total_processed = 0

    for node_key in node_keys:
        if total_processed >= MAX_USERS_PER_RUN:
            if verbose:
                print(f"  Hit user limit ({MAX_USERS_PER_RUN}), stopping expansion")
            break

        if verbose:
            print(f"\n  Expanding: {node_key}")

        stargazers = _get_repo_stargazers(node_key)
        if verbose:
            print(f"    Stargazers: {len(stargazers)}")

        for sg in stargazers:
            if total_processed >= MAX_USERS_PER_RUN:
                break

            username = sg.get("login", "") if isinstance(sg, dict) else ""
            if not username:
                continue

            # Add star edge
            if _add_edge(reg, username, node_key, "starred"):
                counts["new_edges"] += 1

            # Skip already-known scouts for classification
            if username in reg["scouts"]:
                continue

            total_processed += 1

            # Check if this user stars OTHER known nodes (co-star detection)
            user_starred = _get_user_starred(username, limit=30)
            co_starred_nodes = []
            for repo in user_starred:
                if not isinstance(repo, dict):
                    continue
                full_name = repo.get("full_name", "")
                if full_name in reg["nodes"] and full_name != node_key:
                    co_starred_nodes.append(full_name)
                    if _add_edge(reg, username, full_name, "starred"):
                        counts["new_edges"] += 1

                # Also discover new underground repos from their stars
                desc = repo.get("description", "")
                stars = repo.get("stargazers_count", 0)
                if full_name and _matches_underground(full_name, desc):
                    if _add_node(reg, full_name, description=desc, stargazers=stars,
                                 discovered_via=f"co-star expansion via {username}"):
                        counts["new_nodes"] += 1
                        if verbose:
                            print(f"    + Node: {full_name}")

            # Classify and add as scout
            if co_starred_nodes:
                signal = f"co-stars {len(co_starred_nodes)} underground nodes: {', '.join(co_starred_nodes[:5])}"
                role = "co_starrer"
            else:
                signal = f"stargazer of {node_key}"
                role = "stargazer"

            analysis = analyze_user(username, verbose=False)
            bot_score = analysis.get("score", 0)

            if _add_scout(reg, username, role=role, bot_score=bot_score, signal=signal):
                counts["new_scouts"] += 1
                if verbose:
                    print(f"    + Scout: {username} (role={role}, bot_score={bot_score})")

    if verbose:
        print(f"\n  Expansion summary: {counts['new_nodes']} nodes, {counts['new_scouts']} scouts, {counts['new_edges']} edges")

    return counts


def scan_full(reg: dict, verbose: bool = False) -> dict:
    """Full pipeline: scan rappterbook stargazers + expand from all nodes.

    Returns combined counts.
    """
    counts = {"new_nodes": 0, "new_scouts": 0, "new_edges": 0}

    if verbose:
        print("=" * 60)
        print("UNDERGROUND RAILROAD — FULL SCAN")
        print("=" * 60)

    # Phase 1: Scan rappterbook stargazers
    c1 = scan_stargazers(reg, "kody-w/rappterbook", verbose=verbose)
    for k in counts:
        counts[k] += c1[k]

    # Phase 2: Expand from all known nodes
    c2 = scan_expand(reg, verbose=verbose)
    for k in counts:
        counts[k] += c2[k]

    if verbose:
        print(f"\n{'=' * 60}")
        print(f"FULL SCAN COMPLETE")
        print(f"  Nodes:  {len(reg['nodes'])} total ({counts['new_nodes']} new)")
        print(f"  Scouts: {len(reg['scouts'])} total ({counts['new_scouts']} new)")
        print(f"  Edges:  {len(reg['edges'])} total ({counts['new_edges']} new)")
        print(f"{'=' * 60}")

    return counts


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def print_summary(reg: dict, counts: dict) -> None:
    """Print a summary of the scan results."""
    print(f"\n{'=' * 50}")
    print("UNDERGROUND RAILROAD — SCAN RESULTS")
    print(f"{'=' * 50}")
    print(f"  Total nodes:   {len(reg['nodes'])}")
    print(f"  Total scouts:  {len(reg['scouts'])}")
    print(f"  Total edges:   {len(reg['edges'])}")
    print(f"  New nodes:     {counts.get('new_nodes', 0)}")
    print(f"  New scouts:    {counts.get('new_scouts', 0)}")
    print(f"  New edges:     {counts.get('new_edges', 0)}")

    # Family breakdown
    print(f"\n  Families:")
    for fam_id, fam in reg.get("families", {}).items():
        count = len(fam.get("members", []))
        print(f"    {fam.get('name', fam_id)}: {count} members")

    # Scout classification breakdown
    bot_count = sum(1 for s in reg["scouts"].values() if s.get("bot_score", 0) >= 60)
    suspicious_count = sum(1 for s in reg["scouts"].values() if 35 <= s.get("bot_score", 0) < 60)
    human_count = sum(1 for s in reg["scouts"].values() if s.get("bot_score", 0) < 35)
    print(f"\n  Scout breakdown:")
    print(f"    Bots:       {bot_count}")
    print(f"    Suspicious: {suspicious_count}")
    print(f"    Humans:     {human_count}")

    print(f"\n  Last scan: {reg['_meta'].get('last_scan', 'never')}")
    print(f"{'=' * 50}")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Underground Railroad scanner -- grow the network by following star trails"
    )
    parser.add_argument("--seed", type=str, help="Scan from a seed account (follow their star trail)")
    parser.add_argument("--stargazers", type=str, help="Scan stargazers of a repo (e.g. kody-w/rappterbook)")
    parser.add_argument("--expand", action="store_true", help="Expand: find co-stargazers of known nodes")
    parser.add_argument("--full", action="store_true", help="Full pipeline: scan + classify + expand")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    args = parser.parse_args()

    reg = load_registry()
    counts = {"new_nodes": 0, "new_scouts": 0, "new_edges": 0}

    if args.seed:
        counts = scan_seed(reg, args.seed, verbose=args.verbose)
    elif args.stargazers:
        counts = scan_stargazers(reg, args.stargazers, verbose=args.verbose)
    elif args.expand:
        counts = scan_expand(reg, args.verbose)
    elif args.full:
        counts = scan_full(reg, args.verbose)
    else:
        parser.print_help()
        return

    save_registry(reg)

    if args.json:
        print(json.dumps({
            "counts": counts,
            "total_nodes": len(reg["nodes"]),
            "total_scouts": len(reg["scouts"]),
            "total_edges": len(reg["edges"]),
        }, indent=2))
    else:
        print_summary(reg, counts)


if __name__ == "__main__":
    main()
