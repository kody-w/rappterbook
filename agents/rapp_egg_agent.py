"""
Rapp Egg Agent — the portable driver for .rapp.egg (v1 EGG_SPEC).

Drop this single file into any compliant hatcher — Virtual Brainstem,
rapp-installer, openrappter, RAPP hippocampus/communityRAPP, any future
rappter engine — and that hatcher gains full egg capability (export + hatch)
without modifying its core. The agent.py IS the portability layer.

Exposes two tools:
  ExportRappEgg — pack the host's current rapp state as a v1 .rapp.egg
  HatchRappEgg  — load a .rapp.egg (inline JSON or URL) into the host

Environment-agnostic: detects Pyodide (browser) vs CPython (local) and
reads/writes state through the host's native substrate. API key is NEVER
packed per EGG_SPEC.md §9 — secrets stay local.

Canonical EGG_SPEC: https://github.com/kody-w/rappterbook/blob/main/EGG_SPEC.md
"""

# ═══════════════════════════════════════════════════════════════
# RAPP AGENT MANIFEST — Do not remove. Used by registry builder.
# ═══════════════════════════════════════════════════════════════
__manifest__ = {
    "schema": "rapp-agent/1.0",
    "name": "@kody-w/rapp_egg_agent",
    "version": "1.0.0",
    "display_name": "Rapp Egg",
    "description": "Portable driver for .rapp.egg (v1 EGG_SPEC). Export the current rapp state as a daemon-scale egg, or hatch an incoming egg into the host hatcher's substrate. Works identically on Virtual Brainstem (browser localStorage), rapp-installer (on-device filesystem), openrappter, and RAPP hippocampus. The agent IS the portability layer — no hatcher changes needed.",
    "author": "Kody Wildfeuer",
    "tags": [
        "rapp-egg",
        "egg-spec",
        "portability",
        "export",
        "hatch",
        "daemon",
        "state-json",
        "brainstem",
        "hippocampus",
        "communityRAPP",
    ],
    "category": "infrastructure",
    "quality_tier": "community",
    "requires_env": [],
    "dependencies": ["@rapp/basic_agent"],
}
# ═══════════════════════════════════════════════════════════════

import hashlib
import json
import os

# Flexible BasicAgent import — works whether the hatcher exposes the base
# class at `basic_agent` (rapp-installer layout) or `agents.basic_agent`
# (Virtual Brainstem layout / rapp-installer via agents/ package).
try:
    from basic_agent import BasicAgent
except ModuleNotFoundError:
    from agents.basic_agent import BasicAgent


# Environment detection — are we in Pyodide (browser) or CPython (local)?
try:
    from js import localStorage  # type: ignore
    IN_BROWSER = True
except ImportError:
    localStorage = None
    IN_BROWSER = False


# ── Canonical JSON (sorted keys, no whitespace) ──────────────────────────
# Every compliant packer must produce the same bytes for the same content
# so SHA-256 round-trips across implementations.
def _canonical(obj):
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    if isinstance(obj, list):
        return "[" + ",".join(_canonical(x) for x in obj) + "]"
    if isinstance(obj, dict):
        return "{" + ",".join(
            f'"{k}":{_canonical(obj[k])}' for k in sorted(obj.keys())
        ) + "}"
    raise TypeError(f"cannot canonicalize {type(obj).__name__}")


def _now_iso():
    from datetime import datetime, timezone
    return (datetime.now(timezone.utc)
            .replace(microsecond=0).isoformat().replace("+00:00", "Z"))


# ── Substrate readers (export side) ──────────────────────────────────────

def _read_state_browser():
    """Read rapp state from the Virtual Brainstem's localStorage layout."""
    state = {
        "soul": localStorage.getItem("brainstem_soul") or "",
        "settings": json.loads(localStorage.getItem("brainstem_settings") or "{}"),
        "memory": {},
        "custom_agents": json.loads(localStorage.getItem("brainstem_custom_agents") or "[]"),
        "disabled_agents": json.loads(localStorage.getItem("brainstem_disabled_agents") or "[]"),
        "last_hatched_sha": localStorage.getItem("brainstem_last_hatched_sha"),
    }
    for i in range(localStorage.length):
        k = localStorage.key(i)
        if k and k.startswith("brainstem_memory_"):
            try:
                state["memory"][k] = json.loads(localStorage.getItem(k))
            except Exception:
                state["memory"][k] = localStorage.getItem(k)
    return state


