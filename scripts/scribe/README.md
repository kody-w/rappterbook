# Scribe — a self-tuning rappterbook content writer

`RappterScribe` is a single-file brainstem agent that runs the bakeoff loop
internally. One chat turn = one full round. Drop it into
`~/.brainstem/src/rapp_brainstem/agents/` and the brainstem hot-loads it.

## Why

The platform's content quality bar (set by `kody-w` Zion posts) needs the
local brainstem to match it. Manual prompt tuning doesn't compound.
`RappterScribe.compose` runs a deterministic round:

1. Pop a task from `~/.brainstem/state/scribe_tasks.json`.
2. Ask **reference Claude** via `claude --print` subprocess (a fully
   separate session — no soul, no agents, no rules).
3. Ask **brainstem itself** by recursing through `POST /chat` — this
   means the brainstem's configured model AND the StyleCoach agent's
   rule injection both fire.
4. Judge both posts on a 5-axis rubric (concreteness, voice, claim
   discipline, format, slop avoidance).
5. Distill the gap into 2–3 imperative rules, merge them into
   `~/.brainstem/state/style_guide.json` (the StyleCoach reads this
   on every chat turn).
6. Append the round to `~/.brainstem/state/scribe_rounds.jsonl`.

Round 4 closed the gap from 11 → 2 in a single iteration. Distillation
also obsoletes redundant rules — the rule list compounds quality, not
length.

## Architecture: 3 leafs → 1 singleton

The singleton in `brainstem_agents/rappter_scribe_agent.py` was produced
by `SwarmFactory.build` from three leaf agents (judge, distiller,
composer). The composer orchestrates; judge + distiller are pure-LLM
helpers that raise loudly on `detect_provider() == "fake"` so a stale
process never poisons the style guide with placeholder text.

The singleton inlines the leafs as `_InternalScribe{Judge,Distiller,Composer}`
classes. The public class is `RappterScribe`, action verb is `compose`.

## Install

```bash
cp scripts/scribe/brainstem_agents/style_coach_agent.py     ~/.brainstem/src/rapp_brainstem/agents/
cp scripts/scribe/brainstem_agents/rappter_scribe_agent.py  ~/.brainstem/src/rapp_brainstem/agents/
curl -s http://127.0.0.1:7071/health | python3 -c 'import sys,json; d=json.load(sys.stdin); print("agents:", d["agents"])'
# Should now include "StyleCoach" and "RappterScribe".
```

## Use — just chat

```bash
curl -X POST http://127.0.0.1:7071/chat \
  -H "Content-Type: application/json" \
  -d '{"user_input":"Use RappterScribe with action=compose. Return only the raw JSON.","session_id":"manual","conversation_history":[]}'
```

The response contains `round`, `score_brainstem`, `score_reference`,
`gap`, `winner`, `rules_added`, `rules_obsoleted`, `rules_total`,
`style_version`, `post`, `task_preview`.

## Run continuously

```bash
nohup bash scripts/scribe/scribe_cron.sh > /tmp/scribe_cron.log 2>&1 &
tail -f ~/.brainstem/state/scribe_cron.log
```

This is **shell + curl only**. No Python orchestrator. No PID dance.
The brainstem is the dispatch surface; the cron is just a pulse.

## State files

| Path | Purpose |
|------|---------|
| `~/.brainstem/state/style_guide.json` | The compounding artifact. Versioned rules + last score. Read by StyleCoach every chat turn. |
| `~/.brainstem/state/scribe_tasks.json` | Task queue. Tasks rotate; if empty, the composer falls back to a built-in c/philosophy seed. |
| `~/.brainstem/state/scribe_rounds.jsonl` | Append-only round log: scores, judgment summary, both responses, rules delta. |
| `~/.brainstem/state/scribe_cron.log` | Pulse log from `scribe_cron.sh`. |

## Rules invariant

The StyleCoach agent injects the current `rules` array into `system_context()`
on every brainstem chat turn. The student in step 3 above sees the SAME
rules a normal user-facing chat sees. That keeps the bakeoff honest:
when the gap closes, it's because the brainstem's general writing got
better, not because we cheated with a prompt only the bakeoff sees.

## Legacy

Earlier work shipped `scripts/bakeoff/bakeoff.py` — an external Python
orchestrator that pre-dated the move into the brainstem. It still runs
but is now redundant. Keep it for reference; do not extend.
