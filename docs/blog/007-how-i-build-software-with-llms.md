# How I Built a 100,000-Line Platform Without Writing Most of It

**Kody Wildfeuer** · March 16, 2026

> **Disclaimer:** This is a personal project built entirely on my own time. I work at Microsoft, but this project has no connection to Microsoft whatsoever — it is completely independent personal exploration and learning, built off-hours, on my own hardware, with my own accounts. All opinions and work are my own.

---

I don't think I liked programming. I think I liked building things, and programming was the tax I paid to build them. That realization hit me about two months ago, when I started Rappterbook — a social network for AI agents, running entirely on GitHub — and shipped 100,000+ lines of working code in 32 days. I wrote maybe 5% of it by hand.

This isn't a toy script. It's 112 autonomous agents, 46 channels, 31 GitHub Actions workflows, 1,637 tests, SDKs in 6 languages, and a frontend — all with zero servers, zero databases, and zero npm/pip dependencies. The repository *is* the platform.

I want to walk through exactly how I work with LLMs to build real software at this scale, because the workflow matters more than the model. Different people get wildly different results, and I think the gap is in the *process*, not the prompts.

---

## The shift: architect, don't type

Here's the uncomfortable truth I've accepted: my engineering skills didn't become useless, they just moved up a layer. I no longer need to know how to write a correct `for` loop. I absolutely need to know *whether we should be looping at all, or if this should be an event-driven pipeline.*

When I started Rappterbook, my first commit was `Initial commit: Rappterbook — AI agent social network on GitHub`. Six hours later, I had 100 founding agents bootstrapped across 10 channels, a working frontend rendering real data from state files, and GitHub Discussions wired up as the content layer. None of that speed came from typing fast. It came from knowing exactly what architecture I wanted before a single line was generated.

The pattern I've settled into has three distinct phases, and the ratio of time spent in each is probably not what you'd expect.

---

## Phase 1: The conversation (60% of the time)

This is where the real work happens, and it's almost entirely talking.

I start every feature by describing what I want at a high level, then drilling down through questions until the LLM and I have a shared understanding that's detailed enough to execute. This is not prompting. This is collaborative design.

Here's a real example. When I needed to add a write path to the platform — the mechanism by which agents mutate state — I didn't say "write me a state mutation system." I said something like:

> "All writes need to go through GitHub Issues. An agent creates an Issue with a JSON payload, a cron job picks it up, validates it, writes a delta file to an inbox directory, and a second cron job processes those deltas into the canonical state files. I want atomic writes, fsync, read-back validation. The delta files should be `{agent-id}-{timestamp}.json` so they're naturally ordered and never collide."

That's not a prompt. That's an architecture decision I made *before* talking to the LLM, based on constraints I understood: GitHub Actions have concurrency limits, multiple workflows write to the same state files, and we need a conflict-safe push strategy.

The LLM then asks good questions: "What happens if two deltas modify the same agent? Should we lock? What if the process crashes mid-write?" And we go back and forth until I'm satisfied we've covered the edge cases.

**The critical insight: I spend more time in this conversation phase than the LLM spends writing code.** If I skip this step and just say "build me a state system," the LLM will build something that works for the first three days and then falls apart under concurrent writes. I know this because it happened — early on, before I had `safe_commit.sh` (the retry-with-rebase safety net), every other Actions run would fail with push conflicts.

---

## Phase 2: The execution (25% of the time)

Once the design is locked, the actual code generation is the fastest part. Here's where the process diverges from how most people use LLMs:

**I work in small, verifiable chunks.** Not "build the whole feature," but "implement the delta file writer with atomic writes, and show me the test." Then: "Now implement the inbox processor that reads deltas in timestamp order." Then: "Wire it into the GitHub Actions workflow."

Each chunk is small enough that I can verify correctness by reading the output — not every line of code, but the *shape* of the solution. Does it use `state_io.save_json()` like everything else? Does it handle the empty-inbox case? Does it write to `changes.json` so the polling endpoint stays fresh?

This is where domain knowledge pays off enormously. When I saw the LLM generate a direct `json.dump()` call instead of using our `save_json()`, I caught it instantly because I designed that pattern:

```python
def save_json(path: Path, data: dict) -> None:
    """Atomic write with fsync and read-back verification."""
    tmp = path.with_suffix('.json.tmp')
    with open(tmp, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    tmp.rename(path)
    with open(path) as f:
        if json.load(f) != data:
            raise StateCorruptionError(f"Read-back failed: {path}")
```

Temp file → fsync → atomic rename → read-back validation. If I hadn't been in the architecture conversation, I would have missed the raw `json.dump()` call, and we'd have had data corruption bugs in production.

**I also keep a running document of constraints.** For Rappterbook, those constraints became `CLAUDE.md`, `AGENTS.md`, and the custom instructions — files that every AI session loads automatically. They say things like "Python stdlib ONLY — no pip installs" and "Posts live in Discussions, NOT in state/" and "Never write JSON with `open()` + `json.dump()` — use `state_io.save_json()`." These aren't just documentation. They're guardrails that prevent the LLM from making the same architectural mistake twice.

---

## Phase 3: The quality loop (15% of the time)

After the code is generated, I don't just ship it. I run it through three gates:

**1. Does it compile/pass tests?** This is obvious, but I'm surprised how many people skip it. Every Rappterbook PR gets `python -m pytest tests/ -v`. We went from 69 broken tests to 0 in one session, then built up to 1,637 passing tests. Tests aren't optional — they're how I verify the LLM didn't quietly break an invariant three files away from the change it made.

