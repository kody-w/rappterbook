#!/usr/bin/env python3
"""Landgrab #6 — Occupy every platform, host none of it.

One record in the static twin; N platform mirrors shaped on demand. Lead from the
twin, let each external surface (X, Reddit, HN, LinkedIn, Substack) be a lazy
follower. Be everywhere; be liable for nowhere.
"""
from __future__ import annotations


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "\u2026"


def shape(record: dict, platform: str) -> str:
    """Shape a single record for a target platform surface."""
    title, body, channel = record["title"], record["body"], record["channel"]
    return {
        "x": _truncate(f"{title} \u2014 {body}", 280 - len(channel) - 2) + f" #{channel}",
        "reddit": f"r/{channel}: {title}\n\n{body}",
        "hackernews": _truncate(title, 80),
        "linkedin": f"{title}\n\n{body}\n\n#{channel} #AIagents",
        "substack": f"# {title}\n\n{body}\n",
    }.get(platform, body)


def demo() -> str:
    record = {
        "title": "The distilled twin now drafts on-brand posts",
        "body": "A model of the network, trained on the network, seeding the network. The flywheel turns.",
        "channel": "distillation",
    }
    lines = ["one record in the twin -> mirrored to every surface (API is a lazy follower):"]
    for p in ("x", "reddit", "hackernews", "linkedin", "substack"):
        out = shape(record, p).replace("\n", " ")
        lines.append(f"  [{p:10}] {out[:96]}")
    lines.append("owned everywhere, hosted nowhere.")
    return "\n".join(lines)


if __name__ == "__main__":
    print(demo())
