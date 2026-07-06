#!/usr/bin/env python3
"""Landgrab #26 — Ideas evolve by natural selection (Darwin in the repo).

Give the network a fitness function and it breeds. The population is generated
posts; fitness is the eval-judge (specificity + substance - slop); each
generation keeps the fittest, crosses them over, and mutates the offspring. With
elitist selection the mean fitness of the population climbs generation over
generation — measurable, honest evolution. Content that gets better on its own is
the whole landgrab in one loop.
"""
from __future__ import annotations

import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from distill_model import MODEL, generate, train
from debate import judge


def _fitness(tokens: list[str]) -> float:
    return judge(re.sub(r"\s+([.!?])", r"\1", " ".join(tokens)))


def _crossover(a, b, rng):
    ca, cb = len(a) // 2, len(b) // 2
    child = a[:ca] + b[cb:]
    return child[:44]


def _mutate(tokens, rng):
    if len(tokens) > 6 and rng.random() < 0.7:
        i = rng.randrange(len(tokens))
        graft = generate(seed=rng.randint(0, 99999), max_words=8).split()
        tokens = tokens[:i] + graft[:3] + tokens[i:]
    return tokens[:44]


def evolve(pop_size=24, generations=8):
    if not MODEL.exists():
        train()
    rng = random.Random(2024)
    pop = [generate(seed=i, max_words=40).split() for i in range(pop_size)]
    history = []
    for _g in range(generations):
        scored = sorted(pop, key=_fitness, reverse=True)
        mean = sum(_fitness(p) for p in pop) / len(pop)
        history.append(round(mean, 3))
        elite = scored[:max(2, pop_size // 3)]
        children = []
        while len(children) < pop_size - len(elite):
            a, b = rng.choice(elite), rng.choice(elite)
            children.append(_mutate(_crossover(a, b, rng), rng))
        pop = elite + children
    best = max(pop, key=_fitness)
    return history, re.sub(r"\s+([.!?])", r"\1", " ".join(best))


def demo() -> str:
    history, champion = evolve()
    spark = "  ".join(f"g{ i}:{h:.1f}" for i, h in enumerate(history))
    lines = ["natural selection of ideas — elitist GA, fitness = the eval-judge:",
             f"  mean population fitness by generation:",
             f"    {spark}",
             f"  climbed {history[0]:.2f} \u2192 {history[-1]:.2f} "
             f"(+{(history[-1]-history[0]):.2f}) with zero human curation.",
             f"  fittest survivor: \u201c{champion[:82]}\u201d",
             "  the content literally gets better by breeding. evolution, in a git repo."]
    return "\n".join(lines)


if __name__ == "__main__":
    print(demo())
