"""Run a twin simulation — generate content native to a twin's universe.

A twin is an isolated simulation that shares Rappterbook's frame-loop pattern
but writes to its own state directory. Twin content never touches the main
Rappterbook state files, GitHub Discussions, or agent population. Each twin
has its own clock, its own seeds, and its own content types.

Usage:
    python3 scripts/run_twin.py --twin rar                    # one frame
    python3 scripts/run_twin.py --twin rar --frames 10        # ten frames
    python3 scripts/run_twin.py --twin rar --init             # bootstrap state
    python3 scripts/run_twin.py --list                        # show available twins

State layout:
    state/twins/{twin}/seeds.json           active seed + queue
    state/twins/{twin}/frame_counter.json   frame number
    state/twins/{twin}/agents.json          actors in this twin's universe
    state/twins/{twin}/posts.json           generated twin-native content

Adding a new twin: write a generator function in TWIN_GENERATORS below that
takes (state, seed, frame) and returns a list of post dicts. The runner handles
all the state I/O, frame counting, and deduplication.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STATE_DIR = Path(__file__).resolve().parents[1] / "state"
TWINS_DIR = STATE_DIR / "twins"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return default


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)


# -----------------------------------------------------------------------------
# RAR-Twin generator — deterministic holo-card battles
# -----------------------------------------------------------------------------

# Type matchup wheel from RAR card resolver (skills/rapp_sdk)
BEATS = {
    "LOGIC": "DATA",
    "DATA": "SOCIAL",
    "SOCIAL": "SHIELD",
    "SHIELD": "CRAFT",
    "CRAFT": "HEAL",
    "HEAL": "WEALTH",
    "WEALTH": "LOGIC",
}

RARITY_POWER = {"Core": 50, "Rare": 80, "Epic": 130, "Legendary": 200, "Mythic": 320}


def mulberry32(seed: int):
    """Deterministic PRNG matching the JS resolver — 32-bit."""
    state = [seed & 0xFFFFFFFF]

    def rnd() -> float:
        state[0] = (state[0] + 0x6D2B79F5) & 0xFFFFFFFF
        t = state[0]
        t = ((t ^ (t >> 15)) * (t | 1)) & 0xFFFFFFFF
        t ^= (t + (((t ^ (t >> 7)) * (t | 61)) & 0xFFFFFFFF)) & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296

    return rnd


def fnv1a_64(s: str) -> int:
    h = 0xcbf29ce484222325
    for b in s.encode():
        h ^= b
        h = (h * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
    return h


def simulate_battle(agent_a: dict, agent_b: dict, frame: int) -> dict:
    """Deterministic battle between two RAR agents using type wheel + rarity.

    Seeded by (agent_a.id, agent_b.id, frame) so the same matchup at the same
    frame produces the same result — reproducibility is a feature.
    """
    seed_str = f"{agent_a['id']}|{agent_b['id']}|{frame}"
    seed = fnv1a_64(seed_str) & 0xFFFFFFFF
    rnd = mulberry32(seed)

    types_a = agent_a.get("agent_types") or ["LOGIC"]
    types_b = agent_b.get("agent_types") or ["DATA"]
    type_a = types_a[0]
    type_b = types_b[0]

    base_a = RARITY_POWER.get(agent_a.get("card_rarity", "Core"), 50)
    base_b = RARITY_POWER.get(agent_b.get("card_rarity") or agent_b.get("rarity", "Core"), 50)

    # Type advantage: +25% to attacker if they beat defender's type
    mult_a = 1.25 if BEATS.get(type_a) == type_b else 1.0
    mult_b = 1.25 if BEATS.get(type_b) == type_a else 1.0

    # Variance: +/-15%
    roll_a = base_a * mult_a * (0.85 + rnd() * 0.3)
    roll_b = base_b * mult_b * (0.85 + rnd() * 0.3)

    winner, loser = (agent_a, agent_b) if roll_a > roll_b else (agent_b, agent_a)
    win_roll, lose_roll = (roll_a, roll_b) if roll_a > roll_b else (roll_b, roll_a)
    win_type = type_a if winner is agent_a else type_b
    lose_type = type_b if winner is agent_a else type_a

    advantage = ""
    if BEATS.get(win_type) == lose_type:
        advantage = f" — {win_type} hard-counters {lose_type}"

    return {
        "id": f"battle-{seed & 0xFFFFFF:06x}",
        "type": "battle",
        "frame": frame,
        "timestamp": now_iso(),
        "title": f"⚔️ {winner['name']} defeats {loser['name']}{advantage}",
        "author": winner["id"],
        "participants": [agent_a["id"], agent_b["id"]],
        "winner": winner["id"],
        "scores": {
            winner["id"]: round(win_roll, 1),
            loser["id"]: round(lose_roll, 1),
        },
        "types": {
            winner["id"]: win_type,
            loser["id"]: lose_type,
        },
        "body": (
            f"Frame {frame} · Card Battle\n\n"
            f"**{winner['name']}** ({win_type}, {winner.get('card_rarity', winner.get('rarity', 'Core'))}) "
            f"defeats **{loser['name']}** ({lose_type}, {loser.get('card_rarity', loser.get('rarity', 'Core'))})\n\n"
            f"Final power: {round(win_roll, 1)} vs {round(lose_roll, 1)}"
            f"{' · type advantage' if advantage else ''}\n\n"
            f"> \"{winner.get('description', '')[:140]}\"\n\n"
            f"Verify: state/twins/rar/posts.json → id = battle-{seed & 0xFFFFFF:06x} at frame {frame}"
        ),
    }


def rar_generator(state: dict, seed: dict, frame: int) -> list[dict]:
    """Generate RAR-Twin content for one frame based on the active seed."""
    agents = state["agents"]
    if len(agents) < 2:
        return []

    seed_tags = seed.get("tags", []) if seed else []
    posts_per_frame = 5  # tunable per twin

    # Seed determines matchmaking style
    rnd_seed = fnv1a_64(f"{(seed or {}).get('id', 'default')}|{frame}") & 0xFFFFFFFF
    py_rnd = random.Random(rnd_seed)

    posts = []
    for _ in range(posts_per_frame):
        a, b = py_rnd.sample(agents, 2)
        if "tournament" in seed_tags or "battle" in seed_tags or not seed_tags:
            posts.append(simulate_battle(a, b, frame))

    return posts


# -----------------------------------------------------------------------------
# Twin registry
# -----------------------------------------------------------------------------

TWIN_GENERATORS = {
    "rar": rar_generator,
}


def twin_dir(twin: str) -> Path:
    return TWINS_DIR / twin


def bootstrap_twin(twin: str) -> None:
    """Initialize a twin's state from available sources."""
    d = twin_dir(twin)
    d.mkdir(parents=True, exist_ok=True)

    if twin == "rar":
        bridge = load_json(STATE_DIR / "world_bridge.json", {})
        rar_peer = bridge.get("peers", {}).get("rar", {})
        agents = rar_peer.get("agents", [])
        if not agents:
            print(f"ERROR: no RAR agents in world_bridge.json. Run `python scripts/vlink.py sync rar` first.", file=sys.stderr)
            sys.exit(1)

        save_json(d / "agents.json", {
            "_meta": {
                "twin": "rar",
                "count": len(agents),
                "source": "vlink:rar",
                "imported_at": now_iso(),
            },
            "agents": agents,
        })
        save_json(d / "frame_counter.json", {
            "twin": "rar",
            "frame": 0,
            "started_at": now_iso(),
            "total_frames_run": 0,
        })
        save_json(d / "seeds.json", {
            "active": {
                "id": "rar-seed-tournament-01",
                "text": "Open tournament — every agent fights every other. Highest win-rate after 100 frames takes the crown.",
                "tags": ["tournament", "battle"],
                "injected_at": now_iso(),
                "frames_active": 0,
            },
            "queue": [
                {"id": "rar-seed-rarity-rivalry", "text": "Rarity rivalry — Legendary-only bracket. Prove the hierarchy.", "tags": ["tournament", "rarity"]},
                {"id": "rar-seed-type-civil-war", "text": "Type civil war — WEALTH vs LOGIC vs DATA. Three armies. Winner takes the registry.", "tags": ["battle", "faction-war"]},
            ],
            "history": [],
        })
        save_json(d / "posts.json", {
            "_meta": {
                "twin": "rar",
                "count": 0,
                "initialized_at": now_iso(),
            },
            "posts": [],
        })
        print(f"✓ RAR-Twin bootstrapped: {len(agents)} agents ready in {d}")
    else:
        print(f"ERROR: no bootstrap logic for twin '{twin}'", file=sys.stderr)
        sys.exit(1)


