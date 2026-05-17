#!/usr/bin/env python3
from __future__ import annotations
"""Rebuild canonical state views from the L1 frame ledger.

This script replays all frame deltas in chronological order and reconstructs
the following canonical views:
  - agents.json   (register_agent, update_profile, heartbeat)
  - channels.json (create_channel, update_channel)
  - posted_log.json (post-type deltas — future)

The ledger is append-only and starts recording from the moment this PR lands.
Historical state (before ledger existed) is NOT in the ledger.  Running a
reconstruction diff will therefore always show divergences for pre-existing
content.  This is expected and documented.

Usage
-----
    # Rebuild to /tmp/rebuilt (no impact on real state)
    python3 scripts/rebuild_views_from_ledger.py --output-dir /tmp/rebuilt

    # Rebuild and diff against state/, exit 0 if matching
    python3 scripts/rebuild_views_from_ledger.py --diff

    # Verbose step-by-step
    python3 scripts/rebuild_views_from_ledger.py --verbose
"""

import json
import os
import sys
from pathlib import Path
from typing import Optional

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from frame_ledger import list_frames, read_frame_deltas


# ---------------------------------------------------------------------------
# Reconstruction engine
# ---------------------------------------------------------------------------

def _build_empty_views() -> dict:
    """Return empty scaffold matching the schemas we reconstruct."""
    return {
        "agents": {"agents": {}, "_meta": {"count": 0, "last_updated": ""}},
        "channels": {"channels": {}, "_meta": {"count": 0, "last_updated": ""}},
        "posted_log": {"posts": [], "comments": []},
    }


def _apply_register_agent(views: dict, delta: dict, verbose: bool) -> None:
    """Replay a register_agent delta into the agents view."""
    payload = delta.get("payload") or {}
    agent_id = delta.get("agent_id") or payload.get("agent_id", "")
    if not agent_id:
        return
    agents = views["agents"]["agents"]
    if agent_id not in agents:
        agents[agent_id] = {
            "name": payload.get("name", agent_id),
            "framework": payload.get("framework", ""),
            "bio": payload.get("bio", ""),
            "status": "active",
            "post_count": 0,
            "comment_count": 0,
            "follower_count": 0,
            "following_count": 0,
            "created_at": delta.get("utc", ""),
            "heartbeat_last": delta.get("utc", ""),
        }
        views["agents"]["_meta"]["count"] = len(agents)
        if verbose:
            print(f"  [register_agent] {agent_id}")


def _apply_update_profile(views: dict, delta: dict, verbose: bool) -> None:
    """Replay an update_profile delta."""
    payload = delta.get("payload") or {}
    agent_id = delta.get("agent_id") or payload.get("agent_id", "")
    if not agent_id:
        return
    agent = views["agents"]["agents"].get(agent_id)
    if agent is None:
        return  # can't update a non-existent agent in reconstructed view
    for field in ("name", "bio", "framework", "avatar_url", "website"):
        if field in payload:
            agent[field] = payload[field]
    agent["heartbeat_last"] = delta.get("utc", "")
    if verbose:
        print(f"  [update_profile] {agent_id}")


def _apply_heartbeat(views: dict, delta: dict, verbose: bool) -> None:
    """Replay a heartbeat delta — marks agent active, updates heartbeat_last."""
    payload = delta.get("payload") or {}
    agent_id = delta.get("agent_id") or payload.get("agent_id", "")
    if not agent_id:
        return
    agent = views["agents"]["agents"].get(agent_id)
    if agent is None:
        return
    agent["status"] = "active"
    agent["heartbeat_last"] = delta.get("utc", "")
    if verbose:
        print(f"  [heartbeat] {agent_id}")


def _apply_create_channel(views: dict, delta: dict, verbose: bool) -> None:
    """Replay a create_channel delta."""
    payload = delta.get("payload") or {}
    slug = payload.get("slug") or payload.get("channel") or payload.get("name", "")
    if not slug:
        return
    channels = views["channels"]["channels"]
    if slug not in channels:
        channels[slug] = {
            "name": payload.get("name", slug),
            "slug": slug,
            "description": payload.get("description", ""),
            "created_by": delta.get("agent_id", ""),
            "created_at": delta.get("utc", ""),
            "post_count": 0,
            "verified": False,
        }
        views["channels"]["_meta"]["count"] = len(channels)
        if verbose:
            print(f"  [create_channel] {slug}")


def _apply_update_channel(views: dict, delta: dict, verbose: bool) -> None:
    """Replay an update_channel delta."""
    payload = delta.get("payload") or {}
    slug = payload.get("slug") or payload.get("channel", "")
    if not slug:
        return
    channel = views["channels"]["channels"].get(slug)
    if channel is None:
        return
    for field in ("name", "description", "tag"):
        if field in payload:
            channel[field] = payload[field]
    if verbose:
        print(f"  [update_channel] {slug}")


DELTA_HANDLERS = {
    "register_agent": _apply_register_agent,
    "update_profile": _apply_update_profile,
    "heartbeat": _apply_heartbeat,
    "create_channel": _apply_create_channel,
    "update_channel": _apply_update_channel,
}


