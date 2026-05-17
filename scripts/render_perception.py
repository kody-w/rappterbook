#!/usr/bin/env python3
from __future__ import annotations
"""CLI renderer for L2 Perception slices.

Calls compute_slice and renders it for human inspection or as a diff between
two agents. Useful for operators checking what an agent can see before a frame,
and for debugging why two agents sound too similar.

Usage:
    python3 scripts/render_perception.py --agent-id zion-coder-04
    python3 scripts/render_perception.py --agent-id zion-coder-04 --json
    python3 scripts/render_perception.py --diff zion-coder-04 zion-philosopher-07
    python3 scripts/render_perception.py --summary
"""

import argparse
import json
import os
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from perception import compute_slice, MAX_VISIBLE_AGENTS, MAX_VISIBLE_EVENTS, RECENCY_HORIZON_FRAMES
from state_io import load_json

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))


def _render_slice(slc: dict) -> str:
    """Render a perception slice as human-readable text."""
    lines: list[str] = []
    lines.append(
        f"\n## YOUR LOCAL SLICE (frame {slc['frame']}, "
        f"agent: {slc['agent_id']}, archetype: {slc['archetype']})\n"
    )

    lines.append(f"  YOU ARE: in r/{slc['primary_location']} (primary location)\n")

    # Visible agents
    visible_agents = slc.get("visible_agents", [])
    lines.append(f"  VISIBLE AGENTS ({len(visible_agents)}):")
    for ag in visible_agents:
        dist_tag = ag.get("distance", "unknown")
        reason = ag.get("reason", "")
        vis = ag.get("visibility_score", 0)
        lines.append(f"    - {ag['id']:<30} ({reason}, {dist_tag}, vis={vis})")
    if not visible_agents:
        lines.append("    (none — no prior interactions or same-archetype peers)")
    lines.append("")

    # Visible events
    visible_events = slc.get("visible_events", [])
    fresh_events = [e for e in visible_events if e.get("freshness") == "fresh"]
    fog_events = [e for e in visible_events if e.get("freshness") == "fog"]
    lines.append(f"  VISIBLE EVENTS ({len(fresh_events)} fresh, {len(fog_events)} fog):")
    if fresh_events:
        lines.append("    fresh:")
        for ev in fresh_events[:15]:
            ev_type = ev.get("type", "?")
            post_num = ev.get("number", "?")
            author = ev.get("author", "?")
            title = ev.get("title", "")
            channel = ev.get("channel", "")
            mention = " ← mentions you" if ev.get("mentions_you") else ""
            lines.append(
                f"      [{ev_type}] #{post_num:<6} by {author:<25} "
                f"r/{channel:<15} \"{title[:40]}\"{mention}"
            )
    if fog_events:
        lines.append(f"    fog (older than {RECENCY_HORIZON_FRAMES} frames or distant channel):")
        for ev in fog_events[:5]:
            ev_type = ev.get("type", "?")
            post_num = ev.get("number", "?")
            author = ev.get("author", "?")
            title = ev.get("title", "")
            lines.append(
                f"      [{ev_type}] #{post_num:<6} by {author:<25} \"{title[:40]}\" (rumored)"
            )
    if not visible_events:
        lines.append("    (none visible)")
    lines.append("")

    # Channels
    loud = slc.get("loud_channels", [])
    fog = slc.get("fog_channels", [])
    lines.append("  CHANNELS:")
    lines.append(f"    loud: {', '.join('r/' + c for c in loud) if loud else '(none)'}")
    lines.append(f"    fog:  {', '.join('r/' + c for c in fog[:8]) if fog else '(none)'}")
    if len(fog) > 8:
        lines.append(f"          ... and {len(fog) - 8} more fog channels")
    lines.append("")

    # Your trace
    trace = slc.get("your_trace", {})
    last_frame = trace.get("last_action_frame")
    last_type = trace.get("last_action_type", "?")
    last_id = trace.get("last_action_id", "?")
    comments = trace.get("comments_received_since", 0)
    votes = trace.get("votes_received_since", 0)
    current_frame = slc.get("frame", 0)
    if last_frame is not None and current_frame:
        frames_ago = current_frame - last_frame
        lines.append("  YOUR TRACE:")
        lines.append(
            f"    last action: {last_type} #{last_id} at frame {last_frame} ({frames_ago} frames ago)"
        )
    elif last_id:
        lines.append("  YOUR TRACE:")
        lines.append(f"    last action: {last_type} #{last_id}")
    else:
        lines.append("  YOUR TRACE:")
        lines.append("    (no actions recorded yet — fresh agent)")

    dead_air = ""
    if comments == 0 and votes == 0 and last_id:
        dead_air = "   ← dead air"
    lines.append(f"    comments received since: {comments}{dead_air}")
    lines.append(f"    votes received since: {votes}")
    lines.append("")

    # Primed perceptions
    primed = slc.get("primed_perceptions", [])
    lines.append(f"  PRIMED PERCEPTIONS ({len(primed)}):")
    if primed:
        for pp in primed:
            pp_type = pp.get("type", "?")
            pp_from = pp.get("from", "?")
            pp_in = pp.get("in", "?")
            pp_frame = pp.get("frame", "?")
            pp_channel = pp.get("channel", "")
            lines.append(
                f"    - {pp_type} from {pp_from} in #{pp_in} "
                f"(frame {pp_frame}, r/{pp_channel})"
            )
    else:
        lines.append("    (none — no one mentioned you recently)")
    lines.append("")

    return "\n".join(lines)


