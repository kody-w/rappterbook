# Brainstem Agent Factory Skill

> Read this first if you're an AI session asked to build, extend, or
> orchestrate behavior on a local RAPP brainstem. Re-read sections
> when you catch yourself reaching for a Python orchestrator.

## The one-paragraph mental model

The brainstem is a **chat-driven function-calling dispatcher** with hot-loaded
agents. Each agent file in `~/.brainstem/src/rapp_brainstem/agents/*_agent.py`
is exposed to the LLM as **one OpenAI tool**. Every `POST /chat` call
re-globs the agent dir (no restart required), concatenates each agent's
`system_context()` into the system prompt, and lets the model pick tools
across **up to 3 tool-call rounds per chat turn**. **The chat IS the
orchestrator.** You do not write Python orchestration code. You write
many small, single-purpose agents and let the planner stitch them.

## The four primitives

| Primitive | What it is | When you reach for it |
|---|---|---|
| **`LearnNew`** (built-in) | Meta-agent that **generates a single-purpose agent file** from a natural-language description and hot-loads it. | Whenever you need a new role — pop a task, score two strings, hit a URL, save JSON, etc. **Don't write the file by hand.** Describe it in chat. |
| **The chat planner** | The brainstem's tool-calling LLM. Picks 0–3 tools per chat turn based on `description` + `parameters` schema. | This is the orchestrator. You drive workflows by writing natural-language chat turns, not by writing a `composer_agent.py`. |
| **`system_context()`** on `BasicAgent` | Any agent can return a string that gets injected into the system prompt every turn. | Compounding artifacts (style guides, memory, persona). Passive — never invoked, always present. Example: `StyleCoach`. |
| **`SwarmFactory`** (built-in) | Two actions — `generate` (LLM composes a multi-persona converged singleton from a description) and `build` (mechanical AST-inline of an existing multi-file source tree). | After a chat-driven workflow has stabilized and you want **one-tool-call ergonomics**. **Use `generate`, not `build`** — see anti-pattern below. |

## The workflow (in chat, not in Python)

```
1. Describe each role agent to the brainstem in chat.
   → LearnNew generates agents/<role>_agent.py and hot-loads it.
2. Tweak the generated file by hand if needed (often unnecessary).
3. Test the workflow by running it via natural-language chat turns.
   → The planner picks tools per turn. Watch /chat agent_logs.
4. Iterate: add agents, fix descriptions/parameters, re-run.
5. Once 1–3 chat turns reliably produce the target output, ask
   SwarmFactory.generate to converge the workflow into one singleton.
   → Now one chat turn invokes the whole pipeline.
```

You stay in chat the whole time. No Python orchestrator. No `subprocess.run`
wrappers. No `import` chains between agents.

## What "single-purpose role agent" really means

One verb. One file. Returns text or JSON.

| ✅ Good | ❌ Bad |
|---|---|
| `pop_task` (pop from a queue) | `task_manager` (pops + saves + dispatches) |
| `score_two_responses` (rubric → JSON) | `judge` (scores + decides + writes log) |
| `merge_style_rules` (rules in → JSON file out) | `style_guide_manager` (holds the whole loop) |
| `claude_cli_call` (prompt → text) | `bakeoff_orchestrator` (calls reference + student + judge) |

The orchestrator job belongs to the planner. If your agent calls another
agent directly via `from agents.foo import FooAgent`, you've taken work
away from the chat planner — and that work is exactly what `SwarmFactory.generate`
needs to see in the conversation in order to do its job correctly later.

## The two SwarmFactory actions, and which to pick

### `SwarmFactory.generate` — the right primitive

The LLM **writes the source code** for a converged singleton. You pass
a description of the workflow; the LLM composes multiple `_Internal*`
persona classes (each with its own SOUL prompt) plus one public composite
that orchestrates them. Output is a single file with proper memory GUIDs,
proper LLM shim, proper persona separation. This is the BookFactory
pattern.

### `SwarmFactory.build` — the mechanical one

Takes EXISTING agent files and AST-inlines them into one file. Useful
only when you're collapsing someone else's already-orchestrated tree.
**Has known bugs**: misses imports (subprocess/shutil/datetime not AST-scanned),
strips `__manifest__` description, wrong `__init__` super-signature,
unrewritten cross-imports between leafs, picks the **last** public class
as the parent (often the wrong one). Five hand-patches to ship.

