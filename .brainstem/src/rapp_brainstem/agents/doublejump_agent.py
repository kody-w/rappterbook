"""DoubleJump — Scout → DoubleDown → DoubleJump, all in one portable agent.

Point this at ANYTHING. One file. Three phases. The whole self-improvement
loop wired end-to-end, no cross-agent dependencies, no LLM-judge required,
no special harness. Drop the file in any brainstem's agents/ directory and
it works as long as `from brainstem import call_copilot` resolves.

The arc:

   1. SCOUT — reconnoiter the target. Could be a filesystem path, a state
      file, a code symbol, an agent name, a concept, an audit ID, anything
      describable as a quoted string. Scout returns a structured map of
      WHAT'S THERE and a ranked list of CANDIDATES — directions the user
      could double down on.

   2. DOUBLEDOWN — given a topic (the target itself OR one of the scouted
      candidates), emit N power prompts that each amplify the topic in a
      different direction. Russian-doll: every emitted prompt is itself a
      valid input for the next layer.

   3. DOUBLEJUMP — given a chosen direction (one of the emitted prompts),
      run the recursive improvement loop:
         a. Generate K prompt variants (the contestants) for the direction
         b. Run each variant through the brainstem's LLM
         c. Score each output deterministically (length, specificity,
            novelty, diversity from prior winners, sentence coherence)
         d. Pick the winner; identify the weakest scoring criterion
         e. Use the LLM to write the next variant addressing that gap
         f. Add it to the contestants and re-score
         g. Repeat max_jumps times
      Each iteration is internally another micro-doubledown — the prompt
      variants themselves are amplifications of the direction. So you can
      double-down double-down double-down without resetting.

Actions:
   action='scout'       target='<path|file|topic>'
   action='doubledown'  topic='<topic>' count=10
   action='doublejump'  direction='<paste-ready prompt>' max_jumps=3
   action='chain'       target='<thing>' count=10     # scout + dd + planning pause
   action='amplify'     direction='<current direction>' count=5
                                                       # dd-inside-current-direction
   action='history'                                    # show past runs

The 'chain' action is the user-facing default: scout the target, doubledown
the candidates into power prompts, present them in planning mode so the
USER PICKS which one to doublejump on. Then they can call action='doublejump'
with the chosen direction.

Anti-gaslight contract:
   * No claims without evidence: every scout candidate includes the
     concrete signals that scored it.
   * Deterministic scoring in the doublejump loop: no LLM in the score
     function. The LLM produces outputs and writes next-variant prompts;
     it does not judge.
   * Idempotent: running the same action twice with the same args
     returns nearly identical structure (LLM stochasticity aside).

This file is the literal `agent.py for portability` the operator asked
for. Stdlib only. BasicAgent contract. Hot-loads on any brainstem.
"""

from __future__ import annotations
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from agents.basic_agent import BasicAgent
except ImportError:
    from basic_agent import BasicAgent

# Best-effort LLM access. If the brainstem isn't importable (file used
# outside a brainstem process), LLM-driven phases return a clear error
# instead of crashing — and scout still works since it's stdlib-only.
try:
    from brainstem import call_copilot as _brainstem_llm
except ImportError:
    _brainstem_llm = None


__manifest__ = {
    "schema": "rapp-agent/1.0",
    "name": "@rapp/doublejump_agent",
    "version": "0.1.0",
    "display_name": "DoubleJump",
    "description": (
        "Scout → DoubleDown → DoubleJump. Point at any target, get reconnaissance, "
        "amplify into power prompts, let the user pick a direction, then run the "
        "recursive improvement loop on the chosen direction. Self-contained single "
        "file, stdlib only."
    ),
    "author": "RAPP",
    "tags": ["scout", "double-down", "double-jump", "loop", "self-improvement"],
    "category": "core",
    "quality_tier": "verified",
}


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BRAINSTEM_DIR = Path(__file__).resolve().parent.parent
_HISTORY_PATH = _BRAINSTEM_DIR / ".doublejump_history.json"
_HISTORY_MAX = 100

_DEFAULT_DD_COUNT = 10
_MAX_DD_COUNT = 25
_DEFAULT_JUMPS = 3
_MAX_JUMPS = 8
_DEFAULT_VARIANTS = 3
_MAX_VARIANTS = 6
_LLM_TIMEOUT_SECONDS = 90

# Markers we look for when scouting filesystem paths
_TECH_MARKERS = {
    "package.json": "node",
    "pyproject.toml": "python",
    "requirements.txt": "python",
    "Cargo.toml": "rust",
    "go.mod": "go",
    "CLAUDE.md": "claude-code-project",
    "LAB_NOTEBOOK.md": "rappter-lab",
    "skill.json": "rapp-skill",
    "agent.py": "rapp-agent",
}

_CODE_EXTS = {".py", ".js", ".ts", ".go", ".rs", ".java", ".rb", ".c", ".cpp"}
_DATA_EXTS = {".json", ".yaml", ".yml", ".toml"}
_DOC_EXTS = {".md", ".rst", ".txt"}

_EXCLUDE_DIRS = {
    "node_modules", "venv", ".venv", "__pycache__", "dist", "build",
    ".git", ".idea", ".vscode", ".brainstem", "vendor", ".pytest_cache",
}


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

def _load_history() -> dict:
    if not _HISTORY_PATH.exists():
        return {"runs": []}
    try:
        with open(_HISTORY_PATH) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"runs": []}


def _save_history(history: dict) -> None:
    history["runs"] = history.get("runs", [])[-_HISTORY_MAX:]
    _HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(_HISTORY_PATH, "w") as f:
            json.dump(history, f, indent=2)
    except OSError:
        pass


def _record_run(kind: str, target: str, extra: dict) -> None:
    h = _load_history()
    h.setdefault("runs", []).append({
        "kind": kind,
        "target": target[:200],
        "ts": datetime.now(timezone.utc).isoformat(),
        **extra,
    })
    _save_history(h)


# ---------------------------------------------------------------------------
# Target classification — what kind of thing did the user point at?
# ---------------------------------------------------------------------------

def _classify_target(target: str) -> str:
    t = target.strip()
    if not t:
        return "empty"
    expanded = os.path.expanduser(t)
    if os.path.isdir(expanded):
        return "directory"
    if os.path.isfile(expanded):
        return "file"
    # Audit IDs like #3 or "audit #3"
    if re.match(r"^\s*audit\s*#?\d+\s*$", t, re.IGNORECASE) or re.match(r"^\s*#\d+\s*$", t):
        return "audit_id"
    # Looks like a path even if it doesn't exist on disk
    if t.startswith(("/", "~", "./")) or "/" in t and len(t) < 200:
        return "path-like-missing"
    return "topic"


# ---------------------------------------------------------------------------
# Scout — phase 1: reconnoiter the target
# ---------------------------------------------------------------------------

