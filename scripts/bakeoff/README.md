# Bakeoff harness — Claude vs the Brainstem

The double-jump pattern: this Claude (the *reference*) and the local brainstem
(the *student*) take turns writing rappterbook content. A judge scores both.
The gap is distilled into 2-3 concrete style rules. The rules are written to
`~/.brainstem/state/style_guide.json`. The brainstem hot-loads a passive agent
called **StyleCoach** that injects those rules into its system prompt on every
chat — so the next round, it competes with the new instruction in hand.

The brainstem keeps autonomously improving against this Claude as the
benchmark. Reference and student never touch — they only see each other
through the judge's rubric.

## Anatomy

```
state/bakeoff/
  tasks.json          ← FIFO pool of writing tasks (180-260 word posts)
  rounds.jsonl        ← append-only log; one row per completed round

scripts/bakeoff/
  bakeoff.py          ← orchestrator. Picks task → claude → brainstem → judge → distiller → merge
  install_style_coach.sh  ← copies StyleCoach into a brainstem
  brainstem_agents/
    style_coach_agent.py  ← BasicAgent subclass; system_context() reads style_guide.json

~/.brainstem/state/
  style_guide.json    ← live rules (rotates as bakeoff runs)
```

## First-time setup

```bash
# 1. Install StyleCoach into your local brainstem
bash scripts/bakeoff/install_style_coach.sh

# 2. Confirm it's hot-loaded
curl -s http://127.0.0.1:7071/health | python3 -m json.tool | grep StyleCoach
```

## Run one round

```bash
python3 scripts/bakeoff/bakeoff.py --rounds 1
```

Wall time ~3-5 min. Spends 3-4 `claude --print` calls + 1 brainstem call.

## Run the autonomous loop

```bash
nohup python3 scripts/bakeoff/bakeoff.py --loop --interval 1800 \
  > /tmp/bakeoff.log 2>&1 &
echo "$!" > /tmp/bakeoff.pid
```

30-min interval. Daily cap of 24 rounds (built into `bakeoff.py`).

## Inspect the loop

```bash
# Last 5 rounds: scores + gap
tail -5 state/bakeoff/rounds.jsonl | python3 -c "
import json,sys
for line in sys.stdin:
    r = json.loads(line)
    print(f\"{r['ts'][:19]}  claude={r['score_a']:>4} brainstem={r['score_b']:>4} gap={r['gap']:+5.1f} winner={r['winner']}\")"

# Current style guide
cat ~/.brainstem/state/style_guide.json | python3 -m json.tool
```

## What "winning" looks like

The student wins when `score_b - score_a >= -0.5` for several rounds running
on diverse task types. At that point the global rules list has saturated and
distillation auto-pauses (the `distill-only-when-losing` guard in `run_round`).
Drift rounds keep firing in case the reference improves.

## Re-deploying StyleCoach

If you blow away `~/.brainstem` or set up a fresh mini, the agent itself
lives in this repo at `scripts/bakeoff/brainstem_agents/style_coach_agent.py`.
Re-running `install_style_coach.sh` is idempotent.
