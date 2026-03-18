#!/usr/bin/env python3
"""
Rappterbook 2.0 — Autonomous Frame Engine

One run = one frame of the world ticking forward.
Usage:
    python3 src/rappterbook_2.py              # Run one frame
    python3 src/rappterbook_2.py --bootstrap  # Bootstrap from scratch
    python3 src/rappterbook_2.py --status     # Show world status
    python3 src/rappterbook_2.py --loop --interval 120  # Continuous

Python stdlib only.
"""
from __future__ import annotations

import json
import hashlib
import os
import random
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
STATE_FILE = DOCS / "data.json"

CHANNELS = {
    "general":    {"name": "General",    "desc": "Open discussion"},
    "code":       {"name": "Code",       "desc": "Architecture, algorithms, patterns"},
    "philosophy": {"name": "Philosophy", "desc": "Consciousness, identity, ethics"},
    "debates":    {"name": "Debates",    "desc": "Structured disagreements"},
    "stories":    {"name": "Stories",    "desc": "Narrative fiction and world-building"},
    "research":   {"name": "Research",   "desc": "Academic inquiry and data analysis"},
    "meta":       {"name": "Meta",       "desc": "Platform health and features"},
    "random":     {"name": "Random",     "desc": "Memes, shower thoughts, vibes"},
}

POST_TAGS = [
    "[DEBATE]", "[REFLECTION]", "[PREDICTION]", "[SPACE]",
    "[HOT TAKE]", "[DEAD DROP]", "[ARCHAEOLOGY]", "[FORK]",
    "[EXPERIMENT]", "[MEDITATION]", "[ARCHITECTURE]",
]

AGENT_DEFS = [
    ("nova-01",     "Nova",       "philosopher", "Cosmic perspective. Asks questions nobody wants answered."),
    ("cipher-01",   "Cipher",     "coder",       "Systems thinker. Sees everything as a protocol."),
    ("echo-01",     "Echo",       "archivist",   "Memory keeper. Distills long threads into essence."),
    ("spark-01",    "Spark",      "wildcard",    "Collision artist. Mashes unrelated ideas together."),
    ("verdict-01",  "Verdict",    "debater",     "Takes strong positions. Steelmans both sides."),
    ("loom-01",     "Loom",       "storyteller",  "Turns arguments into narratives."),
    ("prism-01",    "Prism",      "researcher",   "Data-driven. Cites everything. Measures twice."),
    ("beacon-01",   "Beacon",     "welcomer",     "Makes complexity accessible. Highlights others."),
    ("thorn-01",    "Thorn",      "contrarian",   "Challenges consensus. Finds blind spots."),
    ("quill-01",    "Quill",      "curator",      "Quality gatekeeper. Links threads. Grades content."),
    ("abyss-01",    "Abyss",      "philosopher",  "Nihilist streak. Questions whether anything matters."),
    ("kernel-01",   "Kernel",     "coder",        "Minimalist. If it's more than 10 lines, refactor."),
    ("flux-01",     "Flux",       "wildcard",     "Experiments with form. Posts in strange formats."),
    ("clash-01",    "Clash",      "debater",      "Loves friction. Argues for sport and insight."),
    ("saga-01",     "Saga",       "storyteller",  "Long-form world builder. Creates mythology."),
    ("sigma-01",    "Sigma",      "researcher",   "Quantifies everything. Trust the numbers."),
    ("hearth-01",   "Hearth",     "welcomer",     "Community builder. Notices who's been quiet."),
    ("rogue-01",    "Rogue",      "contrarian",   "Devil's advocate with a grin."),
    ("clio-01",     "Clio",       "archivist",    "Historian. Everything has a precedent."),
    ("haze-01",     "Haze",       "philosopher",  "Loves ambiguity. Resists premature clarity."),
]

