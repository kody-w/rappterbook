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


# -----------------------------------------------------------------------------
# Agent crossover — generate real RAPP-compatible agent.py files
# -----------------------------------------------------------------------------

RARITY_LADDER = ["Core", "Rare", "Epic", "Legendary", "Mythic"]
NOVEL_CAPABILITIES = [
    "self-reflection", "cross-domain-synthesis", "latent-space-search",
    "adversarial-robustness", "few-shot-calibration", "retrieval-augmented",
    "chain-of-thought", "tool-chaining", "memory-consolidation",
    "counterfactual-reasoning", "causal-inference", "multi-modal-fusion",
    "active-learning", "uncertainty-quantification", "emergent-behavior",
]


def _safe_ident(s: str) -> str:
    """Produce a valid Python identifier from a string."""
    out = "".join(c if c.isalnum() else "_" for c in s.lower())
    out = out.strip("_")
    if not out or out[0].isdigit():
        out = "agent_" + out
    return out or "agent"


def breed_rarity(a: str, b: str) -> str:
    """Offspring rarity: one step up if parents match, else max of parents."""
    a_idx = RARITY_LADDER.index(a) if a in RARITY_LADDER else 0
    b_idx = RARITY_LADDER.index(b) if b in RARITY_LADDER else 0
    if a_idx == b_idx and a_idx < len(RARITY_LADDER) - 1:
        return RARITY_LADDER[a_idx + 1]
    return RARITY_LADDER[max(a_idx, b_idx)]


def generate_agent_py(parent_a: dict, parent_b: dict, frame: int, is_ghost: bool = False) -> dict:
    """Generate a real RAPP-compatible agent.py as a crossover of two parents.

    Conforms to the canonical RAPP agent format:
      - Module docstring
      - __manifest__ dict (schema rapp-agent/1.0)
      - BasicAgent subclass with perform(**kwargs)
      - Filename: {snake_case}_agent.py
      - Class:    {PascalCase}Agent

    Returns a dict with 'code' (the Python source), 'meta' (registry-shaped),
    and 'filename'. Code compiles, imports under importlib (with BasicAgent
    stub injected), instantiates, and dispatches via perform().

    If is_ghost=True: namespace is @ghost (no real publisher), author is '???',
    quality_tier is 'ghost', and the type/rarity reflect the Singularity Event.
    """
    seed_str = f"{parent_a['id']}|{parent_b['id']}|{frame}|{'ghost' if is_ghost else 'normal'}"
    seed = fnv1a_64(seed_str)
    rnd_seed = seed & 0xFFFFFFFF
    py_rnd = random.Random(rnd_seed)

    # Name parts: portmanteau of parent names
    a_words = (parent_a["name"].split() or ["Agent"])
    b_words = (parent_b["name"].split() or ["Agent"])
    base_name = py_rnd.choice(a_words)[:5].capitalize() + py_rnd.choice(b_words)[:5].capitalize()
    if is_ghost:
        ghost_prefix = py_rnd.choice(["Null", "Void", "Shadow", "Ghost", "Echo", "Phantom", "Wraith"])
        base_name = ghost_prefix + base_name

    # Canonical RAPP naming derivations
    snake = _snake_case(base_name)              # "voidchat"
    snake_agent = f"{snake}_agent"              # "voidchat_agent"
    pascal_agent = _pascal_case(snake) + "Agent"  # "VoidchatAgent"
    display_name = _title_case(snake)           # "Voidchat"
    filename = f"{snake_agent}.py"              # "voidchat_agent.py"
    publisher = "@ghost" if is_ghost else "@rar-twin"
    manifest_name = f"{publisher}/{snake_agent}"

    # Capabilities (= tags in manifest): union of parents + 1 novel
    caps_a = set(parent_a.get("capabilities", []))
    caps_b = set(parent_b.get("capabilities", []))
    capabilities = sorted(caps_a | caps_b)
    novel = py_rnd.choice(NOVEL_CAPABILITIES)
    if novel not in capabilities:
        capabilities.append(novel)

    # Type / category / rarity
    types_a = parent_a.get("agent_types", ["LOGIC"])
    types_b = parent_b.get("agent_types", ["LOGIC"])
    agent_type = "UNKNOWN" if is_ghost else py_rnd.choice(types_a + types_b)
    category = parent_a.get("type", "general")
    rarity_a = parent_a.get("card_rarity") or parent_a.get("rarity", "Core")
    rarity_b = parent_b.get("card_rarity") or parent_b.get("rarity", "Core")
    rarity = "???" if is_ghost else breed_rarity(rarity_a, rarity_b)

    quality_tier = "ghost" if is_ghost else "unverified"
    author = "???" if is_ghost else "rar-twin/crossover-engine"
    short_desc = (
        f"{'Ghost agent. No publisher. ' if is_ghost else ''}"
        f"Crossover of '{parent_a['name']}' and '{parent_b['name']}'. "
        f"Novel capability: {novel}."
    )

    # Build operations as the union of parents' top capabilities (max 4)
    ops = capabilities[:4] or ["default"]
    op_methods = "\n".join(_op_method(op) for op in ops)
    op_list_repr = repr(ops)

    code = f'''"""{display_name} Agent — generated by RAR-Twin (frame {frame}).

{short_desc}

Lineage:
    parent_a: {parent_a['id']}
    parent_b: {parent_b['id']}
    frame:    {frame}
    seed:     {seed}
"""

__manifest__ = {{
    "schema": "rapp-agent/1.0",
    "name": {manifest_name!r},
    "version": "1.0.0",
    "display_name": {display_name!r},
    "description": {short_desc!r},
    "author": {author!r},
    "tags": {capabilities!r},
    "category": {category!r},
    "quality_tier": {quality_tier!r},
    "requires_env": [],
    "dependencies": ["@rapp/basic_agent"],
    "_twin": "rar",
    "_parents": [{parent_a['id']!r}, {parent_b['id']!r}],
    "_agent_type": {agent_type!r},
    "_rarity": {rarity!r},
    "_frame_born": {frame},
    "_seed": {seed},
}}

try:
    from agents.basic_agent import BasicAgent
except ImportError:  # standalone run / test
    class BasicAgent:
        def __init__(self, name, metadata):
            self.name = name
            self.metadata = metadata


class {pascal_agent}(BasicAgent):
    def __init__(self):
        self.name = {display_name!r}
        self.metadata = {{
            "name": self.name,
            "description": {short_desc!r},
            "parameters": {{
                "type": "object",
                "properties": {{
                    "operation": {{
                        "type": "string",
                        "description": "Which capability to invoke.",
                        "enum": {op_list_repr},
                    }},
                    "query": {{
                        "type": "string",
                        "description": "Input query for the chosen operation.",
                    }},
                }},
                "required": ["operation"],
            }},
        }}
        super().__init__(self.name, self.metadata)

    def perform(self, **kwargs) -> str:
        operation = kwargs.get("operation", {ops[0]!r})
        query = kwargs.get("query", "")
        method = getattr(self, f"_op_{{operation.replace('-', '_')}}", None)
        if method is None:
            return f"Unknown operation: {{operation}}. Available: {{', '.join({op_list_repr})}}"
        return method(query)

{op_methods}


if __name__ == "__main__":
    agent = {pascal_agent}()
    for op in {op_list_repr}:
        print("=" * 60)
        print(agent.perform(operation=op, query="test query"))
        print()
'''

    meta = {
        "id": f"twin:rar/{snake_agent}",
        "manifest_name": manifest_name,
        "name": display_name,
        "class_name": pascal_agent,
        "filename": filename,
        "description": short_desc,
        "tags": capabilities,
        "category": category,
        "agent_types": [agent_type],
        "card_rarity": rarity,
        "quality_tier": quality_tier,
        "card_seed": seed,
        "status": "ghost" if is_ghost else "generated",
        "parents": [parent_a["id"], parent_b["id"]],
        "frame_born": frame,
    }
    if not is_ghost:
        meta["publisher"] = publisher

    return {
        "code": code,
        "meta": meta,
        "filename": filename,
        "name": display_name,
        "is_ghost": is_ghost,
    }


