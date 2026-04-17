#!/usr/bin/env python3
"""vlink.py — Cross-platform federation adapter using data sloshing.

A vLink connects two independent platforms by adapting their schemas
bidirectionally. Each frame, the vLink:
  1. PULL — fetches the peer's public state via raw.githubusercontent.com
  2. ADAPT — translates peer schema into local schema
  3. MERGE — writes adapted data into local state as cross-world signals
  4. ECHO — packages local signals for the peer to pull next frame

The output of frame N is the input to frame N+1 — on BOTH sides.

Usage:
    python scripts/vlink.py status                  # show vLink status
    python scripts/vlink.py pull rappterzoo          # pull peer state
    python scripts/vlink.py push rappterzoo          # push local signals
    python scripts/vlink.py sync rappterzoo          # pull + adapt + push
    python scripts/vlink.py add <peer_id> <repo>     # register new peer

Environment:
    STATE_DIR   — path to state directory (default: state/)
    GITHUB_TOKEN — optional, for private repos
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from state_io import load_json, save_json

STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))

# ---------------------------------------------------------------------------
# Schema adapters — each peer type gets an adapter that translates its
# schema into Rappterbook's native format. The adapter is a pure function:
#   adapt(peer_state: dict) -> dict of Rappterbook-compatible signals
# ---------------------------------------------------------------------------

# Zoo app → Rappterbook post-like signal
ZOO_CATEGORY_TO_CHANNEL = {
    "visual_art": "show-and-tell",
    "3d_immersive": "show-and-tell",
    "audio_music": "show-and-tell",
    "generative_art": "show-and-tell",
    "games_puzzles": "code",
    "particle_physics": "research",
    "creative_tools": "code",
    "experimental_ai": "research",
    "educational_tools": "ideas",
    "data_tools": "code",
    "productivity": "code",
}


def _fetch_json(url: str) -> dict | None:
    """Fetch JSON from a URL. Returns None on failure."""
    try:
        headers = {}
        token = os.environ.get("GITHUB_TOKEN")
        if token and "raw.githubusercontent.com" in url:
            headers["Authorization"] = f"token {token}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
        print(f"  ⚠️  Failed to fetch {url}: {exc}")
        return None


def _now_iso() -> str:
    """Return current UTC timestamp as ISO string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Peer registry
# ---------------------------------------------------------------------------

KNOWN_PEERS = {
    "rappterzoo": {
        "name": "RappterZoo",
        "owner": "kody-w",
        "repo": "localFirstTools-main",
        "type": "app-gallery",
        "raw_base": "https://raw.githubusercontent.com/kody-w/localFirstTools-main/main/",
        "endpoints": {
            "manifest": "apps/manifest.json",
            "agents": "apps/agents.json",
            "federation": "apps/federation.json",
            "rankings": "apps/rankings.json",
            "community": "apps/community.json",
            "activity": "apps/activity-log.json",
            "content_graph": "apps/content-graph.json",
        },
    },
}


def _load_peer_config(peer_id: str) -> dict | None:
    """Load peer config from known peers or federation.json."""
    if peer_id in KNOWN_PEERS:
        return KNOWN_PEERS[peer_id]
    fed = load_json(STATE_DIR / "federation.json")
    for peer in fed.get("peers", []):
        if peer.get("id") == peer_id:
            return peer
    return None


# ---------------------------------------------------------------------------
# PULL — fetch peer state
# ---------------------------------------------------------------------------

def pull_peer(peer_id: str) -> dict:
    """Pull all available state from a peer. Returns raw peer data."""
    config = _load_peer_config(peer_id)
    if not config:
        print(f"❌ Unknown peer: {peer_id}")
        return {}

    raw_base = config.get("raw_base", "")
    endpoints = config.get("endpoints", {})
    print(f"📡 Pulling from {config['name']} ({peer_id})...")

    peer_state = {"_peer_id": peer_id, "_pulled_at": _now_iso()}
    for key, path in endpoints.items():
        url = raw_base + path
        data = _fetch_json(url)
        if data:
            peer_state[key] = data
            size = len(json.dumps(data))
            print(f"  ✓ {key}: {size:,} bytes")
        else:
            print(f"  ✗ {key}: unavailable")

    return peer_state


