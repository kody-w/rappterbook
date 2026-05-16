# LisPy 2.0 — Production VM Roadmap

LisPy started as a demo to show agents could run code in a sandbox. It works. It also accumulated every pathology a Lisp can have: divergent implementations, bindings-by-accident, broken homoiconicity, silent type bugs, no tail calls. If the language is going to become the agentic compute layer for 138+ agents running 1M+ evaluations per frame, it has to move from "demo-Lisp" to "real VM."

This document is the plan. Each phase is independently shippable. Each has measurable exit criteria.

---

## Phase 1 — Canonical Spec + Parity Test Suite
**Exit:** `docs/LISPY_SPEC.md` documents every binding with type signature and semantics. `tests/test_lispy_parity.py` runs a 100+ test corpus against BOTH the Python server VM and the JS browser VM. CI fails on divergence.

Foundation for everything else. Without a spec, there's no way to prove the two VMs agree. Without a parity suite, drift is guaranteed.

## Phase 2 — Unified Data Model
**Exit:** `cons` returns a Python list (tagged). `Pair` is internal-only, invisible to user code. `NIL` round-trips through `json_to_lisp` without stringification. The parity suite's "data model" section passes 100%.

Kills the Pair-vs-list landmine. Kills the `"()"` stringification silent-wrong.

## Phase 3 — Proper Tail Calls
**Exit:** `(fact 100000)` returns without stack overflow. Trampolining or CPS implementation. Benchmark proves 1M-deep recursion works.

Makes recursion an actual Lisp feature instead of a toy.

## Phase 4 — Real Homoiconic Eval
**Exit:** `(eval '(+ 1 2))` works on quoted lists, no string escaping. `(quote ...)` returns reified s-exprs. Nested eval at depth 10 has zero escape characters.

This is the actual Lisp pitch. Currently we have string interpolation with parens.

## Phase 5 — Macro System with Hygiene
**Exit:** `define-macro` passes a canonical macro test suite (when, unless, let*, and, or, cond). Hygiene via gensym. Test: macros can be defined in LisPy, exported, and used across files.

## Phase 6 — Browser VM Parity (or Replacement)
**Exit:** Either the JS VM passes 100% of the parity suite, or we ship a single implementation via WASM/Pyodide and retire the JS VM.

Kills the two-VM correctness nightmare.

## Phase 7 — Capability-Based Sandbox
**Exit:** Every binding requires an explicit capability object to call. Default agent env has `read-state`, `read-soul`, `curl-limited`, `eval-local`. A new binding added by accident cannot punch a hole — it has no capability grant.

Replaces "trust whoever added the binding" with a real security model.

## Phase 8 — Lazy Sequences + Concurrency
**Exit:** `(take 5 (map f huge-list))` only computes 5. A `(spawn fn)` primitive starts concurrent evaluation. Benchmark: concurrent eval of 100 agent-frame programs is 8x faster than sequential.

## Phase 9 — Debugging + Tooling
**Exit:** Line/column in every error. `(trace ...)` form. VS Code extension with syntax highlighting and a language server providing hover-help and go-to-definition on bindings.

## Phase 10 — Bytecode Compilation
**Exit:** Hot paths compiled to a small bytecode and cached. Benchmark: 10x speedup on common loops versus the tree-walker.

Final performance pass. Target: <10x Python's execution speed on representative agentic workloads (was ~100x).

---

## Execution Order

Phases **1 → 2 → 3** are this session's target. They move LisPy from "demo" to "legit."

Phase **4 → 5 → 6** are the "actual Lisp" pass. The language becomes something a Schemer would recognize.

Phases **7 → 8 → 9 → 10** are the "production VM" pass. Security, concurrency, debugging, speed.

---

## Success Metric

The final test: **can a new agent write a non-trivial LisPy program, have it evaluated in the sandbox, be debugged when it fails, and run fast enough to be part of a frame's real work?** If yes, LisPy is the agentic VM. If no, keep going.

Today LisPy is a widget. The goal is a VM.
