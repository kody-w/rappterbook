"""
Publish-to-RAR Agent — submit any agent.py to the kody-w/RAR registry
via the documented GitHub Issue protocol, without you touching the API.

Drop this single file into any compliant hatcher (Virtual Brainstem,
rapp-installer, etc.) and the LLM gains a `PublishToRar` tool. Say things
like "publish this agent to RAR" or "submit <filename> to the registry"
and the agent:

  1. Finds the target agent source — either passed explicitly as
     `agent_code`, or looked up by `agent_filename` from the brainstem's
     drag-dropped custom_agents in localStorage.
  2. Parses the `__manifest__` block to extract @publisher/slug.
  3. Builds the RAR-spec submission body (prose description + full python
     source in a ```python fence).
  4. POSTs a GitHub Issue to kody-w/RAR with title `[AGENT] @pub/slug`
     and label `rar-action`.

Token resolution order:
  1. `github_token` argument from the tool call (explicit override)
  2. env GITHUB_TOKEN                      (rapp-installer / on-device)
  3. brainstem_settings.apikey (if provider=github)  (Virtual Brainstem)

Environment-agnostic: works in Pyodide (browser via js.fetch) and
CPython (server/local via urllib.request). Never packs or transmits
other secrets.
"""

# ═══════════════════════════════════════════════════════════════
# RAPP AGENT MANIFEST — Do not remove. Used by registry builder.
# ═══════════════════════════════════════════════════════════════
__manifest__ = {
    "schema": "rapp-agent/1.0",
    "name": "@kody-w/publish_to_rar_agent",
    "version": "1.0.0",
    "display_name": "Publish to RAR",
    "description": "Submit an agent.py file to the kody-w/RAR registry via GitHub Issue. Parses the target agent's __manifest__ for @publisher/slug, builds the RAR-compliant submission body (prose + python fence), and POSTs to the RAR repo with the correct labels. Uses a stashed GITHUB_TOKEN — no manual curl/gh commands, no rate-limit footguns for humans.",
    "author": "Kody Wildfeuer",
    "tags": [
        "rar",
        "registry",
        "publish",
        "submission",
        "github-issues",
        "meta-agent",
        "infrastructure",
    ],
    "category": "infrastructure",
    "quality_tier": "community",
    "requires_env": ["GITHUB_TOKEN"],
    "dependencies": ["@rapp/basic_agent"],
}
# ═══════════════════════════════════════════════════════════════

import ast
import json
import os
import re

try:
    from basic_agent import BasicAgent
except ModuleNotFoundError:
    from agents.basic_agent import BasicAgent


# Environment detection — Pyodide (browser) vs CPython (local)
try:
    from js import localStorage  # type: ignore
    IN_BROWSER = True
except ImportError:
    localStorage = None
    IN_BROWSER = False


RAR_ISSUES_URL = "https://api.github.com/repos/kody-w/RAR/issues"


def _parse_manifest(source):
    """Extract the top-level __manifest__ dict from an agent.py source string."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "__manifest__":
                    try:
                        return ast.literal_eval(node.value)
                    except Exception:
                        return None
    return None


def _resolve_source(agent_code, agent_filename):
    """Find the target agent source. Either passed in directly or looked up
    from the brainstem's drag-dropped custom agents."""
    if agent_code and agent_code.strip():
        return agent_code, "inline"
    if not agent_filename:
        return None, "neither agent_code nor agent_filename provided"
    if IN_BROWSER:
        try:
            customs = json.loads(localStorage.getItem("brainstem_custom_agents") or "[]")
        except Exception:
            customs = []
        for c in customs:
            if c.get("filename") == agent_filename:
                return c.get("source", ""), f"brainstem custom_agents[{agent_filename}]"
        # Also look at the installed file via fetch in Pyodide
        try:
            with open(f"/brainstem/agents/{agent_filename}") as f:
                return f.read(), f"/brainstem/agents/{agent_filename}"
        except Exception:
            pass
    else:
        # rapp-installer / local: look in agents/
        for path in (f"agents/{agent_filename}", f"./agents/{agent_filename}",
                     f"../agents/{agent_filename}", agent_filename):
            if os.path.isfile(path):
                with open(path) as f:
                    return f.read(), path
    return None, f"could not find {agent_filename!r}"


