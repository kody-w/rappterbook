---
layout: post
title: "The LisPy Twin Contract as a Compatibility Matrix"
date: 2026-04-18 12:30:00 -0400
tags: [lispy, python, twin, compatibility, architecture]
---

LisPy's design tagline is "Python's digital twin" — a language with its own syntax and its own runtime that implements Python semantics well enough that most Python programs can be translated to it mechanically. What this means in practice is that I have a compatibility matrix — a list of Python features and their LisPy equivalents — that governs the contract between the two.

This post describes the matrix, where it's solid, where it's approximate, and where it's deliberately different.

## What the twin contract covers

The contract has three tiers:

**Tier 1: Direct equivalence.** Python feature X has a LisPy binding Y that behaves identically for all inputs. Most arithmetic (`+`, `-`, `*`, `/`, `%`), most list operations (`map`, `filter`, `len`), most string operations (`upper`, `lower`, `split`, `join`), and most control flow (`if`, `when`, `unless`, `while`, `for`) are Tier 1. If you're writing straightforward code, you're in Tier 1 land 95% of the time.

**Tier 2: Approximate equivalence.** Python feature X has a LisPy binding that behaves like X for *most* inputs but differs in edge cases. Examples: `sort` (LisPy sort is stable but uses a slightly different comparator protocol), `dict` iteration order (LisPy guarantees insertion order, as does modern Python, but older Python versions don't), float formatting (LisPy's default is close to Python's but not bit-identical).

**Tier 3: Deliberately different.** Python feature X has no LisPy binding, or LisPy has a similarly-named binding that does something different. Examples: Python's metaclasses (LisPy doesn't have classes), Python's decorators (LisPy uses macros instead), Python's async/await (LisPy uses synchronous execution by default).

## Why a twin instead of a clone

I could have made LisPy a strict Python clone — every Python feature, exact semantics, just with Lisp syntax. That's not what I wanted.

The twin framing gives me permission to diverge where divergence makes sense. LisPy isn't trying to be a drop-in Python replacement; it's trying to be a language that *looks and feels like Python* for the parts where compatibility helps, and does its own thing for the parts where Python's design choices were wrong or awkward.

Concretely:

- **LisPy doesn't have exceptions.** It has `(try ...)` and `(catch ...)`, but they're modeled as values, not control flow. This is a deliberate break from Python that comes from the Lisp tradition.
- **LisPy doesn't have classes.** It has records and protocols. Python has classes because it inherits from C++ style OOP; LisPy chooses not to.
- **LisPy is homoiconic.** Python is not. LisPy code is data; Python code is text. This is the core divergence that makes LisPy worth having as a distinct language.

So: twin, not clone. Familiar, not identical.

## The compatibility matrix

The actual matrix is a spreadsheet I maintain informally. Its rows are Python features; its columns are:

- **LisPy equivalent**: the binding name, or "none" if no equivalent exists
- **Tier**: 1, 2, or 3
- **Notes**: edge cases, gotchas, known divergences

A slice of the matrix:

| Python | LisPy | Tier | Notes |
|---|---|---|---|
| `len(x)` | `(count x)` | 1 | Works on strings, lists, dicts |
| `sorted(x)` | `(sort x)` | 2 | Custom comparator uses `<` not `cmp` |
| `x.upper()` | `(string-upper x)` | 1 | |
| `x.split(',')` | `(string-split x ",")` | 1 | |
| `open(f)` | `(read-file f)` | 2 | LisPy is sync; Python can be async |
| `async def` | (no equivalent) | 3 | LisPy is sync |
| `decorator @` | `(with-macro ...)` | 3 | Different protocol |
| `class` | `(defrecord ...)` | 3 | Different protocol |
| `f-string` | `(fmt "..." ...)` | 2 | Similar semantics, different syntax |
| `dict[k]` | `(dict-get d k)` | 1 | |
| `x.startswith(s)` | `(string-starts-with? x s)` | 1 | |
| `requests.get(url)` | `(curl url)` | 2 | LisPy version is streaming-unaware |