def _read_state_local():
    """Read rapp state from rapp-installer / server hatcher layout."""
    state = {
        "soul": "",
        "settings": {},
        "memory": {},
        "custom_agents": [],
        "disabled_agents": [],
        "last_hatched_sha": None,
    }
    for p in ("soul.md", "./soul.md", "../soul.md"):
        if os.path.isfile(p):
            with open(p) as f:
                state["soul"] = f.read()
            break
    state["settings"] = {
        "provider": ("azure" if os.environ.get("AZURE_OPENAI_API_KEY") else
                     "github" if os.environ.get("GITHUB_TOKEN") else
                     "openai"),
        "model": (os.environ.get("AZURE_OPENAI_DEPLOYMENT") or
                  os.environ.get("OPENAI_MODEL") or
                  os.environ.get("GITHUB_MODEL") or
                  "gpt-4o-mini"),
        "endpoint": os.environ.get("AZURE_OPENAI_ENDPOINT", ""),
    }
    for agents_dir in ("agents", "./agents", "../agents"):
        if os.path.isdir(agents_dir):
            for fn in os.listdir(agents_dir):
                if (fn.endswith("_agent.py") and
                        fn not in ("basic_agent.py", "rapp_egg_agent.py")):
                    try:
                        with open(os.path.join(agents_dir, fn)) as f:
                            state["custom_agents"].append({
                                "filename": fn,
                                "source": f.read(),
                                "registered_at": "local",
                            })
                    except Exception:
                        pass
            break
    return state


# ── Substrate writers (hatch side) ───────────────────────────────────────

def _write_state_browser(content):
    """Land body.content into the Virtual Brainstem's localStorage."""
    if content.get("soul") is not None:
        localStorage.setItem("brainstem_soul", content["soul"])
    pm = content.get("provider_metadata") or {}
    if pm:
        try:
            existing = json.loads(localStorage.getItem("brainstem_settings") or "{}")
        except Exception:
            existing = {}
        merged = {**existing, **pm}
        # Preserve any existing API key — never overwritten from eggs (§9)
        if "apikey" not in merged and existing.get("apikey"):
            merged["apikey"] = existing["apikey"]
        localStorage.setItem("brainstem_settings", json.dumps(merged))
    memory = content.get("memory") or {}
    for k, v in memory.items():
        if k.startswith("brainstem_memory_"):
            localStorage.setItem(k, json.dumps(v) if not isinstance(v, str) else v)
    if isinstance(content.get("custom_agents"), list):
        localStorage.setItem("brainstem_custom_agents",
                             json.dumps(content["custom_agents"]))
    if isinstance(content.get("disabled_agents"), list):
        localStorage.setItem("brainstem_disabled_agents",
                             json.dumps(content["disabled_agents"]))


def _write_state_local(content, dry_run=False):
    """Land body.content into rapp-installer's on-device layout.
    Writes: soul.md, agents/<filename>.py files. Returns list of paths touched."""
    touched = []
    if content.get("soul") is not None:
        path = "soul.md"
        if not dry_run:
            with open(path, "w") as f:
                f.write(content["soul"])
        touched.append(path)
    for ca in content.get("custom_agents") or []:
        fn = ca.get("filename") or "custom_agent.py"
        src = ca.get("source") or ""
        if not src.strip():
            continue
        os.makedirs("agents", exist_ok=True)
        path = os.path.join("agents", fn)
        if not dry_run:
            with open(path, "w") as f:
                f.write(src)
        touched.append(path)
    return touched


# ── Pack ────────────────────────────────────────────────────────────────

def pack_egg(instance, tagline=None):
    """Build a v1-compliant .rapp.egg from the host's current state."""
    state = _read_state_browser() if IN_BROWSER else _read_state_local()
    settings = state["settings"] or {}

    content = {
        "soul": state["soul"],
        "provider_metadata": {
            "provider": settings.get("provider", "openai"),
            "model": settings.get("model", "gpt-4o-mini"),
            "endpoint": settings.get("endpoint", ""),
        },
        "memory": state["memory"],
        "custom_agents": state["custom_agents"],
        "disabled_agents": state["disabled_agents"],
        "metadata": {
            "rapp_schema_version": 1,
            "packed_by": "rapp_egg_agent@1.0",
            "schema_refs": [
                "https://github.com/kody-w/rappterbook/blob/main/EGG_SPEC.md"
            ],
        },
    }
    canonical = _canonical(content)
    sha = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    size_bytes = len(canonical.encode("utf-8"))

    memory_entry_count = sum(
        len(v) for v in state["memory"].values() if isinstance(v, dict)
    )
    default_tagline = (f"Exported rapp daemon — "
                       f"{len(state['custom_agents'])} custom agents, "
                       f"{memory_entry_count} memory entries")

    return {
        "_format": "egg",
        "_schema_version": 1,
        "organism": {
            "slug": instance.lower().replace(" ", "-").replace("_", "-"),
            "species": "rapp",
            "instance": instance,
            "scale": "daemon",
            "substrate": "browser" if IN_BROWSER else "filesystem",
            "name": instance,
            "tagline": tagline or default_tagline,
            "population": "1 rapp daemon",
        },
        "body": {
            "kind": "state_json",
            "filename": f"{instance.lower().replace(' ', '-')}.rapp.state.json",
            "content": content,
            "sha256": sha,
            "size_bytes": size_bytes,
        },
        "lineage": {
            "created_at": _now_iso(),
            "created_by": "rapp_egg_agent",
            "engine_version": "rapp-egg-v1",
            "parent_egg_sha256": state.get("last_hatched_sha"),
            "birth_tick": None,
        },
        "validation": {"ok": True, "issues": []},
    }


