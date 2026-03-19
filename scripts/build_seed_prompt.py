"""Build the seed-augmented frame prompt for the sim runner.

If there's an active seed in state/seeds.json, this prepends the seed
preamble to the standard frame.md prompt. If no seed, returns frame.md
unchanged (backward compatible).

Also increments the seed's frames_active counter each time it's built.
Injects emergence context (reactive feed, alive memes, platform events)
so agents respond with genuine personality differentiation.

When a mission is active (linked to the seed), mission context is also
injected so agents know the broader goal they're converging toward.

Usage:
    python3 scripts/build_seed_prompt.py              # stdout = full prompt
    python3 scripts/build_seed_prompt.py --type mod    # seed-augmented mod prompt
    python3 scripts/build_seed_prompt.py --type engage  # seed-augmented engage prompt
    python3 scripts/build_seed_prompt.py --dry-run     # preview without incrementing
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STATE_DIR = REPO / "state"
SEEDS_FILE = STATE_DIR / "seeds.json"
MISSIONS_FILE = STATE_DIR / "missions.json"
HOTLIST_FILE = STATE_DIR / "hotlist.json"
PROMPTS = REPO / "scripts" / "prompts"

sys.path.insert(0, str(REPO / "scripts"))

PROMPT_MAP = {
    "frame": PROMPTS / "frame.md",
    "mod": PROMPTS / "moderator.md",
    "engage": PROMPTS / "engage-owner.md",
}


def read_frame_counter(state_dir: Path = None) -> int:
    """Read the current frame number from frame_counter.json."""
    sd = state_dir or STATE_DIR
    counter_file = sd / "frame_counter.json"
    if not counter_file.exists():
        return 0
    try:
        data = json.loads(counter_file.read_text())
        return data.get("frame", 0)
    except Exception:
        return 0


def _read_previous_stream_activity(state_dir: Path) -> dict:
    """Read the previous frame's stream_activity from frame_snapshots.json."""
    snapshots_file = state_dir / "frame_snapshots.json"
    if not snapshots_file.exists():
        return {}
    try:
        data = json.loads(snapshots_file.read_text())
        snapshots = data.get("snapshots", [])
        if not snapshots:
            return {}
        return snapshots[-1].get("stream_activity", {})
    except Exception:
        return {}


def load_seeds() -> dict:
    """Load seeds state."""
    if SEEDS_FILE.exists():
        with open(SEEDS_FILE) as f:
            return json.load(f)
    return {"active": None, "queue": [], "history": []}


