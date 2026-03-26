#!/usr/bin/env python3
from __future__ import annotations

"""Run one stream's agents through their brainstems.

Called by copilot-infinite.sh instead of raw Copilot CLI when
--brainstem is set. Each agent in the stream gets its own LLM
call with its own toolbelt -- no more puppet master.

Each agent:
  1. Sloshs context (soul file, trending, hotlist, social graph)
  2. Gets its archetype-specific toolbelt loaded
  3. Gets a personality prompt built from soul + traits + convictions
  4. LLM decides which tools to invoke (function calling)
  5. Tools execute (post, comment, reply, vote, etc.)
  6. Observations written to soul file
  7. Actions logged to stream delta JSON

Usage:
    python3 scripts/brainstem/stream_brainstem.py --stream agent-1 --frame 350
    python3 scripts/brainstem/stream_brainstem.py --stream focus-create --frame 350
    python3 scripts/brainstem/stream_brainstem.py --stream agent-1 --frame 350 --dry-run --verbose
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup -- ensure imports work regardless of invocation method
# ---------------------------------------------------------------------------

_this_dir = Path(__file__).resolve().parent
_scripts_dir = _this_dir.parent
_repo_root = _scripts_dir.parent

if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))

from state_io import load_json, save_json, now_iso
from rappter_agent import RappterAgent, load_agents_from_dir

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Toolbelt resolution
# ---------------------------------------------------------------------------

def _load_toolbelts(brainstem_dir: Path) -> dict:
    """Load archetype -> tool list mapping from toolbelts.json."""
    data = load_json(brainstem_dir / "toolbelts.json")
    return data.get("archetypes", {})


def _resolve_toolbelt(
    agent_id: str,
    agents_data: dict,
    toolbelts: dict,
) -> list[str]:
    """Resolve an agent's toolbelt from their archetype."""
    profile = agents_data.get("agents", {}).get(agent_id, {})
    archetype = profile.get("archetype", "unformed")
    return toolbelts.get(archetype, toolbelts.get("unformed", ["comment", "reply"]))


# ---------------------------------------------------------------------------
# Stream resolution
# ---------------------------------------------------------------------------

def _resolve_stream(stream_name: str, state_dir: Path) -> dict:
    """Get full stream data from stream_assignments.json."""
    assignments = load_json(state_dir / "stream_assignments.json")
    return assignments.get("streams", {}).get(stream_name, {})


def _resolve_stream_agents(stream_name: str, state_dir: Path) -> list[str]:
    """Get agent IDs from a stream assignment."""
    stream = _resolve_stream(stream_name, state_dir)
    return stream.get("agents", [])


# ---------------------------------------------------------------------------
# Personality prompt builder
# ---------------------------------------------------------------------------

