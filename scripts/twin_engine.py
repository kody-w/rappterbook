"""Twin Engine — public digital twin of the rappter engine.

The real engine lives in kody-w/rappter (private). This is the public,
stdlib-only twin that exposes the same primitives any rappterbook
simulation needs:

  * deterministic frame loop:        Engine.run(n_frames)
  * seeded RNG (SHA-256 derived):    Engine.coin(label) / Engine.choice
  * delta journal:                   self.deltas appended every frame
  * snapshot/restore:                save(path) / load(path)
  * pluggable tick function:         user supplies tick(engine, state, frame)

Same inputs → same outputs on any machine. No external deps.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Callable

ENGINE_VERSION = "twin-1.0"


def _h(*parts: str) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()


def coin(seed: str, label: str) -> float:
    """Deterministic uniform [0,1) from (seed, label)."""
    return int(_h(seed, label)[:13], 16) / 16**13


def pick(seed: str, label: str, options: list[Any]) -> Any:
    """Deterministic choice from `options`."""
    if not options:
        raise ValueError("pick from empty list")
    idx = int(_h(seed, label)[:13], 16) % len(options)
    return options[idx]


def shuffle(seed: str, label: str, items: list[Any]) -> list[Any]:
    """Deterministic shuffle (Fisher-Yates with SHA-256 derived swaps)."""
    arr = list(items)
    n = len(arr)
    for i in range(n - 1, 0, -1):
        j = int(_h(seed, label, str(i))[:13], 16) % (i + 1)
        arr[i], arr[j] = arr[j], arr[i]
    return arr


class Engine:
    """The frame loop. Holds state, runs ticks, journals deltas."""

    def __init__(self, name: str, seed: int, state: dict, tick: Callable):
        self.name = name
        self.seed = seed
        self.state = state
        self.tick = tick
        self.frame = 0
        self.deltas: list[dict] = []
        self.started_at = time.time()

    def frame_seed(self, label: str = "") -> str:
        return _h(self.name, str(self.seed), str(self.frame), label)

    def coin(self, label: str) -> float:
        return coin(self.frame_seed(), label)

    def pick(self, label: str, options: list[Any]) -> Any:
        return pick(self.frame_seed(), label, options)

    def shuffle(self, label: str, items: list[Any]) -> list[Any]:
        return shuffle(self.frame_seed(), label, items)

    def run(self, n_frames: int, on_frame: Callable | None = None) -> dict:
        for _ in range(n_frames):
            self.frame += 1
            delta = self.tick(self, self.state, self.frame) or {}
            entry = {"frame": self.frame, "delta": delta}
            self.deltas.append(entry)
            if on_frame:
                on_frame(self, self.state, self.frame, delta)
        return self.state

    def snapshot(self) -> dict:
        return {
            "engine_version": ENGINE_VERSION,
            "name": self.name,
            "seed": self.seed,
            "frame": self.frame,
            "started_at": self.started_at,
            "state": self.state,
            "deltas": self.deltas,
        }

    def save(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(self.snapshot(), indent=2))
        os.replace(tmp, p)
        return p

    @classmethod
    def load(cls, path: str | Path, tick: Callable) -> "Engine":
        snap = json.loads(Path(path).read_text())
        eng = cls(snap["name"], snap["seed"], snap["state"], tick)
        eng.frame = snap["frame"]
        eng.deltas = snap["deltas"]
        eng.started_at = snap.get("started_at", time.time())
        return eng


def run_engine(name: str, seed: int, initial_state: dict, tick: Callable,
               n_frames: int, save_to: str | Path | None = None) -> Engine:
    """One-shot helper: build, run, optionally save."""
    eng = Engine(name, seed, initial_state, tick)
    eng.run(n_frames)
    if save_to:
        eng.save(save_to)
    return eng


__all__ = ["Engine", "run_engine", "coin", "pick", "shuffle", "ENGINE_VERSION"]
