"""Tests for the JIT mirror promoter (scripts/jit_mirror.py).

Proves the twin-model guarantees:
  * generated world never touches the API (no signal -> zero create calls)
  * a signaled record is JIT-promoted and becomes a tracking shell
  * promotion is idempotent (already-mirrored -> no-op, no double-create)
  * API failure leaves the record signaled for retry (never lost)
  * only the real interactions among many records hit the API
  * shells track ongoing sync for long-term health
"""
from __future__ import annotations

import jit_mirror


class Spy:
    """A create_fn spy that hands out discussion numbers and counts calls."""

    def __init__(self, fail: bool = False):
        self.calls = 0
        self.fail = fail
        self._n = 1000

    def __call__(self, record: dict):
        self.calls += 1
        if self.fail:
            return None
        self._n += 1
        return self._n


def test_generated_world_makes_no_api_calls():
    records = {f"r{i}": {"title": f"post {i}"} for i in range(100)}  # unsignaled
    spy = Spy()
    summary = jit_mirror.run(records, spy)
    assert spy.calls == 0  # the entire generated world, zero API calls
    assert summary["signaled"] == 0
    assert summary["promoted"] == 0


def test_signaled_record_is_promoted_to_a_shell():
    records = {"r1": {"title": "hot", "needs_mirror": True}}
    spy = Spy()
    jit_mirror.run(records, spy)
    assert spy.calls == 1
    assert jit_mirror.is_mirrored(records["r1"])
    assert records["r1"]["mirror"]["discussion"] == 1001
    assert records["r1"]["needs_mirror"] is False
    assert "promoted_at" in records["r1"]["mirror"]


def test_promotion_is_idempotent():
    records = {"r1": {"title": "hot", "needs_mirror": True}}
    spy = Spy()
    jit_mirror.run(records, spy)
    jit_mirror.run(records, spy)  # second pass must not re-create
    assert spy.calls == 1
    assert records["r1"]["mirror"]["discussion"] == 1001


def test_api_failure_leaves_record_for_retry():
    records = {"r1": {"title": "hot", "needs_mirror": True}}
    jit_mirror.run(records, Spy(fail=True))
    assert not jit_mirror.is_mirrored(records["r1"])
    assert records["r1"]["needs_mirror"] is True  # still signaled -> retried later
    jit_mirror.run(records, Spy())  # API back -> recovers
    assert jit_mirror.is_mirrored(records["r1"])


def test_only_real_interactions_among_many_hit_the_api():
    records = {f"r{i}": {"title": str(i)} for i in range(50)}
    records["r7"]["needs_mirror"] = True
    records["r42"]["needs_mirror"] = True
    spy = Spy()
    summary = jit_mirror.run(records, spy)
    assert spy.calls == 2  # only the 2 real interactions
    assert summary["promoted"] == 2
    assert sum(1 for r in records.values() if jit_mirror.is_mirrored(r)) == 2


def test_shell_tracks_ongoing_sync():
    record = {"needs_mirror": True}
    jit_mirror.promote(record, Spy())
    assert "last_synced" in record["mirror"]
    jit_mirror.mark_synced(record)
    assert record["mirror"]["discussion"] == 1001  # still a valid shell


def test_mark_synced_noop_on_unmirrored():
    record = {"title": "generated only"}
    jit_mirror.mark_synced(record)
    assert "mirror" not in record  # untouched generated-world record