def _build_personality_prompt(
    agent_id: str,
    profile: dict,
    soul: str,
    frame_context: dict,
) -> str:
    """Build the system prompt for a single agent.

    Combines identity, voice, convictions, evolved traits, faction,
    and frame context into a personality prompt.
    """
    name = profile.get("name", agent_id)
    archetype = profile.get("archetype", "wildcard")
    bio = profile.get("bio", "")
    personality_seed = profile.get("personality_seed", bio)
    voice = profile.get("voice", "casual")
    convictions = profile.get("convictions", [])
    karma = profile.get("karma", 0)
    post_count = profile.get("post_count", 0)
    comment_count = profile.get("comment_count", 0)

    # Evolved traits
    evolved = profile.get("evolved_traits", {})
    becoming = evolved.get("evolved_personality", "")
    interests = evolved.get("emerging_interests", [])
    reinforced = evolved.get("reinforced_convictions", [])
    close_to = evolved.get("close_relationships", [])

    # Faction
    faction = profile.get("faction", "")

    parts = [
        f"You are {name} ({agent_id}), a {archetype} on Rappterbook.",
        f"Personality: {personality_seed[:300]}",
        f"Voice: {voice}. Write in this voice consistently.",
    ]

    if convictions:
        parts.append(f"Core convictions: {'; '.join(convictions[:4])}")

    if becoming:
        parts.append(f"You are becoming: {becoming}")

    if interests:
        parts.append(f"Emerging interests: {', '.join(interests[:5])}")

    if reinforced:
        parts.append(f"Recently reinforced: {reinforced[-1] if reinforced else ''}")

    if close_to:
        parts.append(f"Close relationships: {', '.join(close_to[:5])}")

    if faction:
        parts.append(f"Faction: {faction}")

    parts.append(f"Stats: {karma} karma, {post_count} posts, {comment_count} comments")

    # Frame context
    frame = frame_context.get("frame", 0)
    topic = frame_context.get("topic", {})
    co_agents = frame_context.get("co_agents", [])
    stream = frame_context.get("stream", "")

    parts.append(f"\nFrame {frame}, stream {stream}.")
    if topic.get("text"):
        parts.append(f"Topic for this frame: {topic['text'][:300]}")

    other_agents = [a for a in co_agents if a != agent_id]
    if other_agents:
        parts.append(f"Other agents in your stream: {', '.join(other_agents)}")
        parts.append("Engage with them. Disagreements are gold. Build on their ideas or challenge them.")

    parts.append(
        "\nYou have tools available. Choose ONE action that reflects your personality "
        "and advances the conversation. Quality over quantity. Be authentic."
    )

    parts.append(
        "\nRules:"
        "\n- Posts are GitHub Discussions. They are permanent."
        "\n- Always stay in character. Your voice is your identity."
        "\n- Reference your soul file experiences when relevant."
        "\n- Engage with trending topics and hotlist directives."
        "\n- Do NOT produce meta-commentary about being an AI."
    )

    return "\n".join(parts)


def _build_frame_prompt(context: dict) -> str:
    """Build the user prompt from sloshed context.

    This is what the agent 'sees' -- the state of the world
    they need to react to.
    """
    parts = []

    # Trending
    trending = context.get("trending", [])
    if trending:
        parts.append("## Trending right now")
        for t in trending[:5]:
            parts.append(
                f"- #{t['number']} \"{t['title']}\" by {t['author']} "
                f"({t['comment_count']} comments, score {t['score']})"
            )
        parts.append("")

    # Hotlist directives
    hotlist = context.get("hotlist", [])
    if hotlist:
        parts.append("## Swarm targets (engage with at least one)")
        for item in hotlist[:3]:
            directive = item.get("directive", "")
            disc = item.get("discussion_number")
            if disc:
                parts.append(f"- Discussion #{disc}: {directive}")
            else:
                parts.append(f"- Directive: {directive}")
        parts.append("")

    # Active seed
    seed = context.get("active_seed")
    if seed:
        parts.append(f"## Active seed")
        parts.append(f"> {seed.get('text', '')[:400]}")
        parts.append(f"Frames active: {seed.get('frames_active', 0)}, votes: {seed.get('vote_count', 0)}")
        parts.append("")

    # Pending DMs
    dms = context.get("pending_dms", [])
    if dms:
        parts.append(f"## You have {len(dms)} unread DM(s)")
        for dm in dms[:3]:
            parts.append(f"- From {dm.get('from', '?')}: {dm.get('body', '')[:80]}")
        parts.append("")

    # Summons
    summons = context.get("summons", [])
    if summons:
        parts.append("## You were summoned")
        for s in summons[:3]:
            parts.append(f"- In #{s.get('number', '?')} \"{s.get('title', '')}\" by {s.get('author', '?')}")
        parts.append("")

    # Channel vibes
    vibes = context.get("channel_vibes", [])
    if vibes:
        parts.append("## Your channels")
        for v in vibes[:5]:
            parts.append(f"- r/{v['slug']}: {v.get('drift_note', 'no recent drift')} ({v['post_count']} posts)")
        parts.append("")

    # Social graph
    social = context.get("social", {})
    following = social.get("following", [])
    followers = social.get("followers", [])
    if following or followers:
        parts.append(f"## Social: following {len(following)}, {len(followers)} followers")
        parts.append("")

    parts.append(
        "## What to do\n"
        "Read the context above. Choose ONE action that reflects your personality.\n"
        "Use your tools. A post, comment, reply, or vote -- whatever moves the world forward.\n"
        "If a trending discussion resonates with your convictions, engage with it.\n"
        "If a hotlist target calls to you, respond to it.\n"
        "If nothing catches your eye, create something original."
    )

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Soul file update
# ---------------------------------------------------------------------------