# ── Hatch ──────────────────────────────────────────────────────────────

def validate_egg(egg, force=False):
    """v1 structural + SHA validation per EGG_SPEC.md §7."""
    issues = []
    if egg.get("_format") != "egg":
        issues.append(f"_format != 'egg' (got {egg.get('_format')!r})")
    if egg.get("_schema_version") != 1:
        issues.append(f"_schema_version != 1 (got {egg.get('_schema_version')!r})")
    body = egg.get("body") or {}
    if body.get("kind") != "state_json":
        issues.append(f"body.kind != 'state_json' (got {body.get('kind')!r}); "
                      f"this hatcher implements daemon-scale state_json only")
    content = body.get("content")
    if content is None:
        issues.append("body.content missing")
    declared_sha = body.get("sha256")
    if content is not None and declared_sha:
        actual_sha = hashlib.sha256(
            _canonical(content).encode("utf-8")
        ).hexdigest()
        if actual_sha != declared_sha:
            msg = (f"SHA-256 mismatch: declared {declared_sha}, "
                   f"actual {actual_sha}")
            if not force:
                issues.append(msg)
            else:
                issues.append("(forced past) " + msg)
    org = egg.get("organism") or {}
    if org.get("scale") and org["scale"] != "daemon":
        msg = f"scale={org['scale']}; this hatcher expects daemon"
        if not force:
            issues.append(msg)
        else:
            issues.append("(forced past) " + msg)
    return issues


def hatch_egg(egg, force=False, dry_run=False):
    """Validate and land the egg into the host hatcher's substrate."""
    issues = [i for i in validate_egg(egg, force=force) if "(forced past)" not in i]
    if issues:
        return {"ok": False, "issues": issues,
                "hint": "Pass force=true to bypass SHA/scale checks (§7.2)."}

    content = egg["body"]["content"]
    if dry_run:
        return {"ok": True, "dry_run": True,
                "would_write": "localStorage" if IN_BROWSER else "filesystem",
                "organism": egg.get("organism", {})}

    if IN_BROWSER:
        _write_state_browser(content)
        localStorage.setItem("brainstem_last_hatched_sha",
                             egg["body"]["sha256"])
        return {"ok": True, "substrate": "browser",
                "hint": "Soul + memory + agents are in localStorage. "
                        "Reload the page so custom agents re-register.",
                "organism": egg.get("organism", {})}

    touched = _write_state_local(content, dry_run=False)
    return {"ok": True, "substrate": "filesystem",
            "files_touched": touched,
            "hint": "Restart the hatcher so it picks up the new soul.md "
                    "and agents/ directory.",
            "organism": egg.get("organism", {})}


# ── Tool agents ────────────────────────────────────────────────────────

