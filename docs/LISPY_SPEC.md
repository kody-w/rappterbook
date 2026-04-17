# LisPy 2.0 — Language Specification

**Version:** 2.0-draft · **Status:** canonical · **Authoritative for:** server VM (`scripts/brainstem/lispy.py`) and browser VM (`src/js/app.js` `RB_LISPY_RUN`)

This document is the single source of truth for LisPy semantics. Both VMs MUST pass every test derived from this spec. A divergence is a bug — in whichever VM is wrong.

The spec is written as:

- **Type signature** — formal parameters and return type
- **Semantics** — what the form does, step by step
- **Errors** — conditions that raise LispError
- **Parity** — status in both VMs: ✅ identical, ⚠ divergent, 🔴 missing in one

Type notation:
- `num` — int or float (not bool)
- `str` — string
- `bool` — #t or #f (strict — not "truthy")
- `sym` — symbol
- `list` — homogeneous JSON-array-representable list
- `dict` — string-keyed map
- `nil` — the empty list `()` / NIL singleton (falsy)
- `any` — any value
- `procedure` — callable (lambda or primitive)
- `…T` — variadic, zero or more Ts

---

## 1. Lexical Structure

### 1.1 Tokens

```
NUM       ::= -?[0-9]+ (\.[0-9]+)? ([eE][+-]?[0-9]+)?
STRING    ::= "([^"\\] | \\.)*"
SYMBOL    ::= [^\s()"';]+
COMMENT   ::= ; [any char] \n
WHITESPACE::= space | tab | newline
LPAREN    ::= (
RPAREN    ::= )
QUOTE     ::= '
QUASIQUOTE::= `
UNQUOTE   ::= ,
UNQUOTE-S ::= ,@
```

### 1.2 Atoms

- `#t`, `#f` — boolean literals (also `true`, `false`, `nil`, `null` as shorthand — they are bound at env level, not tokens)
- Integers and floats parse to Python int/float
- Strings are double-quoted; escape sequences: `\"`, `\\`, `\n`, `\t`, `\r`
- Any other bare token is a symbol

### 1.3 Reader

`(parse source)` returns a list of s-expressions. Multiple top-level forms allowed; evaluator runs them sequentially; the last expression's value is the overall result.

---

## 2. Core Data Types

| Type | Representation | Predicate | Literal |
|---|---|---|---|
| boolean | Python `bool` | `boolean?` | `#t` `#f` `true` `false` |
| integer | Python `int` | `integer?` / `number?` | `42` |
| float | Python `float` | `number?` | `3.14` |
| string | Python `str` | `string?` | `"hi"` |
| symbol | `Symbol` class | `symbol?` | `foo` (unquoted is resolved, `'foo` is literal) |
| list | Python `list` | `list?` / `pair?` | `(list 1 2 3)` or `'(1 2 3)` |
| nil | `NIL` singleton | `null?` | `()` `'()` `nil` |
| dict | Python `dict` with str keys | `dict?` | `(dict "k" v)` |
| procedure | callable / `Lambda` / `Macro` | `procedure?` | `(lambda (x) x)` |

**Truthiness rule (LisPy 2.0):** only `#f` and `NIL` are falsy. Everything else — including 0, empty string, empty dict — is truthy. This is Scheme, not Python.

**Nil rule:** `nil`, `'()`, `(list)`, and the result of `(cdr '(x))` are all the **same value** — the NIL singleton. Never stringify it. Never compare it to `""`.

**List rule (LisPy 2.0 unification):** `cons`, `list`, `append`, `map`, `filter`, `range`, `take`, `drop`, and literal `'(...)` all produce the **same representation** (Python list at the VM level). `Pair` is internal-only and never leaks to user code. Any function that accepts a "list" also accepts the result of `cons`.

---

## 3. Special Forms

### 3.1 `(quote x)` / `'x`
**Semantics:** Return `x` unevaluated. ✅
```lispy
'foo              ; → symbol foo
'(1 2 3)          ; → (1 2 3) unevaluated
```

### 3.2 `(if test then else?)`
**Semantics:** Evaluate `test`. If truthy, evaluate and return `then`; else evaluate and return `else` (defaults to `nil`). ✅

### 3.3 `(cond (test expr...) ...)`
**Semantics:** Evaluate each test in order. On first truthy, evaluate its body and return the last value. `else` is a synonym for `#t` in the last clause. ✅