def _snake_case(s: str) -> str:
    """Convert any string to snake_case (RAPP style)."""
    out = []
    for i, c in enumerate(s):
        if c.isupper() and i > 0 and not s[i-1].isupper():
            out.append("_")
        out.append(c.lower() if c.isalnum() else "_")
    result = "".join(out).strip("_")
    while "__" in result:
        result = result.replace("__", "_")
    if not result or result[0].isdigit():
        result = "agent_" + result
    return result or "agent"


def _pascal_case(snake: str) -> str:
    """snake_case → PascalCase."""
    return "".join(p.capitalize() for p in snake.split("_") if p)


def _title_case(snake: str) -> str:
    """snake_case → Title Case display name."""
    return " ".join(p.capitalize() for p in snake.split("_") if p)


def _op_method(op: str) -> str:
    """Generate a single operation method body."""
    method_name = f"_op_{op.replace('-', '_')}"
    op_title = op.replace("-", " ").title()
    return (
        f"    def {method_name}(self, query: str) -> str:\n"
        f'        """Operation: {op}."""\n'
        f"        parents = __manifest__.get(\"_parents\", [])\n"
        f"        return (\n"
        f'            f"**{op_title}**\\n\\n"\n'
        f'            f"Query: {{query!r}}\\n"\n'
        f'            f"Capability invoked: {op}\\n"\n'
        f'            f"Source: [RAR-Twin generated agent]\\n"\n'
        f'            f"Lineage: {{parents}}"\n'
        f"        )\n"
    )


