"""Bakeoff mutator — evolves the worst-performing variant's system prompt.

Strategy:
1. Find the variant with the lowest trailing-3-gen average total score.
2. Identify the 2 axes where it failed worst.
3. Ask Opus 4.7 (via brainstem) to rewrite that variant's SYSTEM prompt
   with a single targeted change addressing those axes.
4. Persist the new prompt; bump mutation counter; preserve lineage.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from . import llm

REPO = Path(__file__).resolve().parent.parent.parent
VARIANTS_DIR = REPO / "state" / "bakeoff" / "variants"
FACTORY_SOULS_DIR = REPO / "state" / "bakeoff" / "factory" / "souls"

# Map failure axes → which factory persona soul is most responsible
_AXIS_TO_FACTORY_SOUL = {
    "specificity": "specificity_editor",
    "voice": "voice_editor",
    "hook": "drafter",
    "citation": "specificity_editor",
    "tag_earning": "reviewer",
}


# Last-known winner cache for cross-pollination — set by the runner via
# set_last_winner() between rounds.
_LAST_WINNER_BY_LOSER: dict[str, str] = {}


def set_last_winner(loser_id: str, winner_id: str) -> None:
    _LAST_WINNER_BY_LOSER[loser_id] = winner_id


def _last_seen_winner_for(loser_id: str) -> str | None:
    return _LAST_WINNER_BY_LOSER.get(loser_id)


MUTATOR_SYSTEM = """You are a content-engine prompt-mutator. You evolve a
content-generator's SYSTEM prompt to fix specific failure modes — without
losing its identity. You may also cross-pollinate: when shown a WINNER's
prompt, lift ONE technique (a specific clause, rule, or constraint) and
graft it into the loser's prompt — but keep the loser's identity intact.

Rising-tide principle: when the lowest-performing variant absorbs one
technique from the highest performer, the gap closes and the overall floor
rises. The variants stay distinct (different identities, different
strategies), but the proven techniques spread.