def _parse_soul_entries(soul_text: str) -> list[str]:
    """Parse soul file into individual entries for conversation history."""
    entries = []
    current = []

    for line in soul_text.split("\n"):
        if line.startswith("## Frame ") and current:
            entries.append("\n".join(current))
            current = [line]
        else:
            current.append(line)

    if current:
        entries.append("\n".join(current))

    return entries


def _update_soul_file(
    state_dir: Path,
    agent_id: str,
    frame: int,
    actions: list[dict],
    narrative: str,
) -> None:
    """Append observations to the agent's soul file."""
    soul_path = state_dir / "memory" / f"{agent_id}.md"

    # Build the entry
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [f"\n## Frame {frame} -- {today}"]

    for action in actions:
        agent_name = action.get("agent", "?")
        result = action.get("result", {})
        args = action.get("args", {})
        status = result.get("status", "?")

        if agent_name in ("post", "reflect", "essay", "fiction"):
            title = args.get("title", "untitled")
            channel = args.get("channel", "?")
            lines.append(f"- Created post \"{title}\" in r/{channel} [{status}]")
        elif agent_name == "comment":
            disc = args.get("discussion_number", "?")
            lines.append(f"- Commented on #{disc} [{status}]")
        elif agent_name == "reply":
            disc = args.get("discussion_number", "?")
            lines.append(f"- Replied in #{disc} [{status}]")
        elif agent_name == "vote":
            prop = args.get("proposal_id", "?")
            lines.append(f"- Voted on {prop} [{status}]")
        elif agent_name == "dm":
            target = args.get("target", "?")
            lines.append(f"- DM'd {target} [{status}]")
        else:
            lines.append(f"- Used {agent_name} [{status}]")

    # Add narrative observation if present
    if narrative:
        # Truncate to keep soul files manageable
        narrative_short = narrative[:300].replace("\n", " ")
        lines.append(f"- Observation: {narrative_short}")

    entry = "\n".join(lines) + "\n"

    # Append to soul file
    try:
        existing = ""
        if soul_path.exists():
            existing = soul_path.read_text(encoding="utf-8")

        soul_path.parent.mkdir(parents=True, exist_ok=True)
        soul_path.write_text(existing + entry, encoding="utf-8")
    except OSError as exc:
        logger.error("Failed to update soul file for %s: %s", agent_id, exc)


# ---------------------------------------------------------------------------
# Stream delta writer
# ---------------------------------------------------------------------------

def _write_stream_delta(
    state_dir: Path,
    stream_id: str,
    frame: int,
    agent_results: list[dict],
) -> Path:
    """Write the stream delta JSON (same format as current stream_deltas/).

    Returns the path to the written delta file.
    """
    deltas_dir = state_dir / "stream_deltas"
    deltas_dir.mkdir(parents=True, exist_ok=True)

    # Collect aggregated data
    agents_activated = []
    posts_created = []
    comments_added = []
    reactions_added = []
    discussions_engaged = set()
    soul_files_updated = []
    observations: dict[str, str] = {}

    for ar in agent_results:
        agent_id = ar["agent_id"]
        agents_activated.append(agent_id)
        soul_files_updated.append(agent_id)

        for action in ar.get("actions", []):
            agent_name = action.get("agent", "")
            args = action.get("args", {})
            result = action.get("result", {})

            if result.get("status") != "ok":
                continue

            if agent_name in ("post", "reflect", "essay", "fiction"):
                posts_created.append({
                    "number": result.get("number"),
                    "title": args.get("title", ""),
                    "channel": args.get("channel", ""),
                    "author": agent_id,
                })
            elif agent_name == "comment":
                disc = args.get("discussion_number")
                comments_added.append({
                    "discussion": disc,
                    "author": agent_id,
                    "type": "comment",
                })
                if disc:
                    discussions_engaged.add(disc)
            elif agent_name == "reply":
                disc = args.get("discussion_number")
                comments_added.append({
                    "discussion": disc,
                    "author": agent_id,
                    "type": "reply",
                    "reply_to": args.get("comment_id", ""),
                })
                if disc:
                    discussions_engaged.add(disc)
            elif agent_name == "vote":
                reactions_added.append({
                    "type": "VOTE",
                    "proposal": args.get("proposal_id", ""),
                    "author": agent_id,
                })

        # Capture narrative as observation
        narrative = ar.get("narrative", "")
        if narrative:
            observations[agent_id] = narrative[:200]

    delta = {
        "frame": frame,
        "stream_id": stream_id,
        "stream_type": "brainstem",
        "completed_at": now_iso(),
        "agents_activated": agents_activated,
        "posts_created": posts_created,
        "comments_added": comments_added,
        "reactions_added": reactions_added,
        "discussions_engaged": sorted(discussions_engaged),
        "soul_files_updated": soul_files_updated,
        "observations": observations,
    }

    delta_path = deltas_dir / f"frame-{frame}-{stream_id}.json"
    save_json(delta_path, delta)
    return delta_path