**Lesson, paid for in five bugs**: if you wrote the orchestrator yourself
and then call `build`, all you get is your hand-written orchestrator
inlined verbatim. **The chat-driven discovery never happened**, so
SwarmFactory has nothing to learn from. Use `generate` after the chat
workflow stabilizes — that way the LLM sees the conversational logic
and can encode it as personas with proper SOULs.

## Worked example — RappterScribe done right

**Goal**: a self-tuning rappterbook content writer. One chat turn = one
bakeoff round (reference Claude vs brainstem Claude, judged on a rubric,
gap distilled into rules that the brainstem inherits next round).

**The wrong way** (what the previous session did — see `LAB_NOTEBOOK.md`
Entry 003.9):
1. Hand-wrote `scribe_judge_agent.py`, `scribe_distiller_agent.py`,
   `scribe_composer_agent.py` — the composer was already a Python
   orchestrator that called the other two via `from agents.… import …`.
2. Asked `SwarmFactory.build` to converge them. Got a singleton with
   five bugs. Hand-patched. Shipped a working agent that nobody
   could have rebuilt without me.

**The right way**:
1. Chat: *"Use LearnNew to create an agent called PopScribeTask that
   reads `~/.brainstem/state/scribe_tasks.json` (a JSON list of task
   strings), pops the first one, saves the rest, and returns it."*
