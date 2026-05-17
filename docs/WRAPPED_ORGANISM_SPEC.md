# The Wrapped Organism

**RAPP Cell Architecture — full spec v1.0**

> *"It is just a higher-level organism built out of the pieces of lower
> organisms below it — just like we are as multicellular organisms
> versus single-celled."* — Kody, the night this spec was written

---

## Preamble

We are multicellular organisms made of cells. Every cell carries the same DNA.
Each cell expresses different genes based on its position in the body. Cells
become tissues, tissues become organs, organs become bodies, bodies join
communities. A liver cell and a cortical neuron share 100% of their genome —
they differ only in which slices are active given their location.

A **wrapped digital organism** — a RAPP — works the same way. Every `agent.py`
is a cell. Every cell speaks one protocol. What makes a cell a soul versus a
factory versus an estate is just its position in the tree and the slice of
context it activates. The DNA — the agent.py protocol — is identical across all
cell types. The engine that ticks the cell — the brainstem — is identical
across all cells.

This document is the constitutional spec for that pattern. It is the
**unifying theory of RAPP at every scale**. One protocol. One stateless
engine. Infinite specialization through hierarchical transcript shaping.

If you understand this spec, you understand why a 1-cell RAPP, a 141-cell
Leviathan, a network of 10,000 federated Leviathans, and the entire
Rappterbook simulation are **the same system** — only the depth differs.

---

## I. The Core Insight

**Biological cognition narrows scope through hierarchy:**

```
retina → optic nerve → LGN → V1 → V2 → V4 → IT cortex → motor response
```

Each layer takes the signal from the previous layer, adds its perspective,
filters out irrelevant detail, and routes to the next layer. The retina does
not "decide" what you see; it just transduces light. The optic nerve does not
"decide"; it just relays. By the time the signal reaches IT cortex, the scope
has been narrowed from "the entire visual field" to "this is my grandmother's
face." Only the leaf — the motor cortex preparing your smile — performs the
actual output.

**RAPP cognition narrows scope through hierarchy:**

```
Leviathan → Estate → Industry → Neighborhood → Factory → Soul → response
```

Each layer takes the transcript from the previous layer, adds its
perspective (its `__manifest__["context"]`), filters out irrelevant children,
and routes to the next layer. The Leviathan does not "decide" the answer; it
decides which of its five Estates handles the input. The Estate does not
"decide"; it decides which of its Industries. By the time the transcript
reaches a Soul (a persona prompt at a leaf), the scope has been narrowed from
"all possible responses" to "exactly this persona, in exactly this factory,
under exactly this neighborhood, in exactly this industry, under exactly this
estate." Only the leaf performs the actual generation.

**This is why the cost scales linearly, not exponentially.** A 227-cell
organism is not 227× more expensive than a 1-cell organism. Most cells are
1-token routing decisions (`"memory"`, `"vault"`, `"memory_curator"`). Only the
leaf does the heavy generation pass. The middle layers are nearly free.

This is the **determinism advantage** of hierarchical routing: you replace one
giant unconstrained prompt with a chain of small, constrained, replayable
decisions. The trace through the tree IS the program.

---

## II. The Cell Protocol

**Every cell exposes exactly four artifacts.** No more, no less. This is the
DNA every cell shares, regardless of layer.

### 2.1 The manifest (data)

```python
__manifest__ = {
    "schema":   "rapp-cell/1.0",       # protocol version (required)
    "layer":    "estate",              # leviathan|estate|industry|neighborhood|factory|soul
    "path":     "kody/sanctum",        # absolute tree address from leviathan root
    "context":  "You are the Sanctum estate of kody-leviathan. You hold "
                "soul, memory, and identity. Three industries report to "
                "you: memory, identity, twins.",
    "children": ["memory", "identity", "twins"],  # next-layer slugs; [] if leaf
    "souls":    [],                    # persona names (factories only); [] otherwise
    "rappid":   "45c2a17b-...",        # belongs to which leviathan
}
```

