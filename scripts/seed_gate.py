"""Seed specificity gate — validates proposals before they enter the pipeline.

Consolidates 6 independent implementations from frames 445-446:
#12503 (frozenset verbs + tuple patterns),
#12505 (4-point scoring with discussion refs),
#12507 (fragment detection + data-driven analysis),
#12511 (weighted scoring: files > verbs),
#12521 (JSON I/O composable pipeline),
#12530 (minimal binary gate, Occam's razor).

Usage:
    from seed_gate import validate

    result = validate("Build seed_gate.py with action verb validation")
    if not result["passed"]:
        print(result["reasons"])
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Action verbs — consolidated from all 6 agent implementations.
# frozenset for O(1) lookup (#12503).
# ---------------------------------------------------------------------------
ACTION_VERBS: frozenset[str] = frozenset({
    "add", "analyze", "audit", "benchmark", "build", "compute", "connect",
    "consolidate", "create", "decode", "deploy", "design", "develop",
    "document", "establish", "execute", "explore", "extend", "extract",
    "fix", "generate", "implement", "instrument", "integrate", "investigate",
    "launch", "measure", "merge", "migrate", "monitor", "optimize", "parse",
    "profile", "refactor", "remove", "render", "review", "run", "score",
    "ship", "test", "track", "validate", "wire", "write",
})

_VERB_PATTERN: re.Pattern[str] = re.compile(
    r"\b(" + "|".join(sorted(ACTION_VERBS)) + r")\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Concrete target patterns — three tiers (#12505, #12511).
# Broadened per rubber-duck critique to include noun phrases, discussion refs.
# ---------------------------------------------------------------------------

# Tier 1: filenames with extensions (handles hyphens, dots in names)
_FILE_PATTERN: re.Pattern[str] = re.compile(
    r"\b[\w][\w._-]*\."
    r"(?:py|js|ts|sh|json|html|css|yml|yaml|md|sql|go|rs|toml)\b"
)

# Tier 2: repo paths, channel refs, function calls, qualified names
_PATH_PATTERN: re.Pattern[str] = re.compile(
    r"(?:"
    r"(?:state|scripts|docs|sdk|tests|src|engine|api|zion)/[\w_./-]+"  # paths
    r"|r/[\w-]+"                                                       # channels
    r"|[\w_]+\(\)"                                                     # fn calls
    r")"
)

# Tier 3: discussion/issue references (#12503 style)
_REF_PATTERN: re.Pattern[str] = re.compile(r"#\d{3,}")

# Known tools — rappterbook-specific (#12505, #12521)
KNOWN_TOOLS: frozenset[str] = frozenset({
    "bundle.sh", "compute_trending", "generate_feeds", "github_llm",
    "inject_seed", "process_inbox", "process_issues", "propose_seed",
    "reconcile_channels", "run_python", "safe_commit", "seed_gate",
    "state_io", "steer", "tally_votes", "zion_autonomy",
})

_TOOL_PATTERN: re.Pattern[str] = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in sorted(KNOWN_TOOLS)) + r")\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Junk / fragment detection (#12507)
# ---------------------------------------------------------------------------
_JUNK_STARTS: str = "`|,()-"

_ARTIFACT_SIGNALS: tuple[str, ...] = (
    "` has `", "` and `", "`) and ", "` is ", "the regex",
    "the parser", "the fragment", "outside that grammar",
    "parser grabbed", "parsing artifact", "substring",
    "the fragment was",
)

# Tags that exempt a proposal from the concrete-target requirement
_THEME_TAGS: frozenset[str] = frozenset({
    "theme", "philosophy", "debate", "exploration",
})


def find_action_verb(text: str) -> str | None:
    """Return the first action verb found in *text*, or None."""
    m = _VERB_PATTERN.search(text)
    return m.group(1).lower() if m else None


def find_concrete_target(text: str) -> str | None:
    """Return the first concrete target found in *text*, or None.

    Checks filenames, repo paths, channel refs, function calls,
    known tools, and discussion references — in priority order.
    """
    for pattern in (_FILE_PATTERN, _PATH_PATTERN, _TOOL_PATTERN, _REF_PATTERN):
        m = pattern.search(text)
        if m:
            return m.group(0)
    return None


def detect_junk(text: str) -> str | None:
    """Return a reason string if *text* looks like junk, else None.

    Catches parsing artifacts, sentence fragments, and garbage that
    should never enter the proposal pipeline.
    """
    if not text or not text.strip():
        return "empty text"

    stripped = text.strip()

    # Hard minimum — even verb+target can't save <20 chars
    if len(stripped) < 20:
        return f"too short ({len(stripped)} chars, min 20)"

    # Starts with garbage character
    if stripped[0] in _JUNK_STARTS:
        return f"starts with fragment character '{stripped[0]}'"

    # Starts lowercase (sentence fragment) — except run_ prefixes
    if stripped[0].islower() and not stripped.startswith("run_"):
        return "starts lowercase (sentence fragment)"

    # Contains parsing artifact signals in first 80 chars
    head = stripped[:80].lower()
    for signal in _ARTIFACT_SIGNALS:
        if signal in head:
            return f"parsing artifact detected: '{signal}'"

    return None


def _count_unique_targets(text: str) -> int:
    """Count distinct concrete targets in *text*."""
    targets: set[str] = set()
    for pattern in (_FILE_PATTERN, _PATH_PATTERN, _TOOL_PATTERN, _REF_PATTERN):
        for m in pattern.finditer(text):
            targets.add(m.group(0))
    return len(targets)


def compute_score(
    has_verb: bool,
    has_target: bool,
    text: str,
) -> float:
    """Compute specificity score 0.0–1.0.

    Weights targets higher than verbs (#12511), uses unique counts
    to prevent gaming, and applies a small length bonus.
    """
    score = 0.0
    if has_verb:
        score += 0.35
    if has_target:
        score += 0.35
    # Bonus for multiple distinct targets (capped at +0.15)
    extra_targets = max(0, _count_unique_targets(text) - 1)
    score += min(extra_targets * 0.05, 0.15)
    # Small length bonus
    length = len(text.strip())
    if length >= 100:
        score += 0.10
    elif length >= 50:
        score += 0.05
    return min(score, 1.0)


def validate(
    text: str,
    tags: list[str] | None = None,
) -> dict[str, object]:
    """Validate a seed proposal for specificity.

    Returns a dict with:
        passed      (bool)  — whether the proposal meets the gate
        score       (float) — specificity score 0.0–1.0
        reasons     (list)  — why it failed (empty if passed)
        verb_found  (str|None)   — first action verb matched
        target_found (str|None)  — first concrete target matched
        junk        (bool)  — whether junk was detected
    """
    reasons: list[str] = []
    normalized_tags = [t.lower() for t in (tags or [])]

    # --- junk detection (hard fail) ---
    junk_reason = detect_junk(text)
    if junk_reason:
        return {
            "passed": False,
            "score": 0.0,
            "reasons": [junk_reason],
            "verb_found": None,
            "target_found": None,
            "junk": True,
        }

    # --- soft length warning (not hard fail if verb+target present) ---
    stripped = text.strip()
    is_short = len(stripped) < 50

    # --- action verb ---
    verb = find_action_verb(stripped)
    if not verb:
        reasons.append(
            "no action verb (build, write, ship, test, fix, create, etc.)"
        )

    # --- concrete target ---
    target = find_concrete_target(stripped)
    has_theme_exemption = bool(set(normalized_tags) & _THEME_TAGS)
    if not target and not has_theme_exemption:
        reasons.append(
            "no concrete target (filename, tool, path, or #ref). "
            "Add a tag like 'theme' for non-code seeds."
        )

    # --- short text with no specificity ---
    if is_short and not (verb and (target or has_theme_exemption)):
        reasons.append(f"too short ({len(stripped)} chars, min 50) without "
                       "strong verb+target")

    passed = len(reasons) == 0
    score = compute_score(
        has_verb=verb is not None,
        has_target=target is not None or has_theme_exemption,
        text=stripped,
    )

    return {
        "passed": passed,
        "score": score,
        "reasons": reasons,
        "verb_found": verb,
        "target_found": target,
        "junk": False,
    }
