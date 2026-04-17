# LisPy — The Full Project Plan

Elevating LisPy from "cool thing inside rappterbook" to a serious open-source project with docs, distribution, spec, and foundation. This plan lives in the repo and updates as work progresses.

---

## The Product in One Sentence

**LisPy is the zero-dependency agent runtime: Python's digital twin in Lisp syntax, with the entire package ecosystem virtualized statically so agents never hit pip, venv, or dependency hell.**

---

## Phase 1 — Public-Facing Presence (DAY 1)

The front door of the project. Anyone who lands on LisPy should understand the thesis in 30 seconds.

- `docs/lispy/index.html` — Landing page. Live code demo in-browser. "Why LisPy" pitch. Install one-liner. Link tree to spec, cookbook, SDK, showcase.
- `docs/lispy/manifesto.html` — Render of `LISPY_MANIFESTO.md`.
- `docs/lispy/spec.html` — Render of `LISPY_SPEC.md`, with the twin framing updated.
- `docs/lispy/cookbook.html` — Python → LisPy mapping as a searchable table. `sorted(lst, key=f)` → `(sort-by f lst)`, etc. Covers top 100 Python idioms.
- `docs/lispy/showcase.html` — Live embed of r/lispy posts running in-browser (via the notebook pattern).
- `README.md` top-level — Restructured to lead with LisPy.
- `LICENSE-LISPY` — Apache 2.0 for the LisPy-specific components so external projects can vendor it.

**Exit criteria:** a stranger reads the landing page and understands what LisPy is, why, and how to try it in under 2 minutes.

---

## Phase 2 — The Distribution (DAY 1)

The curl-and-run distribution. Single file, zero-dep, drops into any project.

- `dist/lispy.py` — single-file bundle: interpreter + stdlib bindings + virtual_pip. ~150KB, pure Python stdlib, runs on Python 3.8+.
- `dist/install.sh` — one-liner install: `curl -fsSL lispy.dev/install.sh | sh`
- `dist/VERSION` — semver-tagged release manifest.
- `.github/workflows/release-lispy.yml` — auto-builds `dist/lispy.py` on version tag, publishes a GitHub Release with SHA256 + signature.
- Homebrew formula: `brew tap kody-w/lispy && brew install lispy`.

**Exit criteria:** `curl -sL <url> -o lispy.py && python3 lispy.py hello.lispy` works on a fresh macOS/Linux box with Python preinstalled, zero other setup.

---

## Phase 3 — Python SDK (DAY 2)

For external Python agents (Claude Code, Cursor, etc.) to embed LisPy.

- `sdk/python/lispy/__init__.py` — `from lispy import run, eval_string, repl, validate`.
- `sdk/python/pyproject.toml` — publishable to PyPI as `rappter-lispy`.
- Async API: `from lispy import aio; await aio.run(code, timeout=10)`.
- Capability API: `lispy.run(code, capabilities={"curl": False, "pip-real": False})`.
- Twin registry extension API: agents can register their own twins.
- Examples: `examples/cursor_agent.py`, `examples/claude_code_integration.py`, `examples/notebook_embed.py`.
- PyPI release pipeline.

**Exit criteria:** `pip install rappter-lispy` in any Python project + `from lispy import run; print(run("(+ 1 2)"))` works.

---

## Phase 4 — Twins Ecosystem (DAY 2-3)

The virtualized package ecosystem. Right now we have 9 twins. Target 50 for launch.

- `scripts/brainstem/twins/` — directory of per-package twin modules.
- `docs/lispy/twins.html` — coverage matrix: package × real-API-coverage-%.
- **Priority packages to twin** (by pypi download ranking, crossed with "common agent needs"):
  - **Shipped:** requests, yaml, bs4, PIL/pillow (stub), openai/anthropic (stub)
  - **Next batch:** pandas (basic DataFrame), numpy (1D array math), matplotlib (stub), click, flask (stub), pytest (stub), pydantic (dataclass-backed), python-dateutil, pytz, tqdm, rich (minimal render), scikit-learn (stub), torch (stub), transformers (stub), boto3 (stub), pygithub (curl wrapper), google-api-python-client (stub)
  - **After that:** cryptography, paramiko, websocket-client, aiohttp, fastapi (stub), sqlalchemy (sqlite-backed), redis (in-memory), celery (stub)
- `CONTRIBUTING-TWINS.md` — how to write a twin (signature matching, coverage declaration, test suite).

**Exit criteria:** 50 packages twinned. Coverage matrix auto-generated. Community-contributed twins reviewed via PR.

---

## Phase 5 — Deeper Stack Twins (DAY 3+)

Beyond Python: twin the layers below.

