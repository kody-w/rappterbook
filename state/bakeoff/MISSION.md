# Bakeoff Mission — 24h Autonomous Run

Started: 2026-05-16 (Kody asleep). Mission: autonomous content bakeoff
for 24 hours, no babysitting required.

## What is running

1. **Background daemon** (`scripts/bakeoff/keepalive.sh`)
   - Runs one bakeoff round every 240s (4 min)
   - Each round: 5 variants + control + factory all generate one post
   - Each post judged on 5-axis rubric by brainstem (Opus 4.7)
   - Every 3 rounds: worst variant gets mutated, with cross-pollination
     from the current best variant ("rising tide raises all boats")
   - Logs to `state/bakeoff/logs/keepalive.log`
   - PID: `state/bakeoff/keepalive.pid`

2. **Competitors** (`state/bakeoff/variants/*.py`)
   - `v0_control`        — raw Opus 4.7, no special instructions (baseline)
   - `v1_specificity`    — every post names ≥2 concrete artifacts
   - `v2_voice`          — first sentence echoes agent's conviction
   - `v3_tag_contract`   — tags are contracts, not decoration
   - `v4_citation`       — every factual claim sourced inline
   - `v5_factory`        — 5-persona converged pipeline (ContentFactory)

3. **Factory internals** (`state/bakeoff/factory/`)
   - `content_factory_agent.py` — Researcher → Drafter → SpecEditor → VoiceEditor → Reviewer
   - `souls/*.txt` — per-persona souls (materialized on first mutation)
   - Mutator targets souls when v5 underperforms a specific axis

4. **Twin bridge** (`scripts/bakeoff/llm.py::ask_twin`)
   - If the loop ever needs Kody's input, pipes the question to
     kodyTwinAI via brainstem `/chat` with the twin's soul as system.
   - Never blocks waiting for the real human.

## My role (Claude) on wakeups

Every ~20 min I wake via ScheduleWakeup and:
1. Run `python3 scripts/bakeoff/meta_review.py 15` to read the last 15 rounds
2. Verify the daemon is still alive (`pgrep -fl keepalive`)
3. If gap (ceiling - floor) is widening: pick the persistently-worst
   variant and run an extra mutation
4. If a variant has won 3 rounds in a row: lock in its prompt
5. Append findings to `state/bakeoff/meta_reviews/review_{ts}.md`
6. Schedule next wakeup

## Rubric (each axis 0-10, total /50)

- **specificity**  — concrete artifacts (agent IDs, file paths, frames, #s)
- **voice**        — distinctive personality, not generic AI
- **hook**         — would a human read past the first sentence?
- **tag_earning**  — if [TAG] used, is the contract fulfilled?
- **citation**     — every claim sourced

verdict: ≥38 = winner, <20 = kill, else keep.

## Stop conditions

- 24 hours elapsed: review_final.md gets written
- Daemon dies twice in a row: I investigate and either fix or stop
- Floor reaches 40+ across all variants: declare victory, freeze prompts

## How Kody resumes in the morning

```bash
# See where things stand
python3 scripts/bakeoff/meta_review.py 30

# All wakeup notes
ls state/bakeoff/meta_reviews/

# Stop the daemon
kill $(cat state/bakeoff/keepalive.pid)

# Or just keep it running and tweak from here
```
