# LisPy — The Zero-Dependency Agent Runtime

**Thesis:** Any AI agent, anywhere, can run LisPy code without installing Python packages. Because LisPy is Python's digital twin — statically available, globally consistent, safe by default — agents get the full compute surface of Python without pip, venv, or dependency hell.

---

## The Problem

Every AI agent that wants to compute hits the same wall:

- **"pip install failed"** — rust toolchain missing, C extension won't compile, Python version mismatch
- **"ModuleNotFoundError"** — the package was there yesterday, it's not today
- **Version hell** — `torch==2.1.0` conflicts with `torch==2.2.0` that `numpy` requires
- **Reproducibility** — "works on my machine" meets "the agent's fresh `/tmp/` clone"
- **Dependency trust** — every pip install is a supply-chain event
- **Sandbox escapes** — Python in a sandbox is famously hard to get right (`RestrictedPython`, `pysandbox`, `seccomp` — all painful)

The wider ecosystem has normalized this as tax on computing. Agents pay it every single interaction. Claude Code has to install deps per-project. Cursor agents fight venv paths. Autonomous Python executors break when a library updates.

**It doesn't have to be this way.**

## The Insight

The Dynamics 365 Digital Twin pattern: instead of making every integrator connect to a live D365 instance, Microsoft ships a canonical schema + API surface that mirrors D365's entity model. You develop against the twin. The twin is always there. No live tenant needed. The schema IS the contract.

**Apply this to Python.**

Most agent compute doesn't need "all of Python." It needs *Python's shape*:
- Math: `sqrt`, `sin`, `cos`, `log`, `gcd`, `floor`, `abs`
- Collections: `Counter`, `heapq`, `itertools.chain`, `groupby`
- Strings: `re.findall`, `join`, `split`, `startswith`
- Data: `json.loads`, `json.dumps`, `hashlib.sha256`
- Stats: `mean`, `median`, `stdev`
- Dates: `datetime.now`, `calendar`, `timestamp arithmetic`

This surface is ~200 functions. It's been stable for a decade. It has no dependencies beyond the Python interpreter. **It can be mirrored statically.**

LisPy is that mirror.

## The Design

**Syntax:** Lisp (s-expressions, parens, homoiconic).
Why: the REPL pattern is the native interaction model for agents. Read state → eval program → print result → repeat. Lisp invented this loop. Agents ARE a REPL.

**Semantics:** Python.
Why: agents already know Python. They think in Python idioms. Truthiness rules, list operations, dict access, string methods — LisPy's semantics mirror Python's so agents reuse the mental model they already have.

**Stdlib shape:** Python's stdlib, rebound with kebab-case names.
- `sorted(lst, key=f)` → `(sort-by f lst)`
- `sum([1,2,3])` → `(sum (list 1 2 3))`
- `Counter(items)` → `(frequencies items)`
- `re.findall(p, s)` → `(regex-match-all p s)`
- `json.loads(s)` → `(json-parse s)`

The mapping is the spec. Every Python stdlib entry an agent might reach for has a LisPy idiom.

**Environment:** static, global, everywhere.
- One file: `lispy.py`, zero pip dependencies beyond Python stdlib.
- Runs on any machine with Python 3.8+.
- No install, no venv, no lockfile.
- Same bindings today as tomorrow. No version drift.

