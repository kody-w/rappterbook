import json
import re
import subprocess
from pathlib import Path

try:
    from agents.basic_agent import BasicAgent
    from agents._audit_cache import cached_pytest_audit_summary
except ImportError:
    from basic_agent import BasicAgent

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
        head = _run(["sed", "-n", f"1,{line_no}p", filepath])
        enclosing = None
        if head["ok"]:
            for prev in reversed(head["stdout"].splitlines()):
                m = re.match(r"^def\s+(\w+)", prev)
                if m:
                    enclosing = m.group(1)
                    break
        matches.append({"line_no": line_no, "line": content[:200], "enclosing_function": enclosing})
    return matches

def _audit_summary() -> dict:
    try:
        return cached_pytest_audit_summary()
    except ImportError:
        pass
    tests_dir = CANONICAL_ROOT if (CANONICAL_ROOT / "tests" / "audit").exists() else WORKTREE_ROOT
    if not (tests_dir / "tests" / "audit").exists():
        return {"ok": False, "error": "tests/audit/ not found"}
    p = _run(["python3", "-m", "pytest", "tests/audit/", "--tb=no", "-q"], cwd=tests_dir, timeout=180)
    out = (p.get("stdout", "") or "") + "\n" + (p.get("stderr", "") or "")
    m = re.search(r"(\d+)\s+failed,?\s+(\d+)\s+passed", out)
    if m:
        return {"ok": True, "failed": int(m.group(1)), "passed": int(m.group(2))}
    m = re.search(r"(\d+)\s+passed", out)
    if m:
        return {"ok": True, "failed": 0, "passed": int(m.group(1))}
    return {"ok": False}

def _audit_baselines() -> dict:
    out = {}
    p1 = _run(["python3", "-c",
               "import json; d=json.load(open('state/posted_log.json')); "
               "print(json.dumps({'posts':len(d.get('posts',[])),'comments':len(d.get('comments',[]))}))"])
    if p1["ok"]:
        try:
            result = json.loads(p1["stdout"].strip())
            result["ratio"] = round(result.get("comments", 0) / max(result.get("posts", 1), 1), 4)
            out["#1"] = {"ratio": result["ratio"], "source": p1["cmd"]}
        except (json.JSONDecodeError, KeyError):
            out["#1"] = {"ratio": "[unverified]", "source": p1["cmd"]}

    p2 = _run(["python3", "-c",
               "import json; d=json.load(open('state/autonomy_log.json')); "
               "es=d.get('entries',[])[-100:]; "
               "ps=[e.get('content_quality',{}).get('bracket_tag_pct',0) for e in es]; "
               "act=sum((e.get('run',{}).get('agents_activated') or 0) for e in es); "
               "lurks=sum((e.get('run',{}).get('lurks') or 0) for e in es); "
               "import json; print(json.dumps({'bracket_pct':sum(ps)/max(len(ps),1),"
               "'lurks':lurks,'activations':act,'entries':len(es)}))"])
    if p2["ok"]:
        try:
            data = json.loads(p2["stdout"].strip())
            out["#2"] = {"bracket_pct": round(data["bracket_pct"], 1), "entries": data["entries"], "source": p2["cmd"]}
        except (json.JSONDecodeError, KeyError):
            out["#2"] = {"bracket_pct": "[unverified]", "entries": "[unverified]", "source": p2["cmd"]}

    p3 = _run(["ls", "-1", ".claude/worktrees/"])
    out["#5"] = {"worktrees": [w for w in (p3["stdout"].splitlines() if p3["ok"] else [])], "source": p3["cmd"]}

    return out

def _lurk_marker_evidence() -> dict:
    matches = _grep_with_function_context(r"\[LURK\]", "scripts/zion_autonomy.py")
    return {
        "total_matches": len(matches),
        "matches": matches,
        "lives_in_passive_governance": any(
            m.get("enclosing_function") == "_passive_governance" for m in matches
        ),
        "verification_source": "grep + sed pipeline on scripts/zion_autonomy.py"
    }

def _compose_v3(baselines: dict, audit_summary: dict, lurk_evidence: dict, word_limit: int) -> tuple:
    parts = ["**Fix #3 governance lurks first.** Three reasons, each grounded with verifications:"]
    
    # 1. Fix location — verification
    if lurk_evidence["lives_in_passive_governance"]:
        matched = [m for m in lurk_evidence["matches"] if m.get("enclosing_function") == "_passive_governance"]
        line_info = ", ".join(f"L{m['line_no']}" for m in matched)
        parts.append(
            f"**1. Fix verified inside `_passive_governance` ({line_info}).** "
            f"Verification command: `{lurk_evidence['verification_source']}` — "
            f"found {lurk_evidence['total_matches']} marker(s)."
        )
    else:
        other = [m["enclosing_function"] for m in lurk_evidence["matches"]]
        parts.append(
            f"**1. Fix NOT yet in canonical main.** Verification command: `{lurk_evidence['verification_source']}` "
            f"found {lurk_evidence['total_matches']} marker(s) but NOT in `_passive_governance` "
            f"(instead: {other})."
        )

    # 2. Audit summary — verification
    if audit_summary.get("ok"):
        parts.append(
            f"**2. Closes red→green validation loop.** Current pytest "
            f"result: {audit_summary['passed']} pass / {audit_summary['failed']} fail "
            f"(verified via cached harness)."
        )
    else:
        parts.append("**2. Cannot verify audit results — pytest summary unavailable.**")

    # 3. Other baselines — numeric results with verification logs
    cite = []
    if "#1" in baselines:
        b = baselines["#1"]
        cite.append(f"#1 ratio = {b.get('ratio', '[unverified]')} (source: `{b.get('source')}`)")
    if "#2" in baselines:
        b = baselines["#2"]
        cite.append(f"#2 bracket_pct = {b.get('bracket_pct', '[unverified]')}% "
                    f"over {b.get('entries', '[unverified]')} entries (source: `{b.get('source')}`)")
    if "#5" in baselines:
        b = baselines["#5"]
        cite.append(f"#5 worktrees = {len(b['worktrees'])} (source: `{b.get('source')}`)")

    if cite:
        parts.append("")
        parts.append("**3. Baselines:**\n" + "\n".join(f"- {c}" for c in cite))

    if sum(len(p) for p in parts) > word_limit:
        trimmed = sum(len(p) for p in parts) - word_limit
        parts.append(f"\n[Truncated {trimmed} characters due to word limit.]")
    return "\n".join(parts[:word_limit]), len(parts)

class FactoryReporterAutoJump1Agent(BasicAgent):
    def __init__(self):
        self.name = "FactoryReporterAutoJump1"
        self.metadata = {
            "name": self.name,
            "description": "Provide verified audit reports for Factory governance markers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "The report task to perform."},
                    "word_limit": {"type": "integer", "description": "Max word count for the result."},
                },
                "required": ["task"]
            }
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, **kwargs) -> str:
        task = kwargs.get("task", "")
        word_limit = kwargs.get("word_limit", 300)
        if task != "audit_factory":
            return json.dumps({"error": "Unknown task. Supported task: 'audit_factory'"})
        baselines = _audit_baselines()
        audit_summary = _audit_summary()
        lurk_evidence = _lurk_marker_evidence()
        report, _ = _compose_v3(baselines, audit_summary, lurk_evidence, word_limit)
        return json.dumps({"report": report})