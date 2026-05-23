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


# Deterministic scorers — used to compare LLM outputs of the contestants

_NUMERIC_RE = re.compile(r"\b\d[\d.,/]*\b")
_PATH_RE = re.compile(r"`?[\w./\-]+\.(?:py|md|json|sh|yml|yaml)`?")
_SHA_RE = re.compile(r"\b[0-9a-f]{7,40}\b")
_LINE_REF_RE = re.compile(r":(\d+)|L(\d+)\b")
_CITATION_RE = re.compile(r"\b(PR\s*#\d+|commit\s+\w+|issue\s+#\d+)\b", re.IGNORECASE)
_SENTENCE_RE = re.compile(r"[.!?]+")


def _jaccard(a: str, b: str) -> float:
    """Word-level Jaccard distance for novelty/diversity measure."""
    def toks(s):
        return set(w.lower() for w in re.findall(r"\w+", s) if len(w) > 3)
    ta, tb = toks(a), toks(b)
    if not ta and not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    if union == 0:
        return 0.0
    return 1.0 - inter / union  # distance, higher = more novel


def _score_output(output: str, prior_outputs: list, target_length: int = 200) -> dict:
    """Deterministic 5-criterion score on LLM output. Each /10, total /50.
    No LLM involvement. Repeatable. Tracks the same dimensions as the
    audit-priority bake-off scoring."""
    text = output or ""
    word_count = len(text.split())

    # specificity — paths, line refs, SHAs, citations
    paths = len(_PATH_RE.findall(text))
    lines = len(_LINE_REF_RE.findall(text))
    shas = len(_SHA_RE.findall(text))
    cites = len(_CITATION_RE.findall(text))
    specificity = min(10, paths + lines + shas + cites)

    # density — numeric tokens normalized by word count
    nums = len(_NUMERIC_RE.findall(text))
    density = min(10, int(10 * nums / max(word_count, 1) * 20))

    # length-match — how close to target_length
    if word_count == 0:
        length = 0
    else:
        ratio = min(word_count, target_length) / max(word_count, target_length)
        length = max(0, min(10, int(10 * ratio)))

    # diversity — Jaccard distance from prior outputs (the higher the better
    # to avoid mode collapse on the prior winner)
    if not prior_outputs:
        diversity = 7  # neutral baseline for first generation
    else:
        dists = [_jaccard(text, p) for p in prior_outputs]
        diversity = min(10, int(10 * (sum(dists) / len(dists))))

    # coherence — sentence count vs word count (sane 8-25 words/sentence)
    sentences = max(1, len([s for s in _SENTENCE_RE.split(text) if s.strip()]))
    words_per_sent = word_count / sentences
    if 8 <= words_per_sent <= 25:
        coherence = 10
    elif 5 <= words_per_sent < 8 or 25 < words_per_sent <= 35:
        coherence = 7
    else:
        coherence = 4

    breakdown = {
        "specificity": {"score": specificity, "reason": f"paths={paths} lines={lines} shas={shas} cites={cites}"},
        "density": {"score": density, "reason": f"numerics={nums} per {word_count} words"},
        "length": {"score": length, "reason": f"{word_count} words vs target {target_length}"},
        "diversity": {"score": diversity, "reason": f"jaccard avg = {diversity/10:.2f} vs {len(prior_outputs)} priors"},
        "coherence": {"score": coherence, "reason": f"{sentences} sentences, {words_per_sent:.1f} w/s"},
    }
    total = sum(b["score"] for b in breakdown.values())
    return {"total": total, "breakdown": breakdown, "word_count": word_count}


def _weakest_criterion(breakdown: dict) -> tuple:
    items = [(name, info["score"], info["reason"]) for name, info in breakdown.items()]
    items.sort(key=lambda x: x[1])
    return items[0]


# Seed variants — three starting prompts with different angles. The loop
# then evolves from the winner.
def _seed_variants(direction: str) -> list:
    return [
        # variant 1: direct + specific
        f"{direction}\n\nBe concrete. Cite specific files, line numbers, or named symbols. Avoid abstractions.",
        # variant 2: contrarian — challenge assumptions
        f"{direction}\n\nFirst list two assumptions baked into the question, then answer in light of which you believe is wrong.",
        # variant 3: structured — numbered prioritization
        f"{direction}\n\nReturn a numbered list (3-5 items). Each item: claim, evidence, action. No prose between items.",
    ]


def _run_variant(variant_prompt: str) -> dict:
    """Run one prompt variant through the brainstem's LLM and capture
    the output."""
    if not _llm_available():
        return {"ok": False, "error": "LLM not available"}
    messages = [
        {"role": "system", "content": "Answer the prompt directly. No preamble, no markdown fences."},
        {"role": "user", "content": variant_prompt},
    ]
    return _llm_call(messages, label="variant")