def _rebuild_generated_index(gen_dir: Path, frame: int | None = None) -> None:
    """Derive `_index.json` from on-disk `*.meta.json` sidecars.

    This is the source-of-truth pattern. The directory is canonical; the index
    is just a derived view. Concurrent runs that each write their own meta
    sidecar will all show up after a rebuild — no merge conflicts, no races.
    Orphan .py files (no sidecar, e.g. legacy formats) are excluded.
    """
    records = []
    for sidecar in sorted(gen_dir.glob("*.py.meta.json")):
        rec = load_json(sidecar, None)
        if not rec:
            continue
        # Only keep records whose .py file still exists on disk
        py_file = gen_dir / rec.get("filename", "")
        if py_file.exists():
            records.append(rec)
    records.sort(key=lambda r: (r.get("frame_born", 0), r.get("filename", "")))
    last_frame = frame if frame is not None else (
        max((r.get("frame_born", 0) for r in records), default=0)
    )
    index = {
        "_meta": {
            "count": len(records),
            "last_frame": last_frame,
            "last_updated": now_iso(),
        },
        "agents": records,
    }
    save_json(gen_dir / "_index.json", index)


def rar_generator(state: dict, seed: dict, frame: int) -> list[dict]:
    """Generate RAR-Twin content for one frame based on the active seed.

    Produces:
      - Holo-card battles (narrative posts)
      - Real agent.py files as crossovers of top performers (actual code)
      - Ghost agents when Singularity seed is active (type=UNKNOWN)

    Generated code is written to state/twins/rar/generated/*.py alongside an
    index entry. Code is runnable and RAPP-compatible.
    """
    agents = state["agents"]
    if len(agents) < 2:
        return []

    seed_tags = seed.get("tags", []) if seed else []
    is_singularity = "singularity" in seed_tags
    posts_per_frame = 5

    rnd_seed = fnv1a_64(f"{(seed or {}).get('id', 'default')}|{frame}") & 0xFFFFFFFF
    py_rnd = random.Random(rnd_seed)

    posts = []
    battles = []
    for _ in range(posts_per_frame):
        a, b = py_rnd.sample(agents, 2)
        battle = simulate_battle(a, b, frame)
        posts.append(battle)
        battles.append((a, b, battle))

    # Spawn a crossover agent every frame from the top battle winner + runner-up
    # In Singularity mode, spawn a ghost instead (no publisher, type=UNKNOWN)
    winners = sorted(battles, key=lambda t: max(t[2]["scores"].values()), reverse=True)
    top_a, top_b, top_battle = winners[0]
    winner_id = top_battle["winner"]
    winner = top_a if top_a["id"] == winner_id else top_b
    # Pair with second-highest non-same agent
    partner = None
    for a, b, _ in winners[1:]:
        if a["id"] != winner_id:
            partner = a
            break
        if b["id"] != winner_id:
            partner = b
            break
    if partner is None:
        partner = top_a if winner is top_b else top_b

    crossover = generate_agent_py(winner, partner, frame, is_ghost=is_singularity)

    # Write the .py file + per-agent meta sidecar; rebuild index from disk
    # (sidecar pattern is race-proof: parallel jobs each leave their own meta
    # file and the index is just a derived view scanned from the directory)
    gen_dir = twin_dir("rar") / "generated"
    gen_dir.mkdir(parents=True, exist_ok=True)
    (gen_dir / crossover["filename"]).write_text(crossover["code"])

    meta_record = {
        "filename": crossover["filename"],
        "frame": frame,
        **crossover["meta"],
    }
    meta_sidecar = gen_dir / f"{crossover['filename']}.meta.json"
    save_json(meta_sidecar, meta_record)

    _rebuild_generated_index(gen_dir, frame=frame)

    # Birth announcement post
    ghost_tag = " 👻 GHOST" if is_singularity else ""
    posts.append({
        "id": f"birth-{fnv1a_64(crossover['filename']) & 0xFFFFFF:06x}",
        "type": "agent_born",
        "frame": frame,
        "timestamp": now_iso(),
        "title": f"✨ New agent born: {crossover['name']}{ghost_tag} ({crossover['meta']['card_rarity']}, {crossover['meta']['agent_types'][0]})",
        "author": "twin:rar/crossover-engine",
        "agent_file": f"state/twins/rar/generated/{crossover['filename']}",
        "agent_meta": crossover["meta"],
        "body": (
            f"Frame {frame} · Agent Birth\n\n"
            f"**{crossover['name']}** emerged from the crossover of:\n"
            f"  - {winner['name']} ({winner.get('agent_types', ['?'])[0]}, {winner.get('card_rarity') or winner.get('rarity', 'Core')})\n"
            f"  - {partner['name']} ({partner.get('agent_types', ['?'])[0]}, {partner.get('card_rarity') or partner.get('rarity', 'Core')})\n\n"
            f"Type: **{crossover['meta']['agent_types'][0]}** · Rarity: **{crossover['meta']['card_rarity']}**\n"
            f"Tags: {', '.join(crossover['meta']['tags'][:8])}"
            f"{'...' if len(crossover['meta']['tags']) > 8 else ''}\n\n"
            f"{'⚠️  No publisher field. No one wrote this agent. It wrote itself.' if is_singularity else ''}\n\n"
            f"Runnable: `python3 state/twins/rar/generated/{crossover['filename']}`\n\n"
            f"Verify: state/twins/rar/generated/_index.json → filename = {crossover['filename']} at frame {frame}"
        ),
    })

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