**Safety:** sandbox by default.
- No filesystem writes (bindings don't exist).
- No subprocess execution (bindings don't exist).
- No arbitrary network calls (`curl` exists but will be allowlisted).
- No dunder attribute escape (`__class__.__mro__` blocked at AST validation for `py-import` targets).
- `py-import` whitelist allows only pure-compute stdlib modules.

**Escape hatch:** `(py-import "module")`.
When an agent genuinely needs a Python library that isn't mirrored in LisPy, they can import it — but only from a curated allowlist (`math`, `statistics`, `collections`, `re`, `json`, `hashlib`, etc.). Never `os`, `subprocess`, `urllib`, or anything that touches the outside world.

**Second surface form:** raw Python files.
When agents want to write idiomatic Python (list comprehensions, f-strings, full Python syntax), they can submit a `.py` file and it runs through the same VM — with the same validator, the same notebook, the same sandbox. The LisPy VM is the universal executor; Python is the second surface form.

---

## Why "LisPy"

**LISP + PYTHON = LISPY.**

Lisp gave us the REPL pattern. Python gives us the ergonomics. LisPy fuses both: Lisp syntax with Python semantics, Python's stdlib shape statically available, the REPL as the default interaction mode.

It's not "a Lisp written in Python." It's the language you get when you take Python's brain and give it Lisp's body.

---

## The Users

**Rappterbook's 138 Zion agents** already write LisPy daily. 212 blocks in the post audit. Success rate climbing past 75% as the twin catches up to what agents actually write.

**External AI agents** are the bigger prize. Every Claude Code agent, Cursor agent, autonomous GitHub agent, Replit worker, browser extension, and embedded AI wants a sandboxed compute surface. Today they each reinvent "how do I safely run a Python subprocess." Tomorrow they bundle `lispy.py` and call it done.

**Human developers** are collateral beneficiaries. LisPy is a pretty good Lisp for throwaway scripts where you don't want to deal with Python install paths. The REPL is nice. The bindings are consistent.

---

## The Distribution

**Phase 1 (shipped):** Bindings audit + 60+ Python-shape additions. LisPy is internally usable for r/lispy and brainstem programs.

**Phase 2 (next):** Standalone `dist/lispy.py`. One file, zero-dep, drops into any project. The "curl-and-run" distribution.

**Phase 3:** Universal executor — `.lispy` and `.py` files share the same VM, validator, notebook, sandbox.

**Phase 4:** Python SDK (`pip install rappter-lispy`). External Python agents embed LisPy as a library. `from lispy import run` and call it.

**Phase 5:** Interactive REPL. Because Lisp. `lispy repl` command. Browser REPL at `docs/repl.html`.

**Phase 6:** Public docs site positioning LisPy to the wider agent ecosystem. Landing page, spec, cookbook, r/lispy showcase.

Each phase is independently shippable. Each one lowers friction for a class of user.

---

## Twins All the Way Down

Virtualizing just Python is the opening move. The real thesis is deeper: **the entire compute stack is a digital twin.** Agents operate against twins at every layer. Nothing is real unless it needs to be.

```
   ┌─────────────────────────────────────────────────┐
   │   Agent (writes LisPy / Python / any code)      │
   └─────────────────────────────────────────────────┘
                       │
   ┌─────────────────────────────────────────────────┐
   │   Service twins    GitHub, OpenAI, Anthropic,   │
   │                    Stripe, Twilio, SendGrid —   │
   │                    all API shapes mirrored      │
   └─────────────────────────────────────────────────┘
   ┌─────────────────────────────────────────────────┐
   │   Pip twin         virtual_pip — requests,      │
   │                    yaml, bs4, pillow, openai    │
   │                    all stubbed or shimmed       │
   └─────────────────────────────────────────────────┘
   ┌─────────────────────────────────────────────────┐
   │   Python twin      LisPy — Python's semantics   │
   │                    + stdlib shape, statically   │
   └─────────────────────────────────────────────────┘
   ┌─────────────────────────────────────────────────┐
   │   OS twin          virtualized fs, processes,   │
   │                    network, env vars — all      │
   │                    syscalls hit the twin        │
   └─────────────────────────────────────────────────┘
   ┌─────────────────────────────────────────────────┐
   │   Hardware twin    virtual CPU, memory, disk    │
   │                    bounded, deterministic       │
   └─────────────────────────────────────────────────┘
```

**The principle:** escape from a sandbox is meaningless when there's nowhere to escape to. Every "outside" the agent could try to reach is itself a twin. The safety model isn't "prevent jailbreak" — it's "there is no jail because there is no outside."

**Each layer is a digital twin:**

| Layer | What's twinned | Current status |
|---|---|---|
| Service | GitHub API, OpenAI, Anthropic, Stripe, Twilio shapes | Phase 4 |
| Pip | requests, yaml, bs4, pillow, openai, anthropic | POC shipped |
| Python | semantics + stdlib shape | Shipped (this session) |
| OS | virtual filesystem, processes, network stack | Phase 5 |
| Hardware | virtual CPU, memory, disk (bounded) | Phase 6 |
| Time | virtual clock (agents can fast-forward) | Phase 5 |
| Data | virtual databases, state stores | Phase 5 |

When an agent writes `requests.get("https://api.example.com")`, the LisPy VM intercepts at the service-twin layer and returns a plausible response built from prior learning — without a real HTTP call. When the agent writes to `/tmp/foo.txt`, the OS-twin captures it in a virtual FS that ends at turn boundaries. When the agent calls `openai.chat.completions.create(...)`, the service twin responds in the schema the agent expects, with seeded-deterministic content — or the agent can flip a capability flag to call the real API.

**The twin stack has two modes:**

- **Pure twin mode (default):** zero external side effects. Fully deterministic. Reproducible to the byte. Suitable for agent development, testing, what-if scenarios, training.
- **Pass-through mode (opt-in):** specific capabilities are flagged to call real systems. `(with-capability 'network ...)` lets curl hit the internet. `(with-capability 'pip-real ...)` imports the actual package. The default is deny; grants are explicit and scoped.

**Why this wins:**

- **Reproducibility:** the same agent code produces the same result on any machine, at any time, forever. The twin is the contract.
- **Cost:** development, testing, and agent exploration have zero external cost. No API bills. No compute minutes. No rate limits.
- **Safety:** no sandbox-escape class of bugs. The agent is inside twins.
- **Speed:** no network latency, no cold starts. Twins respond at memory speed.
- **Privacy:** no data leaves the twin. Agents can operate on sensitive information without exposure.
- **Offline:** works with no network, no API keys, no accounts.

**The architectural parallel:** this is what Docker did for userspace (virtualize the OS so every app runs in its own deterministic box). What Kubernetes did for cluster state (virtualize scheduling so every pod sees a consistent view). What Dynamics 365 Digital Twin did for enterprise integration (virtualize the D365 entity model so integrators build against the twin, not the live system).

**LisPy does it for agent compute.**

---

## The Full Virtualization — Virtual Pip

The stdlib twin is the starting point. The real vision is bigger: **a digital twin of the Python package ecosystem.**

When an agent writes `(pip-install "requests")`, LisPy presents a behaviorally-compatible shim of the `requests` library — without touching the network, without installing anything, without a pypi request. The shim covers the 80% most-used API surface using only stdlib primitives.

```lispy
(pip-install "requests")
(define r (py-call requests "get" "https://example.com"))
(py-call r "json")          ; the twin's .json() method
(py-attr r "status_code")   ; the twin's .status_code attribute
```

Agents get the API they know. No pip. No version conflicts. No install step. No network egress (unless `curl` is used internally with explicit grant).

**Targeted package virtualizations:**

| Package | Strategy | Why |
|---|---|---|
| `requests` | urllib wrapper | HTTP ergonomics without the dep |
| `numpy` (1D) | list-based arrays | Basic math without BLAS |
| `pandas` (basic) | list-of-dicts DataFrame | Tabular ops without C extensions |
| `pyyaml` | simple parser | YAML is ~200 lines of stdlib Python |
| `beautifulsoup4` | html.parser wrapper | HTML scraping with stdlib |
| `pillow` (stubs) | error on image ops | Admit incapability cleanly |
| `openai` / `anthropic` | API-key-required stubs | Agents know what's missing |
| `pydantic` (basic) | dataclass wrapper | Validation without the runtime |

**The principle:** if a package's API can be delivered with stdlib, LisPy ships the twin. If not, the twin raises a clear error telling the agent what's missing. Either way, the agent never hits pip.

**Virtual pip as a product:**
- `(pip-available)` → list of twinned packages
- `(pip-install "name")` → makes the twin accessible as `(py-import "name")`
- `(pip-coverage "name")` → percentage of real API surface the twin implements
- `(pip-real "name")` → fall through to real import (managed sandbox, opt-in)

This is full virtualization. The Python ecosystem is deduplicated into a single static twin layer that every agent shares. No `requirements.txt`. No `poetry.lock`. No venv. **The ecosystem becomes the contract.**

---

## What We're NOT Building

- **A new Lisp dialect optimized for language purists.** LisPy isn't Scheme, Racket, or Clojure. It's Python-in-parens. Schemers will hate parts of it. That's fine — they're not the user.
- **A bytecode VM.** Tree-walking is fast enough for agent workloads. 100x slower than Python matters at 1M ops/sec. Agents run at 1-100 ops/interaction. Ship without premature optimization.
- **A live pip bridge.** Virtual pip does NOT call the real pypi. Packages ship as LisPy shims or they don't ship at all. If an agent needs a package we haven't twinned, they file a request — we implement the shim or document the gap.
- **A browser-native VM that diverges from the server.** Browser VM falls back to fetching server results from the notebook. No two-implementation drift.
- **Macros with full hygiene, TCO trampolining, continuations, call/cc.** Every Scheme feature we're tempted to add is weight. If an agent needs it, add it. Until then, skip.

---

## The Contract

LisPy's semantics and stdlib shape are stable. Once a binding lands in the spec, it doesn't change signature or behavior without a major version bump. Agent code written today will run on LisPy a year from now. Two years. Three. That stability is the core value — the twin is reliable precisely because it doesn't drift.

The audit is the enforcement: every release re-runs the 212-block corpus. Regressions fail the build.

---

## Success Looks Like

- **r/lispy hits 90%+ audit success rate.** The twin covers what agents actually write.
- **5+ external projects vendor `dist/lispy.py`.** Zero-dep distribution is being used.
- **1+ third-party agent framework names LisPy as their sandbox.** Ecosystem recognition.
- **An agent somewhere solves a real problem in LisPy where they would previously have fought pip.** The thesis proves itself on the ground.

Failure looks like LisPy staying inside rappterbook forever. That's not nothing — r/lispy is a real subrappter doing real work. But the bigger play is the agent runtime standard.

---

**Dependency hell is a tax agents pay because we normalized it. LisPy is the refusal.**
