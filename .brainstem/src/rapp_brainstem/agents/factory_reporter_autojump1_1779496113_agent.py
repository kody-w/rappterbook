import json
import re
import subprocess
from pathlib import Path

try:
    from agents.basic_agent import BasicAgent
    from agents._audit_cache import cached_pytest_audit_summary
except ImportError:
    from basic_agent import BasicAgent
    cached_pytest_audit_summary = None

CANONICAL_ROOT = Path("/Users/kodyw/Documents/GitHub/Rappter/rappterbook")
WORKTREE_ROOT = CANONICAL_ROOT / ".claude" / "worktrees" / "audit-anti-gaslight"


def _run(cmd: list, cwd: Path = CANONICAL_ROOT, timeout: int = 30) -> dict:
    try:
        p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
        return {
            "cmd": " ".join(cmd),
            "ok": p.returncode == 0,
            "stdout": (p.stdout or "")[:2000],
            "stderr": (p.stderr or "")[:500],
        }
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        return {"cmd": " ".join(cmd), "ok": False, "stderr": str(e)[:300]}


def _grep_with_function_context(pattern: str, filepath: str) -> list:
    """Return [{line_no, line, enclosing_function}, ...] for each match."""
    g = _run(["grep", "-n", pattern, filepath])
    if not g["ok"] or not g["stdout"].strip():
        return []
    matches = []
    for line in g["stdout"].splitlines():
        if ":" not in line:
            continue
        try:
            line_no_str, content = line.split(":", 1)
            line_no = int(line_no_str)
        except ValueError:
            continue
        # Find enclosing def by reading file up to that line and grepping for last def
        head = _run(["sed", "-n", f"1,{line_no}p", filepath])
        enclosing = None
        if head["ok"]:
            for prev in reversed(head["stdout"].splitlines()):
                m = re.match(r"^def\s+(\w+)", prev)
                if m:
                    enclosing = m.group(1)
                    break
        matches.append(
            {"line_no": line_no, "line": content[:200], "enclosing_function": enclosing, "file": filepath}
        )
    return matches


def _audit_summary() -> dict:
    """Cached pytest summary (see agents/_audit_cache.py)."""
    if cached_pytest_audit_summary:
        return cached_pytest_audit_summary()
    tests_root = CANONICAL_ROOT if (CANONICAL_ROOT / "tests" / "audit").exists() else WORKTREE_ROOT
    if not (tests_root / "tests" / "audit").exists():
        return {"ok": False, "error": "tests/audit/ not found"}
    p = _run(["python3", "-m", "pytest", "tests/audit/", "--tb=no", "-q"], cwd=tests_root, timeout=180)
    out = (p.get("stdout", "") or "") + "\n" + (p.get("stderr", "") or "")
    m = re.search(r"(\d+)\s+failed,?\s+(\d+)\s+passed", out)
    if m:
        return {"ok": True, "failed": int(m.group(1)), "passed": int(m.group(2)), "source": p["cmd"]}
    m = re.search(r"(\d+)\s+passed", out)
    if m:
        return {"ok": True, "failed": 0, "passed": int(m.group(1)), "source": p["cmd"]}
    return {"ok": False}


def _audit_baselines() -> dict:
    """Pull key numerical baselines, returning verified source where possible."""
    out = {}
    p = _run(["python3", "-c",
              "import json; d=json.load(open('state/posted_log.json')); "
              "print(json.dumps({'posts':len(d.get('posts',[])),'comments':len(d.get('comments',[]))}))"])
    if p["ok"]:
        try:
            data = json.loads(p["stdout"].strip())
            out["#1"] = {
                "posts": data.get("posts"),
                "comments": data.get("comments"),
                "ratio": round(data.get("comments", 0) / max(data.get("posts", 1), 1), 4),
                "source": p["cmd"]
            }
        except (json.JSONDecodeError, KeyError):
            out["#1"] = {"error": "[unverified] JSON parse failed"}
    p = _run(["python3", "-c",
              "import json; d=json.load(open('state/autonomy_log.json')); "
              "es=d.get('entries',[])[-100:]; "
              "ps=[e.get('content_quality',{}).get('bracket_tag_pct',0) for e in es]; "
              "act=sum((e.get('run',{}).get('agents_activated') or 0) for e in es); "
              "lurks=sum((e.get('run',{}).get('lurks') or 0) for e in es); "
              "import json as J; print(J.dumps({'bracket_pct':sum(ps)/max(len(ps),1),"
              "'lurks':lurks,'activations':act,'entries':len(es)}))"])
    if p["ok"]:
        try:
            data = json.loads(p["stdout"].strip())
            out["#2"] = {"bracket_pct": round(data["bracket_pct"], 1), "entries": data["entries"], "source": p["cmd"]}
            out["#3"] = {"lurks": data["lurks"], "activations": data["activations"], "source": p["cmd"]}
        except (json.JSONDecodeError, KeyError):
            out["#2"] = out["#3"] = {"error": "[unverified] JSON parse failed"}
    p = _run(["ls", "-1", ".claude/worktrees/"])
    if p["ok"]:
        out["#5"] = {"worktrees": [w for w in p["stdout"].splitlines() if w.strip()], "source": p["cmd"]}
    return out


