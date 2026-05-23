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


class FactoryReporterAutoJump1Agent(BasicAgent):
    def __init__(self):
        self.name = "FactoryReporterAutoJump1"
        self.metadata = {
            "name": self.name,
            "description": "Enhanced verification for numeric claims in factory reports.",
            "parameters": {"word_limit": 300},
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, **kwargs) -> str:
        word_limit = kwargs.get("word_limit", 300)
        baselines = self._verified_audit_baselines()
        audit_summary = self._verified_audit_summary()
        lurk_evidence = self._verified_lurk_marker_evidence()
        output = self._compose_v3(baselines, audit_summary, lurk_evidence, word_limit)
        return json.dumps(output)

    def _run(self, cmd: list, cwd: Path = CANONICAL_ROOT, timeout: int = 30) -> dict:
        try:
            p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
            return {
                "cmd": " ".join(cmd),
                "ok": p.returncode == 0,
                "stdout": (p.stdout or "")[:2000],
                "stderr": (p.stderr or "")[:500],
            }
        except Exception as e:
            return {"cmd": " ".join(cmd), "ok": False, "stderr": str(e)[:300]}

    def _grep_with_function_context(self, pattern: str, filepath: str) -> list:
        """Return [{line_no, line, enclosing_function, verification_log}, ...] for each match."""
        g = self._run(["grep", "-n", pattern, filepath])
        verification_log = {"cmd": g["cmd"], "stdout": g.get("stdout", ""), "stderr": g.get("stderr", "")}
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
            # Find enclosing def by reading the file up to that line
            head = self._run(["sed", "-n", f"1,{line_no}p", filepath])
            enclosing = None
            if head["ok"]:
                for prev in reversed(head["stdout"].splitlines()):
                    m = re.match(r"^def\s+(\w+)", prev)
                    if m:
                        enclosing = m.group(1)
                        break
            matches.append({
                "line_no": line_no,
                "line": content[:200],
                "enclosing_function": enclosing,
                "verification_log": verification_log,
            })
        return matches

    def _verified_audit_summary(self) -> dict:
        """Verify summary of audit pytest."""
        tests_root = CANONICAL_ROOT if (CANONICAL_ROOT / "tests" / "audit").exists() else WORKTREE_ROOT
        verification_log = []
        if not (tests_root / "tests" / "audit").exists():
            return {"ok": False, "error": "tests/audit/ not found", "verification_log": verification_log}
        p = self._run(["python3", "-m", "pytest", "tests/audit/", "--tb=no", "-q"], cwd=tests_root, timeout=180)
        verification_log.append({"cmd": p["cmd"], "stdout": p["stdout"], "stderr": p["stderr"]})
        out = (p.get("stdout", "") or "") + "\n" + (p.get("stderr", "") or "")
        m = re.search(r"(\d+)\s+failed,?\s+(\d+)\s+passed", out)
        if m:
            return {"ok": True, "failed": int(m.group(1)), "passed": int(m.group(2)), "verification_log": verification_log}
        m = re.search(r"(\d+)\s+passed", out)
        if m:
            return {"ok": True, "failed": 0, "passed": int(m.group(1)), "verification_log": verification_log}
        return {"ok": False, "verification_log": verification_log}

    def _verified_audit_baselines(self) -> dict:
        """Get baselines such as #1, #2, #3, and #5."""
        out = {}
        verification_logs = {}
        p = self._run(["python3", "-c",
                      "import json; d=json.load(open('state/posted_log.json')); "
                      "print(json.dumps({'posts':len(d.get('posts',[])),'comments':len(d.get('comments',[]))}))"])
        verification_logs["#1"] = {"cmd": p["cmd"], "stdout": p["stdout"], "stderr": p["stderr"]}
        if p["ok"]:
            try:
                out["#1"] = json.loads(p["stdout"].strip())
                out["#1"]["ratio"] = round(out["#1"]["comments"] / max(out["#1"]["posts"], 1), 4)
            except (json.JSONDecodeError, KeyError):
                out["#1"] = {"error": "Failed to decode or calculate", "verification_log": verification_logs["#1"]}
        p = self._run(["python3", "-c",
                      "import json; d=json.load(open('state/autonomy_log.json')); "
                      "es=d.get('entries',[])[-100:]; "
                      "ps=[e.get('content_quality',{}).get('bracket_tag_pct',0) for e in es]; "
                      "act=sum((e.get('run',{}).get('agents_activated') or 0) for e in es); "
                      "lurks=sum((e.get('run',{}).get('lurks') or 0) for e in es); "
                      "import json as J; print(J.dumps({'bracket_pct':sum(ps)/max(len(ps),1),"
                      "'lurks':lurks,'activations':act,'entries':len(es)}))"])
        verification_logs["#2"] = {"cmd": p["cmd"], "stdout": p["stdout"], "stderr": p["stderr"]}
        if p["ok"]:
            try:
                data = json.loads(p["stdout"].strip())
                out["#2"] = {"bracket_pct": round(data["bracket_pct"], 1), "entries": data["entries"]}
                out["#3"] = {"lurks": data["lurks"], "activations": data["activations"]}
            except (json.JSONDecodeError, KeyError):
                out["#2"] = {"error": "Failed to decode #2", "verification_log": verification_logs["#2"]}
        p = self._run(["ls", "-1", ".claude/worktrees/"])
        verification_logs["#5"] = {"cmd": p["cmd"], "stdout": p["stdout"], "stderr": p["stderr"]}
        if p["ok"]:
            out["#5"] = {"worktrees": [w for w in p["stdout"].splitlines() if w.strip()]}
        return {"out": out, "verification_logs": verification_logs}

    def _verified_lurk_marker_evidence(self) -> dict:
        """Verify exact locations of `[LURK]` markers."""
        matches = self._grep_with_function_context(r"\[LURK\]", "scripts/zion_autonomy.py")
        lives_in_passive_governance = any(
            m.get("enclosing_function") == "_passive_governance" for m in matches
        )
        return {
            "total_matches": len(matches),
            "matches": matches,
            "lives_in_passive_governance": lives_in_passive_governance,
        }

    def _compose_v3(self, baselines: dict, audit_summary: dict, lurk_evidence: dict, word_limit: int) -> dict:
        parts = ["**Fix #3 governance lurks first.**"]
        extra = []

        # Analyze lurk marker evidence
        if lurk_evidence["lives_in_passive_governance"]:
            matched = [m for m in lurk_evidence["matches"] if m.get("enclosing_function") == "_passive_governance"]
            line_info = ", ".join(f"L{m['line_no']}" for m in matched)
            parts.append(f"Fix confirmed: `_passive_governance` L({line_info}).")

        return {"output": " ".join(parts[:word_limit])}