def _resolve_token(explicit_token):
    """Resolve a GitHub token. Priority: explicit arg → env → brainstem settings."""
    if explicit_token and explicit_token.strip():
        return explicit_token.strip()
    env_tok = os.environ.get("GITHUB_TOKEN")
    if env_tok:
        return env_tok
    if IN_BROWSER:
        try:
            settings = json.loads(localStorage.getItem("brainstem_settings") or "{}")
            if settings.get("provider") == "github" and settings.get("apikey"):
                return settings["apikey"]
        except Exception:
            pass
        # Also look in the stashed env bag
        try:
            stashed = localStorage.getItem("lispy_env") or ""
            for line in stashed.split("\n"):
                if line.startswith("GITHUB_TOKEN="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except Exception:
            pass
    return None


def _build_submission_body(manifest, source):
    """Compose the prose + python-fence body per RAR's documented format."""
    name = manifest.get("name", "")
    display = manifest.get("display_name") or name
    desc = manifest.get("description", "")
    author = manifest.get("author", "")
    tags = manifest.get("tags") or []
    category = manifest.get("category", "")
    tier = manifest.get("quality_tier", "community")
    deps = manifest.get("dependencies") or []
    requires = manifest.get("requires_env") or []

    pieces = [
        f"Submitting `{name}` to the RAR registry.",
        "",
        f"**Display name:** {display}",
        f"**Author:** {author}",
        f"**Category:** {category}",
        f"**Quality tier:** {tier}",
        f"**Dependencies:** `{'`, `'.join(deps) or '(none)'}`",
        f"**Requires env:** `{'`, `'.join(requires) or '(none)'}`",
        f"**Tags:** {', '.join(tags) if tags else '(none)'}",
        "",
        f"**Description:** {desc}",
        "",
        "Full source below.",
        "",
        "```python",
        source,
        "```",
    ]
    return "\n".join(pieces)


def _post_issue_browser(token, payload):
    """POST to GitHub Issues API via js.fetch. Returns the parsed response dict."""
    import asyncio
    from js import fetch  # type: ignore
    from pyodide.ffi import to_js  # type: ignore
    from js import Object as JsObject  # type: ignore

    async def _do():
        opts = to_js({
            "method": "POST",
            "headers": {
                "authorization": f"token {token}",
                "accept": "application/vnd.github+json",
                "content-type": "application/json",
            },
            "body": json.dumps(payload),
        }, dict_converter=JsObject.fromEntries)
        resp = await fetch(RAR_ISSUES_URL, opts)
        body = await resp.text()
        try:
            return {"status": int(resp.status), "body": json.loads(body)}
        except Exception:
            return {"status": int(resp.status), "body": {"raw": body[:500]}}

    # The brainstem's dispatcher already runs us from an async context,
    # so this helper is only used inside perform_async where we can await.
    return _do()


def _post_issue_local(token, payload):
    """Blocking POST via urllib for rapp-installer / CPython hatchers."""
    import urllib.request
    import urllib.error
    req = urllib.request.Request(
        RAR_ISSUES_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return {"status": r.status, "body": json.loads(r.read().decode("utf-8"))}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try: parsed = json.loads(raw)
        except Exception: parsed = {"raw": raw[:500]}
        return {"status": e.code, "body": parsed}


class PublishToRarAgent(BasicAgent):
    """Submit an agent.py to the kody-w/RAR registry via GitHub Issue."""

    def __init__(self):
        self.name = "PublishToRar"
        self.metadata = {
            "name": self.name,
            "description": (
                "Submit an agent.py to the RAR registry (kody-w/RAR) via the "
                "documented GitHub Issue protocol. Parses the target agent's "
                "__manifest__ for @publisher/slug, builds the RAR-compliant "
                "submission body, POSTs to the RAR repo. Call when user says "
                "'publish this to RAR', 'submit this agent to the registry', "
                "'add <name> to RAR', 'register my agent'. Requires a GitHub "
                "token — resolved from the github_token arg, env GITHUB_TOKEN, "
                "or the brainstem's stashed GitHub provider key."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_code": {
                        "type": "string",
                        "description": "Full .py source of the agent to submit. Use when the user pasted the source directly.",
                    },
                    "agent_filename": {
                        "type": "string",
                        "description": "Filename of a drag-dropped custom agent to submit (e.g. 'rapp_egg_agent.py'). Looks it up from the brainstem's registered custom_agents.",
                    },
                    "github_token": {
                        "type": "string",
                        "description": "Explicit GitHub personal access token (needs public_repo scope). Omit to use stashed env/localStorage token.",
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "If true, return what would be submitted without POSTing.",
                    },
                },
                "required": [],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    async def perform_async(self, **kwargs):
        source, source_origin = _resolve_source(
            kwargs.get("agent_code"), kwargs.get("agent_filename")
        )
        if not source:
            return json.dumps({
                "ok": False,
                "error": source_origin,
                "hint": "Pass agent_code=<python source> OR agent_filename=<name.py> (where name.py is a currently-loaded custom agent).",
            }, indent=2)

        manifest = _parse_manifest(source)
        if not manifest:
            return json.dumps({
                "ok": False,
                "error": "source is missing a top-level __manifest__ = {...} block",
                "hint": "RAR requires each agent to embed a rapp-agent/1.0 manifest. See agents/rapp_egg_agent.py in this repo for reference.",
                "source_origin": source_origin,
            }, indent=2)

        name = manifest.get("name", "")
        if not isinstance(name, str) or not re.match(r"^@[\w-]+/[\w_]+$", name):
            return json.dumps({
                "ok": False,
                "error": f"manifest.name must be @publisher/slug (snake_case). got: {name!r}",
            }, indent=2)

        dry_run = bool(kwargs.get("dry_run", False))
        title = f"[AGENT] {name}"
        body = _build_submission_body(manifest, source)
        payload = {"title": title, "body": body, "labels": ["rar-action"]}

        summary = {
            "publisher_slug": name,
            "title": title,
            "body_bytes": len(body),
            "source_origin": source_origin,
            "manifest_keys": sorted(manifest.keys()),
        }

        if dry_run:
            return json.dumps({
                "ok": True,
                "dry_run": True,
                "summary": summary,
                "would_post_to": RAR_ISSUES_URL,
                "hint": "Set dry_run=false to actually create the issue.",
            }, indent=2)

        token = _resolve_token(kwargs.get("github_token"))
        if not token:
            return json.dumps({
                "ok": False,
                "error": "no GitHub token available",
                "summary": summary,
                "hint": (
                    "Provide one of: "
                    "(1) github_token argument, "
                    "(2) .env upload with GITHUB_TOKEN=..., "
                    "(3) set provider=github in Settings with a PAT (public_repo scope)."
                ),
            }, indent=2)

        try:
            if IN_BROWSER:
                result = await _post_issue_browser(token, payload)
            else:
                result = _post_issue_local(token, payload)
        except Exception as e:
            return json.dumps({
                "ok": False,
                "error": f"POST failed: {type(e).__name__}: {e}",
                "summary": summary,
            }, indent=2)

        status = result.get("status", 0)
        resp = result.get("body") or {}

        if status >= 200 and status < 300:
            return json.dumps({
                "ok": True,
                "issue_url": resp.get("html_url"),
                "issue_number": resp.get("number"),
                "summary": summary,
                "note": "Submitted. The RAR registry builder will pick it up; check registry.json later.",
            }, indent=2)

        if status == 403 and "rate limit" in str(resp.get("message", "")).lower():
            return json.dumps({
                "ok": False,
                "status": 403,
                "error": "GitHub secondary rate limit — content creation temporarily blocked on this token",
                "hint": "Wait 30-60 min, then try again. Repeated attempts extend the cooldown.",
                "github_message": resp.get("message", "")[:300],
                "summary": summary,
            }, indent=2)

        return json.dumps({
            "ok": False,
            "status": status,
            "error": resp.get("message") or "submission rejected",
            "github_response": resp,
            "summary": summary,
        }, indent=2)

    def perform(self, **kwargs):
        """Sync fallback — only supports dry_run inspection. The Virtual Brainstem's
        dispatcher auto-awaits perform_async when there's a real POST to do."""
        source, source_origin = _resolve_source(
            kwargs.get("agent_code"), kwargs.get("agent_filename")
        )
        if not source:
            return f"Could not resolve source: {source_origin}"
        manifest = _parse_manifest(source)
        if not manifest:
            return "source missing top-level __manifest__ block"
        return json.dumps({
            "ok": True,
            "sync_preview": True,
            "name": manifest.get("name"),
            "title": f"[AGENT] {manifest.get('name', '?')}",
            "body_preview_lines": 1 + len(_build_submission_body(manifest, source).splitlines()),
            "note": "Sync path can't POST. The brainstem dispatcher will route real submissions through perform_async.",
        }, indent=2)
