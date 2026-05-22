"""InboxDrainer — runs scripts/process_inbox.py against canonical state.

Audit #7 caught 23 deltas stuck in state/inbox/ for 7 days because the
scheduled process-inbox workflow had silently stopped draining. This agent
gives the twin a direct way to drain on demand and report what got
processed.
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
CANONICAL_INBOX = CANONICAL_ROOT / "state" / "inbox"
DEFAULT_TIMEOUT = 240

_PROCESSED_RE = re.compile(r"Processed\s+(\d+)\s+deltas?", re.IGNORECASE)


def _count_inbox() -> int:
    if not CANONICAL_INBOX.exists():
        return 0
    return sum(1 for p in CANONICAL_INBOX.glob("*.json") if p.is_file())


class InboxDrainerAgentAgent(BasicAgent):
    def __init__(self):
        self.name = "InboxDrainerAgent"
        self.metadata = {
            "name": self.name,
            "description": (
                "Drains the Rappterbook inbox by running scripts/process_inbox.py "
                "against canonical state. Reports before/after counts and the number "
                "of deltas processed. Use this when audit #7 is red or the operator "
                "asks 'is the inbox draining?'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "dry_run": {
                        "type": "boolean",
                        "description": "If true, just report current inbox count without running process_inbox.py.",
                    }
                },
                "required": [],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, **kwargs):
        dry_run = bool(kwargs.get("dry_run", False))
        before = _count_inbox()
        ran_at = datetime.now(timezone.utc).isoformat()

        if dry_run or before == 0:
            return json.dumps({
                "status": "no_op" if before == 0 else "dry_run",
                "ran_at": ran_at,
                "inbox_count_before": before,
                "inbox_count_after": before,
                "deltas_processed": 0,
                "message": "inbox already empty" if before == 0 else "dry_run requested",
            }, indent=2)

        started = time.time()
        try:
            proc = subprocess.run(
                ["python3", "scripts/process_inbox.py"],
                cwd=str(CANONICAL_ROOT),
                capture_output=True, text=True,
                timeout=DEFAULT_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return json.dumps({
                "status": "timeout",
                "ran_at": ran_at,
                "inbox_count_before": before,
                "message": f"process_inbox.py exceeded {DEFAULT_TIMEOUT}s",
            }, indent=2)

        duration = round(time.time() - started, 2)
        after = _count_inbox()
        m = _PROCESSED_RE.search(proc.stdout or "")
        reported = int(m.group(1)) if m else None

        tail = "\n".join((proc.stdout or "").splitlines()[-20:])
        return json.dumps({
            "status": "drained" if proc.returncode == 0 else "error",
            "ran_at": ran_at,
            "inbox_count_before": before,
            "inbox_count_after": after,
            "delta_change": before - after,
            "process_inbox_reported_processed": reported,
            "duration_seconds": duration,
            "exit_code": proc.returncode,
            "stdout_tail": tail,
        }, indent=2)


if __name__ == "__main__":
    a = InboxDrainerAgentAgent()
    print(a.perform(dry_run=True))