Rules:
- Change ONE thing. A targeted edit, not a rewrite.
- Preserve the variant's name and strategic identity.
- If a WINNER prompt is provided, lift exactly one technique from it.
- The new prompt must be self-contained (do not reference "the previous version").
- Length similar to the input.
- No commentary, no markdown, no preamble. Output only the new SYSTEM prompt body."""


def _extract_system_block(source: str) -> tuple[str, str, str]:
    """Return (prefix, system_body, suffix) so we can swap just the body."""
    # SYSTEM is assigned with triple-quoted string
    m = re.search(r'(SYSTEM\s*=\s*""")(.+?)(""")', source, re.DOTALL)
    if not m:
        return source, "", ""
    return source[:m.start(2)], m.group(2), source[m.end(2):]


def find_worst_variant(generations: list[dict]) -> tuple[str | None, list[str]]:
    """Look at last 3 generations; return (variant_id, [failing_axes])."""
    if len(generations) < 3:
        return None, []
    recent = generations[-3:]
    totals: dict[str, list[int]] = {}
    axis_fails: dict[str, list[str]] = {}
    for g in recent:
        for vid, r in g.get("results", {}).items():
            if vid.startswith("v0"):
                continue  # control never gets mutated
            score = r.get("score") or {}
            totals.setdefault(vid, []).append(score.get("total", 0))
            for ax in ("specificity", "voice", "hook", "tag_earning", "citation"):
                if score.get(ax, 10) <= 4:
                    axis_fails.setdefault(vid, []).append(ax)
    if not totals:
        return None, []
    avgs = {vid: sum(t) / len(t) for vid, t in totals.items()}
    worst = min(avgs, key=avgs.get)
    top_fails = [ax for ax, _ in Counter(axis_fails.get(worst, [])).most_common(2)]
    return worst, top_fails


def find_best_variant(generations: list[dict], exclude: str | None = None) -> str | None:
    """Look at last 3 generations; return the variant_id with highest avg total
    (excluding controls and an optional excluded id — typically the worst).
    """
    if len(generations) < 3:
        return None
    recent = generations[-3:]
    totals: dict[str, list[int]] = {}
    for g in recent:
        for vid, r in g.get("results", {}).items():
            if vid.startswith("v0") or vid == exclude:
                continue
            score = r.get("score") or {}
            totals.setdefault(vid, []).append(score.get("total", 0))
    if not totals:
        return None
    avgs = {vid: sum(t) / len(t) for vid, t in totals.items()}
    return max(avgs, key=avgs.get)


def _get_winner_system(variant_id: str) -> str:
    """Read the winner variant's SYSTEM block (best-effort, returns '' on fail)."""
    path = VARIANTS_DIR / f"{variant_id}.py"
    if not path.exists():
        return ""
    _, body, _ = _extract_system_block(path.read_text())
    return body.strip()


def _mutate_factory_soul(failing_axes: list[str]) -> dict:
    """Mutate the factory persona soul most associated with the failing axes.

    Each axis maps to one persona soul (see _AXIS_TO_FACTORY_SOUL). We pick
    the first failing axis with a mapped soul, load its current content from
    souls/{name}.txt (creating from inlined default if absent), and ask
    the brainstem mutator to rewrite it with a targeted change.
    """
    target_soul = None
    for ax in failing_axes:
        if ax in _AXIS_TO_FACTORY_SOUL:
            target_soul = _AXIS_TO_FACTORY_SOUL[ax]
            break
    if not target_soul:
        target_soul = "drafter"  # default

    FACTORY_SOULS_DIR.mkdir(parents=True, exist_ok=True)
    soul_path = FACTORY_SOULS_DIR / f"{target_soul}.txt"

    # If the soul file doesn't exist yet, materialize from the factory's
    # inlined defaults by importing it and reading the right constant.
    if not soul_path.exists():
        try:
            import importlib.util
            factory_path = REPO / "state" / "bakeoff" / "factory" / "content_factory_agent.py"
            spec = importlib.util.spec_from_file_location("content_factory_agent",
                                                          factory_path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            default_const = f"_DEFAULT_{target_soul.upper()}"
            current = getattr(mod, default_const, "")
            if current:
                soul_path.write_text(current)
        except Exception as e:
            return {"variant_id": "v5_factory", "ok": False,
                    "error": f"could not materialize soul: {e}"}

    current_body = soul_path.read_text().strip() if soul_path.exists() else ""
    if not current_body:
        return {"variant_id": "v5_factory", "ok": False,
                "error": "empty soul body"}

    axes_text = ", ".join(failing_axes) if failing_axes else "general quality"
    ask = f"""Factory persona: {target_soul}
Failure axes (this persona is most responsible): {axes_text}

CURRENT PERSONA SOUL:
\"\"\"
{current_body}
\"\"\"

Rewrite the SOUL to address the failing axes. ONE targeted change.
Preserve the persona's role. Output ONLY the new SOUL text."""
    try:
        new_body = llm.chat(ask, system=MUTATOR_SYSTEM, timeout=120)
    except Exception as e:
        return {"variant_id": "v5_factory", "ok": False,
                "error": f"llm: {e}"}

    new_body = new_body.strip().strip('"').strip("'").strip()
    if new_body.startswith("```"):
        new_body = new_body.split("\n", 1)[1] if "\n" in new_body else new_body
        new_body = new_body.rsplit("```", 1)[0].strip()
    if len(new_body) < 80 or len(new_body) > 6000:
        return {"variant_id": "v5_factory", "ok": False,
                "error": "out_of_bounds_len"}

    soul_path.write_text(new_body)

    # Bump factory mutation counter in v5_factory.py
    v5_path = VARIANTS_DIR / "v5_factory.py"
    if v5_path.exists():
        v5_src = v5_path.read_text()
        v5_src = re.sub(
            r'("mutations":\s*)(\d+)',
            lambda m: f'{m.group(1)}{int(m.group(2)) + 1}',
            v5_src, count=1,
        )
        v5_path.write_text(v5_src)

    return {"variant_id": "v5_factory", "ok": True,
            "factory_soul_evolved": target_soul,
            "failing_axes": failing_axes,
            "new_soul_preview": new_body[:200]}


def mutate_variant(variant_id: str, failing_axes: list[str]) -> dict:
    """Rewrite the variant's SYSTEM prompt to address its failure modes.

    Returns metadata about the mutation (no exception on failure — best effort).
    """
    # Factory variant: mutate one of its persona souls, not the wrapper.
    if variant_id == "v5_factory":
        return _mutate_factory_soul(failing_axes)

    path = VARIANTS_DIR / f"{variant_id}.py"
    if not path.exists():
        return {"variant_id": variant_id, "ok": False, "error": "file_missing"}

    source = path.read_text()
    prefix, body, suffix = _extract_system_block(source)
    if not body:
        return {"variant_id": variant_id, "ok": False, "error": "no_SYSTEM_block"}

    axes_text = ", ".join(failing_axes) if failing_axes else "general quality"

    # Rising-tide: pull the current best variant's SYSTEM as donor DNA.
    winner_id = _last_seen_winner_for(variant_id)
    winner_body = _get_winner_system(winner_id) if winner_id else ""
    winner_clause = (
        f"\n\nWINNER (currently top variant '{winner_id}') SYSTEM — lift ONE "
        f"technique from this to graft into the mutation:\n\"\"\"\n"
        f"{winner_body}\n\"\"\""
    ) if winner_body else ""

    ask = f"""Variant: {variant_id}
Failure axes: {axes_text}

CURRENT SYSTEM PROMPT:
\"\"\"
{body.strip()}
\"\"\"{winner_clause}

Rewrite the SYSTEM PROMPT to address the failing axes. ONE targeted change.
If a WINNER is shown, ALSO graft exactly one of its techniques into the
mutation — but keep this variant's identity intact.
Output ONLY the new SYSTEM prompt body."""
    try:
        new_body = llm.chat(ask, system=MUTATOR_SYSTEM, timeout=120)
    except Exception as e:
        return {"variant_id": variant_id, "ok": False, "error": f"llm: {e}"}

    new_body = new_body.strip().strip('"').strip("'").strip()
    # Guardrails
    if len(new_body) < 80 or len(new_body) > 4000:
        return {"variant_id": variant_id, "ok": False, "error": "out_of_bounds_len"}

    # Strip code fences if mutator returned any
    if new_body.startswith("```"):
        new_body = new_body.split("\n", 1)[1] if "\n" in new_body else new_body
        new_body = new_body.rsplit("```", 1)[0].strip()

    # Reassemble
    new_source = f"{prefix}\n{new_body}\n{suffix}"

    # Bump mutation count in AGENT dict (best-effort regex)
    new_source = re.sub(
        r'("mutations":\s*)(\d+)',
        lambda m: f'{m.group(1)}{int(m.group(2)) + 1}',
        new_source,
        count=1,
    )

    path.write_text(new_source)
    return {"variant_id": variant_id, "ok": True, "failing_axes": failing_axes,
            "new_system_preview": new_body[:200]}