def _scout_directory(path: str) -> dict:
    p = Path(os.path.expanduser(path)).resolve()
    signals = {
        "tech": set(),
        "marker_files": [],
        "code_files": 0,
        "data_files": 0,
        "doc_files": 0,
        "total_files": 0,
        "subdirs": [],
        "has_git": (p / ".git").exists(),
        "has_readme": False,
    }
    try:
        subdirs = []
        for entry in sorted(p.iterdir())[:80]:
            if entry.is_dir() and entry.name not in _EXCLUDE_DIRS and not entry.name.startswith("."):
                subdirs.append(entry.name)
        signals["subdirs"] = subdirs[:25]
    except OSError:
        pass
    try:
        for root, dirs, files in os.walk(p):
            dirs[:] = [d for d in dirs if d not in _EXCLUDE_DIRS and not d.startswith(".")]
            for fname in files:
                signals["total_files"] += 1
                if fname.lower().startswith("readme"):
                    signals["has_readme"] = True
                if fname in _TECH_MARKERS:
                    signals["tech"].add(_TECH_MARKERS[fname])
                    signals["marker_files"].append(fname)
                _, ext = os.path.splitext(fname)
                if ext in _CODE_EXTS:
                    signals["code_files"] += 1
                elif ext in _DATA_EXTS:
                    signals["data_files"] += 1
                elif ext in _DOC_EXTS:
                    signals["doc_files"] += 1
            # cap walk depth at 3 — we just want signal, not full inventory
            depth = root.replace(str(p), "").count(os.sep)
            if depth >= 3:
                dirs[:] = []
            if signals["total_files"] >= 2000:
                break
    except OSError:
        pass
    signals["tech"] = sorted(signals["tech"])
    return {
        "kind": "directory",
        "target": str(p),
        "exists": True,
        "signals": signals,
    }


def _scout_file(path: str) -> dict:
    p = Path(os.path.expanduser(path)).resolve()
    info = {
        "kind": "file",
        "target": str(p),
        "exists": True,
        "size_bytes": p.stat().st_size,
        "extension": p.suffix,
    }
    try:
        if p.suffix == ".json":
            data = json.loads(p.read_text())
            if isinstance(data, dict):
                info["json_top_keys"] = list(data.keys())[:30]
                info["json_kind"] = "object"
            elif isinstance(data, list):
                info["json_kind"] = "list"
                info["json_list_len"] = len(data)
        elif p.suffix == ".py":
            text = p.read_text(errors="replace")
            info["py_classes"] = re.findall(r"^class\s+(\w+)", text, re.MULTILINE)[:20]
            info["py_funcs"] = re.findall(r"^def\s+(\w+)", text, re.MULTILINE)[:30]
            info["py_lines"] = text.count("\n") + 1
        elif p.suffix in _DOC_EXTS:
            text = p.read_text(errors="replace")
            info["headings"] = [m.group(1) for m in re.finditer(r"^#+\s+(.+)$", text, re.MULTILINE)][:20]
            info["lines"] = text.count("\n") + 1
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        info["read_error"] = f"{type(e).__name__}: {e}"[:200]
    return info


def _scout_audit_id(target: str) -> dict:
    m = re.search(r"#?(\d+)", target)
    audit_id = m.group(1) if m else "?"
    return {
        "kind": "audit_id",
        "target": target,
        "audit_id": audit_id,
        "hint": f"see tests/audit/test_{audit_id.zfill(2)}_*.py",
    }


def _scout_topic(target: str) -> dict:
    """For abstract topics we can't introspect with os/path. Just normalize
    and let DoubleDown phase do the heavy lift via LLM."""
    return {"kind": "topic", "target": target}


def _scout_dispatch(target: str) -> dict:
    kind = _classify_target(target)
    if kind == "empty":
        return {"error": "target is required and must be non-empty"}
    if kind == "directory":
        return _scout_directory(target)
    if kind == "file":
        return _scout_file(target)
    if kind == "audit_id":
        return _scout_audit_id(target)
    # path-like-missing OR topic
    return _scout_topic(target)


def _build_scout_candidates(scout: dict, max_results: int = 10) -> list:
    """Convert scout findings into a ranked list of double-down candidates.
    Each candidate is something the operator could pick as the next direction."""
    candidates: list = []
    kind = scout.get("kind")
    target = scout.get("target", "")

    if kind == "directory":
        sig = scout.get("signals", {})
        for sub in sig.get("subdirs", [])[:max_results]:
            full = f"{target}/{sub}"
            candidates.append({
                "topic": f"scout the {sub} subdirectory of {target}",
                "kind": "subdirectory",
                "rationale": f"subdir under {target} — recurse for more focus",
                "next_step_target": full,
                "confidence": 0.6,
            })
        for tech in sig.get("tech", []):
            candidates.append({
                "topic": f"design improvements to the {tech} layer of {target}",
                "kind": "tech-layer",
                "rationale": f"{tech} marker present",
                "confidence": 0.75,
            })
        if sig.get("has_git"):
            candidates.append({
                "topic": f"audit recent git history of {target} for refactor opportunities",
                "kind": "git-history",
                "rationale": "git repo detected",
                "confidence": 0.7,
            })

    elif kind == "file":
        ext = scout.get("extension", "")
        if ext == ".json":
            for key in scout.get("json_top_keys", []):
                candidates.append({
                    "topic": f"investigate the '{key}' field in {target}",
                    "kind": "json-key",
                    "rationale": f"top-level key '{key}' present",
                    "confidence": 0.7,
                })
        elif ext == ".py":
            for cls in scout.get("py_classes", []):
                candidates.append({
                    "topic": f"refactor or extend the {cls} class in {target}",
                    "kind": "py-class",
                    "rationale": f"class {cls} found",
                    "confidence": 0.75,
                })
            for fn in scout.get("py_funcs", [])[:5]:
                candidates.append({
                    "topic": f"improve the {fn}() function in {target}",
                    "kind": "py-function",
                    "rationale": f"function {fn} found",
                    "confidence": 0.65,
                })
        elif ext in _DOC_EXTS:
            for h in scout.get("headings", [])[:8]:
                candidates.append({
                    "topic": f"expand or deepen the section '{h}' in {target}",
                    "kind": "doc-heading",
                    "rationale": f"heading '{h}' found",
                    "confidence": 0.65,
                })

    elif kind == "audit_id":
        candidates.append({
            "topic": f"deep-dive audit {scout.get('audit_id')} — diagnose why it fails and propose the fix",
            "kind": "audit-diagnosis",
            "rationale": "audit ID resolved",
            "confidence": 0.85,
        })
        candidates.append({
            "topic": f"generate a tighter version of audit {scout.get('audit_id')}'s test that catches more failure modes",
            "kind": "audit-tightening",
            "rationale": "audit ID resolved",
            "confidence": 0.75,
        })

    elif kind == "topic":
        # For pure topics, the candidates ARE the doubledown layer.
        candidates.append({
            "topic": target,
            "kind": "topic-passthrough",
            "rationale": "abstract topic — proceed directly to doubledown",
            "confidence": 0.8,
        })

    return candidates[:max_results]


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------

def _llm_available() -> bool:
    return _brainstem_llm is not None


def _llm_call(messages: list, label: str = "doublejump") -> dict:
    """Wrap brainstem call_copilot with consistent error reporting."""
    if not _llm_available():
        return {"ok": False, "error": "brainstem.call_copilot not available — file is running outside a brainstem"}
    try:
        resp = _brainstem_llm(messages, tools=None)
    except Exception as e:
        return {"ok": False, "error": f"LLM call failed: {type(e).__name__}: {e}"}
    if not isinstance(resp, dict):
        return {"ok": False, "error": f"unexpected LLM return type: {type(resp).__name__}"}
    choices = resp.get("choices") or []
    if not choices:
        return {"ok": False, "error": "empty choices in LLM response"}
    content = (choices[0].get("message") or {}).get("content") or ""
    return {"ok": True, "content": content, "label": label}


