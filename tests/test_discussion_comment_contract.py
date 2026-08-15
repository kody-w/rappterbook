"""Frontend comment counts must share one vote/comment contract."""
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def run_object_method(path: Path, expression: str) -> dict:
    """Evaluate one pure object method with Node and return its JSON result."""
    source = path.read_text(encoding="utf-8")
    script = f"{source}\nconsole.log(JSON.stringify({expression}));"
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def run_async_object_method(path: Path, prelude: str, expression: str) -> dict:
    """Evaluate one async object method with deterministic browser-state stubs."""
    source = path.read_text(encoding="utf-8")
    script = (
        f"{prelude}\n{source}\n"
        f"(async () => console.log(JSON.stringify(await {expression})))()"
        ".catch(error => { console.error(error); process.exit(1); });"
    )
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_vote_comments_are_not_rendered_as_discussion_comments() -> None:
    """Vote-only comments become votes; substantive comments stay comments."""
    result = run_object_method(
        ROOT / "src" / "js" / "discussions.js",
        """RB_DISCUSSIONS.normalizePostedEngagement({
          commentCount: 8,
          vote_comment_count: 6,
          internal_votes: 8,
          voters: ['a','b','c','d','e','f','g','h']
        }, 8, 0)""",
    )
    assert result == {
        "commentCount": 2,
        "totalCommentCount": 8,
        "voteCommentCount": 6,
        "upvotes": 8,
    }


def test_detail_uses_reported_count_when_bodies_are_missing() -> None:
    """A body-cache miss must not become the false claim 'No comments yet'."""
    result = run_object_method(
        ROOT / "src" / "js" / "render.js",
        "RB_RENDER.getDiscussionCommentSummary({commentCount: 2}, [])",
    )
    assert result == {
        "count": 2,
        "renderedCount": 0,
        "missingBodies": True,
        "partialBodies": False,
    }


def test_fetch_discussion_applies_posted_vote_comment_semantics() -> None:
    """The detail model must match the card's vote/comment split."""
    prelude = """
globalThis.RB_STATE = {
  getDiscussionMeta: async () => ({
    number: 20983,
    title: 'Test',
    author_login: 'kody-w',
    category_slug: 'general',
    created_at: '2026-08-15T05:48:42Z',
    url: 'https://github.com/kody-w/rappterbook/discussions/20983',
    upvotes: 0,
    comment_count: 8,
  }),
  getDiscussionBody: async () => ({ body: '*Posted by **zion-coder-05***\\n\\nBody' }),
  fetchJSON: async path => path === 'state/posted_log.json'
    ? { posts: [{
        number: 20983,
        commentCount: 8,
        vote_comment_count: 6,
        internal_votes: 8,
        voters: ['a','b','c','d','e','f','g','h'],
      }] }
    : {},
};
globalThis.RB_AUTH = { getToken: () => null, isAuthenticated: () => false };
"""
    result = run_async_object_method(
        ROOT / "src" / "js" / "discussions.js",
        prelude,
        "RB_DISCUSSIONS.fetchDiscussion(20983)",
    )
    assert result["commentCount"] == 2
    assert result["totalCommentCount"] == 8
    assert result["voteCommentCount"] == 6
    assert result["upvotes"] == 8
    assert result["commentBodiesAvailable"] is False


def test_detail_fallback_names_missing_public_cache_bodies() -> None:
    """The detail renderer must explain missing bodies and link to GitHub."""
    source = (ROOT / "src" / "js" / "render.js").read_text(encoding="utf-8")
    assert "comments exist, but their bodies are not in the public cache yet" in source
    assert "Comments (${commentSummary.count})" in source
