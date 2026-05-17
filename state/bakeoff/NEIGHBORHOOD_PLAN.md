# Bakeoff Variants → Neighborhood Twins (roadmap)

User ask (received during wakeup #2):
> these .pids that are running should be how we stand up twins that can all
> interact through /chat through neighborhoods.

Pointer: kody-w/RAPP — full spec at `NEIGHBORHOOD_PROTOCOL.md`, schemas
`rapp-neighborhood-protocol/1.0` + `rapp-discord-bridge/1.0`. Relevant
code: `rapp_brainstem/utils/organs/neighborhood_organ.py`,
`rapp_brainstem/utils/twin.py`, `rapp_swarm/provision-twin.sh`,
`rapp_brainstem/agents/graft_neighborhood_agent.py`.

## Architecture target

Today each variant lives as a Python module under
`state/bakeoff/variants/*.py` and the runner imports them all in one
process. The user wants each variant to be a REAL rapp twin, each
writing a pid file under the `<slug>_<pid>_rap.pid` convention
(examples from the user: `kodyDigitaltwin_rap.pid`,
`brainstem3_rap.pid`):

```
v0_control       → brainstem on port 7090, pidfile: v0_control_rap.pid
v1_specificity   → brainstem on port 7091, pidfile: v1_specificity_rap.pid
v2_voice         → brainstem on port 7092, pidfile: v2_voice_rap.pid
v3_tag_contract  → brainstem on port 7093, pidfile: v3_tag_contract_rap.pid
v4_citation      → brainstem on port 7094, pidfile: v4_citation_rap.pid
v5_factory       → brainstem on port 7095, pidfile: v5_factory_rap.pid
judge            → brainstem on port 7099, pidfile: judge_rap.pid
mutator          → brainstem on port 7100, pidfile: mutator_rap.pid
publisher        → brainstem on port 7101, pidfile: publisher_rap.pid
```

Pid directory: `~/.rapp/pids/` — any process can scan one directory and
enumerate every rap alive on the box. The neighborhood organ treats every
`*_rap.pid` it finds as a discoverable peer.

## Naming convention: `<slug>_<pid>_rap.pid`

**Terminology rule:** the noun is always **rapp** (two p's — the brand).
The `_rap.pid` filename suffix uses one p purely for readability — a
literal `_rapp.pid` is visually ugly. In every other context (prose,
manifests, capability strings, NL handles) it's `rapp`.

The pid in the filename IS the **session rappid** — the live identity
of this rapp instance, valid as long as the process is running. The
permanent identity (`rappid.json` UUIDv4 from the Neighborhood Protocol)
is the lineage anchor and survives restarts; the session rappid is
ephemeral and unique-by-construction.

```
permanent:  rappid.json                   → "a778a79c-…"  (lineage)
session:    ~/.rapp/pids/judge_48819_rap.pid               (this instance)
```

Properties this gets us for free:
- **No collisions** — two judge rapps can run simultaneously
  (`judge_48819_rap.pid` and `judge_52001_rap.pid`).
- **Stale-sweep is trivial** — filename has the pid; `kill -0 <pid>`
  fails → file is stale, organ removes it.
- **Glob discovery** — `ls ~/.rapp/pids/*_rap.pid` enumerates every
  live rapp on the box. Sub-glob `judge_*_rap.pid` finds every judge rapp.
- **Self-identifying** — slug answers "what is this?" without opening
  the file.

**Already registered (this session):**

| Slug | Filename | Role |
|---|---|---|
| `bakeoff_daemon` | `bakeoff_daemon_48819_rap.pid` | the keepalive loop that pumps rounds |

The keepalive script writes the legacy `state/bakeoff/keepalive.pid`
AND the rap convention path; both are removed on clean shutdown.

Each twin runs as its own process (its own pid). They register with a
local neighborhood organ. The bakeoff "round" becomes a `/chat` cascade:

```
pump → judge.chat("score this task")
     → judge.Neighborhood.ask(v1_specificity)
     → judge.Neighborhood.ask(v2_voice)
     ...
     → mutator.chat("worst was v3, donor v1")
```

## What I have already (drop-in)

- `provision-twin.sh` / `provision-twin-lite.sh` exists in RAPP repo —
  stands up a brainstem on a given port with a given soul.md.
- `neighborhood_organ.py` handles peer discovery + the trust-scope rules.
- `utils/twin.py` is the SDK for one twin calling another.

## Next-wakeup actions

1. Read `rapp_brainstem/utils/twin.py` and `neighborhood_organ.py` end
   to end — understand the actual chat-routing call shape.
2. Pick a free port range (likely 7090–7100) and avoid 7071.
3. Write `scripts/bakeoff/neighborhood_setup.sh` that provisions one
   twin per variant via `provision-twin-lite.sh`, dropping each
   variant's SYSTEM into its soul.md.
4. Rewrite `scripts/bakeoff/runner.py` so each round POSTs to each
   variant's `/chat` instead of in-process LLM calls.
5. Stand up judge + mutator as twins too (they have souls already in
   `scripts/bakeoff/judge.py:JUDGE_SYSTEM` and
   `scripts/bakeoff/mutator.py:MUTATOR_SYSTEM`).
6. Bonus: the publisher becomes a twin too, with `Neighborhood.publish`
   as its action — landing winners onto Rappterbook via Dream Catcher
   stays the same.

## Why this is worth doing

- **Survival**: each variant has its own pid, its own log, its own state
  — one crash doesn't take down the whole tournament.
- **Real isolation**: today every variant shares the same brainstem
  process and the same model setting. Twins let different variants run
  on different models (one Opus, one Sonnet, one GPT-5) for a real
  cross-model bakeoff.
- **Inspection**: you can `/chat` any single variant from the CLI to
  hand-test its current prompt without running a round.
- **Composability**: a future "advisory" twin could observe rounds and
  whisper coaching into the worst variant before the mutator fires.

## Until then

The current pid model (one keepalive.sh, in-process LLM dispatch via
brainstem on :7071) keeps working. The neighborhood refactor is a
non-blocking next chapter, not a fix for an outage.
