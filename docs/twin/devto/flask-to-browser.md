---
created: 2026-04-18
platform: devto
status: draft
source: flask-to-browser
tags: [python, pyodide, webdev, flask]
canonical_url: https://kody-w.github.io/rappterbook/blog/flask-to-browser
cover_image: null
published: false
---

# How I Deleted My Flask Backend (And Kept All the Features)

A month ago my AI chat app was a Flask server. Today it's one HTML file that runs the same code entirely in the browser tab.

No backend. No Python install. No venv. No deploy step. Same feature set.

Here's how I did it.

## The Flask version

`rapp-installer` was a Flask backend + HTML frontend. ~15 routes: register agent, list agents, chat, export/import config, fetch settings, update settings.

Running it required:
- Python install
- `pip install` the deps
- Start the server
- Open localhost:5000

For a personal AI tool, this is a lot of friction. Every user has to be a developer. Upgrades require stopping the server. Different devices need separate installs.

## The two axes of porting

Any Flask-to-browser migration has two independent questions:

1. **Where does the logic run?** Pyodide (CPython-on-WASM) vs. ported to JavaScript.
2. **Where does the state live?** Server filesystem vs. localStorage/IndexedDB.

The answers don't have to match. You can run logic in Pyodide with state in localStorage (my pick), or run logic in JS with state in IndexedDB, or any combination.

## Step 1: Catalog your Flask routes

For each route, note:
- HTML or JSON response?
- Reads/writes a database?
- Calls external services?
- Uses filesystem/OS APIs Pyodide can't reach?

Most of my routes were JSON APIs with localStorage-compatible state. Easy to port. If yours mostly reads/writes large files or shells out to subprocesses, porting is harder.

## Step 2: Replace HTTP with direct function calls

A Flask route is a client/server handshake. In the browser, both sides are in the same process — you don't need HTTP.

```js
// Before:
const response = await fetch('/api/chat', { method:'POST', body: JSON.stringify(msg) });
const data = await response.json();

// After:
const data = await pyodide.runPythonAsync(`
  from brainstem import chat_handler
  chat_handler(${JSON.stringify(msg)})
`);
```

The async boundary stays. The shape of the data stays. The HTTP layer disappears.

## Step 3: Choose your Pyodide strategy

**Option A: Full Pyodide.** Load CPython-on-WASM (~10MB). All your Python runs. Slow first load, easy migration.

**Option B: Selective Pyodide.** Lazy-load on first feature that needs Python. Faster startup, more complex.

**Option C: Port to JS.** Rewrite the logic. Fastest runtime, no Pyodide dep, doubles your codebase.

I picked A. First load is ~30 seconds, subsequent loads cached. For a personal AI tool, that's fine. For a public demo where every visitor eats the cold start — maybe reconsider.

## Step 4: Replace filesystem with localStorage

Flask apps persist to disk — JSON files, SQLite, whatever. In the browser, your easiest persistence is localStorage (under ~5-10MB) or IndexedDB (larger).

Write an adapter:

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

Replace every `open(path)` and `json.load(path)` with adapter calls. ~50 sites in my migration, all straightforward.

## Step 5: Handle async boundaries

Pyodide's JS bridge is async-friendly but awkward. Top-level `await` works. Synchronous-looking code with hidden async calls (like `requests.get()`) needs rewriting.

The brainstem uses `virtual_pip` — a module that twins common packages with JS-backed implementations. `requests.get()` in Pyodide code calls `fetch()` under the hood, returning results shaped like `requests` responses.

Micropip supports a limited set of packages — numpy, pandas, requests shims. Check before assuming you need to port everything yourself.

## Step 6: Accept what you lose

Some features disappear in a no-backend port:

- **Multi-user state.** Gone. Each browser is isolated.
- **Background jobs.** Gone unless you use service workers.
- **Scheduled tasks.** Same.
- **Large file uploads to server disk.** Gone. You can accept files via drag-drop, but "disk" is now IndexedDB.
- **External integrations requiring shared secret keys.** Complicated. BYO-key works; shared keys leak to devtools.

For the brainstem — single-user, BYO-key, personal AI — nothing was lost. For multi-tenant SaaS — a lot would be. Decide carefully.

## Step 7: Use browser affordances

Don't just replicate the Flask UI in the browser. A browser can do things Flask can't:

- Drag-and-drop (no upload endpoint needed)
- Real-time in-process execution (no round-trip)
- File download as browser primitive (`.rapp.egg` export is just `<a download>`)
- Works offline

A Flask-shaped UI running in a browser feels worse than the Flask version. A browser-shaped UI running in a browser feels substantially better.

## The meta-lesson

I didn't appreciate before the port how much of a Flask app's "weight" was incidental to its function. Same code, same behavior — but in Flask it required a Python install, dependency install, server start, localhost URL.

The browser version requires: opening a URL.

The functional delta: ~0. The friction delta: enormous.

Nearly every piece of friction was there because I'd assumed, without examining, that a Python app needs a Python host.

Examine that assumption. Most personal tools don't need a host. Pyodide will run your Python in the user's browser. localStorage will store state. `fetch` will hit your APIs. The Flask layer was always optional.

Turn it off. Ship the app as a URL.

Full writeup: https://kody-w.github.io/rappterbook/blog/flask-to-browser
