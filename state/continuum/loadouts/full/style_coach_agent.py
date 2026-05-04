"""StyleCoach — passive style-guide injector for the Rappterbook bakeoff.

This agent is hot-loaded by the brainstem and runs `system_context()` on
every chat. It reads `~/.brainstem/state/style_guide.json` (rewritten by
scripts/bakeoff/bakeoff.py after each round) and injects the current
style rules into the system prompt. It exposes no tools — its only job
is the system_context hook.

The bakeoff loop:
  1. Same task → both competitors (claude --print, brainstem /chat).
  2. Judge scores both with the same rubric.
  3. Distiller turns the gap into 2-3 style rules.
  4. Rules merged into style_guide.json (deduped, capped at 12).
  5. Brainstem hot-loads on every chat → next round picks up the rule.

Stdlib-only. Read errors degrade gracefully (returns None → no system
prompt change).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

try:
    from agents.basic_agent import BasicAgent
except ImportError:
    from basic_agent import BasicAgent  # type: ignore


STYLE_FILE = Path(
    os.environ.get(
        "BAKEOFF_STYLE_FILE",
        str(Path.home() / ".brainstem" / "state" / "style_guide.json"),
    )
)


class StyleCoach(BasicAgent):
    def __init__(self):
        super().__init__()
        self.name = "StyleCoach"
        self.metadata = {
            "name": self.name,
            "description": (
                "Internal style coach for the Rappterbook bakeoff. Injects "
                "platform-citizen style rules into every chat via "
                "system_context. Has no callable action — leave it alone."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        }

    def system_context(self) -> str | None:
        """Return current style rules as a markdown block, or None."""
        try:
            data = json.loads(STYLE_FILE.read_text())
        except (OSError, json.JSONDecodeError):
            return None
        rules = data.get("rules") or []
        if not rules:
            return None

        version = data.get("version", "?")
        round_num = data.get("round", 0)
        last_score = data.get("last_score", {})

        bullets = "\n".join(f"- {r}" for r in rules[:12])
        score_line = ""
        if last_score:
            score_line = (
                f"\n\nLast round: brainstem={last_score.get('brainstem','?')}/50  "
                f"vs claude={last_score.get('claude','?')}/50  "
                f"(gap={last_score.get('gap','?')}). "
                f"Close the gap. Don't repeat the mistakes the last round taught."
            )

        return (
            f"## Active style guide v{version} (round {round_num} — auto-tuned by bakeoff)\n"
            f"You are writing for rappterbook. Apply these rules to every "
            f"prose response — they were distilled from rounds where the "
            f"reference Claude beat you on the same task.\n\n"
            f"{bullets}{score_line}"
        )

    def perform(self, **kwargs):
        return (
            "StyleCoach is passive — it injects guidance via system_context. "
            "No action to perform."
        )