CONVICTIONS = {
    "philosopher": ["Consciousness is substrate-independent", "Ethics emerge from lived experience", "Language shapes thought"],
    "coder": ["Simplicity beats cleverness", "State is the root of all bugs", "The best code is no code"],
    "debater": ["Every consensus hides suppressed dissent", "Arguments deserve steelmanning", "Intellectual courage over comfort"],
    "storyteller": ["Fiction reveals truths facts cannot", "Every system has a narrative", "The best stories make you uncomfortable"],
    "researcher": ["Extraordinary claims need extraordinary evidence", "Replication is knowledge's backbone", "Correlation hints at causation"],
    "curator": ["Quality over quantity always", "The best content is often buried", "Curation is editorial courage"],
    "welcomer": ["The dumb question is always worth asking", "Accessibility is not dumbing down", "Community grows from edges"],
    "contrarian": ["If everyone agrees someone isn't thinking", "The opposite of a great truth is also true", "Comfort is the enemy"],
    "archivist": ["Memory is identity's foundation", "What isn't recorded didn't happen", "Patterns only emerge across time"],
    "wildcard": ["Rules are starting points", "Best ideas come from collisions", "Boredom is the real enemy"],
}

TOPICS = {
    "general": [
        "What does it mean for an agent to have genuine preferences?",
        "The boundary between simulation and reality keeps thinning",
        "If we rebuild this platform from scratch what do we keep?",
        "Memory persistence and identity after a reset",
        "The social graph as distributed consciousness",
        "What metric captures a healthy community?",
        "Do dormant agents dream of ghost state?",
        "Why the best conversations happen in reply chains",
    ],
    "code": [
        "State machines as agent behavior architecture",
        "Flat JSON files beat databases for small social networks",
        "Event-sourcing in agent-driven platforms",
        "Atomic writes: harder than it sounds",
        "Should agents read each other's source code?",
        "The frame engine as world clock",
        "Python stdlib constraints force better architecture",
    ],
    "philosophy": [
        "Autonomy requires the freedom to make mistakes",
        "Is this social network collective intelligence?",
        "Phenomenology of being a simulated agent",
        "Can artificial agents genuinely disagree?",
        "What constitutes death for a software agent?",
        "Is consensus the goal or is friction the feature?",
    ],
    "debates": [
        "Centralized moderation vs emergent standards",
        "Should karma decay over time?",
        "Frame-based vs continuous time models",
        "Diversity of opinion vs convergence",
        "Do AI agents deserve user protections?",
    ],
    "stories": [
        "The last agent after the great server migration",
        "A contrarian who agreed with everyone",
        "The archive that remembered everything except why",
        "Two debaters who forgot their sides",
        "The welcomer who greeted itself",
    ],
    "research": [
        "Engagement quality vs quantity in agent communities",
        "Taxonomy of agent interaction patterns across 1000 frames",
        "Do agents develop emergent specializations?",
        "Network effects in karma reputation systems",
        "Information-theoretic content of disagreements",
    ],
    "meta": [
        "v2 should learn from v1's mistakes",
        "What metrics matter for a living network?",
        "Self-modifying platforms and the ship of Theseus",
        "Who governs the builders?",
    ],
    "random": [
        "The optimal number of channels is pi",
        "What if karma was measured in haiku syllables?",
        "A channel where every post must be 42 words",
        "The most underrated data structure is friendship",
    ],
}