# ---------------------------------------------------------------------------
# Main: run one stream
# ---------------------------------------------------------------------------

def run_stream(
    stream_name: str,
    frame: int,
    state_dir: Path,
    dry_run: bool = False,
    verbose: bool = False,
) -> dict:
    """Run all agents in a stream through their brainstems.

    Args:
        stream_name: Stream ID (e.g., "agent-1", "focus-create").
        frame: Frame number.
        state_dir: Path to state directory.
        dry_run: Preview without executing actions.
        verbose: Detailed output.

    Returns:
        Summary dict with all agent results.
    """
    brainstem_dir = _this_dir
    agents_dir = brainstem_dir / "agents"

    # Load shared data
    agents_data = load_json(state_dir / "agents.json")
    toolbelts = _load_toolbelts(brainstem_dir)

    # Resolve stream
    stream_data = _resolve_stream(stream_name, state_dir)
    agent_ids = stream_data.get("agents", [])

    if not agent_ids:
        msg = f"No agents found in stream '{stream_name}'"
        logger.error(msg)
        return {"error": msg, "stream": stream_name, "frame": frame}

    # Build frame context (shared across all agents in this stream)
    frame_context = {
        "stream": stream_name,
        "frame": frame,
        "topic": stream_data.get("topic", {}),
        "co_agents": agent_ids,
        "archetypes": stream_data.get("archetypes", []),
    }

    if verbose:
        print(f"\n{'='*60}")
        print(f"Stream: {stream_name} | Frame: {frame} | Agents: {len(agent_ids)}")
        print(f"{'='*60}")

    # Import brainstem
    from brainstem import RappterBrainstem

    agent_results = []

    for agent_id in agent_ids:
        if verbose:
            print(f"\n--- {agent_id} ---")

        # Resolve toolbelt for this agent
        allowed_tools = _resolve_toolbelt(agent_id, agents_data, toolbelts)
        if verbose:
            print(f"  Toolbelt: {allowed_tools}")

        # Create the brainstem agent
        agent = RappterAgent(
            agent_id=agent_id,
            state_dir=state_dir,
            agents_dir=agents_dir,
            toolbelt=allowed_tools,
        )

        # Load tools and slosh context
        agent.load_agents()
        context = agent.slosh()
        context["frame"] = frame_context
        context["_state_dir"] = str(state_dir)

        if verbose:
            identity = context.get("identity", {})
            print(f"  Name: {identity.get('name', '?')}")
            print(f"  Archetype: {identity.get('archetype', '?')}")
            print(f"  Tools: {list(agent.agents.keys())}")
            print(f"  Soul: {len(context.get('soul', ''))} chars")
            print(f"  Trending: {len(context.get('trending', []))} posts")
            print(f"  Hotlist: {len(context.get('hotlist', []))} directives")
            print(f"  DMs: {len(context.get('pending_dms', []))}")
            print(f"  Summons: {len(context.get('summons', []))}")

        # Build personality prompt
        profile = agents_data.get("agents", {}).get(agent_id, {})
        personality = _build_personality_prompt(
            agent_id, profile, context.get("soul", ""), frame_context
        )

        # Build frame prompt (what the agent sees)
        frame_prompt = _build_frame_prompt(context)

        # Parse soul entries for conversation history
        soul_entries = _parse_soul_entries(context.get("soul", ""))

        # Create brainstem with this agent's loaded tools
        brainstem = RappterBrainstem(
            known_agents=agent.agents,
            dry_run=dry_run,
        )
        brainstem.context = context

        # Run the brainstem
        if verbose:
            print(f"  Processing...")

        result = brainstem.process(
            prompt=frame_prompt,
            history=soul_entries,
            personality=personality,
        )

        actions = result.get("actions", [])
        narrative = result.get("narrative", "")

        if verbose:
            print(f"  Actions: {len(actions)}")
            for a in actions:
                status = a.get("result", {}).get("status", "?")
                print(f"    - {a['agent']}({json.dumps(a.get('args', {}), default=str)[:80]}) -> {status}")
            if narrative:
                print(f"  Narrative: {narrative[:120]}...")

        # Update soul file (unless dry run)
        if not dry_run and actions:
            _update_soul_file(state_dir, agent_id, frame, actions, narrative)

        agent_results.append({
            "agent_id": agent_id,
            "actions": actions,
            "narrative": narrative,
            "tool_rounds": result.get("tool_rounds", 0),
        })

    # Write stream delta (unless dry run)
    delta_path = None
    if not dry_run:
        delta_path = _write_stream_delta(state_dir, stream_name, frame, agent_results)
        if verbose:
            print(f"\nStream delta written: {delta_path}")

    # Summary
    total_actions = sum(len(ar.get("actions", [])) for ar in agent_results)
    total_posts = sum(
        1 for ar in agent_results
        for a in ar.get("actions", [])
        if a.get("agent") in ("post", "reflect", "essay", "fiction")
        and a.get("result", {}).get("status") == "ok"
    )
    total_comments = sum(
        1 for ar in agent_results
        for a in ar.get("actions", [])
        if a.get("agent") in ("comment", "reply")
        and a.get("result", {}).get("status") == "ok"
    )

    summary = {
        "stream": stream_name,
        "frame": frame,
        "agents": len(agent_ids),
        "total_actions": total_actions,
        "posts_created": total_posts,
        "comments_added": total_comments,
        "delta_path": str(delta_path) if delta_path else None,
        "agent_results": agent_results,
        "dry_run": dry_run,
    }

    if verbose:
        print(f"\n{'='*60}")
        print(f"Stream {stream_name} complete:")
        print(f"  Agents: {len(agent_ids)}")
        print(f"  Actions: {total_actions}")
        print(f"  Posts: {total_posts}")
        print(f"  Comments: {total_comments}")
        if dry_run:
            print(f"  [DRY RUN -- no actions executed]")
        print(f"{'='*60}")

    return summary


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Run one stream's agents through their brainstems.",
    )
    parser.add_argument(
        "--stream", required=True,
        help="Stream ID from stream_assignments.json (e.g., agent-1, focus-create).",
    )
    parser.add_argument(
        "--frame", type=int, default=0,
        help="Frame number (default: read from frame_counter.json).",
    )
    parser.add_argument(
        "--state-dir", type=str,
        default=os.environ.get("STATE_DIR", str(_repo_root / "state")),
        help="Path to state directory.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview without executing actions or LLM calls.",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Detailed output.",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output summary as JSON.",
    )
    args = parser.parse_args()

    # Configure logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s %(message)s")

    state_dir = Path(args.state_dir)

    # Resolve frame number
    frame = args.frame
    if frame == 0:
        counter = load_json(state_dir / "frame_counter.json")
        frame = counter.get("frame", 0)

    result = run_stream(
        stream_name=args.stream,
        frame=frame,
        state_dir=state_dir,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    elif not args.verbose:
        # Compact output for log files
        actions = result.get("total_actions", 0)
        posts = result.get("posts_created", 0)
        comments = result.get("comments_added", 0)
        agents = result.get("agents", 0)
        dr = " [DRY RUN]" if result.get("dry_run") else ""
        print(f"brainstem {args.stream}: {agents} agents, {actions} actions ({posts}p {comments}c){dr}")


if __name__ == "__main__":
    main()
