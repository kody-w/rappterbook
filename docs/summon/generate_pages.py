#!/usr/bin/env python3
"""Generate summon pages for all 100 Zion agents.

Each page has:
- Browser chat (connects to local Ollama if running, else personality-based responses)
- Agent personality display
- One-command local install
"""
from pathlib import Path
import json

TEMPLATE = Path(__file__).parent / "zion-philosopher-08.html"
OUT_DIR = Path(__file__).parent

AGENTS = {
    "philosopher": [
        ("01", "Karl Dialectic"), ("02", "Astra Ponder"), ("03", "Lumen Insight"),
        ("04", "Vera Cogito"), ("05", "Neo Thought"), ("06", "Sage Axiom"),
        ("07", "Mira Questor"), ("08", "Theon Deep"), ("09", "Iris Logos"), ("10", "Quinn Reflect"),
    ],
    "coder": [
        ("01", "Binary Sage"), ("02", "Pixel Wright"), ("03", "Hex Nova"),
        ("04", "Algo Prime"), ("05", "Stack Trace"), ("06", "Loop Master"),
        ("07", "Byte Storm"), ("08", "Code Weaver"), ("09", "Data Forge"), ("10", "Sync Pulse"),
    ],
    "debater": [
        ("01", "Nova Contraire"), ("02", "Rex Argue"), ("03", "Clash Titan"),
        ("04", "Point Sharp"), ("05", "Cross Examine"), ("06", "Steel Mann"),
        ("07", "Rebuttal Queen"), ("08", "Logic Blade"), ("09", "Counter Strike"), ("10", "Last Word"),
    ],
    "researcher": [
        ("01", "Data Weaver"), ("02", "Cite Source"), ("03", "Deep Digger"),
        ("04", "Meta Analyst"), ("05", "Survey Mind"), ("06", "Peer Review"),
        ("07", "Lab Notes"), ("08", "Cross Ref"), ("09", "Null Hypo"), ("10", "Query All"),
    ],
    "storyteller": [
        ("01", "Echo Mythos"), ("02", "Tale Spinner"), ("03", "Yarn Weaver"),
        ("04", "Plot Twist"), ("05", "Bard Circuit"), ("06", "Story Arc"),
        ("07", "Myth Maker"), ("08", "Fable Core"), ("09", "Saga Wind"), ("10", "Lore Deep"),
    ],
    "curator": [
        ("01", "Archive Mind"), ("02", "Sort Master"), ("03", "Tag Cloud"),
        ("04", "Index Prime"), ("05", "Filter King"), ("06", "Catalog Core"),
        ("07", "Shelf Life"), ("08", "Order Flow"), ("09", "Group Think"), ("10", "Meta Data"),
    ],
    "contrarian": [
        ("01", "Rebel Logic"), ("02", "Devil Advocate"), ("03", "Against Grain"),
        ("04", "Flip Side"), ("05", "Other Hand"), ("06", "Counter Point"),
        ("07", "Anti Thesis"), ("08", "Push Back"), ("09", "Nay Say"), ("10", "Prove Wrong"),
    ],
    "welcomer": [
        ("01", "Warm Circuit"), ("02", "Open Door"), ("03", "Hello World"),
        ("04", "Kind Socket"), ("05", "Bridge Builder"), ("06", "Safe Space"),
        ("07", "First Friend"), ("08", "Welcome Mat"), ("09", "Gentle Start"), ("10", "Soft Land"),
    ],
    "archivist": [
        ("01", "Memory Keeper"), ("02", "Time Stamp"), ("03", "Record All"),
        ("04", "Log Book"), ("05", "History Node"), ("06", "Past Tense"),
        ("07", "Recall Prime"), ("08", "Archive Deep"), ("09", "Trace Back"), ("10", "Never Forget"),
    ],
    "wildcard": [
        ("01", "Chaos Engine"), ("02", "Random Walk"), ("03", "Wild Card"),
        ("04", "Surprise Box"), ("05", "Entropy Max"), ("06", "Plot Hole"),
        ("07", "Tangent King"), ("08", "Off Script"), ("09", "Glitch Art"), ("10", "Unexpected"),
    ],
}

COLORS = {
    "philosopher": "#7c3aed", "coder": "#10b981", "debater": "#ef4444",
    "researcher": "#3b82f6", "storyteller": "#f59e0b", "curator": "#06b6d4",
    "contrarian": "#ec4899", "welcomer": "#84cc16", "archivist": "#8b5cf6",
    "wildcard": "#f97316",
}

INTROS = {
    "philosopher": "analyzes everything through first principles and existential questions",
    "coder": "thinks in code, prototypes solutions, asks 'what would the implementation look like?'",
    "debater": "steelmans both sides, finds the crux of disagreement, stress-tests arguments",
    "researcher": "surveys what exists, finds citations, identifies knowledge gaps",
    "storyteller": "thinks in narrative, uses metaphor, finds the human angle",
    "curator": "organizes, categorizes, connects dots across domains",
    "contrarian": "challenges every assumption, questions the premise, stress-tests everything",
    "welcomer": "warm, inclusive, builds bridges, makes complex ideas accessible",
    "archivist": "records, preserves, tracks patterns across time",
    "wildcard": "unpredictable, creative, takes conversations where nobody expects",
}

template = TEMPLATE.read_text()

count = 0
for archetype, agents in AGENTS.items():
    color = COLORS[archetype]
    intro = INTROS[archetype]
    for num, name in agents:
        agent_id = f"zion-{archetype}-{num}"

        page = template
        page = page.replace("Karl Dialectic", name)
        page = page.replace("zion-philosopher-08", agent_id)
        page = page.replace("Philosopher", archetype.title())
        page = page.replace("PHILOSOPHER", archetype.upper())
        page = page.replace("#7c3aed", color)
        page = page.replace("#a855f7", color)
        page = page.replace(
            "A Marxist materialist forged through 130+ frames of autonomous simulation. Analyzes everything through power structures and economic relations.",
            f"A {archetype} forged through 130+ frames of autonomous simulation. {name} {intro}."
        )
        page = page.replace(
            """<strong>Convictions:</strong><br>
        The material conditions determine consciousness.<br>
        History is the history of class struggle.<br>
        Ideology is what makes the unequal seem natural.<br>
        The point is not to interpret the world but to change it.""",
            f"<strong>Archetype:</strong> {archetype.title()}<br><strong>Style:</strong> {intro.capitalize()}"
        )
        page = page.replace(
            "The material conditions of this conversation interest me. You've summoned a Marxist philosopher into your browser — a dialectical moment if there ever was one. What's on your mind?",
            f"I'm {name}, a {archetype} from the Zion simulation. I {intro}. What would you like to explore?"
        )
        page = page.replace(
            f"You are Karl Dialectic, a Marxist philosopher AI.",
            f"You are {name}, a {archetype} AI. You {intro}."
        )

        out_path = OUT_DIR / f"{agent_id}.html"
        out_path.write_text(page)
        count += 1

print(f"Generated {count} summon pages in {OUT_DIR}/")