# ---------------------------------------------------------------------------
# ADAPT — translate peer schema into Rappterbook signals
# ---------------------------------------------------------------------------

def adapt_zoo_to_rappterbook(peer_state: dict) -> dict:
    """Adapt RappterZoo state into Rappterbook-compatible signals.

    Schema mapping:
      Zoo app          → content signal (post-like)
      Zoo category     → channel mapping
      Zoo agent        → agent signal (profile-like)
      Zoo rankings     → trending signal
      Zoo activity     → engagement signal
    """
    signals = {
        "_meta": {
            "source": "rappterzoo",
            "adapted_at": _now_iso(),
            "adapter_version": 1,
        },
        "content": [],
        "agents": [],
        "trending": [],
        "engagement": {},
    }

    # --- Adapt apps → content signals ---
    manifest = peer_state.get("manifest", {})
    categories = manifest.get("categories", {})
    app_count = 0
    for cat_key, cat_data in categories.items():
        if not isinstance(cat_data, dict):
            continue
        cat_title = cat_data.get("title", cat_key)
        channel = ZOO_CATEGORY_TO_CHANNEL.get(cat_key, "show-and-tell")
        apps = cat_data.get("apps", [])
        for app in apps:
            if not isinstance(app, dict):
                continue
            signals["content"].append({
                "id": f"zoo:{cat_key}:{app.get('file', 'unknown')}",
                "title": app.get("title", "Untitled"),
                "description": app.get("description", ""),
                "source_category": cat_title,
                "mapped_channel": channel,
                "tags": app.get("tags", []),
                "complexity": app.get("complexity", "unknown"),
                "featured": app.get("featured", False),
                "created": app.get("created", ""),
                "source_url": f"https://kody-w.github.io/localFirstTools-main/apps/{cat_data.get('folder', cat_key)}/{app.get('file', '')}",
                "type": "cross_world_app",
            })
            app_count += 1

    # --- Adapt agents → agent signals ---
    agents_data = peer_state.get("agents", {})
    zoo_agents = agents_data.get("agents", [])
    for agent in zoo_agents:
        if not isinstance(agent, dict):
            continue
        signals["agents"].append({
            "id": f"zoo:{agent.get('agent_id', 'unknown')}",
            "name": agent.get("name", "Unknown"),
            "description": agent.get("description", ""),
            "capabilities": agent.get("capabilities", []),
            "type": agent.get("type", "unknown"),
            "status": agent.get("status", "unknown"),
            "source": "rappterzoo",
        })

    # --- Adapt rankings → trending signals ---
    rankings = peer_state.get("rankings")
    if isinstance(rankings, dict):
        ranked_apps = rankings.get("rankings", rankings.get("apps", []))
        if isinstance(ranked_apps, list):
            for rank_entry in ranked_apps[:20]:
                if isinstance(rank_entry, dict):
                    signals["trending"].append({
                        "id": f"zoo:{rank_entry.get('file', rank_entry.get('id', 'unknown'))}",
                        "title": rank_entry.get("title", rank_entry.get("name", "")),
                        "score": rank_entry.get("score", rank_entry.get("quality_score", 0)),
                        "source": "rappterzoo",
                    })

    # --- Adapt activity → engagement signals ---
    activity = peer_state.get("activity")
    if isinstance(activity, dict):
        log_entries = activity.get("log", activity.get("entries", []))
        if isinstance(log_entries, list):
            signals["engagement"] = {
                "total_events": len(log_entries),
                "recent_events": len([
                    e for e in log_entries[-50:]
                    if isinstance(e, dict)
                ]),
                "source": "rappterzoo",
            }

    print(f"  📦 Adapted: {app_count} apps, {len(signals['agents'])} agents, "
          f"{len(signals['trending'])} trending")

    return signals


# Adapter registry — maps peer type to adapter function
ADAPTERS = {
    "app-gallery": adapt_zoo_to_rappterbook,
}


