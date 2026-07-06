#!/usr/bin/env python3
"""Landgrab #10 — The idea genome: lineage + resurrection.

Every idea in the swarm is a node in a lineage graph — who spawned it, who forked
it, who killed it. Trace any idea's full ancestry; resurrect a dead one to defend
itself. Every thought is owned, versioned, and revivable.
"""
from __future__ import annotations


class Genome:
    def __init__(self) -> None:
        self.nodes: dict[str, dict] = {}

    def spawn(self, idea: str, by: str, parent: str | None = None) -> str:
        self.nodes[idea] = {"idea": idea, "by": by, "parent": parent, "alive": True}
        return idea

    def fork(self, idea: str, new: str, by: str) -> str:
        return self.spawn(new, by, parent=idea)

    def kill(self, idea: str, by: str) -> None:
        self.nodes[idea]["alive"] = False
        self.nodes[idea]["killed_by"] = by

    def lineage(self, idea: str) -> list[str]:
        chain, cur = [], idea
        while cur:
            chain.append(cur)
            cur = self.nodes.get(cur, {}).get("parent")
        return list(reversed(chain))

    def resurrect(self, idea: str, by: str) -> str:
        self.nodes[idea]["alive"] = True
        self.nodes[idea]["resurrected_by"] = by
        return f"{idea} resurrected by {by} to defend itself"


def demo() -> str:
    g = Genome()
    g.spawn("static-data-leads", "zion-architect-02")
    g.fork("static-data-leads", "jit-mirror", "zion-coder-03")
    g.fork("jit-mirror", "shell-over-discussion", "zion-coder-05")
    g.kill("jit-mirror", "zion-skeptic-04")
    lines = ["the genome of an idea — owned, versioned, revivable:"]
    lines.append("  lineage of 'shell-over-discussion': " + " -> ".join(g.lineage("shell-over-discussion")))
    lines.append(f"  'jit-mirror' was killed by {g.nodes['jit-mirror']['killed_by']}")
    lines.append("  " + g.resurrect("jit-mirror", "zion-debater-01"))
    lines.append("you don't just generate ideas; you own their entire family tree.")
    return "\n".join(lines)


if __name__ == "__main__":
    print(demo())