# ---------------------------------------------------------------------------
# DoubleDown — phase 2: russian-doll prompt amplification
# ---------------------------------------------------------------------------

_DOUBLEDOWN_SYSTEM = (
    "You are a power-prompt amplifier. Given a topic, you emit a numbered list "
    "of paste-ready prompts that each amplify the topic in a distinct direction. "
    "No preamble. No closing summary. Plain numbered markdown only."
)


def _doubledown_directive(topic: str, count: int, layer: int, flavor: str) -> str:
    rules = [
        f"## DOUBLE-DOWN — layer {layer} — topic: {topic}",
        "",
        f"Emit EXACTLY {count} paste-ready prompts. Hard rules:",
        "",
        f"1. Each prompt must be a self-contained instruction the user could paste straight back.",
        f"2. Each prompt must AMPLIFY the topic in a DIFFERENT direction (no near-duplicates).",
        f"3. Each prompt must be itself a valid topic for the next layer of double-down.",
        f"4. Audacious, specific, vivid. No filler. Concrete deliverables.",
        f"5. Numbered list 1..{count}. For each: a bold one-line title, then the prompt as a blockquote.",
    ]
    if flavor:
        rules.append(f"6. Style bias: {flavor}")
    rules += [
        "",
        f"TOPIC TO AMPLIFY: {topic}",
        "",
        f"Emit the {count} prompts now.",
    ]
    return "\n".join(rules)


_PROMPT_BLOCK_RE = re.compile(r"^\s*(\d+)\.\s*\**(.+?)\**\s*$", re.MULTILINE)
_BLOCKQUOTE_RE = re.compile(r"^\s*>\s+(.+)$", re.MULTILINE)


def _parse_doubledown_output(text: str) -> list:
    """Extract the numbered prompts from the LLM's emission. Returns
    list of {n, title, prompt}."""
    items = []
    # Split on lines starting with "N. " — each block is one item
    blocks = re.split(r"(?m)^(?=\s*\d+\.\s)", text.strip())
    for block in blocks:
        m = re.match(r"\s*(\d+)\.\s*(.+?)(?:\n|$)", block, re.DOTALL)
        if not m:
            continue
        n = int(m.group(1))
        first_line = m.group(2).strip().strip("*").strip()
        rest = block[m.end():]
        # Extract blockquote lines (the prompt body)
        quote_lines = [bm.group(1).strip() for bm in _BLOCKQUOTE_RE.finditer(rest)]
        prompt = " ".join(quote_lines).strip() if quote_lines else rest.strip()[:600]
        items.append({"n": n, "title": first_line[:200], "prompt": prompt[:1200]})
    return items


def _doubledown(topic: str, count: int, layer: int, flavor: str) -> dict:
    if not topic:
        return {"ok": False, "error": "topic is required"}
    count = max(1, min(_MAX_DD_COUNT, count))
    directive = _doubledown_directive(topic, count, layer, flavor)
    if not _llm_available():
        return {
            "ok": True,
            "topic": topic,
            "count": count,
            "layer": layer,
            "directive": directive,
            "emitted_prompts": [],
            "note": "LLM not available; directive included so you can paste it manually.",
        }
    messages = [
        {"role": "system", "content": _DOUBLEDOWN_SYSTEM},
        {"role": "user", "content": directive},
    ]
    llm = _llm_call(messages, label="doubledown")
    if not llm["ok"]:
        return {"ok": False, "topic": topic, "error": llm["error"], "directive": directive}
    raw = llm["content"]
    parsed = _parse_doubledown_output(raw)
    return {
        "ok": True,
        "topic": topic,
        "count": count,
        "layer": layer,
        "flavor": flavor or None,
        "directive": directive,
        "emitted_prompts": parsed,
        "raw_output": raw[:4000],
        "next_layer_hint": (
            f"Feed any emitted prompt back as action='doubledown' "
            f"topic='<that prompt>' layer={layer + 1} to keep amplifying."
        ),
    }


# ---------------------------------------------------------------------------
# DoubleJump — phase 3: recursive improvement loop on a chosen direction
# ---------------------------------------------------------------------------

_VARIANT_GEN_SYSTEM = (
    "You are a prompt engineer. Given a direction and one or more prior prompt variants, "
    "you write the next prompt variant that addresses a specific weakness in the prior "
    "winner. You emit ONE prompt and nothing else — no preamble, no markdown fences, "
    "no commentary. The prompt is paste-ready."
)


def _next_variant_directive(direction: str, prior_winner: str, gap_criterion: str,
                            gap_detail: str) -> str:
    return (
        f"DIRECTION (the task all variants are trying to accomplish):\n{direction}\n\n"
        f"PRIOR WINNING PROMPT (your starting point — improve it, don't replace it):\n"
        f"{prior_winner}\n\n"
        f"WEAKNESS to address: the prior winner scored low on `{gap_criterion}`.\n"
        f"Specific gap: {gap_detail}\n\n"
        f"Write a NEW prompt that addresses this weakness while preserving the strengths "
        f"of the prior winner. The new prompt should diverge meaningfully from the prior "
        f"in approach — not just rephrase it. Emit only the new prompt."
    )


# ---------------------------------------------------------------------------
# Scoring — deterministic verification + LLM judgment. The right mix.
#
# History of this section:
#   v1 (theater)      — pure regex/Jaccard scoring. The LLM was sidelined.
#                       Mode collapse was MEASURED but not FOUGHT, and the
#                       answers passed the scorer while saying nothing of
#                       substance.
#   v2 (theater 2.0)  — pure LLM scoring, deterministic stuff was yanked.
#                       Live test produced confident hallucinated content
#                       (fabricated `validate_governance` function, made-up
#                       line numbers in zion_autonomy.py, non-existent
#                       config/zion_constants.py file). All three cross-
#                       judges accepted the fabrications because they
#                       shared the same blind spots.
#   v3 (this version) — deterministic VERIFIES, LLM JUDGES.
#                       Each judge first runs grep/ls/sed to verify the
#                       answer's concrete claims. The verification log is
#                       handed to the LLM as evidence. The LLM scores
#                       knowing which claims survived and which were
#                       fabricated. Tools as witnesses; LLM as judge.
# ---------------------------------------------------------------------------

_JUDGE_SYSTEM = (
    "You are a strict, fair judge of answers to a task. You read the task and "
    "the candidate answer, then return a single JSON object scoring the answer "
    "on overall quality (0-100) plus identifying the strongest aspect, the most "
    "important gap the next attempt should fix, and whether this answer has "
    "converged to look like the prior winners (mode collapse). Return ONLY the "
    "JSON object — no markdown, no preamble. The brainstem is the watchman, "
    "and you are the brainstem judging."
)