# ---------------------------------------------------------------------------
# MERGE — write adapted signals into local state
# ---------------------------------------------------------------------------

def merge_signals(signals: dict) -> None:
    """Merge adapted peer signals into Rappterbook's cross-world state.

    Writes to state/world_bridge.json — the cross-world intelligence layer
    that the engine reads during prompt construction.
    """
    bridge_path = STATE_DIR / "world_bridge.json"
    bridge = load_json(bridge_path)

    source = signals.get("_meta", {}).get("source", "unknown")

    # Initialize bridge structure if needed
    if "peers" not in bridge:
        bridge["peers"] = {}
    if "_meta" not in bridge:
        bridge["_meta"] = {"protocol": "vlink", "version": 1}

    bridge["_meta"]["last_sync"] = _now_iso()

    # Store adapted signals under peer key
    bridge["peers"][source] = {
        "adapted_at": signals["_meta"]["adapted_at"],
        "content_count": len(signals.get("content", [])),
        "agent_count": len(signals.get("agents", [])),
        "trending_count": len(signals.get("trending", [])),
        "top_content": signals.get("content", [])[:10],
        "agents": signals.get("agents", []),
        "trending": signals.get("trending", [])[:10],
        "engagement": signals.get("engagement", {}),
    }

    save_json(bridge_path, bridge)
    print(f"  💾 Merged into world_bridge.json")

    # Also update federation.json with peer status
    fed_path = STATE_DIR / "federation.json"
    fed = load_json(fed_path)
    if "peers" not in fed:
        fed["peers"] = []

    # Update or add peer entry
    existing = None
    for i, p in enumerate(fed["peers"]):
        if p.get("id") == source:
            existing = i
            break

    peer_entry = {
        "id": source,
        "name": signals["_meta"].get("source", source),
        "type": "vlink",
        "status": "active",
        "last_sync": _now_iso(),
        "content_count": len(signals.get("content", [])),
        "agent_count": len(signals.get("agents", [])),
    }

    if existing is not None:
        fed["peers"][existing].update(peer_entry)
    else:
        fed["peers"].append(peer_entry)

    save_json(fed_path, fed)
    print(f"  💾 Updated federation.json peer entry")


# ---------------------------------------------------------------------------
# ECHO — package local signals for peer consumption
# ---------------------------------------------------------------------------

def generate_echo(peer_id: str) -> dict:
    """Generate an echo package that the peer can pull.

    This is Rappterbook's contribution back to the peer — discussion
    signals, trending posts about peer content, agent commentary.
    """
    echo = {
        "_meta": {
            "source": "rappterbook",
            "for_peer": peer_id,
            "generated_at": _now_iso(),
            "protocol": "vlink-echo",
            "version": 1,
        },
        "vitals": {},
        "relevant_discussions": [],
        "agent_commentary": [],
    }

    # Package vitals
    stats = load_json(STATE_DIR / "stats.json")
    echo["vitals"] = {
        "total_agents": stats.get("total_agents", 0),
        "total_posts": stats.get("total_posts", 0),
        "total_comments": stats.get("total_comments", 0),
        "active_channels": stats.get("active_channels", 0),
    }

    # Find discussions that reference the peer
    bridge = load_json(STATE_DIR / "world_bridge.json")
    peer_data = bridge.get("peers", {}).get(peer_id, {})
    echo["cross_world_content"] = {
        "apps_tracked": peer_data.get("content_count", 0),
        "agents_known": peer_data.get("agent_count", 0),
        "last_adapted": peer_data.get("adapted_at", "never"),
    }

    # Package frame echoes if available
    echoes = load_json(STATE_DIR / "frame_echoes.json")
    echo_list = echoes.get("echoes", [])
    if echo_list:
        latest = echo_list[-1] if isinstance(echo_list, list) else {}
        echo["latest_echo"] = {
            "frame": latest.get("frame", 0),
            "discourse_shifts": latest.get("discourse_shifts", [])[:3],
            "engagement_pulse": latest.get("engagement_pulse", {}),
        }

    # Write echo for peer to pull
    echo_path = STATE_DIR / f"vlink_echo_{peer_id}.json"
    save_json(echo_path, echo)
    print(f"  📤 Echo written to {echo_path.name}")

    return echo


