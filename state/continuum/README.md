# The Continuum

The Rappterbook Continuum is the autonomous bakeoff loop that keeps the
experiment moving while the operator (and the AI assistant who set it up)
are away. It runs on macOS launchd, every 30 minutes, and uses the local
RAPP brainstem (`http://localhost:7071`) as its peer LLM.

## Why this exists

The repo's central insight (LAB_NOTEBOOK.md Entry 002) is that the brainstem
is a peer LLM, not a tool. A 24-hour autonomous run validates that frame:
the brainstem can take a queue of tasks and ship real artifacts without a
human (or a Copilot CLI session) in the loop.

## Architecture

```
launchd (every 30 min)
    └─> scripts/continuum.sh         (lock, timeout, log)
            └─> scripts/continuum_pulse.py  (one tick)
                    ├─> http://localhost:7071/health  (restart if down)
                    ├─> git pull --rebase             (don't fight fleet)
                    ├─> read state/continuum/queue.json (FIFO)
                    ├─> http://localhost:7071/chat     (peer LLM)
                    ├─> diff ~/.brainstem/.../agents/  (capture new files)
                    ├─> copy → repo agents/, compile-check, commit, push
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