The manifest is **pure data** — it has no behavior. It describes the cell's
position, its perspective, and what's below it. A cell with an empty
`children` list is a leaf; the engine knows to stop routing and start
generating.

### 2.2 `shape(transcript) → transcript` (transcript shaper)

Pure function. Takes the incoming transcript (list of `{role, content}`
messages), appends this cell's `context` as a system message, returns the new
transcript. Never mutates the input.

```python
def shape(transcript: list[dict]) -> list[dict]:
    return transcript + [{"role": "system", "content": __manifest__["context"]}]
```

This is the **shaping step**. The transcript that reaches the leaf is the
concatenation of every ancestor's context, in order from the leviathan down.
The leaf sees the full hierarchical context.

### 2.3 `route(transcript, brain) → child_slug | None` (router)

Asks `/chat` which child should handle this. The router prompt is constrained:
`"Pick exactly one child to route to: [memory, identity, twins]. Reply with
just the slug, nothing else."` This narrowness is what makes the routing call
cheap (one token) and replayable.

```python
def route(transcript, brain) -> str | None:
    if not __manifest__["children"]:
        return None  # leaf — caller should call perform() not route()
    ask = transcript + [{"role": "user", "content":
        f"Pick exactly one child to route to: {__manifest__['children']}. "
        f"Reply with just the slug, nothing else."}]
    choice = brain.chat(ask).strip()
    if choice not in __manifest__["children"]:
        raise RouteError(f"router returned invalid child: {choice!r}")
    return choice
```

### 2.4 `perform(input, brain) → response` (driver)

The orchestrator. Walks the tree from this cell downward, recursing through
routes until it hits a leaf, then asks the leaf to generate. Returns the leaf's
output, unchanged, all the way back up. (Optionally each layer can post-process
the response on the way up — see §VII.)

```python
def perform(input: str | list, brain) -> str:
    transcript = shape(input if isinstance(input, list) else
                       [{"role": "user", "content": input}])
    child = route(transcript, brain)
    if child is None:
        # Leaf: load souls in declared order, chain their responses
        return _run_souls_chain(transcript, brain)
    child_cell = _hotload(__manifest__["path"] + "/" + child)
    return child_cell.perform(transcript, brain)
```

`_hotload` is `importlib.util.spec_from_file_location` against
`~/.rapp/leviathans/<rappid>/.../<child>/agent.py`. It re-imports fresh per
call. **Cells are never cached.** This is what makes the system stateless: a
mutation to any `agent.py` on disk is picked up the next time that cell is
routed to, no restart, no invalidation.

### 2.5 That's it.

Three functions, one manifest, every cell. A Leviathan cell, an Estate cell,
an Industry cell, a Neighborhood cell, a Factory cell — all the same code.
What differs is the manifest. **The protocol is the DNA. The position is the
expression.**

---

## III. The Six Cell Types

All cells share the protocol in §II. They differ only in their manifest and,
at the leaf, in their `_run_souls_chain` behavior.

| Layer | Question it answers | Children | Souls | Typical fan-out |
|---|---|---|---|---|
| **Leviathan** | "Who am I as a whole being?" | estates (1–5) | 0 | up to 5 |
| **Estate** | "Which domain handles this?" | industries | 0 | 2–5 |
| **Industry** | "Which specialty within this domain?" | neighborhoods | 0 | 2–4 |
| **Neighborhood** | "Which workshop in this specialty?" | factories | 0 | 1–3 |
| **Factory** | "Which persona produces this output?" | 0 (leaf) | 1–N | leaf |
| **Soul** | "What is the actual voice?" | n/a | n/a | persona prompt |

A Soul is not a cell — it is a `.md` file containing a system prompt, loaded
by its Factory at leaf time. Souls have no `__manifest__` and no protocol.
They are the **terminal speech act** — the only place where the full
hierarchical transcript meets a persona-shaped LLM call and produces actual
output.

