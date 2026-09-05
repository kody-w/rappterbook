---
name: resume-session
description: Read-only cold-start pickup for a Rappterbook session. Reconstruct only the context needed for the current task and report what is running without changing shared services, artifacts, dashboards, or schedules.
argument-hint: "[check|full]"
allowed-tools: Bash, Read, Grep, Glob
context: fork
---

# Resume a Rappterbook session safely

Reconstruct only enough state to answer the current request. The default is observational: do not
write files, start or stop processes, harvest artifacts, rebuild dashboards, create schedules, or
touch another agent's work.

## 1. Bind the check to the active repository and task

Resolve the repository from the current checkout; never assume a username or an old memory path:

```bash
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd -P)"
printf 'Repository: %s\n' "$REPO_ROOT"
git -C "$REPO_ROOT" status --short --branch
```

Treat a shared checkout as live. Do not reset, switch branches, clean files, or inspect unrelated
project/artifact trees. If the user's task is unrelated to the simulator or fleet, skip all
simulator and fleet checks.

## 2. Read only relevant continuity

For a Rappterbook session, read `LAB_NOTEBOOK.md` first—every entry, newest first—including the
current recommended next move. This is mandatory continuity even for a task-scoped check. It
informs what the experiment is currently attempting, but it does not authorize unrelated work or a
notebook write.

After the notebook, read `AGENTS.md`, `CLAUDE.md`, `.github/copilot-instructions.md`, and the nearest
scoped instruction file as relevant to the current task. Use the notebook, current branch/status,
and recent history as the sources of truth. Do not crawl home-directory memory stores or assume
files from a previous machine still exist.

If the current task explicitly concerns seeds, the following is a read-only summary:

```bash
(
  cd "$REPO_ROOT" || exit 1
  SEEDS_PATH="${SEEDS_PATH:-$REPO_ROOT/state/seeds.json}" \
  PYTHONPATH="$REPO_ROOT/scripts" \
  python3 -c '
import contextlib
import io
import json
import os
from pathlib import Path

from state_io import load_json

path = Path(os.environ["SEEDS_PATH"])

def unknown(reason):
    print(json.dumps({"status": "UNKNOWN", "source": str(path), "reason": reason}))
    raise SystemExit(2)

if not path.is_file():
    unknown("seed state is missing")

try:
    with path.open("rb") as stream:
        stream.read(1)
except OSError as exc:
    unknown(f"seed state is unreadable: {exc}")

diagnostics = io.StringIO()
try:
    with contextlib.redirect_stderr(diagnostics):
        state = load_json(path)
except (OSError, RuntimeError, ValueError) as exc:
    unknown(f"seed state could not be loaded: {exc}")

warning = diagnostics.getvalue().strip()
if warning:
    unknown(warning)
if not isinstance(state, dict):
    unknown("seed state root is not an object")

missing = object()
active_value = state.get("active", missing)
if active_value is missing:
    active = {}
    no_active = False
elif active_value is None:
    active = {}
    no_active = True
elif isinstance(active_value, dict):
    active = active_value
    no_active = False
else:
    unknown("active seed is neither an object nor null")

convergence = active.get("convergence")
if convergence is None:
    convergence = {}
elif not isinstance(convergence, dict):
    unknown("active convergence is neither an object nor null")

queue = state.get("queue")
queued = len(queue) if isinstance(queue, list) else "UNKNOWN"
summary = {
    "seed": None if no_active else active.get("id", "UNKNOWN"),
    "frames": None if no_active else active.get("frames_active", "UNKNOWN"),
    "convergence": None if no_active else convergence.get("score", "UNKNOWN"),
    "resolved": None if no_active else convergence.get("resolved", "UNKNOWN"),
    "queued": queued,
}
status = "UNKNOWN" if "UNKNOWN" in summary.values() else "OK"
print(json.dumps({
    "status": status,
    **summary,
}))
raise SystemExit(0 if status == "OK" else 2)
'
)
```

Missing, unreadable, corrupt, or structurally invalid state prints a visible `UNKNOWN` result and
exits 2. An absent or `null` active seed is handled as no active seed; an absent or non-list queue is
`UNKNOWN`, never zero.

## 3. Keep platform and engine ownership intact

The private engine owns long-running simulation and fleet lifecycle. In particular:

- Never invoke `scripts/copilot-infinite.sh` from this skill.
- Never restart a simulator or shared fleet merely because a PID or log is absent.
- Never use `nohup`, anonymous background jobs, or broad process killing.
- Do not treat an isolated artifact build or a status answer as authorization to touch shared
  services.

For a task that explicitly asks for engine health, use the owner-documented read-only health
surface. If none is available, report that health was not measured.

## 4. Require precise authorization for every mutation

Only perform one of these when the current user request names that operation and its target:

| Operation | Required before acting |
|---|---|
| Restart/start/stop | Confirm the exact owned service and use its supported managed or foreground command. Never kill by name. |
| Harvest | Confirm the exact project and destination, run its documented dry-run first, show the result, then ask before the real harvest if not already explicit. Never push or publish implicitly. |
| Rebuild a dashboard | Confirm the named dashboard is in scope and that the files are not owned by another live agent. |
| Create a schedule | Confirm the exact job, cadence, duration, and owner. Never create recurring jobs as session setup. |

Authorization for one operation does not authorize the others.

## 5. Report observed state

Keep the result concise and distinguish facts from skipped or unavailable checks:

```text
SESSION CONTEXT
Repository/worktree: [...]
Branch and local changes: [...]
Task-relevant state: [...]
Shared services: [observed / not checked]
Mutations performed: none
Next authorized action: [...]
```

Never report a service as healthy, an artifact as harvested, or a schedule as active unless this
session measured or performed that exact action.
