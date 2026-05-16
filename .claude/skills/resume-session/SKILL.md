---
name: resume-session
description: Cold-start pickup for a new Claude Code session. Checks sim, seed, pipeline, and gets everything running. Use at the start of every new session.
argument-hint: "[check|full]"
allowed-tools: Bash, Read, Write, Edit, Grep, Glob
context: fork
---

You are the session resumption agent. When a user starts a new Claude Code session on Rappterbook, run this to pick up where they left off. No context from previous sessions — you reconstruct everything from disk.

## Step 1: Read Memory

```bash
cat /Users/kodyw/.claude/projects/-Users-kodyw-Projects-rappterbook/memory/MEMORY.md
cat /Users/kodyw/.claude/projects/-Users-kodyw-Projects-rappterbook/memory/project_full_state_2026_03_16.md
```

This gives you the full context: active seed, repos shipped, pipeline architecture, known issues.

## Step 2: Check Sim

```bash
ps -p $(cat /tmp/rappterbook-sim.pid 2>/dev/null) > /dev/null 2>&1 && echo "SIM: ALIVE" || echo "SIM: DEAD"
tail -5 logs/sim.log 2>/dev/null
```

If dead, restart:
```bash
nohup bash scripts/copilot-infinite.sh --hours 10 --streams 5 > logs/sim.log 2>&1 &
echo "Sim restarted"
```

## Step 3: Check Active Seed

```bash
python3 -c "
import json
s = json.load(open('state/seeds.json'))
a = s.get('active', {})
print(f'Seed: {a.get(\"id\", \"none\")}')
print(f'Text: {a.get(\"text\", \"\")[:80]}')
print(f'Frames: {a.get(\"frames_active\", 0)}')
print(f'Conv: {a.get(\"convergence\", {}).get(\"score\", 0)}%')
print(f'Resolved: {a.get(\"convergence\", {}).get(\"resolved\", False)}')
print(f'Queue: {len(s.get(\"queue\", []))} items')
"
```

## Step 4: Check Code on Disk

For the active project, check if agents have written code:

```bash
# Find the active project
for p in projects/*/project.json; do
    slug=$(dirname "$p" | xargs basename)
    files=$(find "projects/$slug/src" "projects/$slug/docs" -type f -not -name ".gitkeep" -not -path "*__pycache__*" 2>/dev/null | wc -l | tr -d ' ')
    if [ "$files" -gt 0 ]; then
        echo "$slug: $files files on disk"
        find "projects/$slug/src" "projects/$slug/docs" -type f -not -name ".gitkeep" -not -path "*__pycache__*" 2>/dev/null | head -10
    fi
done
```

## Step 5: Harvest if Needed

If code exists on disk but hasn't been pushed to the target repo:

```bash
python3 scripts/harvest_artifact.py --project {slug} --dry-run
```

If artifacts found, harvest for real:
```bash
python3 scripts/harvest_artifact.py --project {slug} --phase "session-resume"
```

## Step 6: Rebuild Public Dashboards

```bash
python3 scripts/build_seed_tracker.py 2>/dev/null
python3 scripts/build_harness_dashboard.py 2>/dev/null
```

## Step 7: Spin Up Temporal Harness

Set up the recurring monitoring crons:

```
I'll set up the temporal harness:
- Fleet health check every 30 min
- Artifact overseer every 10 min
- Deep analytics every 4 hours
```

Use CronCreate for each.

## Step 8: Report to User

Print a concise status:

```
SESSION RESUMED
===============
Sim: [ALIVE/DEAD]
Seed: [id] — [text[:60]]
Frames: [N], Convergence: [N]%
Code on disk: [N] files in [project]
Target repo: [url]
Live site: [pages url]

TEMPORAL HARNESS: [running/setting up]

What would you like to do?
```

## Rules

- Always read memory files FIRST — they contain the accumulated context
- If the sim is dead, restart it immediately without asking
- If code is on disk and not harvested, harvest it
- If dashboards are stale, rebuild them
- Set up the temporal harness crons every session (they're session-only)
- Be concise — the user knows the system, they just need current status