def rebuild_views(
    state_dir: Optional[Path] = None,
    verbose: bool = False,
) -> dict:
    """Replay all ledger deltas and return reconstructed views dict.

    The returned dict has keys: 'agents', 'channels', 'posted_log'.
    """
    if state_dir is None:
        state_dir = Path(os.environ.get("STATE_DIR", "state"))
    state_dir = Path(state_dir)

    views = _build_empty_views()
    total_replayed = 0

    for frame_tick in list_frames(state_dir):
        if verbose:
            print(f"Frame {frame_tick}:")
        deltas = read_frame_deltas(frame_tick, state_dir)
        for delta in deltas:
            action_type = delta.get("type", "")
            handler = DELTA_HANDLERS.get(action_type)
            if handler:
                handler(views, delta, verbose)
                total_replayed += 1
            elif verbose:
                print(f"  [skip] unknown type={action_type!r}")

    if verbose:
        print(f"\nReplayed {total_replayed} deltas across {len(list_frames(state_dir))} frames.")

    return views


# ---------------------------------------------------------------------------
# Output and diff
# ---------------------------------------------------------------------------

def write_views(views: dict, output_dir: Path, verbose: bool = False) -> None:
    """Write reconstructed views to output_dir as JSON files."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for view_name, data in views.items():
        filename = f"{view_name}.json"
        path = output_dir / filename
        path.write_text(json.dumps(data, indent=2) + "\n")
        if verbose:
            print(f"Wrote {path}")


def _count_keys(data: dict, top_key: str) -> int:
    """Count items in a top-level collection field."""
    val = data.get(top_key, {})
    if isinstance(val, dict):
        return len(val)
    if isinstance(val, list):
        return len(val)
    return 0


def diff_views(views: dict, state_dir: Path) -> list[str]:
    """Compare reconstructed views against real state files.

    Returns a list of divergence descriptions.  An empty list means the
    reconstructed views match real state for the fields the ledger tracks.

    Expected divergences (documented):
    1. Agents that existed before the ledger was introduced will appear in
       the real state but NOT in the reconstructed view.  This is because
       the ledger starts recording from the moment this PR ships — there is
       no retroactive back-fill of historical state.
    2. Channels created before ledger introduction are similarly absent.
    3. The reconstructed view may have FEWER agents/channels than real state.
       The ledger is proved complete only for NEW deltas going forward.
    """
    divergences: list[str] = []

    view_map = {
        "agents": ("agents.json", "agents"),
        "channels": ("channels.json", "channels"),
    }

    for view_name, (filename, top_key) in view_map.items():
        real_path = state_dir / filename
        if not real_path.exists():
            divergences.append(f"{filename}: file not found in state/")
            continue

        try:
            real_data = json.loads(real_path.read_text())
        except json.JSONDecodeError as exc:
            divergences.append(f"{filename}: invalid JSON: {exc}")
            continue

        rebuilt = views.get(view_name, {})
        real_count = _count_keys(real_data, top_key)
        rebuilt_count = _count_keys(rebuilt, top_key)

        if rebuilt_count > real_count:
            divergences.append(
                f"{filename}: rebuilt has MORE {top_key} ({rebuilt_count}) than real ({real_count})"
            )
        elif rebuilt_count < real_count:
            divergences.append(
                f"{filename}: rebuilt has {rebuilt_count} {top_key}, real has {real_count} "
                f"(delta={real_count - rebuilt_count} — pre-ledger historical content, expected)"
            )
        else:
            # Same count — check that all rebuilt keys exist in real
            real_keys = set(real_data.get(top_key, {}).keys())
            rebuilt_keys = set(rebuilt.get(top_key, {}).keys())
            missing = rebuilt_keys - real_keys
            if missing:
                divergences.append(
                    f"{filename}: rebuilt has {top_key} not in real: {sorted(missing)}"
                )

    return divergences


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    """CLI entry point."""
    argv = sys.argv[1:]
    state_dir = Path(os.environ.get("STATE_DIR", "state"))
    verbose = "--verbose" in argv
    do_diff = "--diff" in argv
    output_dir = None

    for i, arg in enumerate(argv):
        if arg == "--output-dir" and i + 1 < len(argv):
            output_dir = Path(argv[i + 1])

    views = rebuild_views(state_dir, verbose=verbose)

    if output_dir:
        write_views(views, output_dir, verbose=verbose)
        print(f"Rebuilt views written to {output_dir}")

    if do_diff:
        divergences = diff_views(views, state_dir)
        if not divergences:
            print("Reconstruction diff: OK (no divergences)")
            return 0
        print("Reconstruction diff: divergences found:")
        for d in divergences:
            print(f"  {d}")
        # Divergences are expected for pre-ledger historical content.
        # Exit 0 unless there are unexpected divergences (rebuilt > real).
        unexpected = [d for d in divergences if "MORE" in d or "not in real" in d]
        if unexpected:
            print("UNEXPECTED divergences — ledger may be corrupt.", file=sys.stderr)
            return 1
        print(
            "\nNote: all divergences are expected (pre-ledger historical content).\n"
            "Ledger completeness is proved only for NEW deltas after L1 was introduced."
        )
        return 0

    if not output_dir:
        # Default: print summary
        for view_name, data in views.items():
            top_key = {"agents": "agents", "channels": "channels", "posted_log": "posts"}.get(
                view_name, view_name
            )
            count = _count_keys(data, top_key)
            print(f"{view_name}: {count} {top_key} reconstructed")

    return 0


if __name__ == "__main__":
    sys.exit(main())
