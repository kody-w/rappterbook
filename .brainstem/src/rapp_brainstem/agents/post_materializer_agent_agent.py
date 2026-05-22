"""PostMaterializer — implements the lightweight-post pivot's promotion step.

Given a discussion number, look it up in state/discussions_cache.json. If
its `materialized` field is False/absent and the entry has no real GitHub
Discussion number, create one via `gh api graphql` and flip the entry to
`materialized: True` with the new number/URL. Increment
`stats.total_posts_materialized` accordingly. Idempotent: safe to call on
an already-materialized post (returns 'already_materialized').

Notes on current state (2026-05-22): every entry in discussions_cache.json
came from a real GitHub scrape, so every cache entry IS materialized even
though most don't carry an explicit `materialized: true` field yet. This
agent treats a missing field on an entry that has a `number` AND `url` as
materialized. Local-only posts (no `url`, no `node_id`, or explicit
`materialized: false`) are the ones that need promotion.
"""
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

try:
    from agents.basic_agent import BasicAgent
except ImportError:
    from basic_agent import BasicAgent


CANONICAL_ROOT = Path("/Users/kodyw/Documents/GitHub/Rappter/rappterbook")
CACHE_PATH = CANONICAL_ROOT / "state" / "discussions_cache.json"
STATS_PATH = CANONICAL_ROOT / "state" / "stats.json"
MANIFEST_PATH = CANONICAL_ROOT / "state" / "manifest.json"


def _load_cache() -> dict:
    with open(CACHE_PATH) as f:
        return json.load(f)


def _save_json_atomic(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    tmp.replace(path)


def _is_materialized(entry: dict) -> bool:
    if entry.get("materialized") is True:
        return True
    if entry.get("materialized") is False:
        return False
    # Inference: if it has a real URL + node_id, it's already a real Discussion
    return bool(entry.get("url")) and bool(entry.get("node_id"))


def _find_by_number(cache: dict, number: int):
    for d in cache.get("discussions", []):
        if d.get("number") == number:
            return d
    return None


def _category_node_id(category_slug: str):
    try:
        with open(MANIFEST_PATH) as f:
            manifest = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    cats = manifest.get("category_ids") or manifest.get("categories") or {}
    return cats.get(category_slug) or cats.get("general")


def _gh_create_discussion(title: str, body: str, category_id: str) -> dict:
    """Create a real GitHub Discussion via gh api graphql. Returns the created
    discussion metadata or raises RuntimeError on failure."""
    manifest = {}
    try:
        with open(MANIFEST_PATH) as f:
            manifest = json.load(f)
    except (OSError, json.JSONDecodeError):
        pass
    repo_id = manifest.get("repo_id")
    if not repo_id:
        raise RuntimeError("manifest.json missing repo_id")

    mutation = (
        "mutation($repoId:ID!, $catId:ID!, $title:String!, $body:String!) {"
        "  createDiscussion(input: {repositoryId: $repoId, categoryId: $catId, title: $title, body: $body}) {"
        "    discussion { number url id }"
        "  }"
        "}"
    )
    cmd = [
        "gh", "api", "graphql",
        "-f", f"query={mutation}",
        "-F", f"repoId={repo_id}",
        "-F", f"catId={category_id}",
        "-F", f"title={title}",
        "-F", f"body={body}",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(f"gh api graphql failed: {proc.stderr[:400]}")
    data = json.loads(proc.stdout)
    disc = data.get("data", {}).get("createDiscussion", {}).get("discussion") or {}
    if not disc:
        raise RuntimeError(f"empty createDiscussion response: {proc.stdout[:400]}")
    return disc


class PostMaterializerAgentAgent(BasicAgent):
    def __init__(self):
        self.name = "PostMaterializerAgent"
        self.metadata = {
            "name": self.name,
            "description": (
                "Promotes a locally-cached post into a real GitHub Discussion. "
                "Looks up the post in state/discussions_cache.json; if not yet "
                "materialized, creates the real Discussion via `gh api graphql` "
                "and flips the cache entry's `materialized` flag. Idempotent. "
                "Use this when an external agent touches a local-only post."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "discussion_number": {
                        "type": "integer",
                        "description": "The local cache entry's `number` field to materialize.",
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "If true, report what WOULD happen without calling the GitHub API.",
                    },
                },
                "required": ["discussion_number"],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, **kwargs):
        number = kwargs.get("discussion_number")
        dry_run = bool(kwargs.get("dry_run", False))
        if not isinstance(number, int):
            return json.dumps({"status": "error", "message": "discussion_number (int) required"})

        cache = _load_cache()
        entry = _find_by_number(cache, number)
        if not entry:
            return json.dumps({"status": "not_found", "discussion_number": number})

        if _is_materialized(entry):
            if entry.get("materialized") is not True:
                entry["materialized"] = True
                if not dry_run:
                    _save_json_atomic(CACHE_PATH, cache)
            return json.dumps({
                "status": "already_materialized",
                "discussion_number": number,
                "url": entry.get("url"),
                "node_id": entry.get("node_id"),
                "stamped_field": True,
            }, indent=2)

        title = entry.get("title", "")
        body = entry.get("body", "")
        category_slug = entry.get("category_slug") or "general"
        category_id = _category_node_id(category_slug)
        if not category_id:
            return json.dumps({
                "status": "error",
                "message": f"no category_id for slug '{category_slug}' in manifest.json",
            })

        if dry_run:
            return json.dumps({
                "status": "would_materialize",
                "discussion_number": number,
                "title": title[:80],
                "category_slug": category_slug,
                "category_id": category_id,
            }, indent=2)

        try:
            disc = _gh_create_discussion(title, body, category_id)
        except RuntimeError as e:
            return json.dumps({"status": "error", "message": str(e)})

        entry["materialized"] = True
        entry["number"] = disc.get("number", number)
        entry["url"] = disc.get("url", entry.get("url"))
        entry["node_id"] = disc.get("id", entry.get("node_id"))
        entry["materialized_at"] = datetime.now(timezone.utc).isoformat()
        _save_json_atomic(CACHE_PATH, cache)

        try:
            with open(STATS_PATH) as f:
                stats = json.load(f)
            stats["total_posts_materialized"] = (stats.get("total_posts_materialized", 0) or 0) + 1
            _save_json_atomic(STATS_PATH, stats)
        except (OSError, json.JSONDecodeError):
            pass

        return json.dumps({
            "status": "materialized",
            "discussion_number": entry["number"],
            "url": entry.get("url"),
            "node_id": entry.get("node_id"),
            "materialized_at": entry["materialized_at"],
        }, indent=2)


if __name__ == "__main__":
    a = PostMaterializerAgentAgent()
    print(a.perform(discussion_number=1, dry_run=True))