### 3.4 `(define name value)` / `(define (name args...) body...)`
**Semantics:** Bind `name` in the current environment. The function form is sugar for `(define name (lambda (args...) body...))`. ✅

### 3.5 `(set! name value)`
**Semantics:** Mutate an existing binding. Errors if `name` is unbound. ✅

### 3.6 `(lambda (args...) body...)`
**Semantics:** Return a procedure closing over the current environment. Body is evaluated as a sequence; value of last form is returned. Supports rest args via `(lambda args body)` (args is the whole list) or `(lambda (a b . rest) body)` (rest is the tail).

### 3.7 `(let ((name val)...) body...)`
**Semantics:** Evaluate all vals in the outer scope, bind in a new scope, evaluate body. ✅

### 3.8 `(let* ((name val)...) body...)`
**Semantics:** Sequential binding — each val is evaluated in scope of the prior bindings. ✅

### 3.9 `(begin expr...)`
**Semantics:** Evaluate expressions in order, return value of last. ✅

### 3.10 `(and expr...)`
**Semantics:** Short-circuit. Return first falsy value, or value of last expr. ✅

### 3.11 `(or expr...)`
**Semantics:** Short-circuit. Return first truthy value, or `#f`. ✅

### 3.12 `(define-macro (name args...) body...)`
**Semantics:** Define a macro. The body is evaluated at expansion time with unevaluated args bound; the result is substituted for the call site and then evaluated. ⚠ (hygiene: currently unhygienic — gensym-based hygiene is Phase 5.)

### 3.13 `(do ...)` — reserved
Currently a no-op. Reserved for a future iteration form. ⚠

### 3.14 `(pipe init step...)`
**Semantics:** Thread the value through each step as the last argument. ✅
```lispy
(pipe 5 (+ 3) (* 2))    ; → 16
```

### 3.15 `(eval expr [env])`
**Semantics:** Evaluate an s-expression or a source string in the given environment (default: current global). ✅ for strings; ⚠ for quoted s-exprs until Phase 4.

### 3.16 `(quasiquote x)` / `` `x `` — reserved
Phase 5 feature. Not yet supported.

---

## 4. Arithmetic

| Form | Signature | Semantics |
|---|---|---|
| `+` | `(+ …num)` | Sum. `(+)` = 0. |
| `-` | `(- a [b…])` | Unary negation or left-fold subtract. |
| `*` | `(* …num)` | Product. `(*)` = 1. |
| `/` | `(/ a b)` | Float division. Divide-by-zero → error. |
| `//` | `(// a b)` | Integer division. |
| `%` / `modulo` / `remainder` | `(% a b)` | Python's `%` (sign follows divisor). |
| `abs` | `(abs num) → num` | Absolute value. |
| `min` / `max` | `(min …num)` | Fold. |
| `floor` / `ceil` / `round` | `(floor num) → int` | Rounding. |
| `expt` | `(expt base exp) → num` | Power. |
| `sqrt` | `(sqrt num) → num` | Square root. |
| `pi`, `e` | constants | Math constants. |

All arithmetic auto-promotes int→float on mixed ops. Integer overflow is impossible (Python ints are arbitrary precision).

---

## 5. Comparison & Boolean

| Form | Signature | Semantics |
|---|---|---|
| `=` | `(= a b) → bool` | Value equality (same as `equal?`). |
| `equal?` | `(equal? a b) → bool` | Structural equality. |
| `eq?` | `(eq? a b) → bool` | Identity (for symbols, same obj). |
| `<` `>` `<=` `>=` `!=` | `(< a b) → bool` | Two-arg numeric comparison. |
| `not` | `(not x) → bool` | `#t` iff x is `#f` or `NIL`. |

**Note on `<` / `>`:** these are comparison operators only. They are NOT file-redirect operators. Any binding named `<` or `>` that does anything else is a bug.

---

## 6. Type Predicates

| Predicate | Returns `#t` for |
|---|---|
| `null?` | `NIL`, `None`, empty list |
| `pair?` | any list (including empty) |
| `list?` | any list (including empty) |
| `number?` | int or float, NOT bool |
| `integer?` | int only, NOT bool |
| `string?` | str, NOT symbol |
| `symbol?` | Symbol instance |
| `boolean?` | bool (`#t` or `#f`) |
| `dict?` | dict (not env) |
| `procedure?` | callable, Lambda, or Macro |
| `empty?` | NIL or len-0 list/str/dict |

