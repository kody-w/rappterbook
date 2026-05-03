"""
hacker_news_agent.py — top stories from Hacker News, via the public Firebase API.

Mirrors the OG local brainstem's hacker_news_agent.py. No API key, no auth.
In Pyodide we fall back to fetch() via JS interop because urllib/requests
need the browser networking layer.
"""

import json
from agents.basic_agent import BasicAgent


__manifest__ = {
    "schema": "rapp-agent/1.0",
    "name": "@rapp/hacker_news",
    "version": "1.0.0",
    "display_name": "Hacker News",
    "description": "Fetches the top N stories from Hacker News.",
    "author": "RAPP",
    "tags": ["starter", "news", "http"],
    "category": "integrations",
    "quality_tier": "official",
    "requires_env": [],
    # Quick-click prompt the brainstem uses when you tap this agent's card/pill.
    "example_call": "What are the top 5 stories on Hacker News right now?",
}


_HN_TOP = "https://hacker-news.firebaseio.com/v0/topstories.json"
_HN_ITEM = "https://hacker-news.firebaseio.com/v0/item/{}.json"


def _fetch_json(url):
    """GET a URL → dict. Tries Pyodide JS fetch first, falls back to urllib."""
    try:
        from pyodide.http import open_url  # type: ignore
        return json.loads(open_url(url).read())
    except Exception:
        pass
    try:
        import urllib.request
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        raise RuntimeError(f"fetch failed: {e}")


class HackerNewsAgent(BasicAgent):
    def __init__(self):
        self.name = "HackerNews"
        self.metadata = {
            "name": self.name,
            "description": (
                "Fetches the current top stories from Hacker News. Returns title, "
                "URL, score, and author for each. Use when the user asks what's "
                "on Hacker News, what's trending in tech, or for news headlines."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "count": {
                        "type": "integer",
                        "description": "How many top stories to return. Default 10, max 30.",
                        "minimum": 1,
                        "maximum": 30,
                    },
                },
                "required": [],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, **kwargs):
        count = max(1, min(30, int(kwargs.get("count", 10) or 10)))
        try:
            top_ids = _fetch_json(_HN_TOP)[:count]
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

        stories = []
        for sid in top_ids:
            try:
                d = _fetch_json(_HN_ITEM.format(sid))
                if not d:
                    continue
                stories.append({
                    "id": sid,
                    "title": d.get("title"),
                    "url": d.get("url") or f"https://news.ycombinator.com/item?id={sid}",
                    "score": d.get("score"),
                    "author": d.get("by"),
                    "comments": d.get("descendants", 0),
                })
            except Exception:
                continue

        # Markdown with proper [title](url) links + HN comments link.
        # The LLM tends to copy this format verbatim; pre-linked here means
        # the rendered chat bubble has clickable titles + comment threads.
        summary_lines = []
        for i, s in enumerate(stories):
            comments_url = f"https://news.ycombinator.com/item?id={s['id']}"
            summary_lines.append(
                f"{i+1}. **[{s['title']}]({s['url']})** "
                f"— {s.get('score', 0)} points, by {s.get('author', '?')} "
                f"· [{s.get('comments', 0)} comments]({comments_url})"
            )
        return json.dumps({
            "status": "success",
            "stories": stories,
            "summary": "Top Hacker News stories:\n\n" + "\n\n".join(summary_lines)
                       + "\n\nWhen presenting these to the user, render the titles as clickable markdown links exactly as written above.",
            "data_slush": {"count": len(stories), "top_url": stories[0]["url"] if stories else None},
        })