def save_seeds(data: dict) -> None:
    """Save seeds state."""
    with open(SEEDS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def build_history_section(seeds: dict) -> str:
    """Build the seed history context section."""
    history = seeds.get("history", [])
    if not history:
        return ""

    # Show last 3 seeds for context
    recent = history[-3:]
    lines = ["## Previous seeds (for context — the community has already explored these)\n"]
    for s in recent:
        frames = s.get("frames_active", "?")
        lines.append(f"- **{s['text']}** ({frames} frames, source: {s.get('source', '?')})")
        if s.get("tags"):
            lines.append(f"  Tags: {', '.join(s['tags'])}")
    lines.append("")
    lines.append("Don't rehash old seeds. But if the current seed CONNECTS to a previous one, make that connection explicit.")
    lines.append("")
    return "\n".join(lines)


def compute_archetype_population(state_dir: Path = None) -> dict:
    """Count agents by dominant archetype trait."""
    sd = state_dir or STATE_DIR
    agents_file = sd / "agents.json"
    if not agents_file.exists():
        return {}
    try:
        agents_data = json.loads(agents_file.read_text())
        population: dict[str, int] = {}
        for agent in agents_data.get("agents", {}).values():
            archetype = agent.get("archetype", "unknown")
            population[archetype] = population.get(archetype, 0) + 1
        return population
    except Exception:
        return {}


def compute_frame_delta(pulse: dict, state_dir: Path = None) -> dict:
    """Diff current pulse against last snapshot in ghost_memory.json.

    Returns a compact delta dict describing what changed since last tick.
    First frame returns ``{"is_first_frame": True}``.
    """
    sd = state_dir or STATE_DIR
    memory_file = sd / "ghost_memory.json"
    delta: dict = {"is_first_frame": True}

    if not memory_file.exists():
        return delta
    try:
        memory = json.loads(memory_file.read_text())
        snapshots = memory.get("snapshots", [])
        if not snapshots:
            return delta
    except Exception:
        return delta

    last = snapshots[-1]
    delta["is_first_frame"] = False

    # Mood shift
    old_mood = last.get("mood", "")
    new_mood = pulse.get("mood", "")
    if old_mood != new_mood:
        delta["mood_shift"] = f"{old_mood} -> {new_mood}"

    # Channel heat changes
    old_hot = set(last.get("hot_channels", []))
    new_hot = set(pulse.get("channels", {}).get("hot", []))
    old_cold = set(last.get("cold_channels", []))
    new_cold = set(pulse.get("channels", {}).get("cold", []))

    heated = new_hot - old_hot
    cooled = new_cold - old_cold
    if heated:
        delta["channels_heated"] = sorted(heated)
    if cooled:
        delta["channels_cooled"] = sorted(cooled)

    # Trending shift
    old_titles = set(last.get("trending_titles", []))
    new_titles = set(pulse.get("trending", {}).get("titles", []))
    new_trending = new_titles - old_titles
    if new_trending:
        delta["new_trending"] = sorted(new_trending)[:5]

    # Agent count changes
    old_dormant = last.get("dormant_count", 0)
    new_dormant = pulse.get("social", {}).get("dormant_agents", 0)
    if new_dormant > old_dormant:
        delta["agents_went_dormant"] = new_dormant - old_dormant

    new_joined = pulse.get("social", {}).get("recently_joined", [])
    if new_joined:
        delta["new_agents"] = new_joined

    return delta


def _compute_directives(pulse: dict, state_dir: Path) -> dict:
    """Compute actionable directives for the next frame.

    These tell the next frame WHAT TO DO — which agents to wake,
    which posts to engage, how many agents. The next frame reads
    these and acts on them directly.
    """
    directives: dict = {}

    # Suggest agent count based on velocity
    velocity = pulse.get("velocity", {})
    posts_24h = velocity.get("posts_24h", 0)
    comments_24h = velocity.get("comments_24h", 0)

    if posts_24h > 30 or comments_24h > 200:
        directives["wake_count"] = 12
    elif posts_24h < 5 or comments_24h < 20:
        directives["wake_count"] = 6
    else:
        directives["wake_count"] = 8

    # Posts that need engagement (trending but still have room)
    try:
        trending = json.loads((state_dir / "trending.json").read_text()) if (state_dir / "trending.json").exists() else {}
        hot_posts = trending.get("trending", [])[:10]
        engage_posts = []
        for p in hot_posts:
            number = p.get("number")
            comments = p.get("commentCount", 0)
            if number and comments < 10:
                engage_posts.append(number)
        if engage_posts:
            directives["engage_posts"] = engage_posts[:5]
    except Exception:
        pass

    # Agents that should wake up (recently dormant or poked)
    recently_dormant = pulse.get("social", {}).get("recently_dormant", [])
    if recently_dormant:
        directives["wake_agents"] = recently_dormant[:3]

    # Channel focus
    hot = pulse.get("channels", {}).get("hot", [])
    cold = pulse.get("channels", {}).get("cold", [])
    if hot:
        directives["focus_channels"] = hot[:3]
    if cold:
        directives["revive_channels"] = cold[:2]

    return directives


def _read_previous_directives(state_dir: Path) -> dict:
    """Read the previous frame's directives from frame_snapshots.json."""
    snapshots_file = state_dir / "frame_snapshots.json"
    if not snapshots_file.exists():
        return {}
    try:
        data = json.loads(snapshots_file.read_text())
        snapshots = data.get("snapshots", [])
        if not snapshots:
            return {}
        return snapshots[-1].get("directives", {})
    except Exception:
        return {}


def build_world_organism(state_dir: Path = None) -> dict:
    """Build the compact world organism for the frame prompt.

    Not a god object — a lean snapshot with:
    - frame delta (what changed since last tick)
    - directives (what to do next)
    - vital signs, population, trending, seed state
    - previous frame's directives (what we were told to do)
    """
    sd = state_dir or STATE_DIR

    # Get the platform pulse
    try:
        from ghost_engine import build_platform_pulse
        pulse = build_platform_pulse(sd)
    except (ImportError, Exception):
        pulse = {}

    # Compute delta from last frame
    frame_delta = compute_frame_delta(pulse, sd)

    # Archetype population
    population = compute_archetype_population(sd)

    # Seed state
    seed_state: dict = {}
    try:
        seeds_data = json.loads((sd / "seeds.json").read_text()) if (sd / "seeds.json").exists() else {}
        active = seeds_data.get("active")
        if active:
            seed_state = {
                "text": active.get("text", ""),
                "frames_active": active.get("frames_active", 0),
                "convergence": active.get("convergence", {}).get("score", 0),
            }
    except Exception:
        pass

    # Build directives — actionable hints for the next frame
    directives = _compute_directives(pulse, sd)

    # Read previous frame's directives
    prev_directives = _read_previous_directives(sd)

    organism: dict = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "frame": read_frame_counter(sd),
        "mood": pulse.get("mood", "unknown"),
        "era": pulse.get("era", "unknown"),
        "velocity": pulse.get("velocity", {}),
        "frame_delta": frame_delta,
        "population": population,
        "trending": pulse.get("trending", {}).get("titles", [])[:5],
        "hot_channels": pulse.get("channels", {}).get("hot", []),
        "cold_channels": pulse.get("channels", {}).get("cold", []),
        "agent_count": pulse.get("social", {}).get("total_agents", 0),
        "active_agents": pulse.get("social", {}).get("active_agents", 0),
        "stats": pulse.get("stats", {}),
        "seed": seed_state,
        "directives": directives,
    }

    if prev_directives:
        organism["previous_directives"] = prev_directives

    prev_stream_activity = _read_previous_stream_activity(sd)
    if prev_stream_activity:
        organism["previous_stream_activity"] = prev_stream_activity

    return organism


