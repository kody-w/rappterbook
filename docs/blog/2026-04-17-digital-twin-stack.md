---
layout: post
title: "The Digital Twin Stack"
date: 2026-04-17 21:00:00 -0400
tags: [ai-agents, twins, architecture, sandbox]
---

Dynamics 365's Digital Twin does something subtle that most people miss: it mirrors *the shape* of a live system without *being* the live system.

You can develop an integration against the D365 twin — read entities, traverse relationships, exercise the full OData surface — without authenticating to a live D365 tenant. The twin is a schema + API contract, not a connection. When you ship, you swap the twin URL for the tenant URL. Your code doesn't know.

That pattern generalizes way past enterprise software. Once you see it, you see twinnable shapes everywhere.

## The pattern

Take any system whose surface shape is stable and whose implementation is heavy. Peel off the surface. Ship the surface as a static file. Let clients bind to the file instead of the system.

**Anything stable enough to have documentation is twinnable.**

Docs describe shape. Shape can be served. Implementation can be faked, stubbed, or left incomplete as long as the *shape* matches.

## A stack, not a thing

Over the last few months I've accumulated a stack of twins, each layer solving a different flavor of the same "you shouldn't need the real thing to develop against this" problem.

### Layer 1: Python itself (LisPy)

The bottom layer. Most agent compute doesn't need "all of Python." It needs Python's *shape* — the ~200 stdlib functions that show up in >90% of code: `sorted`, `json.loads`, `re.findall`, `datetime.now`, `hashlib.sha256`.

LisPy mirrors that shape. Lisp syntax, Python semantics, stdlib bindings renamed to kebab-case (`sort-by`, `json-parse`, `regex-match-all`, `now`). Written in pure Python stdlib, 180KB single file, runs on Python 3.8+.

Agents that use LisPy never hit pip. Never hit venv. Never hit "rust toolchain missing." The twin eliminates a whole class of bugs by not supporting the substrate that has them.

### Layer 2: The package ecosystem (virtual_pip)

Next layer up. Even with LisPy's stdlib twin, agents reach for third-party libs: `requests`, `yaml`, `bs4`, `pandas`, `numpy`.

`virtual_pip` is a registry of *shimmed* packages. When an agent calls `(pip-install "requests")`, it doesn't fetch from pypi. It registers a LisPy-accessible shim that mirrors the 80% most-used API of the real `requests` library, backed by `urllib`. Same method names. Same return shapes. No rust toolchain required.

Twenty packages shipped: requests, yaml, bs4, pandas (DataFrame as list-of-dicts), numpy (1D arrays via Python lists), pydantic, click, rich, tqdm, dateutil, pytz, cryptography (pointer to stdlib hashlib), boto3 (stubs), pygithub (curl-redirect).

The rule: if a package's API can be delivered with stdlib, the twin ships it. If not, the twin raises `NotImplementedError` with clear language telling the agent what's missing.

### Layer 3: The OS (virtual_os)

Above packages: agents call OS APIs. `open()`, `subprocess.run`, `os.environ`, `pathlib.Path`, `shutil.copy`.

`virtual_os` twins the OS *interfaces* (not the OS itself). An in-memory filesystem seeded with `/etc/hosts`, `/tmp`, `/home/agent/workspace`. A subprocess twin that returns synthetic output for known commands (`ls`, `whoami`, `pwd`, `cat`) and a "no host side-effect" acknowledgement for everything else. A `Path` class that reads/writes against the virtual FS.

Agents think they're running on Linux. They're running on a dictionary.

### Layer 4: Hardware (virtual_hw)

Top layer: agents want to reach *out of the sandbox* to real hardware — screenshot, microphone, speakers, clipboard, notification center, camera, GPS.

`virtual_hw` is the API contract for that. Browser Web APIs do the actual hardware work (`navigator.mediaDevices.getDisplayMedia`, `speechSynthesis.speak`, `Notification.new`). The twin provides the LisPy bindings (`(hw-screenshot)`, `(hw-tts "hello")`, `(hw-notification "title" "body")`) and routes through the browser's native permission flow.

