---
created: 2026-04-18
platform: reddit
status: draft
subreddit: r/Python
title: "LisPy: Python's digital twin as a zero-dep single-file runtime for AI agent sandboxes"
source: python-dependency-refusal-lispy
register: reddit-post
---

# LisPy: Python's digital twin as a zero-dep single-file runtime

Writing this up because I've seen a few discussions here about pip hell in AI agent contexts, and I've been using a different approach that might be interesting to compare notes on.

**Context**

Every AI agent that needs to compute hits a wall: `pip install` failures, version conflicts between native extensions, `torch==2.1.0` vs `torch==2.2.0` dependency chains, "works on my machine" broken by the fresh `/tmp/` clone the agent just made. You know the pattern.

For a certain class of agent workload — *"I need Python's *shape*, not all of Python"* — there's a cleaner path.

**The idea**

Most agent compute needs maybe 200 stdlib functions. `sorted`, `json.loads`, `re.findall`, `datetime.now`, `hashlib.sha256`, `Counter`, `itertools.chain`. That surface is stable, well-documented, and has no external dependencies.

So I mirrored it into a single-file runtime called LisPy. Lisp syntax, Python semantics, stdlib bindings under kebab-case names.

```
Python                          LisPy
sorted(lst, key=f)              (sort-by f lst)
sum([1, 2, 3])                  (sum (list 1 2 3))
Counter(items)                  (frequencies items)
re.findall(p, s)                (regex-match-all p s)
json.loads(s)                   (json-parse s)
```

Single file, 180KB, zero pip deps, pure Python stdlib. Runs on Python 3.8+. Same bindings today as a year from now.

**Why not just use Pyodide?**

Fair question. Pyodide is great. It's CPython compiled to WASM — runs full Python in the browser, supports micropip, can load real numpy/pandas/scipy as pre-built wheels.

LisPy differentiates in specific cases:

| Concern | LisPy | Pyodide |
|---|---|---|
| Bundle size | 180KB | ~10MB initial |
| Determinism | Frozen twin semantics | Live pypi via micropip |
| Browser-only? | No — runs on CLI/server too | Browser/wasi only |
| Sandbox | Opinionated allowlist | Full Python import |
| Real numpy | Via escape hatch (see below) | Native |

LisPy's market is: when size matters OR when determinism matters OR when you want identical behavior across CLI+browser+server OR when you want a tight sandbox by default. Pyodide is the right call for browser data science with the full ecosystem.

**The escape hatch**

When you genuinely need real Python — say, FFT, matrix ops, scipy.optimize — LisPy in the browser ships a `pyodide-run` binding that drops into Pyodide's CPython runtime:

```lispy
; Twin path — instant, zero bytes
(pip-install "numpy")
(define np (py-import "numpy"))
(py-call (py-call np "array" (list 1 2 3 4 5)) "mean")

; Escape hatch — real Python
(grant-capability "pyodide")
(pyodide-run "import statistics; statistics.stdev([1,2,3,4,5,6,7,8,9,10])")
```

Default stays deterministic and fast. Real Python is explicit, gated by capability grants.

**Try it**

Playground (runs in browser, loads Pyodide, runs actual `dist/lispy.py` inside it):
https://kody-w.github.io/rappterbook/lispy-playground.html

19 preset examples cover virtual pip (20 twinned packages: requests, pandas, numpy, yaml, bs4, pydantic, click, rich, etc.), virtual OS (synthetic filesystem, subprocess twins), hardware bridge (screenshot/mic/clipboard via browser Web APIs), self-modifying code, LLM-in-the-loop sandbox.

Source file: https://github.com/kody-w/rappterbook/blob/main/dist/lispy.py

Writeup: https://kody-w.github.io/rappterbook/blog/#/post/python-dependency-refusal-lispy

**Happy to answer questions**

Particularly curious if anyone else here has shipped a similar "Python-shape twin" approach for sandboxed agent workloads. The closest thing I've found is RestrictedPython (old, hard to maintain) and various "use Lua instead" Bluesky moves. LisPy's specific bet is that keeping Python's semantics + stdlib shape (vs. rewriting in a different language) is worth the embedded-cost of a big stdlib surface.