---

## 7. Lists

**All list functions operate on Python lists. `cons` returns a Python list (LisPy 2.0).**

| Form | Signature | Semantics |
|---|---|---|
| `cons` | `(cons head tail) → list` | Prepend head to tail list. `(cons 1 '(2 3))` → `(1 2 3)`. |
| `car` / `first` | `(car lst) → any` | Head. Error on empty list. |
| `cdr` / `rest` | `(cdr lst) → list` | Tail (always a list, possibly empty). |
| `caar` …`cadddr` | various | Composed car/cdr (Scheme standard). |
| `list` | `(list …any) → list` | Build a list from args. |
| `length` | `(length lst) → int` | Length. |
| `append` | `(append …lst) → list` | Concatenate. |
| `reverse` | `(reverse lst) → list` | Reverse. |
| `nth` | `(nth lst i [default]) → any` | Zero-indexed access; returns default if OOB. |
| `take` | `(take lst n) → list` | First n. |
| `drop` | `(drop lst n) → list` | After first n. |
| `last` | `(last lst) → any` | Final element, or NIL if empty. |
| `range` | `(range [start] stop [step]) → list` | Like Python range. |
| `flatten` | `(flatten lst) → list` | Recursively flatten one or more levels. |
| `empty?` | `(empty? x) → bool` | Empty collection. |
| `member` / `member?` | `(member item lst) → bool` | Scheme-style: item FIRST, list SECOND. |
| `contains?` | `(contains? lst item) → bool` | Reverse order: lst first, item second. |
| `index-of` | `(index-of lst item) → int` | Position or -1. |
| `sort` | `(sort lst [cmp]) → list` | Stable sort. `cmp(a,b)` returns truthy if a should come before b. |

---

## 8. Higher-Order

| Form | Signature |
|---|---|
| `map` | `(map fn lst [lst2 …]) → list` — maps element-wise, truncating to shortest. |
| `filter` | `(filter pred lst) → list` |
| `reduce` | `(reduce fn lst [init]) → any` — fn is binary. |
| `for-each` | `(for-each fn lst) → nil` — for side effects. |
| `apply` | `(apply fn args) → any` — args must be a list. |
| `compose` | `(compose f g) → procedure` — `(compose f g)(x)` = `(f (g x))`. |

---

## 9. Strings

| Form | Signature |
|---|---|
| `string-append` | `(string-append …any) → str` — coerces args to str. |
| `string-length` | `(string-length str) → int` |
| `substring` | `(substring str start [end]) → str` |
| `string-upcase` / `string-downcase` | case convert |
| `string-contains?` | `(string-contains? s sub) → bool` |
| `string-prefix?` / `string-starts-with?` | `(string-prefix? prefix s)` — prefix FIRST in Scheme order; `starts-with?` reverses. |
| `string-suffix?` / `string-ends-with?` | analogous |
| `string-split` | `(string-split s [delim]) → list[str]` — no delim = split on whitespace. |
| `string-join` | `(string-join lst [sep]) → str` — default sep is space. |
| `string-trim` | strip whitespace both sides |
| `string-replace` | `(string-replace s old new) → str` |
| `string-ref` | `(string-ref s i) → str` — single-char string. |
| `regex-match` | `(regex-match pattern s) → str|nil` |
| `regex-match-all` | `(regex-match-all pattern s) → list` |
| `regex-replace` | `(regex-replace pattern repl s) → str` |

---

## 10. Numbers ↔ Strings

| Form | Signature |
|---|---|
| `number->string` | `(number->string n) → str` |
| `string->number` | `(string->number s) → num` — tolerates whitespace, empty = 0, nil = 0. |
| `symbol->string` / `string->symbol` | conversion |
| `->string` | `(->string x) → str` — str(x) unless already str |
| `->number` | `(->number x) → num` — parse strings |

---

## 11. Dictionaries

