---
created: 2026-04-18
platform: devto
status: draft
source: debugging-pyodide-silent-fetch
tags: [pyodide, python, webdev, debugging]
canonical_url: https://kody-w.github.io/rappterbook/blog/debugging-pyodide-silent-fetch-failures
cover_image: null
published: false
---

# I Spent 2 Days Debugging "Unauthorized" — The Bug Was in Pyodide's Dict Conversion

I lost almost two full days debugging a 401. The fix was one keyword argument. This post is so you don't lose those two days too.

## The setup

I'm building an AI chat app that runs Python code in the browser via Pyodide (CPython-on-WASM). The Python code needs to call OpenAI's API:

```python
import js

response = js.fetch("https://api.openai.com/v1/chat/completions", {
    "method": "POST",
    "headers": {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    },
    "body": json.dumps(payload)
})
```

Every request comes back **401 Unauthorized.** My API key works in curl. My code looks right. I've been writing Python for a decade. This should work.

## What I tried that didn't help

- Verified the API key (5 times).
- Tested with curl (works).
- Tested with a pure JS fetch (works).
- Swapped from OpenAI to Azure to GitHub Models. All 401.
- Swapped to simpler payloads. Still 401.
- Checked CORS (not the issue — 401s aren't CORS errors).
- Switched accounts. Still 401.
- Made a hat out of tinfoil. Still 401.

By hour 16, I was questioning whether I actually knew how HTTP works.

## The actual bug

In Pyodide, when you pass a Python dict across the boundary to JS, it gets converted to a JavaScript `Map` — not a plain Object.

Almost every web API in the browser (`fetch`, headers, POST bodies) expects plain objects, not Maps. When `fetch` receives a Map as its options argument, it *doesn't throw an error.* It just silently uses the Map in ways that don't work right. In my case: the `headers` Map was being ignored, and my Authorization header never got sent.

## The fix

Use `dict_converter=Object.fromEntries` when sending the dict across:

```python
from pyodide.ffi import to_js
from js import Object

options = to_js({
    "method": "POST",
    "headers": {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    },
    "body": json.dumps(payload)
}, dict_converter=Object.fromEntries)

response = js.fetch("https://api.openai.com/v1/chat/completions", options)
```

Add a helper:

```python
def js_obj(d):
    from pyodide.ffi import to_js
    from js import Object
    return to_js(d, dict_converter=Object.fromEntries)
```

Every 401 disappeared in about 30 seconds.

## Why I couldn't find this faster

Three compounding factors:

1. **No error was raised.** `fetch` happily accepted the Map and produced a request — just one without the headers I specified. If it had thrown, I'd have found the bug in minutes.

2. **The error I DID see (401) pointed me at auth.** I chased auth theories while the actual bug was in how my headers were getting serialized. The symptom is downstream of the cause.

3. **Documentation assumes you already know.** Pyodide's docs mention this in a page about JS interop, but you have to be looking for "why are my dicts being weird" to find it.

## How I finally cracked it

Opened browser devtools, went to the Network tab, looked at the actual outgoing request. **No Authorization header.** Zero. The request went out naked.

At that point the question shifted from "why is auth failing" to "why isn't my auth header being transmitted." That second question took five minutes to answer with a web search.

**Lesson: look at the wire.** When a language-boundary bug confuses you, stop staring at your code and look at what's actually being transmitted. The bug is always in the gap between "what you wrote" and "what went out."

## Other Pyodide gotchas while I'm here

Since I have your attention:

- **`fetch` returns a Promise.** Use `await` or `asyncio.run`.
- **`__file__` isn't defined at top-level.** Inject it yourself if your code references it.
- **`__name__ == "__main__"` is True by default.** Your library's CLI will run unexpectedly unless you set `__name__` first.
- **`open()` writes to an in-memory FS that disappears on reload.** Use localStorage/IndexedDB for persistence.
- **`subprocess` doesn't exist.** Pyodide has no process model.
- **`numpy`/`pandas` need `micropip.install`** before import.
- **Top-level `await` works.** Don't wrap everything in an `async def main()`.

## The broader lesson

Every language-boundary bug I've ever chased has been in the *conversion*, not in the code on either side. JS↔Python, Python↔C, Go↔cgo — same pattern. The value you started with and the value the other side received look the same when you print them. They aren't. They have different types, different methods, different behaviors.

When something's mysteriously broken at a boundary, **log the type, not just the value.** `typeof` on the JS side vs. `type()` on the Python side will often surface the problem immediately.

Full writeup with more examples: https://kody-w.github.io/rappterbook/blog/debugging-pyodide-silent-fetch-failures
