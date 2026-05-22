"""AuditRunner — runs the Rappterbook audit harness on demand.

Executes `pytest tests/audit/ -v --tb=short` via subprocess in the canonical
repo root. Parses pytest output to extract per-test pass/fail status and
assertion failure messages. Returns a structured JSON report.

This is the anti-gaslight loop in agent form — humans should never have to
run pytest manually again to find out what's broken with the platform.
"""
import json
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from agents.basic_agent import BasicAgent
except ImportError:
    from basic_agent import BasicAgent


CANONICAL_ROOT = Path("/Users/kodyw/Documents/GitHub/Rappter/rappterbook")
# Until PR #19920 merges, tests/audit/ only lives in the worktree. Prefer
# canonical if available; fall back to the worktree so AuditRunner works today.
WORKTREE_ROOT = CANONICAL_ROOT / ".claude" / "worktrees" / "audit-anti-gaslight"
DEFAULT_TIMEOUT = 300


def _pick_tests_root() -> Path:
    if (CANONICAL_ROOT / "tests" / "audit").exists():
        return CANONICAL_ROOT
    if (WORKTREE_ROOT / "tests" / "audit").exists():
        return WORKTREE_ROOT
    return CANONICAL_ROOT

_TEST_LINE_RE = re.compile(r"^(tests/audit/\S+::\S+)\s+(PASSED|FAILED|SKIPPED|ERROR)")
_FAILURE_HDR_RE = re.compile(r"^_{5,}\s+(\S+)\s+_{5,}\s*$")
_ASSERTION_RE = re.compile(r"^E\s+(AssertionError:.*?)(?:\n|$)")


def _parse_pytest_output(stdout: str) -> dict:
    results = []
    failure_blocks: dict[str, list[str]] = {}
    current = None
    for line in stdout.splitlines():
        m = _TEST_LINE_RE.match(line)
        if m:
            test_id, status = m.group(1), m.group(2)
            color = {"PASSED": "green", "FAILED": "red", "ERROR": "red",
                     "SKIPPED": "skipped"}.get(status, "unknown")
            results.append({"test_id": test_id, "status": color, "raw": status})
            continue
        hdr = _FAILURE_HDR_RE.match(line)
        if hdr:
            current = hdr.group(1)
            failure_blocks.setdefault(current, [])
            continue
        if current and line.startswith("E "):
            failure_blocks[current].append(line[2:].strip())
    # Attach assertion messages to failed results
    for r in results:
        if r["status"] != "red":
            continue
        short_id = r["test_id"].rsplit("::", 1)[-1]
        block = failure_blocks.get(short_id) or []
        if block:
            r["assertion_message"] = block[0][:500]
    summary = {
        "total_tests": len(results),
        "passed": sum(1 for r in results if r["status"] == "green"),
        "failed": sum(1 for r in results if r["status"] == "red"),
        "skipped": sum(1 for r in results if r["status"] == "skipped"),
    }
    return {"summary": summary, "results": results}


class AuditRunnerAgentAgent(BasicAgent):
    def __init__(self):
        self.name = "AuditRunnerAgent"
        self.metadata = {
            "name": self.name,
            "description": (
                "Runs the Rappterbook audit harness (pytest tests/audit/) on demand. "
                "Returns structured red/green/skipped counts and per-test assertion "
                "messages. Use this whenever the operator asks 'what's broken with "
                "the platform?' or to verify a fix landed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "test_filter": {
                        "type": "string",
                        "description": "Optional pytest -k expression (e.g. 'reply_ratio' or 'governance'). Default: run all audits.",
                    },
                    "verbose": {
                        "type": "boolean",
                        "description": "If true (default), include all per-test rows in the response. If false, only failed tests are listed.",
                    },
                },
                "required": [],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, **kwargs):
        test_filter = (kwargs.get("test_filter") or "").strip()
        verbose = bool(kwargs.get("verbose", True))

        cmd = ["python3", "-m", "pytest", "tests/audit/", "-v", "--tb=short"]
        if test_filter:
            cmd.extend(["-k", test_filter])

        tests_root = _pick_tests_root()
        started = time.time()
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(tests_root),
                capture_output=True, text=True,
                timeout=DEFAULT_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return json.dumps({
                "status": "timeout",
                "message": f"pytest exceeded {DEFAULT_TIMEOUT}s timeout",
                "elapsed_seconds": DEFAULT_TIMEOUT,
            }, indent=2)
        except FileNotFoundError as e:
            return json.dumps({"status": "error", "message": f"pytest not available: {e}"})

        duration = round(time.time() - started, 2)
        parsed = _parse_pytest_output(proc.stdout)
        results = parsed["results"]
        if not verbose:
            results = [r for r in results if r["status"] == "red"]

        tail = "\n".join(proc.stdout.splitlines()[-50:])
        report = {
            "status": "ok" if proc.returncode == 0 else "failures_detected",
            "ran_at": datetime.now(timezone.utc).isoformat(),
            "command": " ".join(cmd),
            "tests_root": str(tests_root),
            "exit_code": proc.returncode,
            "duration_seconds": duration,
            "summary": parsed["summary"],
            "results": results,
            "raw_tail": tail,
        }
        return json.dumps(report, indent=2)


if __name__ == "__main__":
    a = AuditRunnerAgentAgent()
    print(a.perform(verbose=False))
