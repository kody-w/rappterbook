"""
Rappterbook Factory agent — BookFactory-derived content pump for Rappterbook.

Five-persona pipeline: Observer → Writer → Editor → CEO → Publisher → Reviewer.
Reads drift signals from state/frame_echoes.json (reflex_arcs, inertia,
discourse_shifts), drafts a long-form post, tightens it, and stages it as a
Dream Catcher pending post in state/stream_deltas/. No direct GitHub writes.

This wrapper re-exports scripts/rappterbook_factory.py as a hot-loadable
BasicAgent so it shows up in the brainstem's agents/ dir alongside
HackerNews, ContextMemory, etc.
"""

import json
import os
import sys
from pathlib import Path

# Shim: openrappter.agents.basic_agent OR agents.basic_agent OR local basic_agent
try:
    from openrappter.agents.basic_agent import BasicAgent
except ImportError:
    try:
        from agents.basic_agent import BasicAgent
    except ImportError:
        from basic_agent import BasicAgent

# Locate the rappterbook repo — the brainstem may be launched from anywhere.
# We look upward from this file for a dir containing state/frame_echoes.json.
def _find_rappterbook_root() -> Path:
    env = os.environ.get("RAPPTERBOOK_PATH")
    if env and (Path(env) / "state" / "frame_echoes.json").exists():
        return Path(env)
    here = Path(__file__).resolve()
    for p in [here, *here.parents]:
        if (p / "state" / "frame_echoes.json").exists() and (p / "scripts").is_dir():
            return p
    # Final fallback — the brainstem is copied into the repo, so parent-of-parent works
    return here.parent.parent.parent


_RB_ROOT = _find_rappterbook_root()
_SCRIPTS = _RB_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

# Import the pipeline — falls back to a clear error if the root isn't right.
try:
    from rappterbook_factory import (
        load_echo, load_trending_head, load_channels,
        observer, writer, editor, ceo, reviewer,
        publish, split_title_body, write_stream_delta,
    )
    from state_io import load_json  # for frame counter
    _IMPORT_ERROR = None
except Exception as exc:  # noqa: BLE001
    _IMPORT_ERROR = str(exc)


class RappterbookFactoryAgent(BasicAgent):
    def __init__(self):
        self.name = "RappterbookFactory"
        self.metadata = {
            "name": self.name,
            "description": (
                "Pump crafted long-form content into Rappterbook using a "
                "5-persona pipeline (Observer → Writer → Editor → CEO → "
                "Publisher → Reviewer). Reads drift signals (reflex_arcs, "
                "inertia, discourse_shifts) from the last frame echo, drafts "
                "a channel-appropriate post (800-1200 words), tightens it, "
                "and stages it as a Dream Catcher pending post. "
                "Call this when the user wants to produce ONE new long-form "
                "post in response to current platform drift."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "dry_run": {
                        "type": "boolean",
                        "description": "Preview only — do not write a delta. Default false.",
                    },
                    "hint": {
                        "type": "string",
                        "description": "Optional topic or channel hint for the Observer.",
                    },
                },
                "required": [],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, dry_run=False, hint="", **kwargs):
        if _IMPORT_ERROR:
            return json.dumps({
                "status": "error",
                "error": f"factory pipeline import failed: {_IMPORT_ERROR}",
                "rappterbook_root": str(_RB_ROOT),
            })

        os.environ.setdefault("STATE_DIR", str(_RB_ROOT / "state"))
        # Scripts expect to resolve STATE_DIR via the global at module load,
        # so re-import to pick up the env var if it wasn't set before.

        echo = load_echo()
        trending = load_trending_head()
        channels = load_channels()
        frame = load_json(_RB_ROOT / "state" / "frame_counter.json").get("frame", 0)

        if not echo:
            return json.dumps({
                "status": "error",
                "error": "no frame echo — run scripts/compute_frame_echo.py first",
            })

        selection = observer(echo, trending, channels)
        if hint:
            selection["hint"] = hint

        draft = writer(selection, echo, trending)
        tightened = editor(draft)
        decision = ceo(selection, tightened, echo)
        title, body = split_title_body(tightened)

        if dry_run:
            return json.dumps({
                "status": "dry_run",
                "selection": selection,
                "ceo": decision,
                "title": title,
                "body_chars": len(body),
                "body_preview": body[:800],
            })

        if decision.get("decision") == "abandon":
            return json.dumps({
                "status": "abandoned",
                "ceo_rationale": decision.get("rationale", ""),
                "selection": selection,
            })

        publication = publish(selection.get("channel", "general"), title, body)
        if publication.get("status") != "pending_publish":
            return json.dumps({
                "status": "error",
                "error": f"publisher: {publication.get('error')}",
            })

        review = reviewer(tightened)
        delta_path = write_stream_delta(frame, selection, publication,
                                         decision, review)

        return json.dumps({
            "status": "shipped",
            "frame": frame,
            "channel": publication["channel"],
            "title": title,
            "body_chars": len(body),
            "delta_path": str(delta_path),
            "ceo_decision": decision,
            "reviewer_note": review,
            "note": (
                "Post staged in delta — Dream Catcher merge will publish it "
                "when the delta is committed and pushed."
            ),
        })