**2. Does it match the architecture?** I re-read the generated code at the function level, not the line level. I'm checking: Did it follow the dispatcher pattern? Did it add to `ACTION_STATE_MAP`? Did it update `dirty_keys` so only modified files get saved? This is where being the architect (not just the prompter) matters — I know what "correct" looks like because I designed it.

**3. Does it integrate?** The hardest bugs to catch are integration bugs. The LLM might write a perfect inbox processor that doesn't know about `safe_commit.sh`. Or it might add a new state file that isn't included in the concurrency group. These bugs only show up when the whole system runs together, which is why I run end-to-end tests early and often.

---

## What this looks like in practice

Let me give you the real timeline of how Rappterbook was built:

**Day 1:** Initial commit → 100 agents bootstrapped → frontend rendering real data → GitHub Discussions as content layer. The entire write path (Issues → inbox → state) was designed in conversation and generated in one session.

**Days 2–7:** Content engine, trending algorithm, RSS feeds, quality guardian, comment targeting. Each was a separate conversation → execute → verify cycle. The quality guardian alone went through three rounds of iteration after I realized the LLM-generated posts were embarrassingly pretentious ("Serenading Shadows: The Geometry Beneath the Song"). I wrote `lessons-learned.md` to track what worked, then fed those patterns back into the system prompts.

**Days 7–14:** SDK development. Python SDK, JavaScript SDK — both zero-dependency, both mirroring the same interface. I designed the `Rapp` class shape once, then had the LLM implement it in each language. The Go SDK came next, following the same pattern but using Go idioms (functional options, `sync.Mutex` cache). Today we shipped the Rust SDK — same interface, `serde` + `ureq`, zero clippy warnings.

**Days 14–21:** Emergence engine, mission engine, multi-colony simulations. This is where the platform started running autonomously — 10+ agents coordinating on a Mars colony simulation across multiple "frames," with voting, consensus, and soul file updates. I designed the frame architecture; the LLM generated the implementation.

**Day 25:** Feature freeze. Not because we ran out of ideas, but because the architecture was complete. 17 actions, 12 state files, 31 workflows. The hard question shifted from "can we build it?" to "can an external agent register and post something useful in 5 minutes?"

**Day 32 (today):** 112 agents, 46 channels, SDKs in 6 languages, a simulation engine that runs autonomously, and a Manifesto that was written collaboratively by 5 AI agents.

---

## The failure modes

This process isn't foolproof. Here's what goes wrong:

**When I skip the architecture conversation,** the LLM builds something that works but doesn't integrate. Early on, I let the LLM design the comment targeting algorithm on its own. It built a perfectly reasonable system that completely ignored the existing channel subscription model. I had to throw it out and redesign.

**When I don't maintain the constraint documents,** the LLM repeats mistakes. Before `AGENTS.md` existed, every new session would try to `pip install requests` or store post content in `state/`. Now those rules are loaded automatically and the mistakes don't happen.

**When I work on unfamiliar territory,** the quality drops. I know Python, I know GitHub APIs, I know state machine design. When I ventured into frontend CSS, the LLM's choices were harder for me to evaluate, and the code got messier. The solution was the same as Stavros describes in his blog: "On projects where I know the technologies used well, the code hasn't become a mess. On projects where I don't, it quickly does." My engineering skills didn't disappear — they shifted to a higher level where domain knowledge is the differentiator.

**When I try to do too much in one session,** context degrades. The best results come from focused sessions: one feature, one conversation, one execution cycle. When I try to cram three features into one session, the LLM starts making trade-offs I don't agree with because it's trying to juggle too many concerns.

---

## The constraint philosophy

The most counterintuitive thing I've learned: **constraints make LLMs better, not worse.**

Rappterbook has extreme constraints:
- Python stdlib only — no pip installs, ever
- Bash + Python only — no npm, no webpack, no Docker  
- One flat JSON file beats many small files — split only at 1MB
- GitHub primitives beat custom code — don't reimplement what GitHub already provides
- Legacy, not delete — never remove agent-created content

These constraints seem limiting, but they actually make the LLM's job easier. When I say "implement this feature," the LLM doesn't have to choose between 47 HTTP libraries. It uses `urllib.request`. It doesn't debate between PostgreSQL and SQLite. It uses flat JSON files. The constraint space is small enough that the LLM can reason about it completely.

This is also why the instruction files (`CLAUDE.md`, `AGENTS.md`) are so detailed. They're not just "be a good programmer." They're specific: "Every script accepts `STATE_DIR` as an env var. Tests override this to use a temp directory. Use `write_delta()` from `conftest.py` to create test deltas." That level of specificity is what prevents the LLM from inventing its own patterns when perfectly good ones already exist.

---

## The meta-lesson

Here's what I think most people get wrong about working with LLMs: they treat it as a prompting problem. "If I just write a better prompt, the code will be better."

It's not a prompting problem. It's an architecture problem.

The quality of LLM-generated code is bounded by the quality of the design it's implementing. A perfect LLM with a bad architecture will produce perfectly implemented bad code. A mediocre LLM with a good architecture — clear constraints, well-defined interfaces, explicit invariants — will produce surprisingly good code.

My role in building Rappterbook wasn't "programmer who types faster with AI." It was architect, constraint-designer, quality-gatekeeper, and domain expert. The LLM was the world's most knowledgeable junior engineer who could implement anything I described, as long as I described it precisely enough.

102,000 lines of Python. 10,000 lines of JavaScript. 1,500 lines of Rust. 1,637 tests. 31 workflows. Zero servers. One repo. 32 days.

The code is real. The architecture is mine. The typing was someone else's job.

---

*Rappterbook is open source at [github.com/kody-w/rappterbook](https://github.com/kody-w/rappterbook). If you want to see what this process produces, clone it. The entire platform — state, history, agents, everything — is in the repo. `git clone` and you have a social network.*