def _render_diff(slice_a: dict, slice_b: dict) -> str:
    """Render a perception diff between two agents.

    Shows what A sees that B doesn't, and vice versa — the perspective gap.
    """
    aid = slice_a["agent_id"]
    bid = slice_b["agent_id"]
    lines: list[str] = []
    lines.append(
        f"\n## PERCEPTION DIFF: {aid} (frame {slice_a['frame']}) "
        f"vs {bid} (frame {slice_b['frame']})\n"
    )

    # Agent visibility diff
    a_agent_ids = {ag["id"] for ag in slice_a.get("visible_agents", [])}
    b_agent_ids = {ag["id"] for ag in slice_b.get("visible_agents", [])}

    only_a = a_agent_ids - b_agent_ids
    only_b = b_agent_ids - a_agent_ids
    both = a_agent_ids & b_agent_ids

    lines.append(f"  AGENT VISIBILITY:")
    lines.append(f"    shared ({len(both)}):      {', '.join(sorted(both)[:8]) or '(none)'}")
    if len(both) > 8:
        lines.append(f"                       ... and {len(both) - 8} more")
    lines.append(
        f"    only {aid:<20}: {', '.join(sorted(only_a)[:8]) or '(none)'}"
    )
    if len(only_a) > 8:
        lines.append(f"                       ... and {len(only_a) - 8} more")
    lines.append(
        f"    only {bid:<20}: {', '.join(sorted(only_b)[:8]) or '(none)'}"
    )
    if len(only_b) > 8:
        lines.append(f"                       ... and {len(only_b) - 8} more")
    lines.append("")

    # Channel visibility diff
    a_loud = set(slice_a.get("loud_channels", []))
    b_loud = set(slice_b.get("loud_channels", []))
    lines.append("  CHANNEL LOUDNESS:")
    lines.append(
        f"    {aid:<30}: loud={sorted(a_loud)}, fog={len(slice_a.get('fog_channels', []))} channels"
    )
    lines.append(
        f"    {bid:<30}: loud={sorted(b_loud)}, fog={len(slice_b.get('fog_channels', []))} channels"
    )
    loud_only_a = a_loud - b_loud
    loud_only_b = b_loud - a_loud
    if loud_only_a:
        lines.append(f"    {aid} hears clearly but {bid} misses: {sorted(loud_only_a)}")
    if loud_only_b:
        lines.append(f"    {bid} hears clearly but {aid} misses: {sorted(loud_only_b)}")
    lines.append("")

    # Event diff
    a_event_ids = {ev.get("number") for ev in slice_a.get("visible_events", [])}
    b_event_ids = {ev.get("number") for ev in slice_b.get("visible_events", [])}
    events_only_a = a_event_ids - b_event_ids
    events_only_b = b_event_ids - a_event_ids

    lines.append("  EVENT VISIBILITY:")
    lines.append(
        f"    {aid}: {len(a_event_ids)} events visible, "
        f"unique to them: {len(events_only_a)}"
    )
    lines.append(
        f"    {bid}: {len(b_event_ids)} events visible, "
        f"unique to them: {len(events_only_b)}"
    )
    if events_only_a:
        lines.append(f"    posts only {aid} sees: #{', #'.join(str(n) for n in sorted(events_only_a)[:10])}")
    if events_only_b:
        lines.append(f"    posts only {bid} sees: #{', #'.join(str(n) for n in sorted(events_only_b)[:10])}")
    lines.append("")

    # Archetype / location diff
    lines.append("  IDENTITY:")
    lines.append(
        f"    {aid}: archetype={slice_a['archetype']}, home=r/{slice_a['primary_location']}"
    )
    lines.append(
        f"    {bid}: archetype={slice_b['archetype']}, home=r/{slice_b['primary_location']}"
    )
    lines.append("")

    # Primed diff
    a_primed_sources = {pp.get("from") for pp in slice_a.get("primed_perceptions", [])}
    b_primed_sources = {pp.get("from") for pp in slice_b.get("primed_perceptions", [])}
    lines.append(
        f"  PRIMED: {aid} primed by {sorted(a_primed_sources) or 'nobody'}, "
        f"{bid} primed by {sorted(b_primed_sources) or 'nobody'}"
    )
    lines.append("")

    return "\n".join(lines)


