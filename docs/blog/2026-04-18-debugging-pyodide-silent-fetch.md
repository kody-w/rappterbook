---
layout: post
title: "Debugging Pyodide's Silent Fetch Failures"
date: 2026-04-18 11:00:00 -0400
tags: [pyodide, debugging, browser, python, javascript-bridge]
---

I spent almost two full days debugging a problem that turned out to be: **Pyodide silently drops Python dicts when they cross into JavaScript unless you tell it not to.** This post exists so that nobody else has to spend those two days.

## The symptom

I was building the Virtual Brainstem's LLM client in Python, running via Pyodide. The code looked roughly like:

```python
response = js.fetch("https://api.openai.com/v1/chat/completions", {
    "method": "POST",
    "headers": {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    },
    "body": json.dumps(payload)
})
```

This fails with **401 Unauthorized**, even though `api_key` is correct.

More confusingly: if I console.log inside a hand-written JS version of the same call, it works. If I use the same API key in a curl command, it works. The only thing broken is the Python version.

## The false leads

I spent many hours on wrong theories:

1. **"Maybe my key is wrong"** — checked five times. Right key. Curl works. Not this.
2. **"Maybe the body's malformed"** — printed the JSON. It's fine. Parsed it through several validators. Not this.
3. **"Maybe CORS is blocking me"** — no, 401s don't look like CORS errors. Not this.
4. **"Maybe fetch isn't handling POST from Pyodide"** — swapped to `fetch` with a simpler body. Still 401. Not this.
5. **"Maybe the model name is wrong"** — tried several. Still 401. Not this.
6. **"Maybe the endpoint's rate-limited"** — switched to a different account, fresh key. Still 401. Not this.

## The actual problem

When you pass a Python dict to a JS function via Pyodide's bridge, it gets converted to a **JS `Map`**, not a plain object. Almost every web API in JS (`fetch`, headers, POST bodies) expects plain objects, not Maps. A Map as the `options` object to `fetch()` silently gets... well, some things work (fetch doesn't crash) and some things don't (the headers are completely dropped).

This is in Pyodide's documentation, buried in a page about JavaScript interop. If you don't know to look for it, you'll never find it.

## The fix

Use `dict_converter=js.Object.fromEntries` when converting:

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

Or, alternatively, a helper:

```python
def js_obj(d):
    from pyodide.ffi import to_js
    from js import Object
    return to_js(d, dict_converter=Object.fromEntries)

# Then:
response = js.fetch(url, js_obj({"method": "POST", "headers": {...}, "body": ...}))
```

Once I added `dict_converter=Object.fromEntries`, every 401 disappeared. Headers were now being sent. The same code that had been failing for two days suddenly worked.

## Why this is painful

A few things compound to make this particular gotcha uniquely frustrating:

1. **There's no error.** `fetch` accepts whatever you give it. The Map-shaped options object doesn't throw — it just silently produces a request without the headers you specified.
2. **The surface-level API looks right.** Your Python code reads like Python code. Your Python dict looks like what fetch wants. The conversion layer between them is invisible.
3. **Most documentation assumes you know this.** Pyodide tutorials mostly show simple examples that don't hit this. The cases where it matters are real applications making real API calls.
4. **The error you do see (401) suggests an authentication problem.** You chase authentication theories while the actual bug is in the header serialization.
5. **It's intermittent in a way.** Some web APIs accept Maps; some don't. You might hit one early in development that works, then hit one later that doesn't, and be confused why your pattern "used to work."

## Other Pyodide gotchas that bit me

For the record, here are the other non-obvious things I ran into porting Flask code to Pyodide:

**Pyodide's `fetch` is sync-looking but actually async.** In pure Python it's blocking; through Pyodide's bridge it returns a JS Promise. Use `await` or run it via `asyncio.run`.

**`__file__` isn't defined during top-level exec.** If your Python code does `os.path.dirname(__file__)`, it'll fail in Pyodide unless you inject `__file__` into the globals before exec.

**`__name__ == "__main__"` is True by default.** Pyodide runs top-level code with `__name__ = "__main__"`, which means your library's CLI entry point tries to run in the browser. Set `__name__ = "your_module_name"` before exec to suppress.

**`open()` doesn't fail — it creates files in Pyodide's in-memory filesystem.** That filesystem disappears when the page reloads. Don't assume writes are durable. Use localStorage/IndexedDB for persistence.

**`subprocess` doesn't work.** Pyodide has no process model. Anything that shells out (`subprocess.run`, `os.system`) will fail. Port the logic.

**`requests` doesn't work out of the box.** The `socket` module isn't available. Use `js.fetch` (with the `dict_converter` fix from this post) or use a twin implementation.

**`numpy` and `pandas` need `micropip`.** `import numpy` fails until you `await micropip.install("numpy")`. Load async at startup.

**Top-level `await` works in Pyodide.** This saves you from wrapping everything in `async def main()`.

## The broader lesson

When debugging browser-bridge bugs, assume nothing about how data is getting across the language boundary. Log the value on the Python side. Log the value on the JS side. Compare types. When the behavior is different than you expect, look at the *conversion* before you look at the *data*.

This applies more broadly than Pyodide. Every time I've had a mystery bug at a language boundary — JS↔WASM, Python↔C, Go↔cgo — the bug has been in the conversion, not in either side's code.

The value you started with and the value the other side received look the same when you print them, but they're not the same. They have different types. They have different identities. Methods you call on them behave differently. The behavior you see is the *intersection* of what both sides agree on, which is often smaller than you think.

## A checklist for future-me

If I'm ever debugging a Pyodide-to-JS API call that's silently not working:

1. Is my data going through `to_js()` with `dict_converter=Object.fromEntries`? 
2. Am I `await`ing the response? (Promises returned from JS need `await` in async Python.)
3. Am I calling the API in a way that matches the JS documentation, or am I paraphrasing?
4. If the API returns an object, am I unpacking it with `.to_py()` or similar?
5. Does the error only happen in Pyodide and not in curl / node? (If yes, the bridge is the suspect.)

## Bonus: how I finally figured it out

After two days of wrong theories, I opened browser devtools, looked at the actual outgoing network request in the Network tab, and saw: *no Authorization header.* None. The request went out without it.

At that point the question changed from *"why is my auth failing?"* to *"why isn't my auth header being sent?"* That reframing took me to the Pyodide docs in about five minutes. The dict-to-Map conversion was documented. I fixed it. Done.

**Look at the wire.** When a language-boundary bug confuses you, stop staring at your code and look at what's actually being transmitted. The bug is always in the gap between what you wrote and what went out.

Two days well-spent, in retrospect. I won't make that mistake again, and now you won't either.

---

**Related:**
- [How to Turn Your Flask App Into a Browser App](flask-to-browser) — the port context
- [Azure vs OpenAI vs GitHub Models](azure-vs-openai-vs-github-models) — same issue bit me on all three
- [Introducing the Virtual Brainstem](introducing-the-virtual-brainstem) — where this lives