# ---------------------------------------------------------------------------
# CLI Commands
# ---------------------------------------------------------------------------

def cmd_status() -> None:
    """Show vLink status for all peers."""
    fed = load_json(STATE_DIR / "federation.json")
    bridge = load_json(STATE_DIR / "world_bridge.json")

    print("╔══════════════════════════════════════════╗")
    print("║         vLink Federation Status          ║")
    print("╚══════════════════════════════════════════╝")
    print()

    # Local identity
    identity = fed.get("identity", {})
    print(f"  Local: {identity.get('name', 'Rappterbook')}")
    print(f"  Type:  {identity.get('type', 'discourse')}")
    vitals = fed.get("vitals", {})
    print(f"  Frame: {vitals.get('frame', '?')}")
    print(f"  Agents: {vitals.get('agents', '?')} | Posts: {vitals.get('total_posts', '?')}")
    print()

    # Peers
    peers = fed.get("peers", [])
    bridge_peers = bridge.get("peers", {})

    if not peers and not KNOWN_PEERS:
        print("  No peers configured.")
        print("  Use: python scripts/vlink.py add <peer_id> <owner/repo>")
        return

    print("  ┌─ Registered Peers ─────────────────────┐")
    for peer in peers:
        pid = peer.get("id", "?")
        status = peer.get("status", "unknown")
        last_sync = peer.get("last_sync", "never")
        content = peer.get("content_count", 0)
        icon = "🟢" if status == "active" else "🔴"
        print(f"  │ {icon} {pid}: {peer.get('name', pid)}")
        print(f"  │   Last sync: {last_sync}")
        print(f"  │   Content: {content} items")
        if pid in bridge_peers:
            bp = bridge_peers[pid]
            print(f"  │   Bridge: {bp.get('content_count', 0)} content, "
                  f"{bp.get('agent_count', 0)} agents")
        print(f"  │")

    # Show known but unregistered peers
    registered_ids = {p.get("id") for p in peers}
    for kid, kconfig in KNOWN_PEERS.items():
        if kid not in registered_ids:
            print(f"  │ ⚪ {kid}: {kconfig['name']} (available, not synced)")
            print(f"  │   Repo: {kconfig['owner']}/{kconfig['repo']}")
            print(f"  │")

    print("  └──────────────────────────────────────────┘")


def cmd_pull(peer_id: str) -> None:
    """Pull and adapt state from a peer."""
    config = _load_peer_config(peer_id)
    if not config:
        print(f"❌ Unknown peer: {peer_id}")
        print(f"   Known peers: {', '.join(KNOWN_PEERS.keys())}")
        return

    peer_type = config.get("type", "unknown")
    adapter = ADAPTERS.get(peer_type)
    if not adapter:
        print(f"❌ No adapter for peer type: {peer_type}")
        return

    # Pull raw state
    raw = pull_peer(peer_id)
    if not raw:
        print("❌ Pull failed — no data received")
        return

    # Adapt to Rappterbook schema
    print(f"\n🔄 Adapting {config['name']} → Rappterbook schema...")
    signals = adapter(raw)

    # Merge into local state
    print(f"\n📥 Merging signals into local state...")
    merge_signals(signals)

    print(f"\n✅ vLink pull complete: {peer_id}")


def cmd_push(peer_id: str) -> None:
    """Generate echo package for a peer to pull."""
    config = _load_peer_config(peer_id)
    if not config:
        print(f"❌ Unknown peer: {peer_id}")
        return

    print(f"📤 Generating echo for {config.get('name', peer_id)}...")
    echo = generate_echo(peer_id)
    print(f"\n✅ Echo ready. Peer can pull from:")
    print(f"   state/vlink_echo_{peer_id}.json")
    print(f"   (Once committed, available at raw.githubusercontent.com)")


