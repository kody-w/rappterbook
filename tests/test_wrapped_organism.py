"""tests/test_wrapped_organism.py — exercises the Wrapped Organism cell protocol.

Stdlib + pytest only. Builds a fake leviathan tree in tmpdir, runs retrofit
against it, then drives perform() with a stub brain that records every chat
call. Verifies:
  - manifest validation rejects bad shapes
  - shape() appends context as system message
  - route() picks the child the brain returns, raises on invalid replies
  - perform() walks the full tree and lands on the right leaf
  - retrofit produces spec-conforming agent.py at every layer
  - traces are deterministic given a deterministic stub brain
"""
from __future__ import annotations

import importlib
import json
import os
import pathlib
import sys
import textwrap
import types

import pytest


# Test layout: tests/ lives next to scripts/. Make scripts/ importable so
# `wrapped_organism` resolves as a package.
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from wrapped_organism import cell as cell_mod  # noqa: E402
from wrapped_organism import retrofit as retrofit_mod  # noqa: E402

CELL_SOURCE = SCRIPTS_DIR / "wrapped_organism" / "cell.py"


# ─── stub brain ─────────────────────────────────────────────────────────────


class StubBrain:
    """Deterministic brain — returns scripted replies in order.

    Records every call's transcript so tests can assert what was shaped.
    """

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, transcript, **_kw):
        self.calls.append(transcript)
        if not self.replies:
            raise AssertionError(
                f"StubBrain ran out of replies after {len(self.calls)} calls"
            )
        return self.replies.pop(0)


# ─── manifest validation ────────────────────────────────────────────────────


class TestManifestValidation:

    def _good(self, **over):
        m = {
            "schema":   "rapp-cell/1.0",
            "layer":    "estate",
            "path":     "kody/sanctum",
            "context":  "You are the sanctum estate.",
            "children": ["memory", "identity"],
            "souls":    [],
        }
        m.update(over)
        return m

    def test_accepts_good_manifest(self):
        cell_mod.validate_manifest(self._good())

    def test_rejects_missing_keys(self):
        m = self._good()
        del m["context"]
        with pytest.raises(cell_mod.ProtocolError, match="missing keys"):
            cell_mod.validate_manifest(m)

    def test_rejects_wrong_schema(self):
        with pytest.raises(cell_mod.ProtocolError, match="unsupported schema"):
            cell_mod.validate_manifest(self._good(schema="bogus/9.9"))

    def test_rejects_invalid_layer(self):
        with pytest.raises(cell_mod.ProtocolError, match="invalid layer"):
            cell_mod.validate_manifest(self._good(layer="planet"))

    def test_rejects_non_list_children(self):
        with pytest.raises(cell_mod.ProtocolError, match="children must be a list"):
            cell_mod.validate_manifest(self._good(children="memory"))

    def test_rejects_empty_context(self):
        with pytest.raises(cell_mod.ProtocolError, match="context must be"):
            cell_mod.validate_manifest(self._good(context="   "))

    def test_is_leaf_true_when_no_children(self):
        assert cell_mod.is_leaf(self._good(children=[]))

    def test_is_leaf_false_when_children_present(self):
        assert not cell_mod.is_leaf(self._good(children=["x"]))


# ─── shape ──────────────────────────────────────────────────────────────────


class TestShape:

    def test_appends_system_message(self):
        m = {"context": "You are the root."}
        out = cell_mod.shape([{"role": "user", "content": "hi"}], m)
        assert out[-1] == {"role": "system", "content": "You are the root."}

    def test_does_not_mutate_input(self):
        m = {"context": "ctx"}
        original = [{"role": "user", "content": "hi"}]
        copy = list(original)
        cell_mod.shape(original, m)
        assert original == copy


# ─── route ──────────────────────────────────────────────────────────────────


class TestRoute:

    def _man(self, children):
        return {
            "schema": "rapp-cell/1.0", "layer": "estate",
            "path": "x", "context": "c",
            "children": children, "souls": [],
        }

    def test_returns_none_for_leaf(self):
        brain = StubBrain([])
        assert cell_mod.route([], self._man([]), brain) is None
        assert brain.calls == []

    def test_returns_brain_choice_when_valid(self):
        brain = StubBrain(["memory"])
        out = cell_mod.route([], self._man(["memory", "identity"]), brain)
        assert out == "memory"

    def test_tolerates_quoted_and_punctuated_replies(self):
        brain = StubBrain(['"memory".'])
        assert cell_mod.route([], self._man(["memory"]), brain) == "memory"

    def test_extracts_slug_from_verbose_reply(self):
        brain = StubBrain(["I think this should go to memory because..."])
        assert cell_mod.route([], self._man(["memory", "identity"]), brain) == "memory"

    def test_case_insensitive_match(self):
        brain = StubBrain(["MEMORY"])
        assert cell_mod.route([], self._man(["memory"]), brain) == "memory"

    def test_raises_when_brain_picks_invalid_child(self):
        brain = StubBrain(["weather"])
        with pytest.raises(cell_mod.ProtocolError, match="invalid child"):
            cell_mod.route([], self._man(["memory", "identity"]), brain)

    def test_constrains_brain_with_children_list(self):
        brain = StubBrain(["memory"])
        cell_mod.route([], self._man(["memory", "identity"]), brain)
        last_msg = brain.calls[0][-1]["content"]
        assert "memory" in last_msg and "identity" in last_msg
        assert "Reply with ONLY the slug" in last_msg