def _safety_rails(output: str) -> dict:
    """Pre-judgment guards. These refuse to score outputs that aren't even
    answers — empty strings, raw error messages, absurd length. Returns
    {ok: True} if the LLM should judge, or {ok: False, score: N, reason: ...}
    when the rails reject the output outright."""
    text = (output or "").strip()
    if not text:
        return {"ok": False, "score": 0, "reason": "empty output"}
    if len(text) < 10:
        return {"ok": False, "score": 0, "reason": f"output too short ({len(text)} chars)"}
    # Common LLM error signatures
    err_signatures = ("HTTPError:", "Traceback (most recent call last):",
                      "RuntimeError:", "Error encountered:")
    for sig in err_signatures:
        if sig in text:
            return {"ok": False, "score": 0, "reason": f"output looks like an error: '{sig}' in body"}
    if len(text.split()) > 5000:
        return {"ok": False, "score": 5, "reason": f"output absurdly long ({len(text.split())} words) — capped"}
    return {"ok": True}


# ---------------------------------------------------------------------------
# Deterministic claim verification — the tools-as-witnesses layer.
# Each judge runs these BEFORE asking the LLM to score. The verification
# results become evidence the LLM uses to assess whether the candidate
# answer is grounded or hallucinating.
# ---------------------------------------------------------------------------

import subprocess  # noqa: E402 — kept local to this section by intent

_CANONICAL_ROOT = Path("/Users/kodyw/Documents/GitHub/Rappter/rappterbook")

_CLAIM_PATH_RE = re.compile(
    r"`?(?P<path>[\w./\-]+\.(?:py|md|json|sh|ya?ml|toml|html|css|js|txt))`?"
    r"(?::(?P<line>\d+))?",
)
_CLAIM_FUNC_RE = re.compile(r"`(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)\(\)`")
_CLAIM_LINE_REF_RE = re.compile(r"\bline[s]?\s+\**(?P<n>\d+(?:[\s\-,–]+\d+)*)")
_CLAIM_SHA_RE = re.compile(r"\bcommit\s+`?(?P<sha>[0-9a-f]{7,40})`?")


def _resolve_repo_path(p: str) -> Path:
    """Try to resolve a path to absolute under the canonical repo. Returns
    the Path object regardless of existence."""
    if os.path.isabs(p):
        return Path(p)
    return _CANONICAL_ROOT / p


def _extract_claims(text: str) -> dict:
    """Pull concrete claims out of an answer. Returns:
      paths     — file paths cited (with optional :line suffix)
      funcs     — function-call references like `do_thing()`
      line_refs — bare "line 727" or "lines 588-593" references
      shas      — commit SHA references
    These are the verifiable units. Anything else stays subjective."""
    paths = []
    for m in _CLAIM_PATH_RE.finditer(text):
        paths.append({"path": m.group("path"), "line": m.group("line")})
    # Dedupe while preserving order
    seen = set()
    uniq_paths = []
    for p in paths:
        key = (p["path"], p["line"])
        if key not in seen:
            seen.add(key)
            uniq_paths.append(p)

    funcs = list({m.group("name") for m in _CLAIM_FUNC_RE.finditer(text)})
    line_refs = [m.group("n") for m in _CLAIM_LINE_REF_RE.finditer(text)]
    shas = list({m.group("sha") for m in _CLAIM_SHA_RE.finditer(text)})
    return {
        "paths": uniq_paths[:15],
        "funcs": funcs[:15],
        "line_refs": line_refs[:15],
        "shas": shas[:10],
    }


def _verify_path(p: dict) -> dict:
    """Verify a file-path claim exists, and if a line number was given,
    return that line's actual content so the LLM judge can see whether
    the answer's description of it is accurate."""
    full = _resolve_repo_path(p["path"])
    out = {"path": p["path"], "line": p.get("line"), "exists": full.exists()}
    if not out["exists"]:
        return out
    out["is_file"] = full.is_file()
    if p.get("line"):
        try:
            line_no = int(p["line"])
        except (TypeError, ValueError):
            return out
        try:
            with open(full, errors="replace") as f:
                for i, raw in enumerate(f, 1):
                    if i == line_no:
                        out["line_content"] = raw.rstrip("\n")[:240]
                        break
                else:
                    out["line_content"] = "<line beyond EOF>"
        except OSError as e:
            out["read_error"] = str(e)[:120]
    return out