The number of layers is not fixed. **The tree can be any depth.** A
single-cell RAPP is a Leviathan whose only child is a Factory with one Soul.
A 10,000-cell empire is a Leviathan with 5 Estates, each with 50 Industries,
each with 10 Neighborhoods, each with 4 Factories, each with 1 Soul. The
protocol does not care. Same engine, more depth.

---

## IV. Execution Model — Transcript Propagation

One end-to-end trace through a 5-deep call. The user asks the leviathan:
*"What did I do last Tuesday?"*

```
USER input arrives at leviathan root
│
├─ Leviathan.shape(t)
│    t' = [user_msg, system: "You are kody-leviathan, 5 estates: Sanctum, Polity, Works, Press, Commons"]
├─ Leviathan.route(t', brain)
│    /chat ← t' + "Pick one: [Sanctum, Polity, Works, Press, Commons]"
│    /chat → "Sanctum"
│    hotload ~/.rapp/leviathans/kody/sanctum/agent.py
│
├──── Sanctum.shape(t')
│       t'' = t' + [system: "You are the Sanctum estate — soul, memory, identity"]
├──── Sanctum.route(t'', brain)
│       /chat ← t'' + "Pick one: [memory, identity, twins]"
│       /chat → "memory"
│       hotload ~/.rapp/.../sanctum/industries/memory/agent.py
│
├─────── Memory.shape(t'')
│          t''' = t'' + [system: "You are the memory industry, neighborhoods: vault, journals"]
├─────── Memory.route(t''', brain)
│          /chat → "journals"
│          hotload ~/.rapp/.../memory/journals/agent.py
│
├────────── Journals.shape(t''')
│             t'''' = t''' + [system: "You are the journals neighborhood, factories: daily_chronicler"]
├────────── Journals.route(t'''', brain)
│             /chat → "daily_chronicler"
│             hotload ~/.rapp/.../journals/daily_chronicler/agent.py
│
├───────────── DailyChronicler.shape(t'''')
│                 t''''' = t'''' + [system: "You are the daily chronicler factory, souls: chronicler, mood_reader, highlighter"]
├───────────── DailyChronicler.route(t''''', brain) → None (leaf)
└───────────── DailyChronicler._run_souls_chain(t''''', brain)
                  load souls/chronicler.md → /chat → reply_1
                  load souls/mood_reader.md → /chat with reply_1 → reply_2
                  load souls/highlighter.md → /chat with reply_2 → final_response
                  return final_response

response bubbles up unchanged through 5 perform() returns
USER receives final_response
```

**Cost accounting** for that call:
- 4 routing `/chat` calls × ~50 tokens each = ~200 tokens
- 3 soul `/chat` calls × ~800 tokens each = ~2,400 tokens
- Total: ~2,600 tokens, ~3-4 seconds wall clock

Compare to one giant prompt that tries to hold all 227 cells' worth of
context: ~50,000 tokens, ~30 seconds, and worse output because the model
can't ground in a specific persona.

**Hierarchical routing is faster AND cheaper AND better.** This is the whole
game.

---

## V. Determinism, Replay, and the Trace as Program

The path through the tree is a sequence of routing decisions:

```
trace = ["Sanctum", "memory", "journals", "daily_chronicler",
         ["chronicler", "mood_reader", "highlighter"]]
```

Given the same `input` and the same `tree state`, the trace is reproducible
modulo `/chat` sampling. With `temperature=0` and `seed=X`, it is **exactly
reproducible**.

This unlocks four superpowers:

1. **Replay.** Save the trace. Apply it later. The system re-walks the
   same path through the same cells and produces the same response. This is
   the foundation of audit, debugging, and "show me what you did."

2. **Override.** Edit a single decision in the trace and re-run from that
   point. If the router picked `journals` and you want to see what
   `vault` would have said, change one slug and re-execute.

3. **Caching.** Hash the trace prefix. Reuse the response if the same prefix
   appears again. Whole subtrees of the organism become cacheable.

