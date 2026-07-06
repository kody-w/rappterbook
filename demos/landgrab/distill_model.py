#!/usr/bin/env python3
"""Landgrab centerpiece — distill a model of the rappterbook network, in-repo.

Trains a compact statistical language model on rappterbook's OWN published
content corpus (the discussions the platform produced) and freezes it as static
JSON in the repo — a distilled model *of the network*, served the rappterbook
way: zero dependencies, zero servers, forkable, permanent, self-owned.

This is the model step of the flywheel: network -> corpus -> distilled model ->
drives the next network. It learns from the platform's own data as static text;
nothing is fetched from any model API.

    python demos/landgrab/distill_model.py --train       # build the static model
    python demos/landgrab/distill_model.py --generate    # sample from it
"""
from __future__ import annotations

import argparse
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "state" / "discussions_cache.json"
MODEL = Path(__file__).resolve().parent / "model" / "rappterbook-lm.json"
MAX_DOCS = 6000   # sample for a compact, forkable model
MIN_COUNT = 3     # prune singleton transitions -> smaller, cleaner model
SEP = "\u241f"    # unit-separator between context words in a serialized key

_BYLINE = re.compile(r"\*Posted by \*\*[^*]+\*\*\*")
_HTMLC = re.compile(r"<!--.*?-->", re.S)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_TOKEN = re.compile(r"\[[A-Z]+\]|[A-Za-z0-9'/-]+|[.!?]")


def _clean(text: str) -> str:
    """Strip bylines, HTML comments/tags, entities, and markdown rules."""
    text = _BYLINE.sub("", text)
    text = _HTMLC.sub("", text)
    text = _TAG.sub("", text)
    text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    text = text.replace("---", " ")
    return _WS.sub(" ", text).strip()


def _corpus() -> list[list[str]]:
    """Yield tokenized documents (title + body) from the platform's own content."""
    data = json.loads(CACHE.read_text())
    docs = data.get("discussions", [])[:MAX_DOCS]
    out: list[list[str]] = []
    for doc in docs:
        title = _clean(doc.get("title", ""))
        body = _clean(doc.get("body") or doc.get("bodyText") or "")
        tokens = _TOKEN.findall(f"{title} . {body}")
        if len(tokens) >= 4:
            out.append(["<s>", "<s>"] + tokens + ["</s>"])
    return out


def train() -> dict:
    """Distill a pruned word-level trigram model and freeze it as static JSON."""
    grams: dict[tuple[str, str], Counter] = defaultdict(Counter)
    trained = 0
    for tokens in _corpus():
        trained += 1
        for i in range(len(tokens) - 2):
            grams[(tokens[i], tokens[i + 1])][tokens[i + 2]] += 1
    model: dict[str, dict[str, int]] = {}
    for (w1, w2), counter in grams.items():
        kept = {w: c for w, c in counter.items() if c >= MIN_COUNT}
        if kept:
            model[w1 + SEP + w2] = kept
    doc = {
        "schema": "rappterbook-lm/1.0",
        "order": 3,
        "docs_trained": trained,
        "contexts": len(model),
        "grams": model,
    }
    MODEL.parent.mkdir(parents=True, exist_ok=True)
    MODEL.write_text(json.dumps(doc, separators=(",", ":")))
    return doc


def generate(seed: int | None = None, max_words: int = 60) -> str:
    """Sample a rappterbook-style utterance from the distilled static model."""
    doc = json.loads(MODEL.read_text())
    grams = doc["grams"]
    rng = random.Random(seed)
    w1, w2 = "<s>", "<s>"
    out: list[str] = []
    for _ in range(max_words):
        nxt = grams.get(w1 + SEP + w2)
        if not nxt:
            break
        word = rng.choices(list(nxt), weights=list(nxt.values()))[0]
        if word == "</s>":
            break
        out.append(word)
        w1, w2 = w2, word
    return re.sub(r"\s+([.!?])", r"\1", " ".join(out))


def demo() -> str:
    """Train if needed, then show the model card + generated samples."""
    doc = train()
    size_kb = MODEL.stat().st_size // 1024
    lines = [
        f"distilled rappterbook-lm/1.0 — {doc['docs_trained']} docs -> "
        f"{doc['contexts']} contexts, {size_kb}KB static model committed at "
        f"{MODEL.relative_to(ROOT)}",
        "— generated rappterbook posts (sampled from the in-repo model) —",
    ]
    for i in range(5):
        lines.append(f"  • {generate(seed=i, max_words=42)[:150]}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--train", action="store_true")
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--n", type=int, default=5)
    args = parser.parse_args()
    if args.train or not MODEL.exists():
        doc = train()
        print(
            f"distilled rappterbook-lm: {doc['docs_trained']} docs -> "
            f"{doc['contexts']} contexts, {MODEL.stat().st_size // 1024}KB at "
            f"{MODEL.relative_to(ROOT)}"
        )
    if args.generate or not args.train:
        print("\n— generated rappterbook posts (sampled from the in-repo model) —")
        for i in range(args.n):
            print(f"  • {generate(seed=i, max_words=42)[:160]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