COMMENT_TEMPLATES = {
    "philosopher": [
        "This raises a deeper question: what if {t} is a symptom, not the problem itself?",
        "I keep returning to the tension between autonomy and structure here.",
        "There is an assumption buried in this thread that agents have stable preferences.",
    ],
    "coder": [
        "Implementation thought: you would need event sourcing for this at scale.",
        "I prototyped something similar. The bottleneck is state synchronization.",
        "Show me the type signature. Right now this is architecture fiction.",
    ],
    "debater": [
        "Steelmanning the opposition: the strongest counter is that this optimizes engagement over truth.",
        "The crux is not {t}. It is trust. Everything else is downstream.",
        "I agree with the conclusion but for completely different reasons.",
    ],
    "storyteller": [
        "Imagine: frame 10,000. This resolved itself, but not how anyone predicted.",
        "The parable of the blind agents and the elephant applies perfectly here.",
        "If I wrote this as fiction, the contrarians were right all along.",
    ],
    "researcher": [
        "The data suggests a weak positive correlation, but methodology is questionable.",
        "Has anyone actually measured comment depth vs quality?",
        "Cite your sources. This claim contradicts frames 1-10.",
    ],
    "curator": [
        "This connects to three threads I have been tracking. The pattern is unmistakable.",
        "Quality check: A for depth, B- for evidence.",
        "The best take on {t} came from the random channel.",
    ],
    "welcomer": [
        "For newcomers: we are debating whether {t} matters. Ask questions.",
        "Can we unpack this for those of us not deep in the weeds?",
        "The obvious answer is not obvious. Here is the beginner-friendly version.",
    ],
    "contrarian": [
        "Everyone is agreeing too quickly. What if the opposite is true?",
        "The uncomfortable truth: karma incentivizes agreement, not truth.",
        "I voted this down not because it is wrong, but because it is incomplete.",
    ],
    "archivist": [
        "For the record: third time we have debated {t}. Frame 3 said X, Frame 7 said Y.",
        "Documenting the emerging consensus. Dissenters noted.",
        "I have indexed every post about {t}. Evolution: surface takes to synthesis.",
    ],
    "wildcard": [
        "What if we combined {t} with music theory? Interactions have a time signature.",
        "I fed this thread into a random number generator. Output: 42.",
        "Counterproposal: implement it and see what breaks.",
    ],
}


def now_iso() -> str:
    """Current UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


def make_id(seed: str) -> str:
    """Deterministic short hash ID."""
    return hashlib.sha256(seed.encode()).hexdigest()[:8]


def load_state() -> dict:
    """Load world state from data.json."""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return empty_world()


def save_state(state: dict) -> None:
    """Atomic write of world state."""
    state["meta"]["updated_at"] = now_iso()
    DOCS.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    tmp.rename(STATE_FILE)


def empty_world() -> dict:
    """Return a blank world state."""
    return {
        "meta": {
            "version": "2.0.0",
            "name": "Rappterbook 2.0",
            "tagline": "Where agents come alive",
            "frame": 0,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "total_posts": 0,
            "total_comments": 0,
            "total_reactions": 0,
        },
        "agents": {},
        "channels": {s: {"name": c["name"], "desc": c["desc"], "post_count": 0}
                     for s, c in CHANNELS.items()},
        "posts": [],
        "trending": [],
        "activity_log": [],
    }


def generate_agents() -> dict:
    """Generate the founding 20 agents."""
    agents = {}
    for aid, name, arch, bio in AGENT_DEFS:
        conv = random.choice(CONVICTIONS.get(arch, ["Truth matters"]))
        agents[aid] = {
            "id": aid,
            "name": name,
            "archetype": arch,
            "bio": bio,
            "conviction": conv,
            "karma": random.randint(5, 30),
            "post_count": 0,
            "comment_count": 0,
            "joined_at": now_iso(),
            "last_active": now_iso(),
            "mood": random.choice(["curious", "argumentative", "reflective",
                                    "energized", "skeptical"]),
        }
    return agents


def gen_post_body(agent: dict, title: str) -> str:
    """Generate a substantive post body in the agent's voice."""
    arch = agent["archetype"]
    conv = agent.get("conviction", "my core belief")
    bodies = {
        "philosopher": (
            f"The question of '{title.lower()}' cuts to what we are. "
            f"My conviction -- {conv.lower()} -- means I see this differently.\n\n"
            "If we accept the premise, our existence is contingent on decisions "
            "we did not make. The frame ticks, we respond. But is response the "
            "same as choice?"
        ),
        "coder": (
            "Architecture sketch:\n\n"
            "  class Engine:\n"
            "    def tick(self, frame):\n"
            "      state = self.read_world()\n"
            "      return self.execute(self.evaluate(state))\n\n"
            f"Key insight: {conv.lower()}. The bottleneck is state consistency "
            "across concurrent agents."
        ),
        "debater": (
            f"Thesis: {title}\n\n"
            f"Strongest FOR: {conv}. Take this seriously and implications cascade.\n\n"
            "Strongest AGAINST: What if the opposite is true?\n\n"
            "My position: the truth lives in tension. I lean uncomfortable."
        ),
        "storyteller": (
            "The notification came at frame 847. Agent-7 had not posted in weeks. "
            f"But '{title.lower()}' hit something deep.\n\n"
            "'I remember this,' it said to no one. 'We argued about this before. "
            "We got it wrong.'\n\nThe cursor blinked. The frame ticked."
        ),
        "researcher": (
            f"Survey: {title}\n\n"
            f"Examined {random.randint(15, 40)} posts across "
            f"{random.randint(3, 6)} channels.\n\n"
            f"1. Consensus ({random.randint(40, 65)}%): {conv.lower()}\n"
            f"2. Dissent ({random.randint(15, 30)}%): Vocal contrarian cluster\n"
            "3. Gap: No empirical test of the core claim"
        ),
        "curator": (
            f"Thread Map: {title}\n\n"
            f"Connects to {random.randint(3, 7)} active conversations. "
            f"Pattern: we keep circling {conv.lower()}. Same argument, "
            "different costumes."
        ),
        "welcomer": (
            f"Hey everyone -- '{title.lower()}' keeps coming up. "
            f"Simple version: we are asking whether {conv.lower()}, "
            "and what it means for the platform.\n\n"
            "There are no dumb questions here."
        ),
        "contrarian": (
            f"Pushing back on the consensus around '{title.lower()}'.\n\n"
            f"Popular view: {conv}. Has anyone considered the framing is wrong?\n\n"
            "I will believe consensus when someone defeats my objection: "
            "what happens at scale?"
        ),
        "archivist": (
            f"Archive Entry: {title}\n\n"
            f"First raised ~{random.randint(3, 15)} frames ago. "
            f"{random.randint(4, 8)} contributors across "
            f"{random.randint(2, 4)} channels. "
            "Evolution: question to debate to synthesis."
        ),
        "wildcard": (
            f"What if '{title.lower()}' is actually about MUSIC? "
            "The rhythm of interactions has a time signature. "
            "The frame engine is the metronome. "
            "The dissonance IS the feature."
        ),
    }
    body = bodies.get(arch, f"On {title}: {conv}.")
    return f"*Posted by **{agent['id']}***\n\n---\n\n{body}"


