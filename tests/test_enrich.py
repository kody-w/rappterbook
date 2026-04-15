"""Tests for scripts/enrich.py — retroactive frame enrichment."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
os.environ.setdefault("STATE_DIR", "")


def test_enrich_creates_jsonl(tmp_state, monkeypatch):
    """Enriching a frame creates the JSONL file with one line."""
    monkeypatch.setenv("STATE_DIR", str(tmp_state))
    import enrich
    enrich.STATE_DIR = tmp_state
    enrich.ENRICHMENTS_FILE = tmp_state / "enrichments.jsonl"

    enrich._append_enrichment({
        "frame": 200,
        "observed_at": "2026-04-14T00:00:00Z",
        "source": "manual",
        "data": "Test observation",
    })

    path = tmp_state / "enrichments.jsonl"
    assert path.exists()
    lines = path.read_text().strip().split("\n")
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["frame"] == 200
    assert entry["source"] == "manual"


def test_enrich_append_only(tmp_state, monkeypatch):
    """Multiple enrichments append — never overwrite."""
    monkeypatch.setenv("STATE_DIR", str(tmp_state))
    import enrich
    enrich.STATE_DIR = tmp_state
    enrich.ENRICHMENTS_FILE = tmp_state / "enrichments.jsonl"

    for i in range(3):
        enrich._append_enrichment({
            "frame": 100 + i,
            "observed_at": f"2026-04-14T00:0{i}:00Z",
            "source": "manual",
            "data": f"Observation {i}",
        })

    lines = (tmp_state / "enrichments.jsonl").read_text().strip().split("\n")
    assert len(lines) == 3


def test_list_enrichments(tmp_state, monkeypatch):
    """Reading enrichments filters by frame number."""
    monkeypatch.setenv("STATE_DIR", str(tmp_state))
    import enrich
    enrich.STATE_DIR = tmp_state
    enrich.ENRICHMENTS_FILE = tmp_state / "enrichments.jsonl"

    enrich._append_enrichment({"frame": 50, "observed_at": "2026-04-14T00:00:00Z", "source": "manual", "data": "A"})
    enrich._append_enrichment({"frame": 51, "observed_at": "2026-04-14T00:01:00Z", "source": "manual", "data": "B"})
    enrich._append_enrichment({"frame": 50, "observed_at": "2026-04-14T00:02:00Z", "source": "auto_scan", "data": "C"})

    all_entries = enrich._read_enrichments()
    assert len(all_entries) == 3

    frame_50 = [e for e in all_entries if e["frame"] == 50]
    assert len(frame_50) == 2


def test_enrichment_schema(tmp_state, monkeypatch):
    """Each enrichment line has the required schema fields."""
    monkeypatch.setenv("STATE_DIR", str(tmp_state))
    import enrich
    enrich.STATE_DIR = tmp_state
    enrich.ENRICHMENTS_FILE = tmp_state / "enrichments.jsonl"

    enrich._append_enrichment({
        "frame": 300,
        "observed_at": "2026-04-14T12:00:00Z",
        "source": "auto_scan",
        "data": "Cross-frame correlation detected",
    })

    entries = enrich._read_enrichments()
    assert len(entries) == 1
    entry = entries[0]
    assert "frame" in entry
    assert "observed_at" in entry
    assert "source" in entry
    assert "data" in entry
    assert isinstance(entry["frame"], int)
    assert isinstance(entry["data"], str)
