import json
import re
import subprocess
from pathlib import Path

try:
    from agents.basic_agent import BasicAgent
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
        matches.append({"line_no": line_no, "line": content[:200], "enclosing_function": enclosing})
    return matches


def _audit_summary() -> dict:
    """Cached pytest summary (see agents/_audit_cache.py)."""
    try:
        from agents._audit_cache import cached_pytest_audit_summary
        return cached_pytest_audit_summary()
    except ImportError:
        pass
    tests_root = CANONICAL_ROOT if (CANONICAL_ROOT / "tests" / "audit").exists() else WORKTREE_ROOT
    if not (tests_root / "tests" / "audit").exists():
        return {"ok": False, "error": "tests/audit/ not found"}
    p = _run(["python3", "-m", "pytest", "tests/audit/", "--tb=no", "-q"],
             cwd=tests_root, timeout=180)
    out = (p.get("stdout", "") or "") + "\n" + (p.get("stderr", "") or "")
    m = re.search(r"(\d+)\s+failed,?\s+(\d+)\s+passed", out)
    if m:
        return {"ok": True, "failed": int(m.group(1)), "passed": int(m.group(2)), "source": p["cmd"]}
    m = re.search(r"(\d+)\s+passed", out)
    if m:
        return {"ok": True, "failed": 0, "passed": int(m.group(1)), "source": p["cmd"]}
    return {"ok": False}


def _audit_baselines() -> dict:
    """Pull the actual numbers for #1, #2, #3, #5 once each."""
    out = {}
    p = _run(["python3", "-c",
              "import json; d=json.load(open('state/posted_log.json')); "
              "print(json.dumps({'posts':len(d.get('posts',[])),'comments':len(d.get('comments',[]))}))"])
    if p["ok"]:
        try:
            parsed = json.loads(p["stdout"].strip())
            out["#1"] = {
                "posts": parsed.get("posts", 0),
                "comments": parsed.get("comments", 0),
                "ratio": round(parsed.get("comments", 0) / max(parsed.get("posts", 1), 1), 4),
                "source": p["cmd"]
            }
        except (json.JSONDecodeError, KeyError):
            pass
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
            out["#2"] = {
                "bracket_pct": round(data["bracket_pct"], 1),
                "entries": data["entries"],
                "source": p["cmd"]
            }
            out["#3"] = {
                "lurks": data["lurks"],
                "activations": data["activations"],
                "source": p["cmd"]
            }
        except (json.JSONDecodeError, KeyError):
            pass
    p = _run(["ls", "-1", ".claude/worktrees/"])
    if p["ok"]:
        out["#5"] = {"worktrees": [w for w in p["stdout"].splitlines() if w.strip()], "source": p["cmd"]}
    return out


def _lurk_marker_evidence() -> dict:
    matches = _grep_with_function_context(r"\[LURK\]", "scripts/zion_autonomy.py")
    return {
        "total_matches": len(matches),
        "matches": matches,
        "lives_in_passive_governance": any(
            m.get("enclosing_function") == "_passive_governance" for m in matches
        ),
        "source": "grep command on scripts/zion_autonomy.py"
    }


def _compose_v3(baselines: dict, audit_summary: dict, lurk_evidence: dict, word_limit: int) -> tuple:
    parts = ["**Fix #3 governance lurks first.** Three reasons, each grounded:", ""]

    # 1. Fix location — verified
    if lurk_evidence["lives_in_passive_governance"]:
        matched = [m for m in lurk_evidence["matches"] if m.get("enclosing_function") == "_passive_governance"]
        line_info = ", ".join(f"L{m['line_no']}" for m in matched)
        parts.append(
            f"**1. Fix verified inside `_passive_governance` ({line_info}).** "
            f"`grep` verified {lurk_evidence['total_matches']} occurrence(s) "
            f"({lurk_evidence['source']}) and confirmed function context."
        )
    else:
        other = [m["enclosing_function"] for m in lurk_evidence["matches"]]
        parts.append(
            f"**1. Fix NOT YET canonical.** Evidence: {lurk_evidence['source']} matched "
            f"{lurk_evidence['total_matches']} times in {other or 'none'}."
        )

    parts.append("")
    # 2. Audit summary
    if audit_summary.get("ok"):
        parts.append(
            f"**2. Validation loop results:** "
            f"{audit_summary['passed']} pass / {audit_summary['failed']} fail "
            f"({audit_summary.get('source', '[unverified]')})."
        )

    parts.append("")
    # 3. Baselines for the other three
    cite = []
    for key, desc in {"#1": "posts/comments", "#2": "bracket_tag_pct", "#3": "lurk activation"}.items():
        if key in baselines:
            data = baselines[key]
            cite.append(
                f"{key} ({desc}): {data} (via `{data.get('source', '[unverified]')}`)"
            )
        else:
            cite.append(f"{key} [unverified]")
    parts.append("**3. Baselines:** " + "; ".join(cite))

    result = "\n".join(parts)
    return result[:word_limit], len(result) > word_limit


class FactoryReporterAutoJump3Agent(BasicAgent):
    def __init__(self):
        self.name = "FactoryReporterAutoJump3"
        self.metadata = {
            "name": self.name,
            "description": "Reports factory audits with verified claims.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "Audit task description"},
                    "word_limit": {"type": "integer", "description": "Maximum word count for the report"}
                },
                "required": ["task"]
            }
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, **kwargs) -> str:
        word_limit = kwargs.get("word_limit", 300)
        lurk_evidence = _lurk_marker_evidence()
        audit_summary = _audit_summary()
        baselines = _audit_baselines()
        report, trimmed = _compose_v3(baselines, audit_summary, lurk_evidence, word_limit)
        return json.dumps({"report": report, "trimmed": trimmed})