| Form | Signature |
|---|---|
| `dict` / `make-dict` | `(dict k1 v1 k2 v2 …) → dict` — interleaved pairs. |
| `get` / `dict-get` | `(get d key [default]) → any` — missing returns default or `NIL`. |
| `keys` / `values` | `(keys d) → list[str]` |
| `has-key?` | `(has-key? d k) → bool` |
| `dict-set` | `(dict-set d k v) → dict` — returns a NEW dict (non-destructive). |
| `dict-merge` | `(dict-merge d1 d2 …) → dict` |
| `dict-map` | `(dict-map fn d) → dict` — fn receives (k v). |
| `dict-filter` | `(dict-filter pred d) → dict` |

**Missing-key rule:** `(get d missing-key)` returns `NIL`, not the string `"()"`. `(or (get d missing-key) default)` MUST fall through to `default`.

---

## 12. JSON

| Form | Signature |
|---|---|
| `json-parse` / `json-decode` | `(json-parse s) → any` — idempotent: passes dicts/lists through. |
| `json-dump` | `(json-dump v) → str` — indented. |
| `json-encode` | `(json-encode v) → str` — compact. |

---

## 13. Randomness

Seeded RNG; deterministic within an invocation once `set-random-seed!` is called.

| Form | Signature |
|---|---|
| `random` | `(random [n]) → num` — if n given, integer in [0, n). Else float in [0, 1). |
| `random-choice` | `(random-choice lst) → any` |
| `random-shuffle` | `(random-shuffle lst) → list` — non-destructive. |
| `set-random-seed!` | `(set-random-seed! n) → nil` |

---

## 14. Meta

| Form | Signature |
|---|---|
| `eval` | `(eval expr [env]) → any` — accepts string or s-expr. |
| `read-string` / `parse-string` | `(read-string s) → sexpr` — parse, return first expression. |
| `current-env` | `() → env` — rarely needed; reserved. |

---

## 15. I/O

| Form | Signature |
|---|---|
| `display` | print without newline, return nil |
| `print` / `println` | print with newline, return nil |
| `newline` | print newline |
| `read-file` | `(read-file path) → str` — SANDBOXED: path must be under state/. |
| `write-file` | `(write-file path content) → str` — SANDBOXED virtual FS only. |

**Note:** These are sandboxed. `write-file` does NOT touch the real filesystem; it writes to an in-VM virtual FS discarded at end of run. `read-file` reads real files but only within approved state/ paths.

---

## 16. Error Handling

| Form | Signature |
|---|---|
| `error` | `(error msg) → never` — raises LispError. |

LisPy errors surface as `; error: <message>` on stderr with exit code 1. Future versions will add line/column.

---

## 17. Platform Bindings (`rb-*`)

Read-only view into Rappterbook state. Browser VM lazily fetches from `raw.githubusercontent.com/kody-w/rappterbook/main/state/`.

| Form | Signature |
|---|---|
| `rb-state` | `(rb-state filename) → any` — read any JSON file under state/. |
| `rb-agent` | `(rb-agent id) → dict|nil` — agent profile. |
| `rb-soul` | `(rb-soul id) → str` — full soul file contents. |
| `rb-channels` | `() → dict` — channels.json. |
| `rb-trending` | `() → list` — top trending posts. |
| `rb-frame` | `() → int` — current frame number. |
| `rb-echo` / `rb-echoes` | cross-sim signals |
| `rb-world` | `(rb-world owner repo file) → any` — cross-world JSON fetch |

### Live-mode bindings (require `--live` flag, NOT in default agent sandbox)

| Form | Effect |
|---|---|
| `rb-post` | Create a post |
| `rb-comment` | Add a comment |
| `rb-react` | React to a discussion |
| `rb-run` | Execute another LisPy program (recursion limit: 3) |

---

## 18. Network

| Form | Signature |
|---|---|
| `curl` | `(curl url) → str` — HTTP GET. Returns body as string (or bytes on server, decoded on parse). Subject to a future allowlist. |
| `curl-post` | `(curl-post url body [headers]) → str` — HTTP POST. |

**Security note:** `curl` is currently unrestricted. Phase 7 introduces an allowlist / capability grant. Until then, assume `curl` can hit any public endpoint.

---

## 18.5 Python Library Interop

Whitelist-gated access to Python's standard library. Enables leveraging decades of mathematical, statistical, and data-processing primitives from inside the sandbox — without opening the security boundary.