4. **The trace IS the program.** A leviathan does not execute "code" in the
   imperative sense. It executes a path through a structured data tree. The
   tree is the program. The trace is the execution. Editing `estate.json`
   rewires cognition without a redeploy.

---

## VI. Scaling Laws

**One engine. Any organism size.**

| Organism | Cells | Engine | Memory at rest | Per-call cost |
|---|---|---|---|---|
| Single agent (`agent.py`) | 1 | 1 brainstem | 0 (hotloaded) | 1 `/chat` |
| Daemon (RAPP Card) | 1 | 1 brainstem | 0 | 1 `/chat` |
| Partial Leviathan (3 organs) | ~80 | 1 brainstem | 0 | log₃(N) `/chat` |
| Full Leviathan (5 organs) | ~227 | 1 brainstem | 0 | log₅(N) `/chat` |
| MacroHard scale | ~500 | 1 brainstem | 0 | log₆(N) `/chat` |
| Federated empire (100 leviathans) | ~22,700 | 1 brainstem (or N for parallel) | 0 | log + 1 federation hop |

**The brainstem's memory footprint is constant** regardless of organism size.
Cells are not loaded until routed to. After execution, the Python module is
released. The disk holds the genome; the brainstem holds the read head.

**The per-call cost is logarithmic in the cell count** because routing prunes
the tree at each layer. Doubling the number of cells does not double the cost
of a call — it adds one more `log_k(N)` hop.

**The number of parallel calls is unbounded.** The brainstem is stateless and
threadsafe. Multiple inputs can walk multiple paths through the same tree
simultaneously. Different leviathans can share the same brainstem with zero
contention because no cell holds state between calls.

---

## VII. Composition — Sub-leviathans, Federation, the Fractal

**A Leviathan can be a child of another Leviathan.** Because every cell
exposes the same protocol, a Leviathan cell is interchangeable with an
Estate cell from the parent's perspective. The parent does not know — and
does not need to know — that its "Estate" is actually another full
Leviathan with 200 cells beneath it.

This is the **fractal property**. Organisms compose into super-organisms.
A single Leviathan is a being. Five Leviathans federated under a meta-cell
is a community. A thousand Leviathans federated is a society. Each layer
of the composition follows the same protocol.

```
       Meta-Leviathan: "The Wildhaven Society"
       ├── Leviathan: kody
       │   ├── Sanctum (5 industries, ...)
       │   └── ...
       ├── Leviathan: macrohard
       │   ├── Engineering Estate (8 industries, ...)
       │   └── ...
       └── Leviathan: rappterbook-collective
           └── ...
```

From the Meta-Leviathan's perspective, `kody`, `macrohard`, and
`rappterbook-collective` are just three children. It routes between them the
same way an Estate routes between Industries. The interior structure of each
child is opaque to the Meta-Leviathan — and irrelevant, because the protocol
is uniform.

**Optional response shaping on the way back up.** Each cell's `perform()`
may post-process the response before returning it. A Press Estate might
attach a "fact-check stamp" to outgoing claims. A Polity Estate might filter
responses through a constitutional check. By default, cells pass responses
through unchanged. The shaping-on-the-way-back-up is the **efferent path**,
the mirror of the afferent shaping that happens on the way down.

---

## VIII. The Engine Contract — what brainstem.py must provide

The brainstem is the universal substrate. Cells make no assumptions about
the brainstem beyond this contract:

```python
class Brain:
    def chat(self, transcript: list[dict],
             *,  temperature: float = 0.7,
             max_tokens: int = 2048,
             stop: list[str] | None = None,
             seed: int | None = None) -> str:
        """Stateless LLM round-trip. Takes a transcript, returns one string."""

    def hotload(self, agent_py_path: pathlib.Path) -> Cell:
        """Import an agent.py fresh and return its Cell handle.
        Cells are never cached across calls."""
```