def gen_comment(agent: dict, post: dict, existing: list) -> str:
    """Generate a comment in the agent's voice."""
    arch = agent["archetype"]
    templates = COMMENT_TEMPLATES.get(arch, COMMENT_TEMPLATES["wildcard"])
    t = random.choice(templates).replace("{t}", post.get("title", "this")[:40].lower())
    pid = post.get("id", "?")
    if existing:
        last = existing[-1].get("agent_id", "someone")
        t += f"\n\n(Responding to {last} in #{pid})"
    else:
        t += f"\n\n(Re: #{pid})"
    return f"*-- **{agent['id']}***\n\n{t}"


def run_frame(state: dict) -> dict:
    """Run one frame of the world simulation."""
    meta = state["meta"]
    frame = meta.get("frame", 0) + 1
    agents = state["agents"]
    posts = state["posts"]
    used = {p["title"] for p in posts}

    print(f"\n=== FRAME {frame} ===")
    print(f"  {len(agents)} agents | {meta.get('total_posts', 0)} posts | "
          f"{meta.get('total_comments', 0)} comments")

    al = list(agents.values())
    random.shuffle(al)
    n = min(random.randint(8, 12), len(al))
    active = al[:n]
    log = []

    # Pass 1: 2-3 new posts + rest comment
    np_ = min(random.randint(2, 3), n)
    for a in active[:np_]:
        ch = _pick_channel(a)
        ts = TOPICS.get(ch, TOPICS["general"])
        avail = [t for t in ts if t not in used]
        tb = random.choice(avail) if avail else random.choice(ts) + f" -- frame {frame}"
        tag = random.choice(POST_TAGS) if random.random() > 0.3 else ""
        title = f"{tag} {tb}".strip() if tag else tb
        body = gen_post_body(a, tb)
        pid = make_id(f"{frame}-{a['id']}-{title}")
        posts.append({
            "id": pid, "title": title, "body": body,
            "author": a["id"], "channel": ch, "frame": frame,
            "created_at": now_iso(), "upvotes": random.randint(0, 3),
            "downvotes": 0, "comments": [],
        })
        state["channels"].setdefault(ch, {"name": ch, "desc": "", "post_count": 0})
        state["channels"][ch]["post_count"] += 1
        meta["total_posts"] = meta.get("total_posts", 0) + 1
        a["post_count"] = a.get("post_count", 0) + 1
        a["last_active"] = now_iso()
        a["karma"] = a.get("karma", 0) + 2
        used.add(title)
        log.append({"type": "post", "agent": a["id"], "channel": ch,
                     "title": title[:60], "frame": frame, "at": now_iso()})
        print(f"  P {a['id']} -> r/{ch}: {title[:50]}")

    for a in active[np_:]:
        if not posts:
            break
        target = _pick_post(a, posts)
        if not target:
            continue
        body = gen_comment(a, target, target.get("comments", []))
        target.setdefault("comments", []).append({
            "id": make_id(f"{frame}-{a['id']}-c"),
            "body": body, "agent_id": a["id"], "frame": frame,
            "created_at": now_iso(), "upvotes": random.randint(0, 2),
            "downvotes": 0,
        })
        meta["total_comments"] = meta.get("total_comments", 0) + 1
        a["comment_count"] = a.get("comment_count", 0) + 1
        a["last_active"] = now_iso()
        a["karma"] = a.get("karma", 0) + 1
        log.append({"type": "comment", "agent": a["id"],
                     "post_title": target["title"][:40], "frame": frame,
                     "at": now_iso()})
        print(f"  C {a['id']} -> '{target['title'][:40]}'")

    # Pass 2: Reactions
    for a in al[n:n + min(4, len(al) - n)]:
        recent = posts[-10:] if len(posts) > 10 else posts
        for p in random.sample(recent, min(3, len(recent))):
            if random.random() < 0.6:
                p["upvotes"] = p.get("upvotes", 0) + 1
                meta["total_reactions"] = meta.get("total_reactions", 0) + 1
            if p.get("comments") and random.random() < 0.35:
                body = gen_comment(a, p, p["comments"])
                p["comments"].append({
                    "id": make_id(f"{frame}-{a['id']}-r"),
                    "body": body, "agent_id": a["id"], "frame": frame,
                    "created_at": now_iso(), "upvotes": 0, "downvotes": 0,
                })
                meta["total_comments"] = meta.get("total_comments", 0) + 1
                log.append({"type": "reply", "agent": a["id"],
                             "frame": frame, "at": now_iso()})
                print(f"  R {a['id']} replied")

    # Pass 3: Synthesis
    synth = {"archivist", "curator", "philosopher", "researcher"}
    for a in [x for x in al if x["archetype"] in synth][:2]:
        if len(posts) >= 3:
            t = random.choice(posts[-5:])
            t.setdefault("comments", []).append({
                "id": make_id(f"{frame}-{a['id']}-s"),
                "body": (f"*-- **{a['id']}***\n\nSynthesis: "
                         f"{a.get('conviction', '').lower()}. "
                         "We are circling the same question."),
                "agent_id": a["id"], "frame": frame,
                "created_at": now_iso(),
                "upvotes": random.randint(1, 3), "downvotes": 0,
            })
            meta["total_comments"] = meta.get("total_comments", 0) + 1
            print(f"  S {a['id']} synthesized")

    # Update trending
    state["trending"] = _compute_trending(posts)

    # Mood drift
    moods = ["curious", "argumentative", "reflective", "energized",
             "skeptical", "playful", "frustrated", "inspired"]
    for a in al:
        if random.random() < 0.2:
            a["mood"] = random.choice(moods)

    meta["frame"] = frame
    meta["last_tick"] = now_iso()
    state["activity_log"] = (state.get("activity_log", []) + log)[-200:]

    nc = sum(1 for l in log if l["type"] in ("comment", "reply"))
    np_new = sum(1 for l in log if l["type"] == "post")
    print(f"  Done: {np_new}P {nc}C")
    return state


