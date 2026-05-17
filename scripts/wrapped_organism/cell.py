"""wrapped_organism/cell.py — runtime for one cell of a wrapped digital organism.

Implements the Wrapped Organism Spec v1.0 §II. Every agent.py written by
retrofit.py is a stub that delegates to the functions in this module —
keeping the per-cell file tiny and the protocol behavior in one place
where it can be tested.

The cell protocol:
  - manifest: dict describing this cell's position (layer/path/children/souls/context)
  - shape(transcript, manifest) -> transcript      # append this layer's context
  - route(transcript, manifest, brain) -> child | None  # ask brain which child
  - perform(input, manifest, brain) -> str         # walk the tree, return leaf output

Engine contract (the brain):
  brain.chat(transcript, **kw) -> str              # stateless LLM round-trip

Tested via tests/test_wrapped_organism.py with a stub brain (no real LLM
required for the unit suite — only the integration test hits a real /chat).
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import re
import urllib.error
import urllib.request


SCHEMA_VERSION = "rapp-cell/1.0"

VALID_LAYERS = {"leviathan", "estate", "industry", "neighborhood", "factory"}

MANIFEST_REQUIRED_KEYS = {"schema", "layer", "path", "context", "children", "souls"}


class ProtocolError(ValueError):
    """Raised when a manifest or routing decision violates the spec."""


# ─── manifest helpers ───────────────────────────────────────────────────────


def validate_manifest(manifest: dict) -> None:
    """Raise ProtocolError if the manifest does not match spec v1.0."""
    missing = MANIFEST_REQUIRED_KEYS - set(manifest.keys())
    if missing:
        raise ProtocolError(f"manifest missing keys: {sorted(missing)}")
    if manifest["schema"] != SCHEMA_VERSION:
        raise ProtocolError(f"unsupported schema: {manifest['schema']!r}")
    if manifest["layer"] not in VALID_LAYERS:
        raise ProtocolError(f"invalid layer: {manifest['layer']!r}")
    if not isinstance(manifest["children"], list):
        raise ProtocolError("children must be a list")
    if not isinstance(manifest["souls"], list):
        raise ProtocolError("souls must be a list")
    if not isinstance(manifest["context"], str) or not manifest["context"].strip():
        raise ProtocolError("context must be a non-empty string")


def is_leaf(manifest: dict) -> bool:
    """A cell is a leaf when it has no children to route to."""
    return not manifest.get("children")


# ─── transcript shaping ─────────────────────────────────────────────────────


def shape(transcript: list[dict], manifest: dict) -> list[dict]:
    """Append this cell's context as a system message. Pure; never mutates input."""
    return transcript + [{"role": "system", "content": manifest["context"]}]


# ─── routing ────────────────────────────────────────────────────────────────


def route(transcript: list[dict], manifest: dict, brain) -> str | None:
    """Ask brain which child handles this. Return slug, or None if leaf."""
    children = manifest["children"]
    if not children:
        return None
    ask = transcript + [{
        "role": "user",
        "content": (
            f"You must pick exactly one child of this cell to route to. "
            f"Valid children: {children}. "
            f"Reply with ONLY the slug, no punctuation, no explanation."
        ),
    }]
    raw = brain.chat(ask, temperature=0, max_tokens=32)
    choice = _clean_route_reply(raw, children)
    if choice not in children:
        raise ProtocolError(
            f"router returned invalid child: {raw!r} (valid: {children})"
        )
    return choice


_ROUTE_TOKEN_RE = re.compile(r"[A-Za-z0-9_\-]+")


def _clean_route_reply(raw: str, children: list[str]) -> str:
    """Extract the first valid child slug from a router reply.

    Tolerates the LLM wrapping its answer in quotes, markdown, or extra prose.
    """
    if not raw:
        return ""
    # Direct match first
    stripped = raw.strip().strip("\"'`").strip()
    if stripped in children:
        return stripped
    # Tokenize and find first child slug
    for tok in _ROUTE_TOKEN_RE.findall(raw):
        if tok in children:
            return tok
        # Case-insensitive fallback
        for c in children:
            if tok.lower() == c.lower():
                return c
    return stripped  # let validate() raise


# ─── hotloading ─────────────────────────────────────────────────────────────