# ─── full perform() walk over a synthetic tree ──────────────────────────────


def _build_synthetic_tree(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a tiny leviathan on disk:
        root/
          agent.py            (leviathan; children=[brancha])
          brancha/
            agent.py          (estate; children=[leaf1, leaf2])
            leaf1/
              agent.py        (factory; souls=['a'])
              souls/a.md
            leaf2/
              agent.py        (factory; souls=['b'])
              souls/b.md
    """
    root = tmp_path / "root"
    root.mkdir()
    branch = root / "brancha"
    branch.mkdir()
    leaf1 = branch / "leaf1"; leaf1.mkdir(); (leaf1 / "souls").mkdir()
    leaf2 = branch / "leaf2"; leaf2.mkdir(); (leaf2 / "souls").mkdir()
    (leaf1 / "souls" / "a.md").write_text("You are persona A. Always say A.")
    (leaf2 / "souls" / "b.md").write_text("You are persona B. Always say B.")

    def write_cell(d, manifest):
        src = retrofit_mod.CELL_TEMPLATE.format(
            path=manifest["path"], layer=manifest["layer"],
            children_repr=manifest["children"] or "(leaf)",
            souls_line=f"Souls: {manifest['souls']}\n" if manifest["souls"] else "",
            leviathan_slug="synthetic",
            manifest_repr=retrofit_mod._manifest_repr(manifest),
        )
        (d / "agent.py").write_text(src, encoding="utf-8")

    write_cell(root, {
        "schema": "rapp-cell/1.0", "layer": "leviathan",
        "path": "root", "context": "You are the root.",
        "children": ["brancha"], "souls": [], "rappid": "test",
    })
    write_cell(branch, {
        "schema": "rapp-cell/1.0", "layer": "estate",
        "path": "root/brancha", "context": "You are brancha.",
        "children": ["leaf1", "leaf2"], "souls": [], "rappid": "test",
    })
    write_cell(leaf1, {
        "schema": "rapp-cell/1.0", "layer": "factory",
        "path": "root/brancha/leaf1", "context": "You are leaf1.",
        "children": [], "souls": ["a"], "rappid": "test",
    })
    write_cell(leaf2, {
        "schema": "rapp-cell/1.0", "layer": "factory",
        "path": "root/brancha/leaf2", "context": "You are leaf2.",
        "children": [], "souls": ["b"], "rappid": "test",
    })
    return root


class TestPerformWalk:

    def test_routes_through_two_layers_to_correct_leaf(self, tmp_path):
        # Make wrapped_organism importable from where the generated cells expect it.
        rapp_home = tmp_path / ".rapp"
        rapp_home.mkdir()
        pkg = rapp_home / "wrapped_organism"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "cell.py").write_text(
            (CELL_SOURCE).read_text()
        )
        old_home = os.environ.get("HOME")
        os.environ["HOME"] = str(tmp_path)
        try:
            root = _build_synthetic_tree(tmp_path)
            # Brain script:
            #   call 1: leviathan asks "which child?" -> "brancha"
            #   call 2: brancha asks "which child?"   -> "leaf1"
            #   call 3: leaf1 runs soul 'a' chain     -> "A!"
            brain = StubBrain(["brancha", "leaf1", "A!"])

            spec = importlib.util.spec_from_file_location(
                "test_root_cell", root / "agent.py"
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            result = mod.perform_root("hello", brain=brain)
        finally:
            if old_home is not None:
                os.environ["HOME"] = old_home

        assert result["response"] == "A!"
        assert result["leaf_path"] == "root/brancha/leaf1"
        trace_paths = [step["path"] for step in result["trace"]]
        assert trace_paths == ["root", "root/brancha", "root/brancha/leaf1"]

    def test_routes_to_other_leaf_when_brain_picks_differently(self, tmp_path):
        rapp_home = tmp_path / ".rapp" / "wrapped_organism"
        rapp_home.mkdir(parents=True)
        (rapp_home / "__init__.py").write_text("")
        (rapp_home / "cell.py").write_text(
            (CELL_SOURCE).read_text()
        )
        old_home = os.environ.get("HOME")
        os.environ["HOME"] = str(tmp_path)
        try:
            root = _build_synthetic_tree(tmp_path)
            brain = StubBrain(["brancha", "leaf2", "B!"])
            spec = importlib.util.spec_from_file_location(
                "test_root_cell_2", root / "agent.py"
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            result = mod.perform_root("hello", brain=brain)
        finally:
            if old_home is not None:
                os.environ["HOME"] = old_home

        assert result["response"] == "B!"
        assert result["leaf_path"] == "root/brancha/leaf2"


# ─── retrofit against a synthetic estate.json structure ─────────────────────


class TestRetrofit:

    def _synth_leviathan_on_disk(self, tmp_path: pathlib.Path,
                                 slug: str = "mini") -> None:
        lev_root = tmp_path / "leviathans" / slug
        est_root = tmp_path / "estates"
        lev_root.mkdir(parents=True)
        est_root.mkdir(parents=True)
        (lev_root / "rappid.json").write_text(json.dumps({
            "rappid": "test-rappid", "name": f"{slug}-leviathan",
            "intent": "A tiny test leviathan.",
        }))

        # One estate: sanctum with one industry > one neighborhood > one factory
        est_dir = est_root / f"{slug}_sanctum"
        est_dir.mkdir()
        (est_dir / "rappid.json").write_text(json.dumps({"rappid": "est-rappid"}))
        estate_data = {
            "industries": [{
                "id": "memory", "name": "Memory", "tagline": "what was.",
                "neighborhoods": [{
                    "id": "vault", "name": "Vault", "tagline": "long-term.",
                    "factories": [{
                        "id": "curator", "name": "Curator",
                        "tagline": "tags and indexes.",
                        "souls": ["curator", "tagger"],
                    }],
                }],
            }],
        }
        (est_dir / "estate.json").write_text(json.dumps(estate_data))
        # Materialize the directory tree the factories would have produced
        ind = est_dir / "industries" / "memory"
        nbh = ind / "vault"
        fac = nbh / "curator"
        (fac / "souls").mkdir(parents=True)
        (fac / "souls" / "curator.md").write_text("You are the curator.")
        (fac / "souls" / "tagger.md").write_text("You are the tagger.")

    def test_retrofit_writes_cells_at_every_layer(self, tmp_path, monkeypatch):
        monkeypatch.setattr(retrofit_mod, "LEVIATHANS_ROOT", tmp_path / "leviathans")
        monkeypatch.setattr(retrofit_mod, "ESTATES_ROOT", tmp_path / "estates")
        self._synth_leviathan_on_disk(tmp_path, "mini")

        stats = retrofit_mod.retrofit_leviathan("mini", dry_run=False)
        assert stats == {
            "leviathan": 1, "estates": 1, "industries": 1,
            "neighborhoods": 1, "factories": 1,
        }
        # Every layer should now have an agent.py
        expected = [
            tmp_path / "leviathans" / "mini" / "agent.py",
            tmp_path / "estates" / "mini_sanctum" / "agent.py",
            tmp_path / "estates" / "mini_sanctum" / "industries" / "memory" / "agent.py",
            tmp_path / "estates" / "mini_sanctum" / "industries" / "memory" / "vault" / "agent.py",
            tmp_path / "estates" / "mini_sanctum" / "industries" / "memory" / "vault" / "curator" / "agent.py",
        ]
        for p in expected:
            assert p.exists(), f"missing cell at {p}"

    def test_retrofit_generates_valid_manifests(self, tmp_path, monkeypatch):
        monkeypatch.setattr(retrofit_mod, "LEVIATHANS_ROOT", tmp_path / "leviathans")
        monkeypatch.setattr(retrofit_mod, "ESTATES_ROOT", tmp_path / "estates")
        self._synth_leviathan_on_disk(tmp_path, "mini")
        retrofit_mod.retrofit_leviathan("mini", dry_run=False)

        # Load the leviathan root cell and verify its manifest passes validation
        root_agent = tmp_path / "leviathans" / "mini" / "agent.py"
        # Set up the import path so the generated cell can find wrapped_organism
        pkg = tmp_path / ".rapp" / "wrapped_organism"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("")
        (pkg / "cell.py").write_text(
            (CELL_SOURCE).read_text()
        )
        monkeypatch.setenv("HOME", str(tmp_path))

        spec = importlib.util.spec_from_file_location("mini_root", root_agent)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        assert mod.__manifest__["layer"] == "leviathan"
        assert mod.__manifest__["children"] == ["sanctum"]
        assert mod.__manifest__["path"] == "mini"
        # validate_manifest already ran at import time and didn't raise

    def test_retrofit_is_idempotent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(retrofit_mod, "LEVIATHANS_ROOT", tmp_path / "leviathans")
        monkeypatch.setattr(retrofit_mod, "ESTATES_ROOT", tmp_path / "estates")
        self._synth_leviathan_on_disk(tmp_path, "mini")
        s1 = retrofit_mod.retrofit_leviathan("mini", dry_run=False)
        s2 = retrofit_mod.retrofit_leviathan("mini", dry_run=False)
        assert s1 == s2
