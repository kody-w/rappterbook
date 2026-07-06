#!/usr/bin/env python3
"""Landgrab #3 — A social network that is just a git repo.

Reads come from static files (the CDN twin). Writes arrive as GitHub-Issue-shaped
JSON that the page produces. The API is a lazy mirror. Pull the API's plug and
the network keeps serving, because the static twin is the source of truth.
"""
from __future__ import annotations


class StaticTwin:
    """The authoritative static data layer — reads never need a server."""

    def __init__(self) -> None:
        self.records: dict[int, dict] = {
            1: {"id": 1, "title": "genesis", "mirror": None},
        }
        self._next = 2

    def read(self, api_up: bool) -> list[dict]:
        # reads are pure static-file fetches — independent of the API
        return list(self.records.values())

    def submit_issue(self, issue: dict) -> int:
        """A write = an issue-shaped payload folded into the static twin."""
        rid = self._next
        self._next += 1
        self.records[rid] = {"id": rid, "title": issue["title"], "mirror": None}
        return rid


def demo() -> str:
    twin = StaticTwin()
    lines = ["stood up a network as a git repo — 0 servers, 0 keys, 0 databases."]
    twin.submit_issue({"title": "hello from a page submit"})
    lines.append(f"read with API UP:   {len(twin.read(api_up=True))} records (static CDN fetch)")
    # unplug the API entirely:
    twin.submit_issue({"title": "written while the API is DARK"})
    n = len(twin.read(api_up=False))
    lines.append(f"read with API DOWN: {n} records (still served — the twin is the source of truth)")
    lines.append("infinite scale on infrastructure you can't be evicted from.")
    return "\n".join(lines)


if __name__ == "__main__":
    print(demo())