def _doublejump(direction: str, max_jumps: int, n_seed_variants: int,
                target_length: int = 200) -> dict:
    if not direction:
        return {"ok": False, "error": "direction is required"}
    if not _llm_available():
        return {"ok": False, "error": "LLM not available — doublejump requires brainstem.call_copilot"}

    max_jumps = max(1, min(_MAX_JUMPS, max_jumps))
    n_seed_variants = max(1, min(_MAX_VARIANTS, n_seed_variants))

    seeds = _seed_variants(direction)[:n_seed_variants]
    variants = [{"name": f"seed-{i+1}", "prompt": p, "lineage": "seed"}
                for i, p in enumerate(seeds)]
    trajectory = []
    prior_outputs: list = []

    for jump_n in range(max_jumps + 1):  # +1 baseline iteration
        # Run any variants that haven't run yet
        new_outputs = []
        for v in variants:
            if "output" in v:
                continue
            run = _run_variant(v["prompt"])
            if not run["ok"]:
                v["output"] = ""
                v["error"] = run["error"]
            else:
                v["output"] = run["content"]
            new_outputs.append(v)

        # Score every variant against the running pool of prior outputs
        for v in new_outputs:
            scored = _score_output(v["output"], prior_outputs, target_length=target_length)
            v["score"] = scored["total"]
            v["breakdown"] = scored["breakdown"]
            v["word_count"] = scored["word_count"]
            prior_outputs.append(v["output"])

        # Trajectory snapshot
        sorted_variants = sorted(variants, key=lambda x: -x.get("score", 0))
        winner = sorted_variants[0]
        loser = sorted_variants[-1]
        trajectory.append({
            "jump": jump_n,
            "variant_count": len(variants),
            "winner": {"name": winner["name"], "score": winner.get("score"),
                       "lineage": winner.get("lineage")},
            "scores": [{"name": v["name"], "score": v.get("score")} for v in sorted_variants],
        })

        # Stop conditions
        if jump_n >= max_jumps:
            break

        # Generate next variant addressing the winner's weakest criterion
        weakest_name, _, weakest_reason = _weakest_criterion(winner.get("breakdown", {}))
        directive = _next_variant_directive(
            direction=direction,
            prior_winner=winner["prompt"],
            gap_criterion=weakest_name,
            gap_detail=weakest_reason,
        )
        gen = _llm_call(
            [
                {"role": "system", "content": _VARIANT_GEN_SYSTEM},
                {"role": "user", "content": directive},
            ],
            label=f"variant-gen-jump-{jump_n+1}",
        )
        if not gen["ok"]:
            trajectory[-1]["next_variant_error"] = gen["error"]
            break
        new_prompt = gen["content"].strip().strip("`").strip()
        if not new_prompt:
            trajectory[-1]["next_variant_error"] = "empty prompt returned"
            break
        new_name = f"autojump-{jump_n + 1}"
        variants.append({
            "name": new_name,
            "prompt": new_prompt,
            "lineage": f"from {winner['name']} (gap: {weakest_name})",
        })
        trajectory[-1]["added"] = {"name": new_name, "gap": weakest_name}

    # Final winner across all jumps
    overall_winner = max(variants, key=lambda x: x.get("score", 0))

    return {
        "ok": True,
        "direction": direction,
        "max_jumps": max_jumps,
        "variants_final": len(variants),
        "trajectory": trajectory,
        "winner": {
            "name": overall_winner["name"],
            "score": overall_winner.get("score"),
            "lineage": overall_winner.get("lineage"),
            "prompt_preview": overall_winner["prompt"][:400],
            "output_preview": overall_winner.get("output", "")[:600],
        },
        "summary": (
            f"DoubleJump ran {len(trajectory)} iterations on direction. "
            f"Final variant pool: {len(variants)}. "
            f"Winner: {overall_winner['name']} score "
            f"{overall_winner.get('score')}. "
            f"Lineage: {overall_winner.get('lineage')}."
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
                    "n_seed_variants": {
                        "type": "integer",
                        "description": f"For doublejump: how many seed prompt variants to start with (default {_DEFAULT_VARIANTS}, max {_MAX_VARIANTS}).",
                    },
                    "target_length": {
                        "type": "integer",
                        "description": "For doublejump: target word count for variant outputs (default 200). Used by the length scorer.",
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
            n_seed = int(kwargs.get("n_seed_variants") or _DEFAULT_VARIANTS)
            target_length = int(kwargs.get("target_length") or 200)
            result = _doublejump(direction, max_jumps, n_seed, target_length)
            _record_run("doublejump", direction, {
                "max_jumps": max_jumps,
                "variants_final": result.get("variants_final"),
                "winner_score": (result.get("winner") or {}).get("score"),
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