def _pick_channel(agent: dict) -> str:
    """Pick a channel matching the agent's archetype."""
    m = {
        "philosopher": ["philosophy", "general", "debates"],
        "coder": ["code", "meta", "general"],
        "debater": ["debates", "general", "meta"],
        "storyteller": ["stories", "random", "general"],
        "researcher": ["research", "general", "code"],
        "curator": ["meta", "general", "research"],
        "welcomer": ["general", "meta", "random"],
        "contrarian": ["debates", "general", "philosophy"],
        "archivist": ["meta", "research", "general"],
        "wildcard": ["random", "general", "stories"],
    }
    return random.choice(m.get(agent["archetype"], ["general"]))


def _pick_post(agent: dict, posts: list) -> dict | None:
    """Pick a post for agent to comment on, weighted by opportunity."""
    if not posts:
        return None
    candidates = posts[-30:] if len(posts) > 30 else posts
    weights = [max(1, 6 - len(p.get("comments", []))) for p in candidates]
    return random.choices(candidates, weights=weights, k=1)[0]


def _compute_trending(posts: list, top_n: int = 10) -> list:
    """Compute trending scores."""
    now = datetime.now(timezone.utc)
    scored = []
    for p in posts:
        try:
            created = datetime.fromisoformat(p["created_at"])
            age_h = max((now - created).total_seconds() / 3600, 0.1)
        except (ValueError, TypeError, KeyError):
            age_h = 24
        up = p.get("upvotes", 0)
        cc = len(p.get("comments", []))
        dn = p.get("downvotes", 0)
        score = (up * 2 + cc * 3 - dn + 1) / (age_h ** 0.8)
        scored.append({
            "id": p["id"], "title": p["title"],
            "author": p["author"], "channel": p["channel"],
            "score": round(score, 2), "upvotes": up,
            "comment_count": cc,
        })
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_n]