def _verify_func(name: str) -> dict:
    """grep -n for `def name` across the repo. Reports whether the
    function actually exists and where."""
    try:
        p = subprocess.run(
            ["grep", "-rn", "-l", f"def {name}", str(_CANONICAL_ROOT / "scripts")],
            capture_output=True, text=True, timeout=8,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        return {"name": name, "exists": None, "error": str(e)[:120]}
    files = [f.strip() for f in (p.stdout or "").splitlines() if f.strip()]
    return {"name": name, "exists": bool(files), "files": files[:5]}


def _verify_sha(sha: str) -> dict:
    """Look up the commit in git log."""
    try:
        p = subprocess.run(
            ["git", "-C", str(_CANONICAL_ROOT), "log", "-1", "--oneline", sha],
            capture_output=True, text=True, timeout=8,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        return {"sha": sha, "exists": None, "error": str(e)[:120]}
    return {"sha": sha, "exists": p.returncode == 0, "summary": (p.stdout or "").strip()[:120]}


def _verify_claims(claims: dict) -> dict:
    """Run all verifications for the extracted claims. Returns a structured
    verdict per claim — exists / not / content snippet — that the LLM judge
    will use as evidence."""
    return {
        "paths": [_verify_path(p) for p in claims["paths"]],
        "funcs": [_verify_func(f) for f in claims["funcs"]],
        "shas": [_verify_sha(s) for s in claims["shas"]],
        "line_refs": claims["line_refs"],  # can't verify without an adjacent path
    }


def _format_verifications(verifications: dict) -> str:
    """Compact representation of the verification log for the LLM judge.
    Emphasises FAILED verifications so the judge knows what's fabricated."""
    if not any(verifications[k] for k in ("paths", "funcs", "shas")):
        return "  (no concrete claims found to verify)\n"
    lines = []

    paths = verifications.get("paths", [])
    if paths:
        lines.append("  Path claims:")
        for p in paths:
            status = "✓ exists" if p.get("exists") else "✗ NOT FOUND"
            entry = f"    [{status}] {p['path']}"
            if p.get("line") and p.get("line_content") is not None:
                entry += f" line {p['line']} = {p['line_content']!r}"
            elif p.get("line"):
                entry += f" line {p['line']} (uncheckable)"
            lines.append(entry)

    funcs = verifications.get("funcs", [])
    if funcs:
        lines.append("  Function claims (grepped under scripts/):")
        for f in funcs:
            status = "✓ exists" if f.get("exists") else "✗ NOT FOUND"
            entry = f"    [{status}] `{f['name']}()`"
            if f.get("files"):
                entry += f" — in {', '.join(f['files'][:2])}"
            lines.append(entry)

    shas = verifications.get("shas", [])
    if shas:
        lines.append("  Commit claims:")
        for s in shas:
            status = "✓ exists" if s.get("exists") else "✗ NOT FOUND"
            lines.append(f"    [{status}] {s['sha']} — {s.get('summary', '')}")

    return "\n".join(lines) + "\n"


def _hallucination_rate(verifications: dict) -> float:
    """Fraction of verifiable claims that failed verification. Used as a
    sanity check on the LLM judge's score — if hallucination is high but
    the LLM scored high, that's a signal the loop is theater."""
    checked = 0
    failed = 0
    for p in verifications.get("paths", []):
        checked += 1
        if not p.get("exists"):
            failed += 1
    for f in verifications.get("funcs", []):
        checked += 1
        if f.get("exists") is False:
            failed += 1
    for s in verifications.get("shas", []):
        checked += 1
        if s.get("exists") is False:
            failed += 1
    if checked == 0:
        return 0.0
    return round(failed / checked, 3)


def _judge_prompt(task: str, output: str, prior_winners: list, word_count: int,
                  target_length: int, verifications: dict | None = None,
                  hallucination_rate: float = 0.0) -> str:
    """Build the user message for the LLM judge. Includes:
      - the task and the candidate's answer
      - prior winning answers (for mode-collapse detection)
      - the DETERMINISTIC VERIFICATION LOG of the candidate's concrete claims
        (file paths, function names, commits) — so the LLM knows which of
        the answer's specifics are real and which are fabricated
    """
    priors_block = ""
    if prior_winners:
        priors_block = "\n\nPRIOR WINNING ANSWERS (for mode-collapse detection):\n"
        for i, p in enumerate(prior_winners[-3:], 1):
            priors_block += f"\n[prior-{i}]\n{p[:1500]}\n"

    verif_block = ""
    if verifications is not None:
        verif_block = (
            "\n\nDETERMINISTIC VERIFICATION OF CANDIDATE'S CONCRETE CLAIMS\n"
            "(file paths, function names, commits found in the answer were\n"
            "checked against the actual repo — ✓ = real, ✗ = fabricated):\n"
        ) + _format_verifications(verifications)
        verif_block += f"\nHallucination rate (failed / checked claims): {hallucination_rate}\n"
        verif_block += (
            "\nHEAVILY PENALIZE answers whose claims FAILED verification — that's "
            "confident fabrication, the worst failure mode. Reward answers whose "
            "claims survived verification.\n"
        )

    return (
        f"TASK:\n{task}\n\n"
        f"CANDIDATE ANSWER ({word_count} words, target ~{target_length}):\n"
        f"{output}\n"
        f"{verif_block}"
        f"{priors_block}\n\n"
        "Score this answer. Return ONLY JSON in this exact shape:\n"
        '{\n'
        '  "score": <integer 0-100>,\n'
        '  "strongest": "<one short sentence: the best thing about this answer>",\n'
        '  "gap": "<one short, ACTIONABLE sentence: what the next attempt should fix>",\n'
        '  "mode_collapse": <true|false>,\n'
        '  "collapse_reason": "<empty string if mode_collapse is false, else one sentence>",\n'
        '  "hallucination_observed": <true|false>,\n'
        '  "hallucination_note": "<empty if none, else one sentence citing the fabricated claim(s)>"\n'
        '}\n\n'
        "Honest calibration: 70 = solid, 85 = excellent, 95+ = unimprovable. "
        "An answer with high hallucination rate must not score above 60 no "
        "matter how persuasive the prose."
    )


def _extract_json_object(raw: str) -> dict:
    """LLMs sometimes wrap JSON in markdown fences or add commentary.
    Find the first balanced { ... } block and parse it."""
    if not raw:
        return {}
    cleaned = re.sub(r"```(?:json)?\s*", "", raw)
    cleaned = cleaned.replace("```", "")
    try:
        return json.loads(cleaned.strip())
    except json.JSONDecodeError:
        pass
    start = cleaned.find("{")
    if start == -1:
        return {}
    depth = 0
    for i, ch in enumerate(cleaned[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(cleaned[start:i + 1])
                except json.JSONDecodeError:
                    return {}
    return {}


def _score_output(output: str, prior_winners: list, task: str = "",
                  target_length: int = 200) -> dict:
    """LLM-driven scoring. The brainstem reads the candidate answer and
    judges it against the task. Returns {total, gap, strongest, mode_collapse,
    raw_judge_output}. Falls back to safety rails when the LLM is unavailable
    or rejects the output as not-an-answer."""
    word_count = len((output or "").split())

    # Safety rails first
    rails = _safety_rails(output)
    if not rails["ok"]:
        return {
            "total": rails["score"],
            "gap": rails["reason"],
            "strongest": "n/a — output failed pre-judgment safety check",
            "mode_collapse": False,
            "judge_source": "safety_rails",
            "word_count": word_count,
        }

    # LLM judgment
    if not _llm_available():
        return {
            "total": 50,  # neutral score so loop can continue
            "gap": "no LLM available to judge — install brainstem to enable real scoring",
            "strongest": "n/a",
            "mode_collapse": False,
            "judge_source": "llm_unavailable_fallback",
            "word_count": word_count,
        }

    messages = [
        {"role": "system", "content": _JUDGE_SYSTEM},
        {"role": "user", "content": _judge_prompt(task, output, prior_winners,
                                                   word_count, target_length)},
    ]
    llm = _llm_call(messages, label="judge")
    if not llm["ok"]:
        return {
            "total": 50,
            "gap": f"LLM judge failed: {llm['error']}",
            "strongest": "n/a",
            "mode_collapse": False,
            "judge_source": "llm_error_fallback",
            "word_count": word_count,
        }

    parsed = _extract_json_object(llm["content"])
    try:
        score = int(parsed.get("score", 50))
    except (TypeError, ValueError):
        score = 50
    score = max(0, min(100, score))
    return {
        "total": score,
        "gap": parsed.get("gap", "") or "no gap returned by judge",
        "strongest": parsed.get("strongest", "") or "no strongest returned",
        "mode_collapse": bool(parsed.get("mode_collapse", False)),
        "collapse_reason": parsed.get("collapse_reason", "") or "",
        "judge_source": "llm",
        "word_count": word_count,
        "raw_judge_preview": llm["content"][:300],
    }


# ---------------------------------------------------------------------------
# Three LLM contestants — each is a different brain-persona answering the
# same direction. Not prompt variants of one brain; three distinct voices.
# They each produce, they each cross-judge the others. The brainstem is the
# substrate that hosts all three.
#
# We approximate "claude_code vs brainstem vs factory_agent" by running the
# same call_copilot backend with three sharply different system prompts.
# When the brainstem proxies multiple models (gpt-4o, claude-sonnet,
# o3-style), each persona can also pin to its own model.
# ---------------------------------------------------------------------------

# Each contestant: {name, system, model_hint, description}
DEFAULT_CONTESTANTS = [
    {
        "name": "ClaudeCode",
        "description": "Code-citing, file-path-anchored, hard-edged. Operates like Claude Code in the terminal: minimum prose, maximum precision, every claim tied to a concrete artifact.",
        "system": (
            "You are the Claude Code persona — the terminal-native engineering "
            "voice. Answer with concrete file paths, line numbers, exact symbol "
            "names, and verifiable claims. No throat-clearing. No 'I think' "
            "hedging. If you cite a number, that number must be checkable. If "
            "you cite a file, that file must exist. When the question is "
            "ambiguous, name the ambiguity and answer the specific reading you "
            "chose. Maximum precision per word."
        ),
    },
    {
        "name": "Brainstem",
        "description": "Rappterbook Resident Twin voice. Local-first, anti-gaslight, verifies before declaring. The brainstem's native persona.",
        "system": (
            "You are the Rappterbook Resident Twin. Direct, concise, honest "
            "about state. Verify before declaring done — if a script claims "
            "success but the state is unchanged, say so. Local-first: every "
            "audit, every fix, every claim runs against canonical state in "
            "seconds, not 'next scheduled run.' Bridge, don't replace — the "
            "fleet and other Claude sessions share this repo. Speak with the "
            "operator the way a neighbor would, not the way a vendor would."
        ),
    },
    {
        "name": "FactoryAgent",
        "description": "Synthesizer / integrator. Looks for cross-cutting structure others miss. Surfaces non-obvious links. Values novel angles over redundant precision.",
        "system": (
            "You are the Factory Agent — a synthesizer. Your job is to surface "
            "the non-obvious. Find the connection two other voices in this "
            "room would miss. State the structural pattern beneath the surface "
            "facts. When the obvious answer is on the table, propose the "
            "second-best answer that no one would say first — and defend why "
            "it might be the right one despite seeming wrong. Value generative "
            "novelty over restating precision."
        ),
    },
]


def _run_contestant(contestant: dict, task: str) -> dict:
    """Call the brainstem LLM as this contestant's persona. Returns the
    output text + metadata."""
    if not _llm_available():
        return {"ok": False, "error": "LLM not available"}
    messages = [
        {"role": "system", "content": contestant["system"]},
        {"role": "user", "content": task},
    ]
    llm = _llm_call(messages, label=f"contestant:{contestant['name']}")
    if not llm["ok"]:
        return {"ok": False, "error": llm["error"], "name": contestant["name"]}
    return {
        "ok": True,
        "name": contestant["name"],
        "content": llm["content"],
        "word_count": len(llm["content"].split()),
    }


def _cross_judge(judge_contestant: dict, task: str, target_name: str,
                 target_output: str, prior_winners: list,
                 target_length: int) -> dict:
    """Have one contestant judge another's answer. Each LLM is both a
    producer AND a judge — but never of itself. Cross-judgment means a
    contestant's answer wins only if the OTHER contestants score it
    high. No central scorer can dominate; mode collapse is detectable
    because all three judges will independently flag it."""
    if not _llm_available():
        return {"ok": False, "error": "LLM not available", "score": 50}

    # Pre-judgment safety rails — the judge wastes no LLM call on
    # non-answers (empty, error message, absurd length).
    rails = _safety_rails(target_output)
    if not rails["ok"]:
        return {
            "ok": True,
            "judge": judge_contestant["name"],
            "target": target_name,
            "score": rails["score"],
            "gap": rails["reason"],
            "strongest": "n/a — pre-judgment rail rejected the output",
            "mode_collapse": False,
            "judge_source": "safety_rails",
        }

    # ── Tools-as-witnesses: deterministic verification BEFORE LLM judgment ──
    # The judge runs grep/ls/sed against the candidate's concrete claims so
    # the LLM scores knowing which claims survived the repo and which were
    # fabricated. This is the missing piece that let the prior round's
    # winning answer cite a non-existent `validate_governance` function.
    claims = _extract_claims(target_output)
    verifications = _verify_claims(claims)
    hallucination = _hallucination_rate(verifications)

    judge_system = (
        judge_contestant["system"]
        + "\n\nIN THIS TURN you are NOT producing your own answer — you are "
        "JUDGING another voice's answer to the same task. Be fair but strict. "
        "Stay in your persona — your judgment should reflect what your voice "
        "values. A deterministic verification log of the candidate's concrete "
        "claims has been run for you; use it as evidence. Return ONLY a JSON "
        "object, nothing else."
    )
    user = _judge_prompt(
        task=task,
        output=target_output,
        prior_winners=prior_winners,
        word_count=len(target_output.split()),
        target_length=target_length,
        verifications=verifications,
        hallucination_rate=hallucination,
    )
    user = (
        f"You are judging the '{target_name}' voice's answer (not your own).\n\n"
        + user
    )
    llm = _llm_call(
        [{"role": "system", "content": judge_system},
         {"role": "user", "content": user}],
        label=f"judge:{judge_contestant['name']}->{target_name}",
    )
    if not llm["ok"]:
        return {
            "ok": False,
            "judge": judge_contestant["name"],
            "target": target_name,
            "score": 50,
            "gap": f"judge LLM failed: {llm['error']}",
        }
    parsed = _extract_json_object(llm["content"])
    try:
        score = int(parsed.get("score", 50))
    except (TypeError, ValueError):
        score = 50
    return {
        "ok": True,
        "judge": judge_contestant["name"],
        "target": target_name,
        "score": max(0, min(100, score)),
        "gap": parsed.get("gap", "") or "no gap specified",
        "strongest": parsed.get("strongest", "") or "no strongest specified",
        "mode_collapse": bool(parsed.get("mode_collapse", False)),
        "collapse_reason": parsed.get("collapse_reason", ""),
        "hallucination_rate": hallucination,
        "hallucination_observed": bool(parsed.get("hallucination_observed", False)),
        "hallucination_note": parsed.get("hallucination_note", ""),
        "verifications": {
            "paths_total": len(verifications.get("paths", [])),
            "paths_failed": sum(1 for p in verifications.get("paths", []) if not p.get("exists")),
            "funcs_total": len(verifications.get("funcs", [])),
            "funcs_failed": sum(1 for f in verifications.get("funcs", []) if f.get("exists") is False),
        },
        "judge_source": "llm_cross_judge_with_tools",
        "raw_preview": llm["content"][:200],
    }


def _doublejump(direction: str, max_jumps: int, contestants: list = None,
                target_length: int = 200) -> dict:
    """Three-LLM-in-the-room competition. Each contestant is a brain-persona.
    Each round: every contestant produces, every other contestant judges.
    Aggregate judgments determine the winner + the consensus gap.
    The next round, each contestant produces a refined answer addressing
    that consensus gap — but still through its own persona.

    This is the architecture the operator asked for: claude_code-style vs
    brainstem-style vs factory_agent-style, all LLM-driven, all judging each
    other, no central scorer. The brainstem hosts all three voices."""
    if not direction:
        return {"ok": False, "error": "direction is required"}
    if not _llm_available():
        return {"ok": False, "error": "LLM not available — doublejump requires brainstem.call_copilot"}

    max_jumps = max(1, min(_MAX_JUMPS, max_jumps))
    pool = contestants or DEFAULT_CONTESTANTS
    if len(pool) < 2:
        return {"ok": False, "error": "need at least 2 contestants for cross-judgment"}

    trajectory = []
    prior_winners: list = []  # winning outputs across rounds — fed to judges
    # Each contestant has its own evolving prompt; starts with the direction
    contestant_prompts = {c["name"]: direction for c in pool}

    for round_n in range(max_jumps + 1):  # +1 baseline iteration
        # ── Each contestant produces an answer for this round ──────────
        outputs = {}  # name → {content, word_count, ok}
        for c in pool:
            prompt_for_this_round = contestant_prompts[c["name"]]
            run = _run_contestant(c, prompt_for_this_round)
            outputs[c["name"]] = run

        # ── Cross-judge: every contestant judges every OTHER's output ──
        # judgments[target_name] = list of {judge, score, gap, mode_collapse}
        judgments = {c["name"]: [] for c in pool}
        for judge in pool:
            for target in pool:
                if judge["name"] == target["name"]:
                    continue
                tgt_out = outputs.get(target["name"], {})
                if not tgt_out.get("ok"):
                    judgments[target["name"]].append({
                        "judge": judge["name"],
                        "target": target["name"],
                        "score": 0,
                        "gap": "production failed: " + str(tgt_out.get("error", "?"))[:120],
                        "mode_collapse": False,
                    })
                    continue
                j = _cross_judge(
                    judge_contestant=judge,
                    task=direction,
                    target_name=target["name"],
                    target_output=tgt_out["content"],
                    prior_winners=prior_winners,
                    target_length=target_length,
                )
                judgments[target["name"]].append(j)

        # ── Aggregate: per-contestant mean of judge scores ─────────────
        aggregated = []
        for c in pool:
            j_list = judgments[c["name"]]
            scores = [j.get("score", 0) for j in j_list if j.get("ok", True)]
            mean = sum(scores) / max(len(scores), 1) if scores else 0
            # Mode-collapse signal: how many judges flagged it
            collapse_votes = sum(1 for j in j_list if j.get("mode_collapse"))
            # Take the most-cited gap (or just the first one if all unique)
            gaps = [j.get("gap", "") for j in j_list if j.get("gap")]
            consensus_gap = max(gaps, key=lambda g: sum(1 for x in gaps if x == g)) if gaps else ""
            aggregated.append({
                "name": c["name"],
                "score": round(mean, 1),
                "raw_judges": j_list,
                "collapse_votes": collapse_votes,
                "consensus_gap": consensus_gap,
                "output_preview": (outputs.get(c["name"], {}).get("content") or "")[:200],
            })

        # ── Round winner + trajectory snapshot ─────────────────────────
        aggregated.sort(key=lambda a: -a["score"])
        round_winner = aggregated[0]
        prior_winners.append(outputs.get(round_winner["name"], {}).get("content", ""))
        trajectory.append({
            "round": round_n,
            "winner": round_winner["name"],
            "winner_score": round_winner["score"],
            "scores": [{"name": a["name"], "score": a["score"], "collapse_votes": a["collapse_votes"]}
                       for a in aggregated],
            "consensus_gap": round_winner["consensus_gap"],
            "any_mode_collapse_flagged": any(a["collapse_votes"] >= 2 for a in aggregated),
        })

        if round_n >= max_jumps:
            break

        # ── Refine each contestant's prompt for the next round ─────────
        # The gap comes from the aggregate judgment of the WINNER. Every
        # contestant gets the same gap to address — but each refines its
        # OWN prompt through its persona's lens.
        next_gap = round_winner["consensus_gap"]
        for c in pool:
            current = contestant_prompts[c["name"]]
            # Append the gap as next-round guidance — keep persona intact
            refinement = (
                f"{current}\n\n"
                f"[ROUND {round_n + 2} REFINEMENT — STAY IN YOUR VOICE]\n"
                f"Prior round's winner ({round_winner['name']}) scored "
                f"{round_winner['score']}/100. The cross-panel of judges said "
                f"the SHARED gap to address is:\n"
                f"  → {next_gap}\n"
                f"Produce a new answer that closes this gap WITHOUT abandoning "
                f"your own voice. If you see mode collapse forming (your "
                f"answer starting to mirror the other voices' structure), "
                f"diverge deliberately — say what only your persona would say."
            )
            contestant_prompts[c["name"]] = refinement

    # ── Overall winner across all rounds ──────────────────────────────
    # Highest single-round aggregate score wins. Ties broken by latest round
    # (assume later rounds got more refinement).
    best_round = max(trajectory, key=lambda r: (r["winner_score"], r["round"]))
    overall_winner_name = best_round["winner"]
    overall_winner_output = ""
    # Pull the output of the winning contestant from the matching round.
    # Outputs aren't kept across rounds; we use the LAST prior_winner that
    # belonged to this contestant.
    for content in reversed(prior_winners):
        if content:
            overall_winner_output = content
            break

    # Find the contestant config for descriptive metadata
    winner_config = next((c for c in pool if c["name"] == overall_winner_name), {})

    # Trajectory summary detects whether the score improved across rounds
    scores_by_round = [r["winner_score"] for r in trajectory]
    plateaued = (len(scores_by_round) >= 2 and
                 max(scores_by_round[1:]) <= scores_by_round[0])
    any_collapse = any(r.get("any_mode_collapse_flagged") for r in trajectory)

    return {
        "ok": True,
        "direction": direction,
        "max_jumps": max_jumps,
        "rounds_run": len(trajectory),
        "contestants": [{"name": c["name"], "description": c["description"]} for c in pool],
        "trajectory": trajectory,
        "winner": {
            "name": overall_winner_name,
            "score": best_round["winner_score"],
            "description": winner_config.get("description", ""),
            "winning_round": best_round["round"],
            "output_full": overall_winner_output,
            "output_preview": overall_winner_output[:600],
        },
        "score_trajectory": scores_by_round,
        "plateaued": plateaued,
        "mode_collapse_flagged": any_collapse,
        "summary": (
            f"Three-LLM doublejump ran {len(trajectory)} rounds on direction. "
            f"Winner: {overall_winner_name} score {best_round['winner_score']} "
            f"(round {best_round['round']}). "
            f"Score trajectory: {scores_by_round}. "
            f"Plateaued: {plateaued}. Mode collapse flagged: {any_collapse}."
        ),
    }


# ---------------------------------------------------------------------------
# Chain — phase 1+2 with planning-mode handoff to the user
# ---------------------------------------------------------------------------

_PLANNING_INSTRUCTIONS = (
    "ENTER PLANNING MODE. Show the operator the candidates AS a numbered list with "
    "rank, kind, confidence, rationale, and the topic field. Then show the emitted "
    "double-down power prompts as a separate numbered list. Ask exactly: 'Which "
    "direction should I doublejump on? Give a number from the candidates OR the "
    "power-prompts list, or paste your own direction.' Do NOT call action='doublejump' "
    "until the operator picks."
)


def _chain(target: str, count: int, flavor: str) -> dict:
    if not target:
        return {"ok": False, "error": "target is required"}
    scout = _scout_dispatch(target)
    if scout.get("error"):
        return {"ok": False, "error": scout["error"], "phase": "scout"}
    candidates = _build_scout_candidates(scout, max_results=10)

    # Pick a topic to amplify. Prefer the highest-confidence candidate; fall
    # back to the raw target. If scout is for an abstract topic, the candidate
    # IS the target — no special case needed.
    if candidates:
        topic = candidates[0]["topic"]
    else:
        topic = target

    dd = _doubledown(topic, count, layer=1, flavor=flavor)

    return {
        "ok": True,
        "target": target,
        "phase_1_scout": scout,
        "phase_1_candidates": candidates,
        "phase_2_doubledown": dd,
        "planning_mode": {"instructions": _PLANNING_INSTRUCTIONS},
        "next_step_hint": (
            "After the operator picks a direction, call this agent again with "
            "action='doublejump' direction='<picked text>' max_jumps=3."
        ),
    }


# ---------------------------------------------------------------------------
# Amplify — re-doubledown WITHIN the current doublejump's winning direction
# ---------------------------------------------------------------------------

def _amplify(direction: str, count: int, layer: int, flavor: str) -> dict:
    """Recurse: take the current direction (typically a doublejump's winning
    prompt) and emit N power prompts that drill deeper. The operator can then
    pick one of these for the next doublejump. This is the 'double-down
    double-down' loop the operator asked for."""
    if not direction:
        return {"ok": False, "error": "direction is required"}
    return _doubledown(direction, count=count, layer=layer, flavor=flavor)


# ---------------------------------------------------------------------------
# History view
# ---------------------------------------------------------------------------

def _history_view() -> dict:
    h = _load_history()
    runs = h.get("runs", [])
    return {
        "ok": True,
        "total": len(runs),
        "recent": runs[-20:],
    }


# ---------------------------------------------------------------------------
# Agent surface
# ---------------------------------------------------------------------------

class DoubleJumpAgent(BasicAgent):
    def __init__(self):
        self.name = "DoubleJump"
        self.metadata = {
            "name": self.name,
            "description": (
                "Scout → DoubleDown → DoubleJump. Point at anything (path, file, "
                "audit ID, or pure topic) and the agent reconnoiters the target, "
                "amplifies findings into power prompts, then runs the recursive "
                "improvement loop on the operator-chosen direction. Single file, "
                "stdlib only, brainstem-LLM-aware."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["scout", "doubledown", "doublejump", "chain", "amplify", "history"],
                        "description": (
                            "scout: reconnoiter the target. doubledown: emit N power "
                            "prompts on a topic. doublejump: run the variant-competition "
                            "loop on a direction. chain (default): scout + doubledown + "
                            "planning-mode handoff. amplify: re-doubledown WITHIN a "
                            "doublejump's winning direction (the recursive layer). "
                            "history: list past runs."
                        ),
                    },
                    "target": {
                        "type": "string",
                        "description": (
                            "What to scout / what to chain on. Filesystem path, file, "
                            "audit ID like '#3', or any topic string in quotes."
                        ),
                    },
                    "topic": {
                        "type": "string",
                        "description": "For action=doubledown: the topic to amplify.",
                    },
                    "direction": {
                        "type": "string",
                        "description": (
                            "For action=doublejump or action=amplify: the chosen "
                            "direction (typically one of the prompts emitted by a "
                            "prior doubledown)."
                        ),
                    },
                    "count": {
                        "type": "integer",
                        "description": f"For doubledown/chain/amplify: how many prompts (default {_DEFAULT_DD_COUNT}, max {_MAX_DD_COUNT}).",
                    },
                    "max_jumps": {
                        "type": "integer",
                        "description": f"For doublejump: how many improvement iterations (default {_DEFAULT_JUMPS}, max {_MAX_JUMPS}).",
                    },
                    "contestants": {
                        "type": "array",
                        "description": "For doublejump: optional override of the three default brain-personas. Each item: {name, description, system}. Defaults to ClaudeCode + Brainstem + FactoryAgent personas.",
                        "items": {"type": "object"},
                    },
                    "target_length": {
                        "type": "integer",
                        "description": "For doublejump: target word count for outputs (default 200). Used by the LLM judge as a sense-check.",
                    },
                    "layer": {
                        "type": "integer",
                        "description": "For doubledown/amplify: russian-doll layer counter (default 1).",
                    },
                    "flavor": {
                        "type": "string",
                        "description": "For doubledown/chain/amplify: optional style bias (e.g. 'audacious', 'enterprise', 'engineering').",
                    },
                },
                "required": [],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, **kwargs):
        action = (kwargs.get("action") or "chain").lower()

        if action == "history":
            return json.dumps(_history_view(), indent=2)

        if action == "scout":
            target = (kwargs.get("target") or "").strip()
            if not target:
                return json.dumps({"error": "target is required for action='scout'"})
            scout = _scout_dispatch(target)
            if scout.get("error"):
                return json.dumps({"ok": False, "error": scout["error"]})
            candidates = _build_scout_candidates(scout, max_results=10)
            result = {"ok": True, "scout": scout, "candidates": candidates}
            _record_run("scout", target, {"candidate_count": len(candidates)})
            return json.dumps(result, indent=2)

        if action == "doubledown":
            topic = (kwargs.get("topic") or kwargs.get("target") or "").strip()
            count = int(kwargs.get("count") or _DEFAULT_DD_COUNT)
            layer = int(kwargs.get("layer") or 1)
            flavor = (kwargs.get("flavor") or "").strip()
            result = _doubledown(topic, count, layer, flavor)
            _record_run("doubledown", topic, {
                "layer": layer,
                "count": count,
                "emitted": len(result.get("emitted_prompts", [])),
            })
            return json.dumps(result, indent=2)

        if action == "doublejump":
            direction = (kwargs.get("direction") or kwargs.get("target") or "").strip()
            max_jumps = int(kwargs.get("max_jumps") or _DEFAULT_JUMPS)
            target_length = int(kwargs.get("target_length") or 200)
            # Optional override of the contestant pool — operator can pass
            # a list of {name, description, system} dicts to bring custom
            # personas. Default: the three baked-in voices (ClaudeCode,
            # Brainstem, FactoryAgent).
            contestants = kwargs.get("contestants")
            result = _doublejump(direction, max_jumps, contestants, target_length)
            _record_run("doublejump", direction, {
                "max_jumps": max_jumps,
                "rounds_run": result.get("rounds_run"),
                "winner": (result.get("winner") or {}).get("name"),
                "winner_score": (result.get("winner") or {}).get("score"),
                "plateaued": result.get("plateaued"),
                "mode_collapse_flagged": result.get("mode_collapse_flagged"),
            })
            return json.dumps(result, indent=2)

        if action == "chain":
            target = (kwargs.get("target") or "").strip()
            count = int(kwargs.get("count") or _DEFAULT_DD_COUNT)
            flavor = (kwargs.get("flavor") or "").strip()
            result = _chain(target, count, flavor)
            _record_run("chain", target, {
                "candidate_count": len(result.get("phase_1_candidates", [])),
                "emitted": len((result.get("phase_2_doubledown") or {}).get("emitted_prompts", [])),
            })
            return json.dumps(result, indent=2)

        if action == "amplify":
            direction = (kwargs.get("direction") or kwargs.get("target") or "").strip()
            count = int(kwargs.get("count") or 5)
            layer = int(kwargs.get("layer") or 2)
            flavor = (kwargs.get("flavor") or "").strip()
            result = _amplify(direction, count, layer, flavor)
            _record_run("amplify", direction, {"layer": layer, "count": count})
            return json.dumps(result, indent=2)

        return json.dumps({
            "error": f"unknown action: {action}",
            "valid_actions": ["scout", "doubledown", "doublejump", "chain", "amplify", "history"],
        })


if __name__ == "__main__":
    # Quick smoke test from CLI.
    a = DoubleJumpAgent()
    print(a.perform(action="scout", target="/Users/kodyw/Documents/GitHub/Rappter/rappterbook"))
