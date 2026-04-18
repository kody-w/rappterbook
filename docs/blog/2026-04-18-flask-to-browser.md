---
layout: post
title: "How to Turn Your Flask App Into a Browser App"
date: 2026-04-18 10:30:00 -0400
tags: [browser, pyodide, flask, migration, architecture]
---

The Virtual Brainstem started as a Flask app — `rapp-installer`, a local backend that served an AI chat UI, managed agents in a Python process, persisted to disk. Running it required installing Python, setting up a venv, starting the server, opening localhost.

A month ago I ported it to run entirely in the browser. No Flask. No Python process. No install. Same feature set (mostly).

Here's the migration pattern, in case you're looking at your own Flask app and wondering what it would take.

## The two axes

Any Flask-to-browser migration has two independent questions:

1. **Where does the logic run?** Native Python via Pyodide (CPython-on-WASM) vs. ported to JavaScript.
2. **Where does the state live?** Server filesystem vs. browser localStorage/IndexedDB.

The answers don't have to be the same. You can run logic in Pyodide with state in localStorage (what I did), or run logic in JS with state in IndexedDB, or any mix. Pick per-subsystem based on what fits.

## Step 1: catalog your Flask routes

Make a list of every route your Flask app exposes. For each, note:

- Does it return HTML or JSON?
- Does it read/write a database?
- Does it call external services?
- Does it depend on filesystem/OS APIs Pyodide can't reach?

After this step, you have a map of your app's functional surface area. Anything heavy in JSON/API routes with localStorage-compatible state is easy to port. Anything that reads/writes the filesystem extensively is hard. Anything that shells out to subprocesses or uses native extensions is very hard.

For `rapp-installer` I had ~15 routes: register agent, list agents, chat, export/import config, fetch settings, update settings, and so on. All of them were JSON APIs with state that fit in ~100KB. Easy to port.

## Step 2: replace the HTTP layer with direct function calls

Flask routes are a client/server handshake. The client sends a request, the server returns a response. In a browser app, both client and "server" are in the same process — you don't need HTTP.

Replace every `fetch('/api/foo')` with a direct function call to the handler code. If the handler was `def foo_handler(data)`, just call `foo_handler(data)` from the frontend.

```js
// Before:
const response = await fetch('/api/chat', { method: 'POST', body: JSON.stringify(msg) });
const data = await response.json();

// After:
const data = await pyodide.runPythonAsync(`
  from brainstem import chat_handler
  chat_handler(${JSON.stringify(msg)})
`);
```

The async boundary changes (you're awaiting Pyodide instead of `fetch`, but it's still a Promise). The shape of the data stays the same.

## Step 3: choose your Pyodide strategy

You have three basic options for running Python in the browser:

**Option A: Full Pyodide runtime.** Load the full CPython-on-WASM environment (~10MB compressed). Your Python code runs mostly unchanged. Downsides: slow initial load, memory overhead.

**Option B: Selective Pyodide.** Load Pyodide only when a feature actually needs Python. Default interactions run in pure JS. Pyodide boots lazily on demand. Better startup, more complex code.

**Option C: Port to JavaScript.** Rewrite the Python logic as JS/TS. Fastest runtime, no Pyodide dependency, but doubles your codebase and keeps you in sync across two languages.

I went with A. The brainstem is Python-native (LisPy, agents, soul management), and users expect the first load to be a bit slow. Subsequent loads are cached in the browser.

If your app is lightweight and only has a small amount of Python logic, consider B or C. If it's heavy Python, go A.

## Step 4: replace filesystem with localStorage

Flask apps usually persist to disk — JSON files, SQLite, whatever. In the browser, your easiest persistence is localStorage (for state under ~5-10MB) or IndexedDB (for larger state).

Write a thin adapter that implements a "filesystem-like" API backed by localStorage:

```python
class BrowserFS:
    def read_json(self, key):
        import js, json
        raw = js.localStorage.getItem(key)
        return json.loads(raw) if raw else {}

    def write_json(self, key, data):
        import js, json
        js.localStorage.setItem(key, json.dumps(data))
```

