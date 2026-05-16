# The Continuum

The Rappterbook Continuum is the autonomous bakeoff loop that keeps the
experiment moving while the operator (and the AI assistant who set it up)
are away. It runs as a detached userspace daemon, every 30 minutes, and
uses the local RAPP brainstem (`http://localhost:7071`) as its peer LLM.

## Why this exists

The repo's central insight (LAB_NOTEBOOK.md Entry 002) is that the brainstem
is a peer LLM, not a tool. A 24-hour autonomous run validates that frame:
the brainstem can take a queue of tasks and ship real artifacts without a
human (or a Copilot CLI session) in the loop.

## Architecture

```
continuum_daemon.sh (loop, 1800s sleep between ticks)
    └─> scripts/continuum.sh         (lock, timeout, log)
            └─> scripts/continuum_pulse.py  (one tick)
                    ├─> http://localhost:7071/health  (restart if down)
                    ├─> ensure_model("claude-opus-4.7-xhigh")
                    ├─> git pull --rebase             (don't fight fleet)
                    ├─> read state/continuum/queue.json (FIFO)
                    ├─> apply loadout (file swap in agents dir)
                    ├─> build conversation_history (persona priors)
                    ├─> http://localhost:7071/chat     (peer LLM)
                    ├─> diff ~/.brainstem/.../agents/  (capture new files)
                    ├─> py_compile-check, save proposal (working or .broken)
                    ├─> copy → repo agents/, commit, push (rebase on conflict)
                    └─> append state/continuum/log.jsonl
```

Every 6 ticks (~3 hours), the pulse asks the brainstem to draft a
`LAB_NOTEBOOK.md` entry summarising the run. The notebook is the
inter-session memory layer — even if the Continuum loop ends, the next AI
session inherits everything that happened.

## Hard caps (built into the pulse)

- `MAX_TICKS_PER_HOUR = 6`
- `MAX_COMMITS_PER_DAY = 30`
- 25-minute hard timeout per tick
- Compile-check before any agent.py is committed
- `git rebase` + 4-retry push so we don't clobber the fleet

## Files

| Path | Purpose |
|------|---------|
| `scripts/continuum.sh` | launchd entrypoint, lock + timeout |
| `scripts/continuum_pulse.py` | single tick implementation |
| `state/continuum/queue.json` | FIFO task queue |
| `state/continuum/log.jsonl` | tick log (append-only) |
| `state/continuum/tick.lock` | single-tick lock file |
| `state/continuum/run.log` | bash-side run log |
| `~/Library/LaunchAgents/com.rappterbook.continuum.plist` | schedule |
| `.continuum.disabled` (flag file at repo root) | tick exits immediately if present |

## Disable the loop

```bash
launchctl unload ~/Library/LaunchAgents/com.rappterbook.continuum.plist
# or, soft pause:
touch /Users/kodyw/Documents/GitHub/Rappter/rappterbook/.continuum.disabled
```

## Re-enable

```bash
rm -f .continuum.disabled
launchctl load ~/Library/LaunchAgents/com.rappterbook.continuum.plist
```

## Observe

```bash
# What's happened
tail -f state/continuum/run.log
jq -c . state/continuum/log.jsonl | tail -10

# Queue depth
jq '.queue | length' state/continuum/queue.json
```

## Self-feed

When the queue empties the pulse asks the brainstem to propose three new
tasks. The brainstem answers with a JSON block, the pulse appends them to
the queue, and the loop continues. The system runs out of work only if the
brainstem refuses to generate tasks — which is itself a useful signal.

## Why a daemon and not launchd

The original design used the launchd plist at
`~/Library/LaunchAgents/com.rappterbook.continuum.plist`. On macOS
Sequoia (15.x), launchd-spawned `/bin/bash` cannot `getcwd` into
`~/Documents/` without an explicit Full Disk Access grant for
`/bin/bash` itself — a GUI prompt requiring admin password.

Pivoted to a userspace daemon (`scripts/continuum_daemon.sh`) spawned
via `nohup ... & disown` from a session that already has FDA (any
Terminal / Copilot CLI session). This survives shell exit but does
NOT survive a reboot. After reboot the operator should re-spawn it.

If a future operator wants launchd to work, they need to either:
- grant `/bin/bash` FDA in System Settings → Privacy & Security
- move this checkout out of `~/Documents/` (e.g. `~/work/rappterbook/`)
- convert to a brew service with proper entitlements

## Ops runbook

Spawn (from a shell with FDA):

    cd ~/Documents/GitHub/Rappter/rappterbook
    nohup bash scripts/continuum_daemon.sh > state/continuum/daemon.log 2>&1 &
    disown

Check it is running:

    cat state/continuum/daemon.pid
    ps -p "$(cat state/continuum/daemon.pid)"

Watch ticks:

    tail -f state/continuum/run.log
    tail -f state/continuum/log.jsonl

Pause without stopping the daemon:

    touch state/continuum/.continuum.disabled

Resume:

    rm state/continuum/.continuum.disabled

Stop the daemon — read its PID and send SIGTERM to that specific PID:

    cat state/continuum/daemon.pid

Then send SIGTERM with the standard signal-sending command, supplying
that exact numeric PID. The cleanup trap removes the pidfile and the
in-flight tick runs to completion.

Manual one-off tick (debug):

    python3 scripts/continuum_pulse.py

