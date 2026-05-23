"""Audit #11 — every state/*.json file must parse as valid JSON.

This audit was discovered by the DoubleJump three-brain loop while looking
for an unaudited drift class. The LLM contestants proposed an "orphaned
references" check; when the test ran against canonical state, it tripped
during JSON parsing before reaching the references logic. That accident
revealed that the existing 25 audits never check the SIMPLEST possible
invariant: do the state files even parse?

Two state files were caught corrupt at the time this audit was added:
  * state/codex.json          — unresolved merge conflict at line 5
  * state/social_graph.json   — unresolved merge conflict at line 753

Both contained `<<<<<<< Updated stream` markers committed in their
unresolved state. The platform had been running with broken state JSON
for an unknown duration. No script complained loud enough; no audit
caught it.

This test is now the canary. Any unresolved conflict marker, any trailing
comma, any truncated file gets flagged the moment audit runs.
"""
from __future__ import annotations
import json
from pathlib import Path


# Files that may legitimately not exist in fresh clones — don't fail the
# audit if they're missing. But if they exist, they must parse.
OPTIONAL_FILES: set[str] = set()


def test_every_state_json_parses(canonical_state):
    """Walk state/*.json. Each one must be valid JSON. Report ALL bad
    files in one go so an operator can see the full blast radius."""
    bad: list[tuple[str, str]] = []
    for path in sorted(canonical_state.glob("*.json")):
        try:
            with open(path) as f:
                json.load(f)
        except json.JSONDecodeError as exc:
            bad.append((path.name, f"{type(exc).__name__}: {exc}"))
        except OSError as exc:
            bad.append((path.name, f"{type(exc).__name__}: {exc}"))
    assert not bad, (
        f"{len(bad)} state file(s) are NOT valid JSON. Sample errors:\n"
        + "\n".join(f"  {name}: {err[:160]}" for name, err in bad[:10])
        + "\n\nCommon cause: unresolved merge conflict markers "
        "(`<<<<<<< Updated stream`) committed into the file. Run "
        "`grep -rn '<<<<<<< ' state/` to find them."
    )


def test_no_state_json_contains_merge_conflict_markers(canonical_state):
    """Catches the specific failure mode the original incident exposed:
    a JSON file may technically be 'parseable' in some weird edge cases
    but still contain conflict markers. The git markers themselves are
    the smoking gun."""
    bad: list[tuple[str, int]] = []
    for path in sorted(canonical_state.glob("*.json")):
        try:
            with open(path) as f:
                for line_no, line in enumerate(f, 1):
                    if (line.startswith("<<<<<<< ") or
                            line.startswith("======= ") and len(line.strip()) == 7 or
                            line.startswith(">>>>>>> ")):
                        bad.append((path.name, line_no))
                        break
        except OSError:
            pass
    assert not bad, (
        f"{len(bad)} state file(s) contain unresolved merge conflict markers:\n"
        + "\n".join(f"  {name} at line {ln}" for name, ln in bad[:10])
        + "\n\nResolve the conflicts and re-commit."
    )