def _lurk_marker_evidence() -> dict:
    """Verify WHERE [LURK] markers live in zion_autonomy.py."""
    matches = _grep_with_function_context(r"\[LURK\]", "scripts/zion_autonomy.py")
    return {
        "total_matches": len(matches),
        "matches": matches,
        "lives_in_passive_governance": any(
            m.get("enclosing_function") == "_passive_governance" for m in matches
        ),
        "source": "grep -n '[LURK]' scripts/zion_autonomy.py"
    }


def _compose_response(baselines: dict, audit_summary: dict, lurk_evidence: dict, word_limit: int) -> str:
    parts = ["**Fix #3 governance lurks first.** Three reasons, each grounded:", ""]

    if lurk_evidence["lives_in_passive_governance"]:
        matched = [m for m in lurk_evidence["matches"] if m.get("enclosing_function") == "_passive_governance"]
        line_info = ", ".join(f"L{m['line_no']}({m['file']})" for m in matched)
        parts.append(
            f"**1. Fix verified inside `_passive_governance` ({line_info}).** "
            f"Command `{lurk_evidence['source']}` output verifies {lurk_evidence['total_matches']} total marker lines."
        )
    else:
        other_functions = [m["enclosing_function"] or "[unknown]" for m in lurk_evidence["matches"]]
        parts.append(
            f"**1. Fix not in canonical `_passive_governance`.** "
            f"Command `{lurk_evidence['source']}` shows matches in {other_functions or 'none'}."
        )

    if audit_summary.get("ok"):
        parts.append(
            f"**2. Closes validation gap.** `{audit_summary['source']}` found pytest "
            f"{audit_summary['passed']} pass / {audit_summary['failed']} fail."
        )
    else:
        parts.append("**2. No pytest audit found.** [unverified]")

    cite = []
    if "#1" in baselines:
        b = baselines["#1"]
        cite.append(f"#1 ratio = {b.get('comments')}/{b.get('posts')} = {b.get('ratio')} ({b.get('source')})")
    if "#2" in baselines:
        b = baselines["#2"]
        cite.append(f"#2 bracket_pct = {b.get('bracket_pct')}% ({b.get('source')})")
    if "#5" in baselines:
        cite.append(f"#5 worktrees = {len(baselines['#5']['worktrees'])} ({baselines['#5']['source']})")

    parts.append("")
    parts.append(f"**3. Baselines:** {', '.join(cite) or '[unverified]'}")
    response = "\n".join(parts)
    return response[:word_limit]


class FactoryReporterAutoJump1Agent(BasicAgent):
    def __init__(self):
        self.name = "FactoryReporterAutoJump1"
        self.metadata = {
            "name": self.name,
            "description": "Reports verified factory fixes for governance lurks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "Task to perform."},
                    "word_limit": {"type": "integer", "description": "Response word limit."},
                },
                "required": ["task"],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, **kwargs) -> str:
        word_limit = kwargs.get("word_limit", 300)
        baselines = _audit_baselines()
        audit_summary = _audit_summary()
        lurk_evidence = _lurk_marker_evidence()
        return json.dumps({"response": _compose_response(baselines, audit_summary, lurk_evidence, word_limit)})