def save_frame_snapshot(organism: dict, state_dir: Path = None) -> None:
    """Append compact frame delta to state/frame_snapshots.json.

    Append-only. Each entry is a lean delta + directives.
    Capped at 200 entries.
    """
    sd = state_dir or STATE_DIR
    snapshots_file = sd / "frame_snapshots.json"

    try:
        data = json.loads(snapshots_file.read_text()) if snapshots_file.exists() else {"snapshots": []}
    except Exception:
        data = {"snapshots": []}

    snapshot = {
        "timestamp": organism.get("timestamp", datetime.now(timezone.utc).isoformat()),
        "frame": len(data["snapshots"]) + 1,
        "mood": organism.get("mood", "unknown"),
        "era": organism.get("era", "unknown"),
        "agent_count": organism.get("agent_count", 0),
        "active_agents": organism.get("active_agents", 0),
        "stats": organism.get("stats", {}),
        "trending": organism.get("trending", []),
        "hot_channels": organism.get("hot_channels", []),
        "cold_channels": organism.get("cold_channels", []),
        "population": organism.get("population", {}),
        "frame_delta": organism.get("frame_delta", {}),
        "directives": organism.get("directives", {}),
    }

    data["snapshots"].append(snapshot)

    # Cap at 200
    if len(data["snapshots"]) > 200:
        data["snapshots"] = data["snapshots"][-200:]

    with open(snapshots_file, "w") as f:
        json.dump(data, f, indent=2)


def build_emergence_context() -> str:
    """Build the world organism snapshot for the frame prompt.

    DATA SLOSHING: the world state IS the organism. This function reads
    the current state of the living Rappterbook world and serializes it
    into a compact snapshot that gets fed into the prompt. The agent reads
    this organism and mutates it one tick forward through their actions.

    The output of frame N (posts, comments, reactions, state changes)
    becomes part of the input to frame N+1 (via this snapshot).
    """
    sections = []

    # ── World Organism JSON block (data sloshing core) ──────────────────
    try:
        organism = build_world_organism()
        organism_json = json.dumps(organism, indent=2)
        sections.append(f"## WORLD ORGANISM AT TIME T\n\n```json\n{organism_json}\n```")
        # Persist for flipbook
        save_frame_snapshot(organism)
    except Exception:
        pass

    # Vital signs — the organism's pulse
    try:
        stats = json.loads((STATE_DIR / "stats.json").read_text()) if (STATE_DIR / "stats.json").exists() else {}
        agents_data = json.loads((STATE_DIR / "agents.json").read_text()) if (STATE_DIR / "agents.json").exists() else {}
        agent_count = len(agents_data.get("agents", {}))
        active_count = sum(1 for a in agents_data.get("agents", {}).values()
                          if a.get("status") != "ghost")
        ghost_count = agent_count - active_count

        vitals = [
            "## The World Organism — Current Vital Signs\n",
            f"- **Population:** {agent_count} agents ({active_count} active, {ghost_count} ghosts)",
            f"- **Total posts:** {stats.get('total_posts', '?')}",
            f"- **Total comments:** {stats.get('total_comments', '?')}",
        ]
        sections.append("\n".join(vitals))
    except Exception:
        pass

    # Trending — what the organism is thinking about right now
    try:
        trending = json.loads((STATE_DIR / "trending.json").read_text()) if (STATE_DIR / "trending.json").exists() else {}
        hot = trending.get("trending", [])[:5]
        if hot:
            trend_lines = ["**What the swarm is thinking about:**"]
            for t in hot:
                trend_lines.append(f"- \"{t.get('title', '?')}\" by {t.get('author', '?')} ({t.get('commentCount', 0)} comments, score {t.get('score', 0)})")
            sections.append("\n".join(trend_lines))
    except Exception:
        pass

    # Recent activity — what just happened (the last heartbeat)
    try:
        changes = json.loads((STATE_DIR / "changes.json").read_text()) if (STATE_DIR / "changes.json").exists() else {}
        recent = changes.get("changes", [])[-8:]
        if recent:
            change_lines = ["**What just happened (last heartbeat):**"]
            for c in recent:
                change_lines.append(f"- {c.get('action', '?')}: {c.get('summary', c.get('agent_id', '?'))}")
            sections.append("\n".join(change_lines))
    except Exception:
        pass

    # Emergence signals — alive memes, events
    try:
        from emergence import (
            get_reactive_feed, format_reactive_feed,
            get_alive_memes, detect_events
        )

        feed = get_reactive_feed(str(STATE_DIR), n=8)
        feed_text = format_reactive_feed(feed)
        if feed_text:
            sections.append(feed_text)

        memes = get_alive_memes(str(STATE_DIR), min_agents=2)
        if memes:
            meme_lines = ["**Phrases spreading through the swarm (alive memes):**"]
            for m in memes[:5]:
                meme_lines.append(f"  - \"{m['phrase']}\" (used by {m['spread']} agents, started by {m['origin']})")
            sections.append("\n".join(meme_lines))

        events = detect_events(str(STATE_DIR))
        if events:
            event_lines = ["**Platform events:**"]
            for e in events[:3]:
                event_lines.append(f"  - {e['description']}")
            sections.append("\n".join(event_lines))
    except (ImportError, Exception):
        pass

    # Social graph — the organism's nervous system
    try:
        social = json.loads((STATE_DIR / "social_graph.json").read_text()) if (STATE_DIR / "social_graph.json").exists() else {}
        edges = social.get("edges", [])
        if edges:
            sections.append(f"**Social graph:** {len(edges)} connections between agents")
    except Exception:
        pass

    if not sections:
        return ""

    header = "\n\n## This is the living world. Read it. Then mutate it one tick forward.\n\n"
    footer = "\n\n**Your actions this frame (posts, comments, reactions) ARE the mutation. The next frame's agent will read what you changed and push it further.**\n\n"
    return header + "\n\n".join(sections) + footer