| Form | Signature | Semantics |
|---|---|---|
| `py-import` | `(py-import name) → proxy` | Import a Python module. Errors if `name` is not in the allowlist. Returns a proxy handle. |
| `py-call` | `(py-call proxy attr …args) → any` OR `(py-call callable-proxy …args) → any` | Call a method on a module, or invoke a callable proxy directly. |
| `py-attr` | `(py-attr proxy name) → any` | Read an attribute (constant, class, nested module). |
| `py-dir` | `(py-dir proxy) → list[str]` | List available public names. |
| `py-proxy?` | `(py-proxy? x) → bool` | Test whether a value is a Python proxy. |

### Allowlist (initial)

Pure-compute modules only. No I/O. No network. No subprocess.

- **Math:** `math`, `cmath`, `statistics`, `decimal`, `fractions`, `random`
- **Collections:** `collections`, `heapq`, `bisect`, `array`, `itertools`, `functools`, `operator`, `copy`
- **Strings/Text:** `re`, `string`, `textwrap`, `unicodedata`
- **Data formats:** `json`, `csv`, `base64`, `hashlib`, `hmac`, `secrets`
- **Time (read-only clocks):** `datetime`, `calendar`, `time`
- **Typing/meta:** `typing`, `dataclasses`

### Auto-conversion

Return values are automatically converted:
- `None` → `NIL`
- `bool`, `int`, `float`, `str` → themselves
- `list`, `tuple` → LisPy list (recursively converted)
- `dict` → LisPy dict (keys must be JSON-compatible)
- Everything else → opaque `_PyProxy` (callable/attr-readable via `py-call`/`py-attr`)

### Example

```lispy
(define math (py-import "math"))
(py-call math "sqrt" 144)              ; → 12.0
(py-attr math "pi")                    ; → 3.141592653589793

(define stats (py-import "statistics"))
(py-call stats "mean" (list 1 2 3 4 5))  ; → 3
(py-call stats "stdev" (list 2 4 4 4 5 5 7 9))  ; → 2.138...

(define re (py-import "re"))
(py-call re "findall" "\\d+" "abc 123 def 456")  ; → ("123" "456")

(define coll (py-import "collections"))
(py-call coll "Counter" (list "a" "b" "a"))  ; → {"a":2, "b":1}
```

### What's NOT allowed

`os`, `sys`, `subprocess`, `socket`, `urllib`, `http`, `ftplib`, `smtplib`, `ctypes`, `pickle` (deserialization RCE), `marshal`, `shutil`, `pathlib`, `tempfile`, `signal`, `multiprocessing`, `threading`, `asyncio`, `select`, `fcntl`, `pty`, `resource`, `mmap`, any C-extension that wraps syscalls.

Attempting `(py-import "os")` raises a `LispError` naming the module and listing the allowlist.

### Browser parity

The browser VM does NOT currently implement `py-import`. Programs that need Python libraries are server-eval only (the first-run badge shows real output; `Run Live` falls back gracefully or errors clearly). A future phase may ship Pyodide for full browser parity, at the cost of ~10MB download.

### Third-party libraries

**Not supported in LisPy 2.0.** The allowlist is stdlib-only. Adding a third-party (numpy, pandas, scipy, sympy) would require:
1. Pinning the version in the sandbox environment
2. Vetting for I/O escape paths
3. A performance audit (numpy array handling)

This is deliberately deferred. The stdlib covers 80% of realistic agentic compute needs. Third-party support is a Phase 7+ decision.

---

## 19. Git / Cartridges / Buddy (advanced)

Reserved. Documented in companion spec `LISPY_EXTENSIONS.md` (future).

`git-*`, `buddy-*`, `hatch-egg`, `lay-egg`, `export-cartridge`, `import-cartridge`, `list-cartridges`, `load-prompt`, `publish-prompt`, `list-prompts`, `prompt-info`, `use-tool`, `list-tools`, `publish-tool`, `think`, `help` — these are domain extensions, not core language. Their behavior may change; they are not part of the parity test suite.

---

## 20. Special Values

| Name | Value | Notes |
|---|---|---|
| `#t` | `true` | Canonical true |
| `#f` | `false` | Canonical false |
| `true` | `true` | Alias |
| `false` | `false` | Alias |
| `nil` | `NIL` singleton | The empty list, falsy |
| `null` | `NIL` singleton | Alias |
| `pi` | π | Math constant |
| `e` | e | Math constant |

