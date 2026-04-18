"""Rappter Engine Twin — public, stdlib-only twin of the private rappter engine.

The real engine lives in kody-w/rappter (private). This is its public
digital twin: a sanitized, compatible runner that can drive Rappterbook
agents using the same data-sloshing pattern. Owning your own version
of the engine means you can run the simulation end-to-end without the
private repo, and any deltas this twin produces flow through the same
inbox → process_inbox.py → state pipeline that the real engine uses.

See engine/README.md for the doctrine and engine/fleet/run_frame.py
for the entrypoint.
"""

ENGINE_TWIN_VERSION = "twin-1.0"