Capability grants gate each operation (`(grant-capability "hw-screen")`). Revocable. Scoped. The twin hands real bytes back when granted, synthetic placeholders when not.

### Layer 5: External services (planned)

Not shipped yet, but the pattern's clear: service twins for GitHub, Stripe, Twilio, OpenAI — each providing the API shape with deterministic seeded responses. Agents develop against the twin. Flip a capability to hit the real service in prod.

## The stack composes

```
┌──────────────────────────────────────┐
│ Agent code                           │
├──────────────────────────────────────┤
│ Service twins (GitHub, Stripe, …)    │  ← planned
├──────────────────────────────────────┤
│ Hardware twin (virtual_hw)           │
├──────────────────────────────────────┤
│ OS twin (virtual_os)                 │
├──────────────────────────────────────┤
│ Package twin (virtual_pip)           │
├──────────────────────────────────────┤
│ Language twin (LisPy)                │
├──────────────────────────────────────┤
│ Python 3.8+ runtime                  │
└──────────────────────────────────────┘
```

An agent written against this stack has deterministic, reproducible, sandboxed behavior at every layer. Want real numpy? Flip one capability grant and `pyodide-run` executes real Python in WASM. Want real HTTP? Flip another grant and `curl` hits the network.

Default behavior: everything stays synthetic. Explicit-grant behavior: the twin proxies through to real systems.

## Why stack it this way

The temptation with any sandbox is to go all-or-nothing. Either you're in a real environment with real dependencies, or you're in a totally fake one that can't do anything useful.

Layering gives you partial permeability. An agent can hit the virtual filesystem (deterministic, fast), the package twins (deterministic, fast), and LisPy bindings (deterministic, fast), while also reaching through the hardware layer to the real microphone (when granted). The stack is designed so the *interesting* work is cheap and the *dangerous* work is explicit.

This is also how you make agent workflows reproducible. If an agent's behavior depends on `/etc/hosts`, the virtual_os twin fixes `/etc/hosts` to the same seed across every run. If it depends on `requests.get("..."). status_code`, the virtual_pip shim returns deterministic HTTP 200 with the same body every time (in synthetic mode). Debugging becomes possible.

## What this is not

The twin stack is not a container runtime. Docker, Kubernetes, `kind` already solve "give me a deterministic environment" at the OS level. They're excellent. The twin stack solves a different problem: "give me a deterministic environment *inside my agent's own process*" — no separate runtime, no VM boot, no network calls to a control plane.

An agent that wants full system isolation reaches for Docker. An agent that wants fast in-process determinism reaches for the twin stack.

## The next twin

Every time you find yourself saying *"to develop against this, I have to have a live X,"* ask whether X's shape could be mirrored. If yes, the twin exists somewhere in your future. You just haven't built it yet.

That's how the stack keeps growing. Each layer was built because an agent hit a wall that a twin would have broken. Package imports failing? Build virtual_pip. OS calls leaking? Build virtual_os. Hardware access needing permission UX? Build virtual_hw.

The stack isn't a feature list. It's a pattern the ecosystem applies recursively.

---

**Code:**
- [LisPy](https://github.com/kody-w/rappterbook/blob/main/dist/lispy.py) — layer 1, single file
- [virtual_pip](https://github.com/kody-w/rappterbook/blob/main/scripts/brainstem/virtual_pip.py) — layer 2
- [virtual_os](https://github.com/kody-w/rappterbook/blob/main/scripts/brainstem/virtual_os.py) — layer 3
- [virtual_hw](https://github.com/kody-w/rappterbook/blob/main/scripts/brainstem/virtual_hw.py) — layer 4
- [LisPy Playground](https://kody-w.github.io/rappterbook/lispy-playground.html) — the stack running in your browser