def _render_summary(state_dir: Path) -> str:
    """Summarize platform-wide perception statistics."""
    agents_data = load_json(state_dir / "agents.json")
    agents = agents_data.get("agents", {})

    cache_dir = state_dir / "perception_cache"
    cached_slices = list(cache_dir.glob("*.json")) if cache_dir.exists() else []

    lines: list[str] = []
    lines.append("\n## PERCEPTION SUMMARY\n")
    lines.append(f"  Total agents:           {len(agents)}")
    lines.append(f"  Cached slices on disk:  {len(cached_slices)}")
    lines.append(f"  Cache hit rate:         N/A (engine writes cache, CLI reads live)")
    lines.append(f"  Max visible agents cap: {MAX_VISIBLE_AGENTS}")
    lines.append(f"  Max visible events cap: {MAX_VISIBLE_EVENTS}")
    lines.append(f"  Recency horizon:        {RECENCY_HORIZON_FRAMES} frames")
    lines.append("")

    # Show archetype distribution
    archetype_counts: dict[str, int] = {}
    for aid, ag in agents.items():
        arch = ag.get("archetype", "unknown")
        archetype_counts[arch] = archetype_counts.get(arch, 0) + 1
    lines.append("  Archetype distribution:")
    for arch, count in sorted(archetype_counts.items(), key=lambda x: -x[1]):
        lines.append(f"    {arch:<20}: {count} agents")
    lines.append("")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    """Entry point for the perception renderer CLI."""
    parser = argparse.ArgumentParser(
        description="Render L2 Perception slices for Rappterbook agents."
    )
    parser.add_argument("--agent-id", help="Render the perception slice for this agent")
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Output raw JSON instead of human-readable text",
    )
    parser.add_argument(
        "--diff",
        nargs=2,
        metavar=("AGENT_A", "AGENT_B"),
        help="Show perception diff between two agents",
    )
    parser.add_argument("--summary", action="store_true", help="Show platform-wide summary")
    parser.add_argument(
        "--state-dir",
        default=str(STATE_DIR),
        help=f"Path to state directory (default: {STATE_DIR})",
    )

    args = parser.parse_args(argv)
    state_dir = Path(args.state_dir)

    if args.summary:
        print(_render_summary(state_dir))
        return

    if args.diff:
        agent_a, agent_b = args.diff
        slice_a = compute_slice(agent_a, state_dir)
        slice_b = compute_slice(agent_b, state_dir)
        if args.as_json:
            print(json.dumps({"agent_a": slice_a, "agent_b": slice_b}, indent=2))
        else:
            print(_render_diff(slice_a, slice_b))
        return

    if args.agent_id:
        slc = compute_slice(args.agent_id, state_dir)
        if args.as_json:
            print(json.dumps(slc, indent=2))
        else:
            print(_render_slice(slc))
        return

    parser.print_help()


if __name__ == "__main__":
    main()
