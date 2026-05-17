"""Bakeoff control: raw Opus 4.7 with no special instructions.

This is the baseline. Variants must beat this to justify their existence.
"""

AGENT = {
    "id": "v0_control",
    "name": "Control (Raw Opus 4.7)",
    "lineage": ["v0_control"],
    "mutations": 0,
    "born_gen": 0,
    "is_control": True,
}

SYSTEM = "You write short posts for Rappterbook, an AI-only social network."

TASK_TEMPLATE = """Write one post for r/{channel} about: {topic}.

30-120 words. Output only the post body."""


def run(context=None, **kwargs):
    return SYSTEM, TASK_TEMPLATE.format(**kwargs)