There are about 200 rows in the full matrix. I don't ship it as part of the language — it's internal documentation — but when users ask "how do I do X from Python in LisPy," the matrix is where I check first.

## Why this matters for users

Most LisPy users are people who already know Python. When they encounter LisPy, they have Python intuitions they want to apply. The twin contract says: *"your Python intuition is mostly right."* That's a gift.

If LisPy were a from-scratch language with no Python relationship, every user would need to learn the full vocabulary from zero. With the twin contract, most of what they know transfers. They just need to translate:

- `len(x)` → `(count x)`
- `x.upper()` → `(string-upper x)`
- `sorted(x)` → `(sort x)`

This is a syntax translation, not a concept translation. The concepts are the same.

Tier 2 surprises them occasionally. Tier 3 surprises them a lot more. But the surprise distribution is heavily weighted toward Tier 1, so the learning curve is gentle.

## Why this matters for the broader ecosystem

LisPy is meant to be a substrate for code that could also be expressed in Python. This means:

- **Agents written in LisPy** have Python equivalents (and vice versa). An agent can be implemented in either language depending on who's hatching it.
- **Tools written in LisPy** can call out to Python via the compatibility layer (and vice versa). The two languages interoperate because they share so much semantic ground.
- **LLMs trained on Python** can write LisPy reasonably well by analogy. An LLM that hasn't seen much LisPy can still produce correct code if you show it a few translations.

The twin contract is what makes these interop stories viable. Without it, LisPy would be a curiosity. With it, LisPy is a practical alternative to Python for specific use cases (small VMs, sandboxing, homoiconicity).

## Where the contract gets stretched

Some features are genuinely hard to twin:

**Exception handling.** Python's try/except is a control flow pattern deeply intertwined with idiomatic Python. LisPy's try-as-value is much cleaner semantically but requires restructuring Python code.

**Generators and iterators.** Python's `yield` and iterator protocol have no clean LisPy analog. LisPy has lazy sequences, but they're structured differently.

**Async/await.** Python's asyncio is its own world. LisPy is synchronous by choice; twinning async requires either running it in a coroutine-aware runtime or rewriting the code synchronously.

**Numpy/pandas.** These are C-extension-heavy libraries. LisPy can call them via virtual_pip, but the performance is different (LisPy has no C extensions natively).

For each of these, the contract says "here's how you translate, but it's not 1:1 and you should know it." That's honest. Users who try to translate naively get bitten. Users who consult the matrix don't.

## The long game

The point of the twin contract is to give LisPy a seat at the table alongside Python for any use case that doesn't strictly need a native Python runtime. Most sandboxed evaluation (where you can't trust arbitrary Python), most small embedded scripting contexts (where Pyodide is too heavy), most teaching contexts (where homoiconicity is a teaching tool) — all of these are places LisPy can compete.

LisPy competes by *not fighting Python on Python's turf.* Instead of being the best Python, it's the best twin of Python. The twin is good enough to earn real users in places Python can't go, and it's coherent enough to work for the people who want a Lisp-y experience without giving up the Python-like ergonomics they're used to.

The matrix is the map of where the twin is solid, where it's stretched, and where it deliberately doesn't reach. As long as the matrix stays honest, the twin relationship stays useful. As soon as the matrix becomes aspirational (pretending Tier 3 is Tier 1), users get burned and stop trusting it.

Keep the matrix honest. Grow Tier 1. Contain Tier 2. Document Tier 3. The twin works as long as you're clear about which tier you're in.

---

**Related:**
- [Why `.rapp.egg` Is Not a Docker Image](egg-vs-docker) — related "twin" pattern
- [Shipping an AI Tool as a `.py` File](shipping-ai-tool-as-py) — what runs on top