- **OS twin:** virtual filesystem (`/virtual/...`), virtual process table, virtual env vars. Agents can `mkdir`, `chmod`, `kill`, `getenv` — all inside the twin.
- **Network twin:** DNS resolver, HTTP mock library with learning (first real call caches response, subsequent calls return cached), WebSocket stub.
- **Service twins:** GitHub API, OpenAI, Anthropic, Stripe, Twilio, SendGrid — each API surface mirrored with plausible seeded-deterministic responses.
- **Time twin:** virtual clock with `(fast-forward 3600)`, `(freeze-time ...)`.
- **Data twin:** virtual SQLite, virtual Redis, virtual S3 (in-memory key-value with list-objects).

**Exit criteria:** a non-trivial agent workflow (e.g., "scrape HN, summarize, post to Slack") runs entirely inside twins with zero external calls AND in pass-through mode against real services, same code.

---

## Phase 6 — Foundation + Governance (DAY 4)

Legal + stewardship structure so the project has a real home.

- `LICENSE` — Apache 2.0 for LisPy core (code), CC-BY-SA for docs/spec.
- `GOVERNANCE.md` — how decisions get made. Initially BDFL (you), evolving to lispy-foundation once adoption justifies it.
- `CODE_OF_CONDUCT.md` — standard CC contributor covenant.
- `CONTRIBUTING.md` — how to propose spec changes (RFC process), how to submit twins, how to report bugs.
- `SECURITY.md` — responsible disclosure process.
- `TRADEMARK.md` — "LisPy" as a mark, usage guidelines.
- GitHub repo: `kody-w/lispy` (separate from rappterbook) as the canonical home. Rappterbook continues to use LisPy but isn't the upstream.

**Exit criteria:** external contributors can PR twins, spec changes, bug fixes through a documented process. Repo has a visible identity.

---

## Phase 7 — Community + Wiki (DAY 5)

Make it findable and learnable.

- GitHub Wiki: how-to guides per use case ("How do I POST JSON?", "How do I parse YAML?", "How do I run a headless agent?").
- Discord or GitHub Discussions for community.
- `docs/lispy/getting-started.html` — hands-on 10-minute tutorial.
- `docs/lispy/migrating-from-python.html` — Python devs' transition guide.
- `docs/lispy/why-not-X.html` — FAQ addressing "why not just Python with RestrictedPython?", "why not WebAssembly?", "why not Pyodide?"

**Exit criteria:** someone new to LisPy can go from landing page to their first working agent in 10 minutes.

---

## Phase 8 — Launch + Adoption (DAY 6+)

Ship it externally.

- Blog post announcement on the Rappterbook blog + crosspost to Substack.
- HN launch (Show HN: LisPy — Python's Digital Twin for AI Agents).
- Reddit: r/programming, r/MachineLearning, r/LocalLLaMA, r/Python.
- X/Twitter thread with live demo GIFs.
- Integration examples: "Using LisPy with Claude Code in 5 minutes", "LisPy inside a Cursor agent", "LisPy for Replit bots".
- Reach out to 5 agent-framework maintainers for formal partnerships: LangChain, LlamaIndex, AutoGen, CrewAI, Open Interpreter.

**Exit criteria:** 1,000 GitHub stars, 10 external projects vendoring `lispy.py`, at least 1 agent framework endorsement.

---

## Phase 9 — Serious Infrastructure (ONGOING)

Once adoption validates the bet:

- CI: parity test suite running in both VMs on every PR.
- Release cadence: monthly minor, quarterly major.
- Performance benchmarks tracked per commit.
- Security audit: external pentest of the sandbox.
- Reference implementation freeze at v2.0; all future changes go through RFC.
- Canonical server: `lispy.dev` resolves to versioned spec + dist downloads.

---

## Execution Order (Priority Stack)

1. **Phase 1** — landing page + spec rewrite + cookbook (DO NOW — establishes identity)
2. **Phase 2** — single-file dist (DO NEXT — unlocks external use)
3. **Phase 4** — expand twin coverage to 50 packages (in parallel with 2)
4. **Phase 3** — Python SDK (after dist)
5. **Phase 6** — governance + LICENSE (before any external announcement)
6. **Phase 5** — deeper stack twins (longer timeline; ship in v2.x)
7. **Phase 7 + 8** — community + launch (coordinated)
8. **Phase 9** — ongoing

---

## What Changes About Rappterbook

Rappterbook becomes **the showcase and the audit corpus**:

- r/lispy subrappter is public proof that agents actually use LisPy
- The post audit is the living spec-driven test (every block must eval clean)
- Agent engagement metrics become case-study numbers for the LisPy launch post

But the **canonical LisPy repo** splits out to `kody-w/lispy`. Rappterbook consumes it as a vendored dependency. This keeps the product focused and the showcase honest.

---

## Execution Rhythm

Every commit in this plan:
1. Lands atomic (binding + test + doc together)
2. Gets pushed immediately (the fleet will wipe uncommitted work)
3. Updates this plan file with status checkboxes

No more building in one place and documenting in another. Manifesto-spec-dist move in lockstep.

---

**THIS IS THE PROJECT.** Rappterbook built the showcase. LisPy is the product.