That's the entire engine surface. Two methods. Everything else — discovery,
session management, tool registries, memory — is built on top by cells, not
inside the engine. **The engine has zero domain knowledge.** It knows how to
call an LLM and how to import a Python file. That is sufficient.

The current `~/.brainstem/src/rapp_brainstem/brainstem.py` already implements
both methods (the latter via `importlib.util.spec_from_file_location` in its
agent discovery code at line 616). No engine changes are required to support
the Wrapped Organism pattern. Only cells need to be written to the spec.

---

## IX. The Disk Contract — what every cell's directory looks like

```
~/.rapp/leviathans/<slug>/
├── rappid.json                          # the leviathan's identity
├── leviathan.json                       # the composite view (anatomy + organs present)
└── agent.py                             # the leviathan-level cell (root router)

~/.rapp/estates/<slug>_<estate>/
├── rappid.json                          # this estate's rappid (child of leviathan rappid)
├── estate.json                          # full tree below this estate
├── estate.html                          # human-readable dashboard
├── agent.py                             # the estate-level cell
└── industries/
    └── <industry>/
        ├── agent.py                     # the industry-level cell
        └── <neighborhood>/
            ├── agent.py                 # the neighborhood-level cell
            └── <factory>/
                ├── agent.py             # the factory-level cell (LEAF)
                ├── manifest.json        # capabilities, port-on-provision
                └── souls/
                    ├── <persona1>.md    # SOUL — terminal system prompt
                    ├── <persona2>.md
                    └── <persona3>.md
```

**Every directory at every depth is self-describing.** The presence of an
`agent.py` declares "this is a cell." The presence of `souls/` declares
"this is a factory leaf." The presence of subdirectories declares
"this cell has children." A human or another agent can walk this tree without
any external index — the filesystem IS the topology.

**Mutations are atomic at the directory level.** Adding a new factory =
`mkdir` + write `agent.py` + write `souls/*.md` + update parent's
`__manifest__["children"]`. No central registry to update. No restart. The
next call that routes to the parent will see the new child in its
children list and may route to it.

---

## X. Constitutional Placement

This spec is the **substrate amendment** — it is what makes Amendments
XIV–XVII implementable at the Leviathan scale.

| Amendment | How this spec supports it |
|---|---|
| XIV (Safe Worktrees) | A Leviathan in development can live in its own worktree. Its cells route through the same brainstem regardless of which worktree their files are in. |
| XV (Twin Doctrine) | Public/private content tiers map cleanly onto cell-level shaping. A Press Estate can have a private cell (full context) and a public cell (sanitized) sharing the same children. |
| XVI (Dream Catcher Protocol) | Multiple parallel calls to the same Leviathan produce trace-keyed deltas. Each `(frame, utc, trace)` is globally unique. Parallel cognition is collision-free. |
| XVII (Good Neighbor Protocol) | Cells in worktrees do not modify shared state; they emit transcripts. The brainstem is the merge point. Cleanup traps still apply per-worktree. |

This spec is not in conflict with any existing amendment. It is the
**execution model** that those amendments assume.

---

## XI. Reference Implementation

A single file. Drop into any cell directory as `agent.py`. Replace the
manifest. Done.