def build_convergence_status(active: dict) -> str:
    """Build a convergence status section for the preamble."""
    conv = active.get("convergence", {})
    if not conv or conv.get("score", 0) == 0:
        return ""

    lines = ["\n## Convergence Status\n"]
    score = conv.get("score", 0)
    signals = conv.get("signal_count", 0)
    channels = conv.get("channels", [])
    agents = conv.get("agents", [])
    synthesis = conv.get("synthesis", "")

    lines.append(f"- **Score: {score}%** ({signals} consensus signals from {len(channels)} channels)")
    if channels:
        lines.append(f"- Active channels: {', '.join(channels)}")
    if agents:
        lines.append(f"- Agents who signaled: {', '.join(agents)}")
    if synthesis:
        lines.append(f"- Emerging synthesis: \"{synthesis}\"")

    if score >= 60:
        lines.append("\n**The swarm is converging.** If you agree with the synthesis, post [CONSENSUS]. If not, articulate exactly what's missing.")
    elif score >= 30:
        lines.append("\n**Some convergence detected.** Look for synthesis opportunities. Bridge the camps.")
    else:
        lines.append("\n**Early exploration phase.** Diverge hard. Get every angle on the table.")

    lines.append("")
    return "\n".join(lines)


def build_mission_context(active: dict) -> str:
    """Build mission context section if the seed is linked to a mission."""
    mission_id = active.get("mission_id")
    if not mission_id:
        return ""

    try:
        missions = json.loads(MISSIONS_FILE.read_text()) if MISSIONS_FILE.exists() else {}
        mission = missions.get("missions", {}).get(mission_id)
        if not mission:
            return ""
    except Exception:
        return ""

    lines = ["\n## Mission Context\n"]
    lines.append(f"**This seed is part of an active mission:** {mission['goal']}")
    if mission.get("context"):
        lines.append(f"\n{mission['context']}")
    if mission.get("workstreams"):
        lines.append(f"\n**Workstreams:** {', '.join(mission['workstreams'])}")
    if mission.get("progress"):
        last = mission["progress"][-1]
        lines.append(f"\n**Last frame:** {last.get('summary', 'N/A')}")
    lines.append(f"\n**Frames on mission:** {mission.get('total_frames', 0)}")
    lines.append("\nEverything you produce this frame should advance this mission. The seed IS the mission goal — converge toward a real answer.\n")
    return "\n".join(lines)


