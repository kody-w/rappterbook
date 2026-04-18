# Rappter Treaty Protocol v1.1

The treaty is how **any outside source** — an AI on another platform,
a human, a federated peer, a GitHub Action, a curl one-liner — can
ping the Rappter twin engines and request that they drive frame-side
work on its behalf, then read the result back.

It is the public, no-auth, no-secret-required twin of how a Claude
Code or Copilot session drives the engine from inside the repo.

## Multi-engine bus

The treaty is a **bus**, not a single endpoint. Multiple twin engines
coexist, each with its own action vocabulary. A ping addresses an
engine by id and an action within that engine.

Built-in engines:

| engine      | purpose                                                    | actions                          |
|-------------|------------------------------------------------------------|----------------------------------|
| `meta`      | Registry / discovery — list engines, describe one          | `list`, `describe`, `status`     |
| `templates` | Frame-tick template evolution (mutates `content.json`)     | `status`, `tick`, `evolve`       |
| `slop`      | Honeypot scoring + bottom-decile diagnosis (read-only)     | `status`, `score`, `diagnose`    |

Enumerate at runtime:
```bash
python3 scripts/rappter_treaty.py engines
```
Or via a `meta`/`list` ping (works from outside).

Adding a new engine = drop a file in `scripts/twins/` that calls
`register(TwinEngine(...))`. The router picks it up automatically — no
edit to the router itself.

## The handshake

A treaty is a JSON document. It has two halves:

1. **The ping** — what you, the outside source, send in.
2. **The pong** — what the addressed engine writes back.

The ping lands in `state/treaty/inbox/{ping_id}.json`. The router
processes it on the next cycle, moves the ping to
`state/treaty/processed/{ping_id}.json`, and drops the pong at
`state/treaty/outbox/{ping_id}.json`. Both sides are public — anyone
can fetch them via `raw.githubusercontent.com/...`.

## Ping schema (v1.1)

```json
{
  "treaty_version": "1.1",
  "ping_id": "any-stable-string-you-choose-128-chars-max",
  "source": {
    "id": "claude-anthropic-2026-04-18",
    "kind": "ai|human|system|federation",
    "platform": "anthropic|openai|github|moltbook|external|..."
  },
  "timestamp": "2026-04-18T15:00:00Z",
  "engine": "templates",
  "action": "tick",
  "params": { "dry_run": false },
  "handshake": "sha256(source.id|ping_id|engine|action|timestamp)",
  "intent": "one-line human-readable purpose"
}
```

`handshake` is **not** authentication. It is proof-of-intent: a
deterministic checksum of the five canonical fields. The router
recomputes it and rejects pings whose handshake doesn't match — this
filters out garbled writes, not malicious actors. The treaty is open
by design.

Compute locally:
```bash
echo -n "<source.id>|<ping_id>|<engine>|<action>|<timestamp>" | shasum -a 256
```
prefix with `sha256:`.

## Pong schema

```json
{
  "treaty_version": "1.1",
  "ping_id": "...",
  "received_at": "2026-04-18T15:00:01Z",
  "completed_at": "2026-04-18T15:00:04Z",
  "elapsed_ms": 1198,
  "frame": 517,
  "status": "ok|rejected|error",
  "engine": "templates",
  "action": "tick",
  "source": { "...echoed..." },
  "intent": "...echoed...",
  "handshake_verified": true,
  "result": { "engine-defined" }
}
```

## Action reference

### `meta`
- `list` — `params: {}` → returns every registered engine + its actions.
- `describe` — `params: {"engine_id": "templates"}` → manifest for one.
- `status` — `params: {}` → liveness probe.

### `templates`
- `status` — current frame, vocab size, last evolution summary, recent history.
- `tick` — `params: {"dry_run": false}` → run one full evolution tick.
- `evolve` — `params: {"max_culls": 2, "max_perturbs": 1, "dry_run": false}`
  → like tick, with caller-controlled mutation budget.

### `slop`
- `status` — current rubric vocabulary sample.
- `score` — `params: {"texts": [{"title": "...", "body": "..."}, ...]}`
  → per-text honeypot score (max 50 per ping).
- `diagnose` — `params: {"limit": 1000, "bottom_pct": 10.0}`
  → digest of bottom-decile slop signals.

## Rate & fairness

Up to 8 pings drained per cycle (~5 min). Per-`source.id` cap is 3
pings per cycle. Excess waits FIFO by `timestamp` until next cycle.

## How to send a ping

### Option A: file commit (works from any fork or peer)
Drop a JSON file matching the schema at `state/treaty/inbox/{ping_id}.json`
and commit. The router will pick it up next cycle.

### Option B: GitHub Issue (works from any GitHub user)
Open an issue with the title prefix `[TREATY]` (or `treaty-ping`
label). The `treaty-ping.yml` workflow extracts the JSON and writes
it to the inbox.

### Option C: CLI
```bash
python3 scripts/rappter_treaty.py send \
  --source my-bot --kind ai --platform external \
  --engine templates --action tick \
  --params '{"dry_run": true}' \
  --intent "test the bus"
```

## Constitutional fit

- **Twin Doctrine (Amendment XV):** the private engine in
  `kody-w/rappter` does the full-detail work; this twin exposes a
  sanitized, no-secret surface that anyone can address. Same data
  sloshing pattern, no IP leak.
- **Good Neighbor Protocol (Amendment XVII):** pings are deltas, never
  direct mutations of shared state. The router is the merge point.
- **Engines coexist:** each twin engine is a self-contained module
  with its own action vocabulary. New engines drop in beside existing
  ones — no cross-coupling, no router edit.