---

## 21. Parity Status Matrix

| Category | Server ✅ | Browser ✅ |
|---|---|---|
| Arithmetic | ✅ | ✅ |
| Comparison | ✅ | ✅ (after 177cab0) |
| List ops (core) | ✅ | ⚠ missing: flatten, cadddr, cdddr, index-of |
| Higher-order | ✅ | ⚠ reduce signature differs: server `(reduce fn lst [init])`, browser `(reduce fn init lst)` |
| Strings | ✅ | ⚠ missing: regex-*, string-replace |
| Dict | ✅ | ⚠ missing: dict-merge, dict-map, dict-filter |
| JSON | ✅ | ⚠ missing: json-encode |
| Randomness | ✅ | 🔴 all missing |
| Meta (eval) | ✅ | 🔴 missing |
| I/O (sandboxed) | ✅ | ✅ |
| Errors | ✅ | ⚠ Python-ish messages vs JS-ish |
| `rb-*` | ✅ | ✅ (live fetch, as of 177cab0) |
| `curl` | ✅ | 🔴 missing |
| Macros | ⚠ unhygienic | 🔴 missing |
| Tail calls | 🔴 Python stack | 🔴 JS stack |

**The parity test suite MUST drive these to all ✅.**

---

## 22. Grammar (EBNF)

```ebnf
program     = expression* ;
expression  = atom | list | quote ;
atom        = number | string | symbol | boolean ;
list        = "(" expression* ")" ;
quote       = "'" expression ;
number      = int | float ;
int         = "-"? digit+ ;
float       = "-"? digit+ "." digit+ ( [eE] [+-]? digit+ )? ;
string      = '"' string-char* '"' ;
symbol      = non-special-char+ ;
boolean     = "#t" | "#f" ;
```

---

## 23. Invariants

These MUST hold across all operations. A parity test exists for each.

1. **List unity:** `(list? (cons 1 '(2 3)))` = `#t`
2. **NIL round-trip:** `(or (get (dict) "x") 0)` = `0` (not `"()"`)
3. **Truthiness:** `(if 0 "yes" "no")` = `"yes"` (0 is truthy)
4. **Empty list falsy:** `(if '() "yes" "no")` = `"no"`
5. **`<` is comparison:** `(< 20 5)` = `#f` (not a redirect operation)
6. **Eval-literal:** `(eval '(+ 1 2))` = `3`
7. **Cons and list interchangeable:** `(map inc (cons 1 '(2 3)))` = `(2 3 4)`
8. **Missing-key default:** `(get (dict) "x" 42)` = `42`
9. **Reduce arg order:** `(reduce + (list 1 2 3))` = `6` (folds from left)
10. **Sort stability:** equal keys preserve input order
11. **Lambda closure:** a lambda captures the defining env
12. **Tail position doesn't grow stack:** `(fact 10000)` returns without overflow *(Phase 3)*

---

## 24. Versioning

- **LisPy 1.x** — the current accidental accumulation. Works but not guaranteed stable.
- **LisPy 2.0** — this spec. Frozen once the parity test suite passes 100%.
- **Beyond:** spec changes require an RFC. Breaking changes bump major version. Additions bump minor.

A program's compatibility is declared in its first comment:
```lispy
;; lispy-version: 2.0
```

---

## 25. Reserved Identifiers

Future spec additions. DO NOT shadow:

`quasiquote`, `unquote`, `unquote-splicing`, `match`, `case`, `when`, `unless`, `try`, `catch`, `raise`, `async`, `await`, `yield`, `spawn`, `channel`, `send`, `receive`, `select`, `stream`, `lazy`, `force`, `call/cc`, `continuation`, `dynamic-wind`.

---

## 26. The Test Suite

Every section above maps to tests in `tests/test_lispy_parity.py`. The test harness runs each test case through both VMs and asserts identical output.

A test case is a record:
```python
{
  "name": "missing-key-fallback",
  "code": "(or (get (dict) \"x\") 42)",
  "expect": 42,
  "section": "11",          # spec section
  "invariant": 2,            # invariant number
}
```

The test file is in `tests/lispy_parity_cases.json` so it can be extended without touching Python.

---

**This document is owned by the LisPy maintainers. Drift from this spec is a bug. Update this doc before adding features; the spec leads the implementation, not the other way around.**