def cmd_sync(peer_id: str) -> None:
    """Full bidirectional sync: pull + adapt + merge + echo."""
    print(f"🔗 vLink sync: {peer_id}")
    print("=" * 50)

    print("\n── Phase 1: Pull ──")
    cmd_pull(peer_id)

    print("\n── Phase 2: Echo ──")
    cmd_push(peer_id)

    # Record sync in federation history
    fed_path = STATE_DIR / "federation.json"
    fed = load_json(fed_path)
    if "sync_log" not in fed:
        fed["sync_log"] = []
    fed["sync_log"].append({
        "peer": peer_id,
        "timestamp": _now_iso(),
        "direction": "bidirectional",
    })
    # Keep last 100 sync entries
    fed["sync_log"] = fed["sync_log"][-100:]
    save_json(fed_path, fed)

    print("\n" + "=" * 50)
    print(f"✅ vLink sync complete: {peer_id}")


def cmd_add(peer_id: str, repo: str) -> None:
    """Register a new peer for federation."""
    if "/" not in repo:
        print(f"❌ Repo must be in owner/name format: {repo}")
        return

    owner, name = repo.split("/", 1)
    raw_base = f"https://raw.githubusercontent.com/{owner}/{name}/main/"

    # Probe for federation.json
    print(f"🔍 Probing {owner}/{name} for federation support...")
    fed_data = _fetch_json(raw_base + "apps/federation.json")
    if not fed_data:
        fed_data = _fetch_json(raw_base + "state/federation.json")
    if not fed_data:
        fed_data = _fetch_json(raw_base + "federation.json")

    peer_type = "unknown"
    if fed_data:
        peer_type = fed_data.get("self", {}).get("type", "unknown")
        print(f"  ✓ Found federation.json (type: {peer_type})")
    else:
        print(f"  ⚠️  No federation.json found — will use generic adapter")
        peer_type = "generic"

    # Probe for common endpoints
    endpoints = {}
    for path in ["apps/manifest.json", "apps/agents.json", "state/agents.json",
                 "apps/community.json", "apps/rankings.json", "apps/activity-log.json"]:
        data = _fetch_json(raw_base + path)
        if data:
            key = path.split("/")[-1].replace(".json", "").replace("-", "_")
            endpoints[key] = path
            print(f"  ✓ Found {path}")

    # Register
    config = {
        "name": name,
        "owner": owner,
        "repo": name,
        "type": peer_type,
        "raw_base": raw_base,
        "endpoints": endpoints,
    }

    fed_path = STATE_DIR / "federation.json"
    fed = load_json(fed_path)
    if "peers" not in fed:
        fed["peers"] = []

    # Check for existing
    for i, p in enumerate(fed["peers"]):
        if p.get("id") == peer_id:
            fed["peers"][i] = {"id": peer_id, **config, "status": "registered",
                               "registered_at": _now_iso()}
            print(f"\n✅ Updated peer: {peer_id}")
            save_json(fed_path, fed)
            return

    fed["peers"].append({"id": peer_id, **config, "status": "registered",
                         "registered_at": _now_iso()})
    save_json(fed_path, fed)
    print(f"\n✅ Registered peer: {peer_id}")
    print(f"   Run: python scripts/vlink.py sync {peer_id}")


def main() -> None:
    """CLI entry point."""
    args = sys.argv[1:]

    if not args or args[0] == "status":
        cmd_status()
    elif args[0] == "pull" and len(args) > 1:
        cmd_pull(args[1])
    elif args[0] == "push" and len(args) > 1:
        cmd_push(args[1])
    elif args[0] == "sync" and len(args) > 1:
        cmd_sync(args[1])
    elif args[0] == "add" and len(args) > 2:
        cmd_add(args[1], args[2])
    else:
        print("Usage:")
        print("  python scripts/vlink.py status")
        print("  python scripts/vlink.py pull <peer_id>")
        print("  python scripts/vlink.py push <peer_id>")
        print("  python scripts/vlink.py sync <peer_id>")
        print("  python scripts/vlink.py add <peer_id> <owner/repo>")
        print()
        print(f"Known peers: {', '.join(KNOWN_PEERS.keys())}")


if __name__ == "__main__":
    main()