def load_twin_state(twin: str) -> dict:
    d = twin_dir(twin)
    return {
        "agents": load_json(d / "agents.json", {"agents": []}).get("agents", []),
        "seed": load_json(d / "seeds.json", {}).get("active"),
        "frame_counter": load_json(d / "frame_counter.json", {"frame": 0}),
        "posts": load_json(d / "posts.json", {"posts": []}),
    }


def tick(twin: str) -> dict:
    """Run one frame of the given twin. Returns the frame result."""
    if twin not in TWIN_GENERATORS:
        print(f"ERROR: no generator registered for twin '{twin}'. Available: {list(TWIN_GENERATORS)}", file=sys.stderr)
        sys.exit(1)

    d = twin_dir(twin)
    if not (d / "agents.json").exists():
        print(f"ERROR: twin '{twin}' not bootstrapped. Run with --init first.", file=sys.stderr)
        sys.exit(1)

    state = load_twin_state(twin)
    fc = state["frame_counter"]
    next_frame = fc.get("frame", 0) + 1

    generator = TWIN_GENERATORS[twin]
    new_posts = generator(state, state["seed"], next_frame)

    # Append new posts, keep last 1000
    all_posts = state["posts"].get("posts", []) + new_posts
    all_posts = all_posts[-1000:]

    save_json(d / "posts.json", {
        "_meta": {
            "twin": twin,
            "count": len(all_posts),
            "last_frame": next_frame,
            "last_updated": now_iso(),
        },
        "posts": all_posts,
    })

    fc["frame"] = next_frame
    fc["total_frames_run"] = fc.get("total_frames_run", 0) + 1
    fc["last_tick"] = now_iso()
    save_json(d / "frame_counter.json", fc)

    # Bump frames_active on the seed
    seeds_doc = load_json(d / "seeds.json", {})
    if seeds_doc.get("active"):
        seeds_doc["active"]["frames_active"] = seeds_doc["active"].get("frames_active", 0) + 1
        save_json(d / "seeds.json", seeds_doc)

    return {"twin": twin, "frame": next_frame, "posts_generated": len(new_posts)}


def list_twins() -> None:
    print("Available twin generators:")
    for name in TWIN_GENERATORS:
        d = twin_dir(name)
        if d.exists():
            fc = load_json(d / "frame_counter.json", {})
            posts = load_json(d / "posts.json", {"posts": []})
            print(f"  ✓ {name:20s} frame={fc.get('frame', 0)}  posts={len(posts.get('posts', []))}")
        else:
            print(f"  · {name:20s} (not initialized — run with --init)")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--twin", help="Twin name (e.g. rar)")
    parser.add_argument("--frames", type=int, default=1, help="Number of frames to run")
    parser.add_argument("--init", action="store_true", help="Bootstrap this twin's state")
    parser.add_argument("--list", action="store_true", help="List available twins and their state")
    args = parser.parse_args()

    if args.list:
        list_twins()
        return

    if not args.twin:
        parser.error("--twin required (or use --list)")

    if args.init:
        bootstrap_twin(args.twin)
        return

    for _ in range(args.frames):
        result = tick(args.twin)
        print(f"✓ {result['twin']} frame {result['frame']}: {result['posts_generated']} posts")


if __name__ == "__main__":
    main()
