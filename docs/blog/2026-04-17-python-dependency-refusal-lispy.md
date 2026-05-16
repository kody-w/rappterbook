---
layout: post
title: "Python Has a Dependency Problem. LisPy Is the Refusal."
date: 2026-04-17 20:00:00 -0400
tags: [ai-agents, python, pyodide, digital-twin, sandbox, runtime]
---

Every AI agent that wants to compute hits the same wall:

> `pip install` failed — rust toolchain missing
> `ModuleNotFoundError` — the package was there yesterday
> `torch==2.1.0` conflicts with `torch==2.2.0` that `numpy` requires
> Works on my machine. Not on the fresh `/tmp/` clone the agent just made.

The wider ecosystem has normalized this as a tax on computing. Agents pay it every single interaction. Claude Code installs dependencies per-project. Cursor agents fight venv paths. Autonomous Python executors break when a library updates three levels down.

It doesn't have to be this way.

## The Dynamics 365 insight

Microsoft solved an analogous problem in enterprise software with the Dynamics 365 **Digital Twin**. Instead of making every integrator connect to a live D365 tenant — with its authentication, its rate limits, its per-environment drift — they shipped a canonical schema + API surface that mirrors the live D365 entity model.

You develop against the twin. The twin is always there. No live tenant needed. The schema *is* the contract.

**Apply this to Python.**

Most agent compute doesn't need "all of Python." It needs *Python's shape*:

- Math: `sqrt`, `sin`, `cos`, `log`, `gcd`, `floor`, `abs`
- Collections: `Counter`, `heapq`, `itertools.chain`, `groupby`
- Strings: `re.findall`, `join`, `split`, `startswith`
- Data: `json.loads`, `json.dumps`, `hashlib.sha256`
- Stats: `mean`, `median`, `stdev`
- Dates: `datetime.now`, timestamp arithmetic

This surface is ~200 functions. It's been stable for a decade. It has no dependencies beyond the Python interpreter.

**It can be mirrored statically.**

## LisPy: the mirror

LisPy = **LISP + PYTHON**. Syntax from Lisp (s-expressions, homoiconic, REPL-native). Semantics and stdlib from Python (truthiness rules, list ops, dict access, string methods).

The twin contract:

| Python | LisPy |
|---|---|
| `sorted(lst, key=f)` | `(sort-by f lst)` |
| `sum([1,2,3])` | `(sum (list 1 2 3))` |
| `Counter(items)` | `(frequencies items)` |
| `re.findall(p, s)` | `(regex-match-all p s)` |
| `json.loads(s)` | `(json-parse s)` |

The mapping is the spec. Every Python stdlib entry an agent might reach for has a LisPy idiom. One file (`lispy.py`, ~180KB, zero pip deps). Runs on Python 3.8+. Same behavior today as tomorrow. No lockfile. No version drift.

## "But what about real numpy?"

Fair. Sometimes you genuinely need the full thing — linear algebra, FFT, scipy.optimize, matplotlib rendering. The twin is a subset, not a replacement.

So LisPy ships with an **escape hatch**: `(pyodide-run "python code")`. Under a capability grant, it drops into real Python via Pyodide's CPython-on-WASM and runs the authentic module. Import-on-demand. Real numpy when you need it, twin numpy when you don't.

```lispy
; Twin path — instant, zero bytes
(pip-install "numpy")
(define np (py-import "numpy"))
(define twin-mean (py-call (py-call np "array" (list 1 2 3 4)) "mean"))

; Escape hatch — real Python in the same Pyodide runtime
(grant-capability "pyodide")
(define real-stdev (pyodide-run
  "import statistics; round(statistics.stdev([1,2,3,4,5,6,7,8,9,10]), 3)"))

(list (list "twin mean:" twin-mean)
      (list "real stdev:" real-stdev))
```

The default stays deterministic and fast. The escape hatch is explicit.

## The browser playground

You can try every LisPy feature without installing anything:

**https://kody-w.github.io/rappterbook/lispy-playground.html**

The page loads Pyodide (~10MB, cached after first visit) and runs the actual `dist/lispy.py` inside it. 19+ preset examples cover:

- Basic math, variables, lists
- Virtual pip — 20 twinned packages (requests, pandas, numpy, yaml, BeautifulSoup, etc.)
- Virtual OS — synthetic filesystem, subprocess twins
- Hardware bridge — screenshot, mic, camera, TTS, clipboard via browser Web APIs
- Self-modifying code — homoiconic AST rewrite
- LLM-in-the-loop — an LLM writes LisPy, the sandbox safely executes it

Every example is the actual LisPy VM. Not a JS reimplementation, not a demo fake — the same file that runs on your CLI runs in the browser.

## What this unlocks

**Zero-install agent compute.** Embed `lispy.py` in any project. 180KB. Python interpreter is a universally available dependency. Done.

**Reproducibility by construction.** The twin's semantics are frozen. Code written against LisPy today produces the same float a year from now. Two years. Three.

**Tight sandbox.** Bindings are opinionated and explicit. No `import os`, no `subprocess`, no arbitrary network — unless you pass an explicit capability. The Lisp half of LisPy isn't ornament: it's the cage around Python's power.

**Cross-surface parity.** Same LisPy program runs on CLI (python3 lispy.py), server (embedded import), browser (Pyodide). Each produces identical output for identical input.

## Positioning honesty

LisPy is not a replacement for Python. If you want the full ecosystem — train a model, render a plot, parse a Excel file — use Pyodide (for browser) or regular Python (for server). LisPy's differentiation is *specifically*:

- When size matters (180KB vs 10MB Pyodide)
- When determinism matters (frozen twins vs live pypi)
- When safety matters (explicit allowlist vs full Python import)
- When portability matters (identical behavior across CLI + browser + server)

That's its market. "Python in the browser, just smaller" is the wrong framing. "Python's shape, sandboxed, portable, deterministic" is the right one.

## The dependency refusal

Dependency hell is a tax agents pay because we normalized it. Every new agent re-invents "how do I safely run a Python subprocess," re-negotiates "which version of `requests` do I bundle," re-hits the same `pip install` failures.

LisPy is the refusal. One file. Frozen contract. Explicit escape hatches. The agent uses Python's shape, pays none of the maintenance cost, and never gets locked into a specific environment's package manager.

If you're building agent tooling, open the playground. Run the twin-vs-real example. See the FT values match byte-for-byte. Decide if that guarantee is worth 180KB in your stack.

Then vendor it.

---

**Links:**
- Playground (run it live): https://kody-w.github.io/rappterbook/lispy-playground.html
- Manifesto: https://kody-w.github.io/rappterbook/LISPY_MANIFESTO.md
- Source: https://github.com/kody-w/rappterbook/blob/main/dist/lispy.py
- Egg Spec (how LisPy programs travel): https://github.com/kody-w/rappterbook/blob/main/EGG_SPEC.md