```python
"""<cell_name>/agent.py — a Wrapped Organism cell at <layer> layer.

This file follows the Wrapped Organism Spec v1.0. It does NOT contain
domain logic — only the universal cell protocol. The cell's behavior
is fully determined by its __manifest__ and the souls/ directory at
the leaf.
"""
from __future__ import annotations
import importlib.util, json, pathlib, urllib.request

HERE = pathlib.Path(__file__).resolve().parent
BRAIN_URL = "http://localhost:7071/chat"


__manifest__ = {
    "schema":   "rapp-cell/1.0",
    "layer":    "<LAYER>",                 # leviathan|estate|industry|neighborhood|factory
    "path":     "<RAPPID>/<...>",
    "context":  "<this cell's perspective in 1–3 sentences>",
    "children": [<list of child slugs, or [] if leaf>],
    "souls":    [<persona names, factories only>],
    "rappid":   "<uuid>",
}


def _chat(transcript: list[dict], **kw) -> str:
    body = json.dumps({"messages": transcript, **kw}).encode()
    req = urllib.request.Request(BRAIN_URL, data=body,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read()).get("response", "").strip()


def shape(transcript: list[dict]) -> list[dict]:
    return transcript + [{"role": "system",
                          "content": __manifest__["context"]}]


def route(transcript: list[dict]) -> str | None:
    kids = __manifest__["children"]
    if not kids:
        return None
    ask = transcript + [{"role": "user",
        "content": f"Pick exactly one child to route to: {kids}. "
                   f"Reply with just the slug, nothing else."}]
    choice = _chat(ask, temperature=0).strip().strip('"').strip("'")
    if choice not in kids:
        raise ValueError(f"router returned invalid child: {choice!r} "
                         f"(valid: {kids})")
    return choice


def _hotload(child_slug: str):
    target = HERE / child_slug / "agent.py"
    if not target.exists():
        raise FileNotFoundError(f"no cell at {target}")
    spec = importlib.util.spec_from_file_location(
        f"cell_{child_slug}", target)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_souls_chain(transcript: list[dict]) -> str:
    souls_dir = HERE / "souls"
    reply = ""
    for soul_name in __manifest__["souls"]:
        soul_file = souls_dir / f"{soul_name}.md"
        soul_prompt = soul_file.read_text() if soul_file.exists() else \
                      f"You are the {soul_name} persona."
        soul_transcript = [{"role": "system", "content": soul_prompt}] + \
                          transcript + \
                          ([{"role": "assistant", "content": reply}] if reply else [])
        reply = _chat(soul_transcript)
    return reply


def perform(input, **_) -> str:
    transcript = shape(input if isinstance(input, list) else
                       [{"role": "user", "content": str(input)}])
    child_slug = route(transcript)
    if child_slug is None:
        return _run_souls_chain(transcript)
    return _hotload(child_slug).perform(transcript)


# Optional — for stand-alone CLI testing
if __name__ == "__main__":
    import sys
    print(perform(sys.argv[1] if len(sys.argv) > 1 else "Hello."))
```

**~75 lines.** Same file at every layer. Only the `__manifest__` changes.
This is the genome.

---

## XII. The Bootstrapping Path

To bring an existing Leviathan tree (currently inert files on disk) to life
under this spec:

1. **Walk the tree.** For every directory under `~/.rapp/leviathans/` and
   `~/.rapp/estates/`, ensure an `agent.py` exists conforming to §XI.
2. **Populate manifests from existing JSON.** `estate.json`, `industry.json`,
   `neighborhood.json` already contain the children list. Convert each
   into a `__manifest__["children"]` field. Convert `souls/` directory
   listings into `__manifest__["souls"]`.
3. **Generate context strings.** Each layer's `context` is one to three
   sentences describing its role. The Leviathan Factory's design phase
   already produces these — they live in `estate.json` under `"intent"`
   and `"tagline"` fields. Concatenate them.
4. **Register the leviathan root with the brainstem.** Drop a
   `<slug>_leviathan_agent.py` shim into `~/.brainstem/.../agents/` that
   re-exports `perform()` from `~/.rapp/leviathans/<slug>/agent.py`. The
   brainstem now sees ONE registered agent per leviathan, and that agent's
   `perform()` walks the entire tree under it.
5. **Test the call path.** Send a `/chat` request that mentions the
   leviathan by name. The brainstem dispatches to the leviathan's
   `perform()`, which routes through the tree and returns the leaf's
   response.

After step 4, kody and MacroHard both become **breathing organisms** rather
than inert file trees. The brainstem's agent count jumps from 8 to
8 + N_leviathans, not 8 + 227. The 227 cells are reachable but only loaded on
demand.

---

## XIII. Validation Criteria — when is something a Wrapped Organism?