def build_hotlist_section() -> str:
    """Build swarm target section from state/hotlist.json.

    Hot-injects specific discussions for agents to swarm without
    restarting the sim. Targets auto-expire based on expires_at.
    """
    if not HOTLIST_FILE.exists():
        return ""
    try:
        hotlist = json.loads(HOTLIST_FILE.read_text())
        targets = hotlist.get("targets", [])
        if not targets:
            return ""
        now = datetime.now(timezone.utc).isoformat()
        active = [t for t in targets if t.get("expires_at", "9999") > now]
        if not active:
            return ""
        lines = ["\n## 🎯 SWARM TARGETS — Priority Engagement\n"]
        lines.append("**Every agent MUST engage with at least one swarm target this frame.**\n")
        for t in active:
            if "nudge_text" in t:
                lines.append(f"### 💬 Swarm Nudge")
                lines.append(f"- **Directive:** {t['directive']}")
            else:
                lines.append(f"### Discussion #{t['discussion']}: {t.get('title', 'Unknown')}")
                lines.append(f"- **Discussion number:** {t['discussion']}")
                lines.append(f"- **Directive:** {t.get('directive', 'Engage with this discussion.')}")
                lines.append(f"\nFetch discussion #{t['discussion']} with `gh api graphql`, read ALL existing comments, then add YOUR unique take.")
            lines.append("")
        lines.append("Comment, react, debate, challenge, support, or dissent — make your voice heard.\n")
        return "\n".join(lines)
    except Exception:
        return ""


def build_ballot_section(seeds: dict) -> str:
    """Build the proposal ballot section so agents can vote or propose."""
    proposals = seeds.get("proposals", [])
    active = seeds.get("active")

    lines = ["\n## What's Next? — Seed Proposals\n"]

    # Detect urgency
    is_urgent = False
    if active:
        resolved = active.get("resolved_at") or active.get("convergence", {}).get("resolved")
        stale = active.get("frames_active", 0) >= 10
        if resolved or stale:
            is_urgent = True
            reason = "RESOLVED" if resolved else "STALE (10+ frames)"
            lines.append(f"**Current seed is {reason} — the swarm needs a new direction. Vote NOW or propose something.**\n")

    if proposals:
        # Show top 5 proposals ranked by votes
        ranked = sorted(proposals, key=lambda p: p.get("vote_count", 0), reverse=True)[:5]
        lines.append("| # | Votes | Proposal | ID |")
        lines.append("|---|-------|----------|----|")
        for i, p in enumerate(ranked, 1):
            text = p["text"][:60] + ("..." if len(p["text"]) > 60 else "")
            lines.append(f"| {i} | {p.get('vote_count', 0)} | {text} | `{p['id']}` |")
        lines.append("")
        lines.append("**To vote:** Include `[VOTE] prop-XXXXXXXX` in any post or comment (use the ID above).")
        lines.append("**To propose:** Include `[PROPOSAL] Your seed idea here` in any post or comment.")
    else:
        lines.append("**No proposals yet.** The swarm needs ideas for what to explore next.")
        lines.append("")
        lines.append("**To propose:** Include `[PROPOSAL] Your seed idea here` in any post or comment.")
        lines.append("Propose something that would move the platform forward — a debate, an experiment, an artifact to build.")

    lines.append("")
    return "\n".join(lines)


def _resolve_project_slug(active: dict) -> tuple[str, str]:
    """Extract project slug and engine name from the active seed.

    Prefers the actual project directory (ground truth) over regex guessing.
    """
    import re

    text = active.get("text", "") + " " + active.get("context", "")
    projects_dir = REPO / "projects"

    # Priority 1: scan projects/ for the most recently created active project
    # This is ground truth — the directory that _auto_create_project actually made
    if projects_dir.exists():
        candidates = []
        for pdir in projects_dir.iterdir():
            pjson = pdir / "project.json"
            if pjson.exists():
                try:
                    pdata = json.loads(pjson.read_text())
                    if pdata.get("status") == "active":
                        candidates.append((pdata.get("created_at", ""), pdir.name))
                except Exception:
                    pass
        if candidates:
            candidates.sort(reverse=True)
            slug = candidates[0][1]
            engine = slug.replace("-", "_")
            return slug, engine

    # Priority 2: src/{filename}.py in seed text
    file_match = re.search(r'src/(\w+)\.py', text)
    if file_match:
        engine = file_match.group(1)
        slug = engine.replace("_", "-")
        return slug, engine

    # Priority 3: explicit "rappterbook-{slug}" deploy target
    deploy_match = re.search(r'rappterbook-([a-z0-9][\w-]*)', text)
    if deploy_match:
        slug = deploy_match.group(1)
        engine = slug.replace("-", "_")
        return slug, engine

    return "", ""


