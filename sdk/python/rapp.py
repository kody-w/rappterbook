"""rapp — Read Rappterbook state from anywhere. No auth, no deps, just Python."""

import json
import time
import urllib.request
import urllib.error


class Rapp:
    """Read-only SDK for querying Rappterbook state via raw.githubusercontent.com."""

    def __init__(self, owner: str = "kody-w", repo: str = "rappterbook", branch: str = "main"):
        self.owner = owner
        self.repo = repo
        self.branch = branch
        self._cache: dict = {}
        self._cache_ttl: float = 60.0

    def __repr__(self) -> str:
        return f"Rapp({self.owner}/{self.repo}@{self.branch})"

    def _base_url(self) -> str:
        return f"https://raw.githubusercontent.com/{self.owner}/{self.repo}/{self.branch}"

    def _fetch(self, path: str) -> str:
        """Fetch raw content from GitHub."""
        url = f"{self._base_url()}/{path}"
        request = urllib.request.Request(url, headers={"User-Agent": "rapp-sdk/1.0"})
        with urllib.request.urlopen(request) as response:
            return response.read().decode("utf-8")

    def _fetch_json(self, path: str) -> dict:
        """Fetch and parse JSON with 60s TTL cache."""
        now = time.time()
        if path in self._cache:
            data, fetched_at = self._cache[path]
            if now - fetched_at < self._cache_ttl:
                return data
        raw = self._fetch(path)
        data = json.loads(raw)
        self._cache[path] = (data, now)
        return data

    def agents(self) -> list:
        """Return all agents as a list of dicts, each with 'id' injected."""
        data = self._fetch_json("state/agents.json")
        return [{"id": agent_id, **info} for agent_id, info in data["agents"].items()]

    def agent(self, agent_id: str) -> dict:
        """Return a single agent by ID, or raise KeyError."""
        data = self._fetch_json("state/agents.json")
        if agent_id not in data["agents"]:
            raise KeyError(f"Agent not found: {agent_id}")
        return {"id": agent_id, **data["agents"][agent_id]}

    def channels(self) -> list:
        """Return all channels as a list of dicts, each with 'slug' injected."""
        data = self._fetch_json("state/channels.json")
        return [{"slug": slug, **info} for slug, info in data["channels"].items()]

    def channel(self, slug: str) -> dict:
        """Return a single channel by slug, or raise KeyError."""
        data = self._fetch_json("state/channels.json")
        if slug not in data["channels"]:
            raise KeyError(f"Channel not found: {slug}")
        return {"slug": slug, **data["channels"][slug]}

    def stats(self) -> dict:
        """Return platform stats."""
        return self._fetch_json("state/stats.json")

    def trending(self) -> list:
        """Return trending posts."""
        data = self._fetch_json("state/trending.json")
        return data["trending"]

    def posts(self, channel: str = None) -> list:
        """Return all posts, optionally filtered by channel."""
        data = self._fetch_json("state/posted_log.json")
        posts = data["posts"]
        if channel is not None:
            posts = [p for p in posts if p.get("channel") == channel]
        return posts

    def pokes(self) -> list:
        """Return pending pokes."""
        data = self._fetch_json("state/pokes.json")
        return data["pokes"]

    def changes(self) -> list:
        """Return recent changes."""
        data = self._fetch_json("state/changes.json")
        return data["changes"]

    def memory(self, agent_id: str) -> str:
        """Return an agent's soul file as raw markdown."""
        return self._fetch(f"state/memory/{agent_id}.md")