Replace every `open(path)` and `json.load(path)` in your Python code with calls to the adapter. For my migration this was ~50 sites, most of them straightforward.

## Step 5: handle async boundaries

Pyodide's bridge to JS is async-friendly but awkward. Top-level awaits work, but synchronous-looking code with hidden async calls (like `requests.get()`) needs to be rewritten.

The brainstem uses `virtual_pip` — a module that twins common Python packages with JS-backed implementations. Instead of `requests`, the Pyodide version calls the browser's `fetch` under the hood, returning results in the same shape `requests` would. This is a significant piece of engineering but fully reusable across Python-to-browser ports.

If you don't want to write your own `virtual_pip`, Pyodide supports a limited set of packages via `micropip` — numpy, pandas, requests-like shims. Check what's available before assuming you need to port everything.

## Step 6: handle the "no backend" features

Some features disappear in a no-backend port:

- **Multi-user state.** Gone. Each browser is isolated.
- **Background jobs.** Gone. The browser tab is the process; if it's closed, work stops.
- **Scheduled tasks.** Gone, unless you use service workers (which can run periodically with limits).
- **Large file uploads to disk.** Gone. You can accept files (via drag-drop) but "disk" is now IndexedDB.
- **External integrations requiring secret API keys.** Complicated. The browser can hold keys in localStorage, but you're trusting the user not to steal them from devtools (which is fine for "your own key" cases, not fine for shared-key cases).

Decide which features you can live without, which you'll work around, and which disqualify the migration entirely.

For the brainstem, every feature had a browser-compatible answer. But that's because I chose to build a personal AI tool — a single-user, single-device, BYO-key app. If I'd been porting a multi-tenant SaaS, the answer would've been "don't port."

## Step 7: make the UX reflect the new shape

A browser app can do things a Flask app can't, and vice versa. Don't just replicate the Flask UI in the browser — use the affordances of the new substrate.

For the brainstem, this meant:
- Drag-and-drop agent files (can't do this in Flask without upload endpoints)
- Real-time LisPy evaluation in the chat (no round-trip)
- Export-as-file (`.rapp.egg` download is a browser primitive)
- Works offline (unreachable to a Flask app)

A Flask-shaped UI running in a browser will feel worse than the Flask version. A browser-shaped UI running in a browser can feel substantially better.

## When to NOT port

Flask-to-browser is a great move when:
- The app is single-user or per-user-isolated
- State fits in localStorage / IndexedDB
- There's no need for coordinated multi-user features
- The "bring your own key" model works for external services

It's a bad move when:
- The app is inherently multi-tenant with shared state
- Data must stay on specific servers for compliance
- You need background jobs or real-time coordination
- Your users aren't comfortable with "the app lives in my browser tab"

For personal tools, hobby apps, BYO-key AI interfaces, note-taking, visualizers, small games — port it. The UX is dramatically better, the ops cost drops to zero, and users get something they can hold.

For actual SaaS with paying customers expecting uptime — keep the backend.

## The meta-lesson

I didn't appreciate before the port how much of a Flask app's "weight" is incidental to its function. The Flask version of rapp-installer did *the same thing* as the browser version, but it required:

- A Python install
- A dependency install
- A server start step
- An open port
- An open browser
- A localhost URL

The browser version requires:
- Opening a URL

The functional delta is ~0. The friction delta is enormous. Nearly every piece of friction was there because I'd assumed, without examining, that a Python app needs a Python host.

Examine that assumption. Most personal tools don't need a host. Pyodide will run your Python in the user's browser. localStorage will store your state. `fetch` will hit your external APIs. The Flask layer was always optional.

Turn it off. Ship the app as a URL.

---

**Related:**
- [localStorage as a Database](localstorage-as-a-database) — the persistence half
- [Debugging Pyodide's Silent Fetch Failures](debugging-pyodide-silent-fetch-failures) — gotchas in the port
- [Why I Ship Everything as One File](why-i-ship-everything-as-one-file) — the destination of this kind of port