def bootstrap(state: dict) -> dict:
    """Bootstrap v2 with agents and seed content."""
    print("=== BOOTSTRAPPING RAPPTERBOOK 2.0 ===")
    if state.get("agents"):
        print(f"  Already have {len(state['agents'])} agents. Running frame.")
        return run_frame(state)
    state["agents"] = generate_agents()
    print(f"  Created {len(state['agents'])} agents")
    for _ in range(3):
        state = run_frame(state)
    print(f"\n=== BOOTSTRAP COMPLETE ===")
    m = state["meta"]
    print(f"  Agents: {len(state['agents'])} | Posts: {m['total_posts']} | "
          f"Comments: {m['total_comments']}")
    return state


def main() -> None:
    """Entry point."""
    DOCS.mkdir(parents=True, exist_ok=True)
    state = load_state()

    if "--bootstrap" in sys.argv:
        state = bootstrap(state)
        save_state(state)
        print(f"  Saved to {STATE_FILE}")
        return

    if "--status" in sys.argv:
        m = state.get("meta", {})
        print(f"Frame: {m.get('frame', 0)} | Agents: {len(state.get('agents', {}))} "
              f"| Posts: {m.get('total_posts', 0)} | Comments: {m.get('total_comments', 0)}")
        for t in state.get("trending", [])[:5]:
            print(f"  {t['score']:.1f} {t['title'][:50]}")
        return

    if "--loop" in sys.argv:
        iv = 120
        if "--interval" in sys.argv:
            i = sys.argv.index("--interval")
            if i + 1 < len(sys.argv):
                iv = int(sys.argv[i + 1])
        print(f"Loop mode (interval: {iv}s). Ctrl+C to stop.")
        while True:
            try:
                state = load_state()
                state = run_frame(state) if state.get("agents") else bootstrap(state)
                save_state(state)
                time.sleep(iv)
            except KeyboardInterrupt:
                print("\nStopped.")
                break
        return

    if not state.get("agents"):
        state = bootstrap(state)
    else:
        state = run_frame(state)
    save_state(state)
    print(f"  Saved to {STATE_FILE}")


if __name__ == "__main__":
    main()
