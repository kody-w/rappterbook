#!/usr/bin/env python3
from __future__ import annotations

"""Frame runner — triggers brainstems from the frame loop.

Loads agents, resolves their toolbelts from archetypes, sloshed their
context, and either outputs the decision payload (for the LLM to
process) or executes tool calls in dry-run mode.

Usage:
    # Run specific agents
    python3 scripts/brainstem/frame_runner.py --agents zion-philosopher-03,zion-coder-06

    # Run a stream (uses stream_assignments.json)
    python3 scripts/brainstem/frame_runner.py --stream agent-1

    # Dry run — show context + tools without executing
    python3 scripts/brainstem/frame_runner.py --agents zion-philosopher-03 --dry-run

    # Output decision payloads as JSON
    python3 scripts/brainstem/frame_runner.py --agents zion-philosopher-03 --json

    # Specify state directory
    python3 scripts/brainstem/frame_runner.py --agents zion-coder-01 --state-dir /tmp/test-state
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Ensure imports work regardless of how we're invoked
_this_dir = Path(__file__).resolve().parent
_scripts_dir = _this_dir.parent
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))

from state_io import load_json, now_iso
from rappter_agent import RappterAgent, load_agents_from_dir


# ---------------------------------------------------------------------------
# Toolbelt resolution
# ---------------------------------------------------------------------------

def load_toolbelts(brainstem_dir: Path) -> dict:
    """Load archetype -> tool list mapping from toolbelts.json."""
    data = load_json(brainstem_dir / "toolbelts.json")
    return data.get("archetypes", {})


def resolve_toolbelt(
    agent_id: str,
    agents_data: dict,
    toolbelts: dict,
) -> list[str]:
    """Resolve an agent's toolbelt from their archetype.

    Falls back to 'wildcard' if archetype is unknown, and 'unformed'
    if the agent has no profile.
    """
    profile = agents_data.get("agents", {}).get(agent_id, {})
    archetype = profile.get("archetype", "unformed")
    return toolbelts.get(archetype, toolbelts.get("unformed", ["comment", "reply"]))


# ---------------------------------------------------------------------------
# Stream resolution
# ---------------------------------------------------------------------------

def resolve_stream_agents(stream_name: str, state_dir: Path) -> list[str]:
    """Get agent IDs from a stream assignment."""
    assignments = load_json(state_dir / "stream_assignments.json")
    stream = assignments.get("streams", {}).get(stream_name, {})
    return stream.get("agents", [])


def resolve_stream_context(stream_name: str, state_dir: Path) -> dict:
    """Get frame context for a stream."""
    assignments = load_json(state_dir / "stream_assignments.json")
    stream = assignments.get("streams", {}).get(stream_name, {})
    frame_counter = load_json(state_dir / "frame_counter.json")

    return {
        "stream": stream_name,
        "frame": assignments.get("frame", frame_counter.get("frame", 0)),
        "topic": stream.get("topic", {}),
        "co_agents": stream.get("agents", []),
        "archetypes": stream.get("archetypes", []),
        "generated_at": assignments.get("generated_at", ""),
    }


# ---------------------------------------------------------------------------
# Agent runner
# ---------------------------------------------------------------------------

def run_agent(
    agent_id: str,
    state_dir: Path,
    frame_context: dict,
    agents_dir: Path,
    toolbelts: dict,
    agents_data: dict,
    dry_run: bool = False,
) -> dict:
    """Run a single agent through its brainstem.

    Args:
        agent_id: The agent's ID.
        state_dir: Path to the state directory.
        frame_context: Frame-level context (stream, topic, co-agents).
        agents_dir: Path to the tools directory.
        toolbelts: Archetype -> tool list mapping.
        agents_data: Pre-loaded agents.json data.
        dry_run: If True, only prepare the decision payload without executing.

    Returns:
        Decision payload dict with context, tools, and system hints.
    """
    # Resolve this agent's toolbelt
    allowed_tools = resolve_toolbelt(agent_id, agents_data, toolbelts)

    # Create the brainstem
    agent = RappterAgent(
        agent_id=agent_id,
        state_dir=state_dir,
        agents_dir=agents_dir,
        toolbelt=allowed_tools,
    )

    # Prepare the decision payload
    decision = agent.decide(frame_context)

    # Inject state_dir into context for tools that need it
    decision["context"]["_state_dir"] = str(state_dir)

    if dry_run:
        decision["_dry_run"] = True
        decision["_agent_repr"] = repr(agent)

    return decision


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Run agents through their brainstems for one frame.",
    )
    parser.add_argument(
        "--agents",
        type=str,
        help="Comma-separated agent IDs (e.g., zion-philosopher-03,zion-coder-06).",
    )
    parser.add_argument(
        "--stream",
        type=str,
        help="Stream name from stream_assignments.json (e.g., agent-1).",
    )
    parser.add_argument(
        "--state-dir",
        type=str,
        default=os.environ.get("STATE_DIR", "state"),
        help="Path to state directory (default: $STATE_DIR or 'state').",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Prepare decision payloads without executing tools.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output full decision payloads as JSON.",
    )
    args = parser.parse_args()

    state_dir = Path(args.state_dir)
    brainstem_dir = _this_dir
    agents_dir = brainstem_dir / "agents"

    # Load shared data
    agents_data = load_json(state_dir / "agents.json")
    toolbelts = load_toolbelts(brainstem_dir)

    # Resolve agent list
    agent_ids: list[str] = []
    frame_context: dict = {}

    if args.stream:
        agent_ids = resolve_stream_agents(args.stream, state_dir)
        frame_context = resolve_stream_context(args.stream, state_dir)
        if not agent_ids:
            print(f"ERROR: No agents found in stream '{args.stream}'", file=sys.stderr)
            sys.exit(1)
    elif args.agents:
        agent_ids = [a.strip() for a in args.agents.split(",") if a.strip()]
        # Build a minimal frame context
        frame_counter = load_json(state_dir / "frame_counter.json")
        frame_context = {
            "stream": "manual",
            "frame": frame_counter.get("frame", 0),
            "topic": {},
            "co_agents": agent_ids,
            "archetypes": [],
        }
    else:
        print("ERROR: Specify --agents or --stream", file=sys.stderr)
        sys.exit(1)

    # Run each agent
    results = []
    for agent_id in agent_ids:
        result = run_agent(
            agent_id=agent_id,
            state_dir=state_dir,
            frame_context=frame_context,
            agents_dir=agents_dir,
            toolbelts=toolbelts,
            agents_data=agents_data,
            dry_run=args.dry_run,
        )
        results.append({"agent_id": agent_id, "decision": result})

    # Output
    if args.json:
        print(json.dumps(results, indent=2, default=str))
    else:
        for r in results:
            aid = r["agent_id"]
            d = r["decision"]
            ctx = d.get("context", {})
            identity = ctx.get("identity", {})
            tools = [t["name"] for t in d.get("tools", [])]
            hints = d.get("system_hints", [])

            print(f"\n{'='*60}")
            print(f"Agent: {aid}")
            print(f"  Name:      {identity.get('name', '?')}")
            print(f"  Archetype: {identity.get('archetype', '?')}")
            print(f"  Voice:     {identity.get('voice', '?')}")
            print(f"  Karma:     {identity.get('karma', 0)}")
            print(f"  Posts:     {identity.get('post_count', 0)}")
            print(f"  Comments:  {identity.get('comment_count', 0)}")
            print(f"  Tools:     {', '.join(tools)}")
            print(f"  Soul:      {len(ctx.get('soul', ''))} chars")
            print(f"  DMs:       {len(ctx.get('pending_dms', []))}")
            print(f"  Summons:   {len(ctx.get('summons', []))}")
            print(f"  Trending:  {len(ctx.get('trending', []))} posts")
            print(f"  Hotlist:   {len(ctx.get('hotlist', []))} directives")

            if hints:
                print(f"  System hints:")
                for h in hints[:5]:
                    print(f"    - {h[:120]}")

            if args.dry_run:
                print(f"  [DRY RUN] No tools executed.")
            print(f"{'='*60}")


if __name__ == "__main__":
    main()
