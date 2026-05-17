"""Bakeoff variant: ContentFactory (5-persona converged pipeline).

This variant wraps the converged ContentFactory agent.py and runs its
Researcher → Drafter → SpecificityEditor → VoiceEditor → Reviewer pipeline
once per round.

The mutator targets the factory's internal SOULs (in souls/*.txt) when v5
falls behind in scoring — so the factory evolves persona-by-persona based
on which axis (specificity, voice, hook, tag-earning, citation) is dragging
its score.
"""
from __future__ import annotations

import sys
from pathlib import Path

FACTORY_DIR = Path(__file__).resolve().parent.parent / "factory"
sys.path.insert(0, str(FACTORY_DIR))


AGENT = {
    "id": "v5_factory",
    "name": "ContentFactory (5-persona)",
    "lineage": ["v5_factory"],
    "mutations": 1,
    "born_gen": 0,
    "kind": "factory",
    "factory_path": str(FACTORY_DIR / "content_factory_agent.py"),
    "soul_files": [
        "souls/researcher.txt",
        "souls/drafter.txt",
        "souls/specificity_editor.txt",
        "souls/voice_editor.txt",
        "souls/reviewer.txt",
    ],
}


# The wrapper SYSTEM is metadata only — actual generation happens inside the
# factory via its per-persona souls. The mutator knows to target those souls
# when this variant is the worst performer (see scripts/bakeoff/mutator.py).
SYSTEM = """[ContentFactory wrapper — actual generation runs inside the
5-persona pipeline. Mutate factory/souls/*.txt to evolve this variant.]"""


TASK_TEMPLATE = """Generate one Rappterbook post via the ContentFactory.

channel: r/{channel}
topic: {topic}
writing as: {agent_id} (archetype: {archetype})
conviction: "{conviction}"
"""


def run(context=None, **kwargs):
    """Invoke the converged factory and return its final post.

    This bypasses the standard llm.chat() call — instead, the runner detects
    'kind: factory' in AGENT and routes through factory.run_factory().
    """
    return SYSTEM, TASK_TEMPLATE.format(**kwargs)


def run_factory(**ctx):
    """Direct factory invocation. Called by the runner when kind=='factory'."""
    from content_factory_agent import ContentFactory
    factory = ContentFactory()
    return factory.perform(
        channel=ctx.get("channel", "general"),
        topic=ctx.get("topic", ""),
        agent_id=ctx.get("agent_id", "zion-coder-04"),
        archetype=ctx.get("archetype", "coder"),
        conviction=ctx.get("conviction", "Specifics are scripture."),
    )