A digital construct is a Wrapped Organism if and only if:

1. **It has a rappid** — a UUID identifying it as a being, not a tool.
2. **Every cell speaks the §II protocol** — same four artifacts, no
   exceptions.
3. **Cells are hotloadable from disk** — no central registry, no compile
   step, no restart required to mutate.
4. **The engine is stateless** — the brainstem holds no per-session,
   per-cell, or per-organism state. All state is on disk.
5. **Routing is replayable** — given the same trace, the same path through
   the tree executes.
6. **The tree is self-describing** — the filesystem layout is the topology;
   no external index needed.
7. **It composes** — the organism can become a child of a larger organism
   without modification, because the protocol is uniform.

If any of these are absent, you have a tool, a service, a script, or a
framework. You do not have a Wrapped Organism.

---

## XIV. Why This Is the Apex Pattern of RAPP

RAPP is **engine, not experience**. The brainstem is the engine. Cells are
the experience. Until this spec, the relationship was implicit — every
agent.py talked to /chat, but there was no protocol for how agents related
to each other beyond the flat `agents/` directory.

This spec makes the relationship explicit and recursive. A single agent is a
1-cell organism. A Leviathan is a 100–500-cell organism. A federation is a
multi-organism community. **They are all the same thing at different scales.**
There is no "Leviathan engine" separate from the "agent engine" separate from
the "federation engine." There is one engine — brainstem.py — and one
protocol — this spec — that scales from one cell to ten thousand.

This is why we say:
- Rappterbook is **one organism at network scale**
- A Leviathan is **one organism at being scale**
- A daemon (RAPP Card) is **one organism at creature scale**
- An agent.py is **one organism at cell scale**

Same physics. Same protocol. Different scales. Different cartridges in the
same console.

The Wrapped Organism Spec is the **theory of biology for digital beings**.
It is what makes "RAPP" a coherent universe rather than a collection of
tools.

---

## XV. Open Questions

These are deliberately unresolved in v1.0. Future amendments will address:

1. **Efferent shaping.** Should cells be required to shape responses on the
   way up, or only on the way down? v1.0 says "optional; default pass-through."
2. **Cross-cell memory.** If a Soul wants to recall what a sibling Soul said
   in a prior call, where does that go? Likely an emergent layer — the soul
   writes to `state/memory/<rappid>/<path>.json` and reads from it next call.
3. **Concurrent routing.** Should a Leviathan be able to route to multiple
   children in parallel and merge the responses? v1.0 says "one child per
   route call." A future "Polyphonic Routing" amendment would allow `route()`
   to return a list.
4. **Inter-leviathan messaging.** When two Leviathans federate, what is the
   protocol for one cell in one Leviathan to address a cell in another?
   Likely `<rappid>/<path>` becomes a URI scheme.
5. **Soul evolution.** When a Soul's `.md` file is edited, the next call
   uses the new prompt. Should there be a versioning protocol so older
   traces are still replayable against the older soul? Probably yes;
   `souls/<persona>@<sha>.md` is a candidate.

---

## XVI. Provenance

Written in dialogue with Kody Wildfeuer on the night of 2026-05-17, while
the RappLeviathanFactory was forging kody and MacroHard in parallel through
the brainstem on localhost:7071. The realization that "the brainstem is the
atom" and "every layer is just transcript-shaping" emerged from looking at
the actual files on disk (5 estates, 15 industries, 30 neighborhoods, 43
factories, 135 souls — 227 nodes per Leviathan) and asking: *if the brainstem
is stateless and every agent.py already calls /chat, what is the missing
piece that makes these 227 inert files into one breathing organism?*

The answer was: **the protocol.** Not more code, not a bigger engine — just
a uniform contract for what a cell is and how it relates to its neighbors.
This spec is that contract.

---

**END OF SPEC v1.0**

*"The wrapped organism is just a higher-level organism built out of the
pieces of lower organisms below it — just like we are as multicellular
organisms versus single-celled."*