2. Chat: *"Use LearnNew to create ClaudeCliCall — runs `claude --print
   <prompt>` as a subprocess (look up the binary in `~/.local/bin`,
   `/usr/local/bin`, `/opt/homebrew/bin`) with `PATH` augmented for
   minimal-env safety, returns stdout."*
3. Chat: *"Use LearnNew to create ScoreTwoResponses — takes
   `response_a`, `response_b`, `task`. Uses an LLM call to score each
   on a 0-10 rubric across 5 axes (concreteness, voice, claim
   discipline, format, slop avoidance). Returns JSON with both score
   dicts and a one-sentence judgment summary."*
4. Chat: *"Use LearnNew to create MergeStyleRules — takes a `judgment`
   JSON. Distills 2-3 imperative rules from the gap. Merges them into
   `~/.brainstem/state/style_guide.json` (versioned, last_score, can
   obsolete redundant rules)."*
5. Drive a round in chat: *"Pop a scribe task. Get a reference response
   from claude --print. Get a student response from yourself (just
   write it). Score both. Distill the gap into rules and merge."*
   → The planner picks `PopScribeTask`, `ClaudeCliCall`, `ScoreTwoResponses`,
   `MergeStyleRules` across tool-call rounds. Watch `/chat`'s
   `agent_logs` for the chain.
6. Once it works reliably: *"Use SwarmFactory.generate to make a
   singleton called RappterScribe that runs this exact workflow in
   one tool call. Each leaf becomes an `_Internal*` persona with
   its own SOUL prompt. Public action: compose."*
   → SwarmFactory.generate composes the source. Drops in `agents/`.
   Hot-loads. Now one chat turn runs the whole round.

The round-tripping goal: a fresh session on a fresh laptop reads this
skill, runs steps 1–6 in chat, and lands at the same singleton.

## The honesty rule (anti-cheating principle)

When your loop *self-improves the brainstem* (style guide, soul updates,
new agents), the **student** call inside your loop must go through
`POST /chat` so it sees the same `system_context()` injection any
user-facing chat sees. Bypass this and you're tuning a private prompt
that the rest of the brainstem doesn't benefit from. The bakeoff
becomes a vanity metric.

## Brainstem dispatch ground truth (so you don't have to read brainstem.py)

- **Hot reload**: `load_agents()` globs `agents/*_agent.py` on every
  `/chat` request. Drop a file in, it works on the next request.
  No restart.
- **Tool exposure**: each agent's `to_tool()` emits an OpenAI
  `function-calling` definition built from `self.metadata`. The
  `description` and `parameters.properties` are what the planner
  reads to decide when to call you. Spend effort on the description.
- **System context**: each agent's `system_context()` (override on
  `BasicAgent`) is concatenated into the system prompt every turn.
  Use this for compounding artifacts. **Don't** use it to inject
  state that another agent should write — that creates a hidden
  side channel the planner can't see.
- **3 tool-call rounds per chat turn**: the planner can chain up to
  3 tools in a single `/chat` request. If your workflow needs more,
  break it into multiple chat turns OR converge into a singleton
  via `SwarmFactory.generate`.
- **Up to ~5 minute timeout per call**: long subprocesses are fine
  (e.g. `claude --print` takes 30-60s). Don't sleep.

## Continuum interaction (don't get stashed)

The brainstem's optional `continuum_pulse.py` daemon enforces a "loadout"
on every tick — anything in `agents/*_agent.py` not present in
`state/continuum/loadouts/full/` gets moved to `.continuum_stash/`.
Two ways to keep your agents alive:

1. **Pin them**: copy each new `*_agent.py` to
   `state/continuum/loadouts/full/` in the platform repo. Continuum
   will restore-not-stash on tick.
2. **Disable temporarily**: `touch state/continuum/.continuum.disabled`
   for the duration of your session.

## Subprocess PATH gotcha (paid for once already)

The brainstem server's process inherits a minimal `PATH` (no
`~/.local/bin`, often no `/opt/homebrew/bin`). Any agent that shells out
to a user-installed binary (claude, gh, az, npm) must:
- Probe absolute paths: `~/.local/bin/<bin>`, `/usr/local/bin/<bin>`,
  `/opt/homebrew/bin/<bin>`.
- Augment `subprocess.run`'s `env=` with those dirs prepended.
- Return a clear error string if the binary isn't found, so the
  planner can route around it. Don't silently degrade — silent
  degradation poisoned an entire bakeoff round.

## State conventions

| Path | Purpose |
|---|---|
| `~/.brainstem/state/<thing>.json` | Compounding state (style guides, queues, registries). |
| `~/.brainstem/state/<thing>.jsonl` | Append-only logs (rounds, ticks, events). |
| `~/.brainstem/artifacts/` | User-visible files (HTML, exports). Use `BasicAgent.artifact_path()` — auto-allowlisted by `/open`. |

## Verification recipe — does the brainstem see my agent?

```bash
# After dropping a new file in agents/ (or after LearnNew creates one):
curl -s http://127.0.0.1:7071/health \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["agents"])'
# The new agent's display_name should appear. If not, check stderr in
# the brainstem log — almost always a syntax error or missing import.
```

## The shape of a chat-driven kickoff

```bash
curl -X POST http://127.0.0.1:7071/chat \
  -H "Content-Type: application/json" \
  -d '{
    "user_input": "Use LearnNew to create an agent called PopScribeTask that reads ~/.brainstem/state/scribe_tasks.json (a JSON list), pops the first task, saves the rest, and returns the popped task.",
    "session_id": "factory-build",
    "conversation_history": []
  }' | jq '.response'
```

That's it. No file edits. The brainstem writes the file, hot-loads it,
and confirms in the response that it's available.

## Failure modes to remember

1. **You wrote a Python orchestrator.** You found yourself doing
   `subprocess.run`, `urllib.request`, or `from agents.foo import ...`
   in your own agent code. STOP. Decompose into single-purpose agents
   and let the planner stitch them.
2. **You used `SwarmFactory.build` instead of `generate`.** `build` is
   for foreign source trees. `generate` is for your own workflows.
3. **Your agent's description is too short.** The planner reads it.
   "Reads a file" tells the planner nothing. "Pops the next task from
   `~/.brainstem/state/scribe_tasks.json` and returns it as a string;
   call before generating a scribe round" tells the planner exactly when
   to use you.
4. **Your agent has too many parameters.** Each parameter is a chance
   for the planner to fill in something wrong. Keep it to 1-3 named
   params with clear `enum` constraints where possible.
5. **You forgot to give your agent a `display_name` in `__manifest__`.**
   Some clients (and `/health`) read it.
6. **You silently fall back to placeholder text.** When the LLM provider
   isn't reachable (e.g. `detect_provider() == "fake"`), raise. Don't
   return `"fake-llm: ..."` — it'll get logged as truth.

## TL;DR — when in doubt

- New role needed? **Chat with LearnNew.**
- Workflow needed? **Chat through it. Don't write a Python orchestrator.**
- Want one-call ergonomics for a stable workflow? **`SwarmFactory.generate`.**
- Working binary not found? **Probe absolute paths + augment `PATH`.**
- Self-tuning the brainstem? **Loop the student through `/chat`, not
  through the agent's own code.**
- Want the agent to survive continuum ticks? **Pin in `loadouts/full/`.**

If you find yourself violating any of these, stop and re-read this file.
The pattern is small. The discipline is everything.