def hotload(cell_dir: pathlib.Path, child_slug: str):
    """Import the child cell's agent.py fresh. Never cached."""
    target = cell_dir / child_slug / "agent.py"
    if not target.exists():
        raise FileNotFoundError(f"no cell at {target}")
    spec = importlib.util.spec_from_file_location(
        f"wrapped_cell_{child_slug}_{id(target)}", target
    )
    if spec is None or spec.loader is None:  # pragma: no cover - import failure
        raise ImportError(f"could not load spec for {target}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ─── leaf execution (souls chain) ───────────────────────────────────────────


def run_souls_chain(transcript: list[dict], manifest: dict,
                    souls_dir: pathlib.Path, brain) -> str:
    """At a leaf, load each soul in order and chain their replies."""
    reply = ""
    souls = manifest.get("souls") or []
    if not souls:
        # Bare leaf: ask brain with the accumulated transcript and no soul.
        return brain.chat(transcript)
    for soul_name in souls:
        soul_file = souls_dir / f"{soul_name}.md"
        if soul_file.exists():
            soul_prompt = soul_file.read_text(encoding="utf-8")
        else:
            soul_prompt = f"You are the {soul_name} persona."
        chain = [{"role": "system", "content": soul_prompt}] + transcript
        if reply:
            chain.append({"role": "assistant", "content": reply})
        reply = brain.chat(chain)
    return reply


# ─── driver ─────────────────────────────────────────────────────────────────


def perform(input_, manifest: dict, cell_dir: pathlib.Path,
            brain, trace: list | None = None) -> dict:
    """Walk the tree from this cell. Return {response, trace, leaf_path}.

    `input_` may be a string (initial call) or a list[dict] transcript
    (recursive call from a parent cell). Always returns a dict so the
    routing trace is preserved end-to-end for replay/debugging.
    """
    validate_manifest(manifest)
    if trace is None:
        trace = []

    transcript = shape(
        input_ if isinstance(input_, list) else [{"role": "user", "content": str(input_)}],
        manifest,
    )

    trace.append({"path": manifest["path"], "layer": manifest["layer"]})

    if is_leaf(manifest):
        response = run_souls_chain(transcript, manifest, cell_dir / "souls", brain)
        return {"response": response, "trace": trace, "leaf_path": manifest["path"]}

    child = route(transcript, manifest, brain)
    if child is None:  # pragma: no cover - is_leaf catches this
        raise ProtocolError(f"router returned None for non-leaf {manifest['path']}")
    child_cell = hotload(cell_dir, child)
    if not hasattr(child_cell, "__manifest__") or not hasattr(child_cell, "perform_local"):
        raise ProtocolError(
            f"child cell {child} does not expose __manifest__ + perform_local"
        )
    return child_cell.perform_local(transcript, brain, trace)


# ─── default brain (calls a real brainstem /chat endpoint) ──────────────────


class BrainstemBrain:
    """Calls a RAPP brainstem's /chat endpoint. Stateless."""

    def __init__(self, url: str = "http://localhost:7071/chat", timeout: int = 180):
        self.url = url
        self.timeout = timeout

    def chat(self, transcript: list[dict], **_kw) -> str:
        # The local brainstem accepts {"user_input": "..."}. Build a single
        # prompt that preserves the ORIGINAL user input alongside the current
        # routing instruction — without both, the router picks blind based on
        # static layer context and biases to the same leaf every time.
        sys_parts = [m["content"] for m in transcript if m["role"] == "system"]
        user_parts = [m["content"] for m in transcript if m["role"] == "user"]
        assistant_parts = [m["content"] for m in transcript if m["role"] == "assistant"]
        prompt = ""
        if sys_parts:
            prompt += "[CONTEXT]\n" + "\n\n".join(sys_parts) + "\n[/CONTEXT]\n\n"
        if assistant_parts:
            prompt += "[PRIOR ASSISTANT]\n" + assistant_parts[-1] + "\n[/PRIOR ASSISTANT]\n\n"
        if user_parts:
            if len(user_parts) > 1:
                prompt += "[ORIGINAL INPUT]\n" + user_parts[0] + "\n[/ORIGINAL INPUT]\n\n"
                prompt += "[CURRENT REQUEST]\n" + user_parts[-1] + "\n[/CURRENT REQUEST]"
            else:
                prompt += user_parts[0]
        body = json.dumps({"user_input": prompt}).encode("utf-8")
        req = urllib.request.Request(
            self.url, data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
        except urllib.error.URLError as e:  # pragma: no cover - network path
            raise RuntimeError(f"brainstem unreachable: {e}")
        return (data.get("response") or "").strip()
