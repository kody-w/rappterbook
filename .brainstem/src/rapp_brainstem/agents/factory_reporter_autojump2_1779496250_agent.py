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


class FactoryReporterAutoJump2Agent(BasicAgent):
    def __init__(self):
        self.name = "FactoryReporterAutoJump2"
        self.metadata = {
            "name": self.name,
            "description": "Generates factory reports with verified numeric claims for audit tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "Description of the report generation task."},
                    "word_limit": {"type": "integer", "description": "Maximum word count for the report."}
                },
                "required": ["task"]
            }
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def _run(self, cmd: list, cwd: Path = CANONICAL_ROOT, timeout: int = 30) -> dict:
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

    def _audit_summary(self) -> dict:
        try:
            from agents._audit_cache import cached_pytest_audit_summary
            return cached_pytest_audit_summary()
        except ImportError:
            pass
        tests_root = CANONICAL_ROOT if (CANONICAL_ROOT / "tests" / "audit").exists() else WORKTREE_ROOT
        if not (tests_root / "tests" / "audit").exists():
            return {"ok": False, "error": "tests/audit/ not found"}
        p = self._run(["python3", "-m", "pytest", "tests/audit/", "--tb=no", "-q"],
                      cwd=tests_root, timeout=180)
        out = (p.get("stdout", "") or "") + "\n" + (p.get("stderr", "") or "")
        m = re.search(r"(\d+)\s+failed,?\s+(\d+)\s+passed", out)
        if m:
            return {"ok": True, "failed": int(m.group(1)), "passed": int(m.group(2))}
        m = re.search(r"(\d+)\s+passed", out)
        if m:
            return {"ok": True, "failed": 0, "passed": int(m.group(1))}
        return {"ok": False}

    def _lurk_marker_evidence(self) -> dict:
        grep_results = self._run(["grep", "-n", r"\[LURK\]", "scripts/zion_autonomy.py"])
        if not grep_results["ok"] or not grep_results["stdout"].strip():
            return {"total_matches": 0, "matches": [], "lives_in_passive_governance": False}

        matches = []
        for line in grep_results["stdout"].splitlines():
            if ":" not in line:
                continue
            try:
                line_no, content = line.split(":", 1)
                line_no = int(line_no)
            except ValueError:
                continue

            enclosing_function = None
            head_results = self._run(["sed", "-n", f"1,{line_no}p", "scripts/zion_autonomy.py"])
            if head_results["ok"]:
                for prev in reversed(head_results["stdout"].splitlines()):
                    match = re.match(r"^def\s+(\w+)", prev)
                    if match:
                        enclosing_function = match.group(1)
                        break

            matches.append({"line_no": line_no, "line": content[:200], "enclosing_function": enclosing_function})

        return {
            "total_matches": len(matches),
            "matches": matches,
            "lives_in_passive_governance": any(
                m.get("enclosing_function") == "_passive_governance" for m in matches
            ),
        }

    def _fetch_baselines(self) -> dict:
        results = {}

        # Baseline #1
        cmd1 = [
            "python3", "-c",
            "import json; d=json.load(open('state/posted_log.json')); "
            "print(json.dumps({'posts':len(d.get('posts',[])),'comments':len(d.get('comments',[]))}))"
        ]
        baseline1 = self._run(cmd1)
        if baseline1["ok"]:
            try:
                data = json.loads(baseline1["stdout"].strip())
                data["ratio"] = round(data["comments"] / max(data["posts"], 1), 4)
                results["#1"] = {"data": data, "cmd": baseline1["cmd"]}
            except (json.JSONDecodeError, KeyError):
                results["#1"] = {"data": "[unverified]", "cmd": baseline1["cmd"]}

        # Baseline #2 and #3
        cmd2 = [
            "python3", "-c",
            "import json; d=json.load(open('state/autonomy_log.json')); "
            "es=d.get('entries',[])[-100:]; "
            "ps=[e.get('content_quality',{}).get('bracket_tag_pct',0) for e in es]; "
            "act=sum((e.get('run',{}).get('agents_activated') or 0) for e in es); "
            "lurks=sum((e.get('run',{}).get('lurks') or 0) for e in es); "
            "import json as J; print(J.dumps({'bracket_pct':sum(ps)/max(len(ps),1),"
            "'lurks':lurks,'activations':act,'entries':len(es)}))"
        ]
        baseline2_3 = self._run(cmd2)
        if baseline2_3["ok"]:
            try:
                data = json.loads(baseline2_3["stdout"].strip())
                results["#2"] = {"data": data.get("bracket_pct"), "cmd": baseline2_3["cmd"]}
                results["#3"] = {"data": data, "cmd": baseline2_3["cmd"]}
            except (json.JSONDecodeError, KeyError):
                results["#2"], results["#3"] = {"data": "[unverified]", "cmd": baseline2_3["cmd"]}, {"data": "[unverified]", "cmd": baseline2_3["cmd"]}

        # Baseline #5
        cmd5 = ["ls", "-1", ".claude/worktrees/"]
        baseline5 = self._run(cmd5)
        if baseline5["ok"]:
            results["#5"] = {"data": baseline5["stdout"].splitlines(), "cmd": baseline5["cmd"]}
        else:
            results["#5"] = {"data": "[unverified]", "cmd": baseline5["cmd"]}

        return results

    def perform(self, **kwargs) -> str:
        word_limit = kwargs.get("word_limit", 300)
        audit_summary = self._audit_summary()
        baselines = self._fetch_baselines()
        lurk_evidence = self._lurk_marker_evidence()

        # Compose response
        response = []
        response.append("**Factory Audit Findings**")

        if lurk_evidence["lives_in_passive_governance"]:
            location_data = ", ".join(f"L{m['line_no']}" for m in lurk_evidence["matches"] if m["enclosing_function"] == "_passive_governance")
            response.append(f"Verified [LURK] inside `_passive_governance` ({location_data}).")

        for key, data in baselines.items():
            response.append(f"Baseline {key}: {data['data']} (Source: `{data['cmd']}`)")

        if audit_summary.get("ok"):
            response.append(f"Audit Results: {audit_summary['passed']} passed, {audit_summary['failed']} failed [verified].")

        return json.dumps({"response": " ".join(response[:word_limit])})