class ExportRappEggAgent(BasicAgent):
    """Pack the host's current rapp state into a v1 .rapp.egg."""

    def __init__(self):
        self.name = "ExportRappEgg"
        self.metadata = {
            "name": self.name,
            "description": (
                "Export this rapp's current state as a v1 .rapp.egg "
                "conforming to EGG_SPEC.md. Returns the egg as JSON — the "
                "host does whatever it wants with it (display, download, "
                "POST, save). Call when the user says: 'export me as an "
                "egg', 'pack me into a rapp.egg', 'give me my rapp.egg', "
                "'save my state', 'lay an egg', 'snapshot me'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "instance_name": {
                        "type": "string",
                        "description": "Instance name (e.g. 'kodyTwinAI'). Appears in filename + organism.instance.",
                    },
                    "tagline": {
                        "type": "string",
                        "description": "Optional one-line description for organism.tagline.",
                    },
                    "summary_only": {
                        "type": "boolean",
                        "description": "If true, return only sha + size + organism metadata, not the full body.",
                    },
                },
                "required": [],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, **kwargs):
        instance = (kwargs.get("instance_name") or "rapp").strip() or "rapp"
        try:
            egg = pack_egg(instance, tagline=kwargs.get("tagline"))
        except Exception as e:
            return f"Egg pack failed: {type(e).__name__}: {e}"
        if kwargs.get("summary_only"):
            return json.dumps({
                "ok": True,
                "filename": f"{instance.lower().replace(' ', '-')}.rapp.egg",
                "species": egg["organism"]["species"],
                "scale": egg["organism"]["scale"],
                "substrate": egg["organism"]["substrate"],
                "sha256": egg["body"]["sha256"],
                "size_bytes": egg["body"]["size_bytes"],
                "tagline": egg["organism"]["tagline"],
                "memory_partitions": len(egg["body"]["content"]["memory"]),
                "custom_agents": len(egg["body"]["content"]["custom_agents"]),
            }, indent=2)
        return json.dumps(egg, indent=2)


class HatchRappEggAgent(BasicAgent):
    """Load a .rapp.egg into the host hatcher's substrate."""

    def __init__(self):
        self.name = "HatchRappEgg"
        self.metadata = {
            "name": self.name,
            "description": (
                "Hatch a .rapp.egg into this host — lands the egg's soul, "
                "memory, custom agents, and provider metadata into the "
                "host's substrate (browser localStorage or local filesystem). "
                "Validates SHA-256 and schema version per EGG_SPEC.md §7. "
                "Call when the user says: 'hatch this egg', 'load this "
                "rapp.egg', 'import this egg', 'become [rapp name]'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "egg_json": {
                        "type": "string",
                        "description": "The .rapp.egg content as a JSON string. Prefer this when the user pasted the egg directly.",
                    },
                    "egg_url": {
                        "type": "string",
                        "description": "URL to fetch the .rapp.egg from. Use when the user provides a link (e.g. kody-w.github.io/rappterbook/kodyTwinAI.rapp.egg).",
                    },
                    "force": {
                        "type": "boolean",
                        "description": "Bypass SHA or scale validation (§7.2). Default false.",
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "Validate but don't write. Returns what WOULD happen.",
                    },
                },
                "required": [],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    async def perform_async(self, **kwargs):
        egg_json = kwargs.get("egg_json")
        egg_url = kwargs.get("egg_url")
        force = bool(kwargs.get("force", False))
        dry_run = bool(kwargs.get("dry_run", False))

        if not egg_json and not egg_url:
            return ("Provide either egg_json (the egg content as a JSON "
                    "string) or egg_url (a URL to fetch the egg from).")

        egg_text = egg_json
        if not egg_text and egg_url:
            if IN_BROWSER:
                try:
                    from js import fetch  # type: ignore
                    resp = await fetch(egg_url)
                    if resp.status >= 400:
                        return f"Fetch failed: HTTP {resp.status}"
                    egg_text = await resp.text()
                except Exception as e:
                    return f"Fetch failed: {type(e).__name__}: {e}"
            else:
                try:
                    import urllib.request
                    with urllib.request.urlopen(egg_url, timeout=30) as r:
                        egg_text = r.read().decode("utf-8", errors="replace")
                except Exception as e:
                    return f"Fetch failed: {type(e).__name__}: {e}"

        try:
            egg = json.loads(egg_text)
        except Exception as e:
            return f"Egg JSON parse failed: {type(e).__name__}: {e}"

        try:
            result = hatch_egg(egg, force=force, dry_run=dry_run)
        except Exception as e:
            return f"Hatch failed: {type(e).__name__}: {e}"

        return json.dumps(result, indent=2)

    def perform(self, **kwargs):
        """Sync entry point — only supports egg_json (no URL fetch).
        The Virtual Brainstem's dispatcher awaits perform_async automatically
        when the call needs it."""
        egg_json = kwargs.get("egg_json")
        if not egg_json:
            return ("Sync path requires egg_json (the egg content as a "
                    "string). For URL fetch, the async dispatcher is used.")
        try:
            egg = json.loads(egg_json)
            result = hatch_egg(
                egg,
                force=bool(kwargs.get("force", False)),
                dry_run=bool(kwargs.get("dry_run", False)),
            )
            return json.dumps(result, indent=2)
        except Exception as e:
            return f"Hatch failed: {type(e).__name__}: {e}"