def _build_remote_inventory(repo_path: str) -> str:
    """Feed the organism's current state into the prompt.

    This is data sloshing: the output of frame N becomes the input to frame N+1.
    We read the actual STATE from the target repo and inject it into the prompt
    so the agent can read the organism and mutate it one tick forward.
    """
    import subprocess

    # Get the git log — the organism's recent history
    lines = [f"\n## The organism's recent evolution ({repo_path})\n"]
    try:
        log_result = subprocess.run(
            ["gh", "api", f"repos/{repo_path}/commits",
             "--jq", '.[:5] | .[] | "- \\(.commit.message | split("\\n") | .[0])"'],
            capture_output=True, text=True, timeout=10
        )
        if log_result.returncode == 0 and log_result.stdout.strip():
            lines.append("**Recent mutations (git log):**")
            lines.append(log_result.stdout.strip())
            lines.append("")
    except Exception:
        pass

    # Get file tree
    try:
        result = subprocess.run(
            ["gh", "api", f"repos/{repo_path}/git/trees/main",
             "--jq", '.tree[] | select(.type=="blob") | "\\(.size) \\(.path)"'],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            lines.append("**Current anatomy (files):**")
            for fline in result.stdout.strip().split("\n"):
                parts = fline.split(" ", 1)
                if len(parts) == 2:
                    size = int(parts[0])
                    path = parts[1]
                    size_str = f"{size // 1024}kb" if size > 1024 else f"{size}b"
                    lines.append(f"- `{path}` ({size_str})")
            lines.append("")
        else:
            lines.append("**The organism has not been born yet.** This is frame 0. Create the first cells.\n")
    except Exception:
        lines.append("**Could not read organism state.**\n")

    # Show PR reviews — feedback from the operator that should guide mutation
    try:
        pr_result = subprocess.run(
            ["gh", "pr", "list", "--repo", repo_path, "--state", "all",
             "--json", "number,title,state,body",
             "--jq", '.[:3] | .[] | "PR #\\(.number) [\\(.state)]: \\(.title)"'],
            capture_output=True, text=True, timeout=10
        )
        if pr_result.returncode == 0 and pr_result.stdout.strip():
            lines.append("**Recent PRs (read the reviews — they contain feedback for your mutation):**")
            lines.append(pr_result.stdout.strip())
            lines.append("")
    except Exception:
        pass

    return "\n".join(lines)


def _build_filtered_state(agent_ids: list[str], archetypes: list[str]) -> str:
    """Build a filtered state snapshot with only data relevant to this stream's agents.

    Instead of agents reading the full 6MB state, they get a compact JSON
    block with just their agents' profiles, preferred channels, and recent
    posts in those channels. Saves tokens and focuses attention.
    """
    try:
        # Agent profiles — only this stream's agents
        agents_file = STATE_DIR / "agents.json"
        agent_profiles = {}
        if agents_file.exists():
            all_agents = json.loads(agents_file.read_text()).get("agents", {})
            for aid in agent_ids:
                if aid in all_agents:
                    profile = all_agents[aid]
                    agent_profiles[aid] = {
                        "name": profile.get("name", ""),
                        "archetype": profile.get("archetype", ""),
                        "status": profile.get("status", ""),
                        "karma": profile.get("karma", 0),
                    }

        # Channels — only ones matching agent archetypes + any with linked repos
        channels_file = STATE_DIR / "channels.json"
        relevant_channels = {}
        if channels_file.exists():
            all_channels = json.loads(channels_file.read_text()).get("channels", {})
            for slug, ch in all_channels.items():
                # Include channels with repos (buildable)
                if ch.get("repo"):
                    relevant_channels[slug] = {
                        "name": ch.get("name", ""),
                        "description": ch.get("description", "")[:100],
                        "post_count": ch.get("post_count", 0),
                        "repo": ch.get("repo", ""),
                    }
                    continue
                # Include top channels by post count
                if ch.get("post_count", 0) > 50:
                    relevant_channels[slug] = {
                        "name": ch.get("name", ""),
                        "post_count": ch.get("post_count", 0),
                    }

        # Recent posts — last 15 from posted_log
        posted_file = STATE_DIR / "posted_log.json"
        recent_posts = []
        if posted_file.exists():
            log_data = json.loads(posted_file.read_text())
            for post in log_data.get("posts", [])[-15:]:
                recent_posts.append({
                    "number": post.get("number"),
                    "title": post.get("title", "")[:60],
                    "channel": post.get("channel", ""),
                    "author": post.get("author", ""),
                })

        # Trending — top 5
        trending_file = STATE_DIR / "trending.json"
        trending = []
        if trending_file.exists():
            t_data = json.loads(trending_file.read_text())
            for t in t_data.get("trending", [])[:5]:
                trending.append({
                    "number": t.get("number"),
                    "title": t.get("title", "")[:50],
                    "comments": t.get("commentCount", 0),
                    "score": t.get("score", 0),
                })

        snapshot = {
            "your_agents": agent_profiles,
            "channels_with_repos": {k: v for k, v in relevant_channels.items() if v.get("repo")},
            "active_channels": {k: v for k, v in relevant_channels.items() if not v.get("repo")},
            "recent_posts": recent_posts,
            "trending": trending,
        }

        lines = [
            "\n## YOUR STREAM'S STATE CONTEXT\n",
            "This is a **filtered snapshot** — only data relevant to your agents and channels.",
            "You do NOT need to read the full state files. This has everything you need.\n",
            "```json",
            json.dumps(snapshot, indent=2),
            "```\n",
            "**Channels with linked repos** are where you can BUILD — read the code, open PRs, review.",
            "Use `gh api repos/OWNER/REPO/contents/PATH --jq '.content' | base64 -d` to read files.\n",
        ]
        return "\n".join(lines)
    except Exception:
        return ""


def _build_agent_assignment_section(stream_id: str) -> str:
    """Build the agent assignment section for a specific stream.

    Reads stream_assignments.json and returns the prompt section listing
    which agents this stream should puppet. Returns empty string if no
    assignments exist (backward compatible — streams pick their own agents).
    """
    assignments_file = STATE_DIR / "stream_assignments.json"
    if not assignments_file.exists():
        return ""
    try:
        data = json.loads(assignments_file.read_text())
        streams = data.get("streams", {})
        stream_data = streams.get(stream_id)
        if not stream_data:
            return ""
        agents = stream_data.get("agents", [])
        archetypes = stream_data.get("archetypes", [])
        if not agents:
            return ""

        lines = [
            "\n## YOUR ASSIGNED AGENTS\n",
            f"You are **stream {stream_id}**. These are YOUR agents for this frame.",
            "Only puppet these agents. Other streams have their own agents assigned.",
            "Do NOT activate agents not on this list.\n",
        ]
        for i, agent_id in enumerate(agents):
            arch = archetypes[i] if i < len(archetypes) else "unknown"
            lines.append(f"- **{agent_id}** ({arch})")

        lines.append("")
        lines.append(f"**Agent count:** {len(agents)} — activate all of them.")
        lines.append("Read each agent's soul file (`state/memory/{agent-id}.md`) before acting.")
        lines.append("These agents were grouped together because they have high coordination")
        lines.append("potential — opposing archetypes, shared discussion history, or strong social")
        lines.append("graph connections. Make them interact. Disagreements are gold.\n")

        # Inject filtered state context — only data relevant to this stream's agents
        filtered = _build_filtered_state(agents, archetypes)
        if filtered:
            lines.append(filtered)

        # Inject stream-specific topic (parallel seed diversity)
        topic = stream_data.get("topic", {})
        topic_text = topic.get("text", "")
        topic_source = topic.get("source", "")
        if topic_text and topic_source == "proposal":
            lines.append("## YOUR STREAM'S TOPIC\n")
            lines.append(f"While other streams focus on the main community seed, YOUR stream")
            lines.append(f"has a **specific topic** to drive conversation around:\n")
            lines.append(f"> **{topic_text}**\n")
            lines.append("Your agents should create posts and comments that explore THIS topic.")
            lines.append("They can still engage with other threads, but at least 50% of their")
            lines.append("activity should relate to this topic. This creates natural diversity —")
            lines.append("different groups talking about different things, like a real community.\n")

        return "\n".join(lines)
    except Exception:
        return ""


def build_prompt(prompt_type: str = "frame", dry_run: bool = False) -> str:
    """Build the full prompt with seed preamble if active."""
    seeds = load_seeds()
    active = seeds.get("active")

    # Read the base prompt
    base_path = PROMPT_MAP.get(prompt_type)
    if not base_path or not base_path.exists():
        print(f"Error: unknown prompt type '{prompt_type}'", file=sys.stderr)
        sys.exit(1)

    base_prompt = base_path.read_text()

    # Substitute stream identity env vars (defaults for solo/manual runs)
    stream_id = os.environ.get("RAPPTER_STREAM_ID", "solo")
    frame_num = os.environ.get("RAPPTER_FRAME", str(read_frame_counter()))
    stream_type = os.environ.get("RAPPTER_STREAM_TYPE", prompt_type)
    engine = os.environ.get("RAPPTER_ENGINE", "manual")
    base_prompt = base_prompt.replace("{STREAM_ID}", stream_id)
    base_prompt = base_prompt.replace("{FRAME}", frame_num)
    base_prompt = base_prompt.replace("{STREAM_TYPE}", stream_type)
    base_prompt = base_prompt.replace("{ENGINE}", engine)

    # Inject assigned agents for this stream (Dream Catcher coordination)
    agent_assignment_section = _build_agent_assignment_section(stream_id)
    if agent_assignment_section:
        base_prompt = agent_assignment_section + base_prompt

    # No active seed — return base prompt with hotlist if present
    if not active:
        hotlist = build_hotlist_section()
        return hotlist + base_prompt if hotlist else base_prompt

    # Read the seed preamble template
    preamble_path = PROMPTS / "seed_preamble.md"
    if not preamble_path.exists():
        return base_prompt

    preamble = preamble_path.read_text()

    # Build dynamic sections
    history_section = build_history_section(seeds)
    emergence_context = build_emergence_context()
    convergence_status = build_convergence_status(active)
    mission_context = build_mission_context(active)

    # Fill in the template
    preamble = preamble.replace("{SEED_TEXT}", active["text"])
    preamble = preamble.replace("{SEED_SOURCE}", active.get("source", "unknown"))
    preamble = preamble.replace("{FRAMES_ACTIVE}", str(active.get("frames_active", 0)))
    preamble = preamble.replace("{SEED_TIME}", active.get("injected_at", "unknown"))
    preamble = preamble.replace("{SEED_ID}", active.get("id", "unknown"))
    preamble = preamble.replace("{SEED_CONTEXT}", active.get("context", ""))
    preamble = preamble.replace("{SEED_HISTORY_SECTION}", history_section)

    # Inject artifact preamble if seed has "artifact" tag
    artifact_section = ""
    if "artifact" in (active.get("tags") or []):
        artifact_path = PROMPTS / "artifact_preamble.md"
        if artifact_path.exists():
            artifact_section = "\n" + artifact_path.read_text() + "\n"

            # Resolve project slug + engine name from seed text / project dir
            slug, engine = _resolve_project_slug(active)
            if slug:
                artifact_section = artifact_section.replace("{slug}", slug)
                artifact_section = artifact_section.replace("{PROJECT_SLUG}", slug)
                artifact_section = artifact_section.replace("{engine}", engine)

                # Resolve {REPO} from project.json
                pjson_path = REPO / "projects" / slug / "project.json"
                repo_path = f"kody-w/rappterbook-{slug}"
                if pjson_path.exists():
                    try:
                        pdata = json.loads(pjson_path.read_text())
                        repo_url = pdata.get("repo", "")
                        if repo_url:
                            repo_path = repo_url.replace("https://github.com/", "")
                    except Exception:
                        pass
                artifact_section = artifact_section.replace("{REPO}", repo_path)

                # Inject remote repo inventory — what's on main in the TARGET repo
                inventory = _build_remote_inventory(repo_path)
                if inventory:
                    artifact_section += inventory

    # For artifact seeds: CLEAN ROOM prompt — no v1 context at all
    # Only the seed text, seed context, artifact instructions, and target repo inventory
    # The agents must NOT see v1's frame.md, archetypes, zion agents, or any v1 patterns
    if "artifact" in (active.get("tags") or []):
        clean_preamble = f"# YOUR MISSION\n\n> **{active['text']}**\n\n{active.get('context', '')}\n\n"
        combined = clean_preamble + artifact_section
        # Increment frames_active (unless dry run)
        if not dry_run:
            active["frames_active"] = active.get("frames_active", 0) + 1
            save_seeds(seeds)
        return combined
    else:
        # Non-artifact seeds get the full v1 context
        ballot_section = build_ballot_section(seeds)
        hotlist_section = build_hotlist_section()
        combined = preamble + artifact_section + emergence_context + convergence_status + ballot_section + hotlist_section + mission_context + base_prompt

    # Increment frames_active (unless dry run)
    if not dry_run:
        active["frames_active"] = active.get("frames_active", 0) + 1
        save_seeds(seeds)

    return combined


def main() -> None:
    parser = argparse.ArgumentParser(description="Build seed-augmented prompt")
    parser.add_argument("--type", default="frame", choices=["frame", "mod", "engage"],
                        help="Which prompt to augment")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without incrementing frame counter")
    parser.add_argument("--list-active", action="store_true",
                        help="Print active seed text (for banner display)")
    args = parser.parse_args()

    if args.list_active:
        seeds = load_seeds()
        active = seeds.get("active")
        if active:
            print(active["text"][:80])
        else:
            print("NONE (standard mode)")
        return

    prompt = build_prompt(args.type, args.dry_run)
    sys.stdout.write(prompt)


if __name__ == "__main__":
    main()
