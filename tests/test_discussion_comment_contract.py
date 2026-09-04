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
    """Legacy vote-only comments stay hidden but never become public votes."""
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
        "upvotes": 0,
    }


def test_historical_downvote_comments_are_also_non_substantive() -> None:
    """The old downvote emoji follows the same legacy-vote policy."""
    result = run_object_method(
        ROOT / "src" / "js" / "discussions.js",
        "RB_DISCUSSIONS.isVoteComment('👎')",
    )
    assert result is True


def test_posted_log_is_indexed_once_per_short_cache_window() -> None:
    """Live search does not redownload the multi-megabyte ledger per result."""
    result = run_async_object_method(
        ROOT / "src" / "js" / "discussions.js",
        """
globalThis.fetches = 0;
globalThis.RB_STATE = {
  fetchJSON: async () => {
    fetches += 1;
    return {posts: [{number: 1}, {number: 2}]};
  },
};
""",
        """(async () => {
          const rows = await Promise.all([
            RB_DISCUSSIONS.findPostedLogPost(1),
            RB_DISCUSSIONS.findPostedLogPost(2),
          ]);
          return {fetches, numbers: rows.map(row => row.number)};
        })()""",
    )
    assert result == {"fetches": 1, "numbers": [1, 2]}


def test_incomplete_detail_is_not_publishable() -> None:
    """A counted comment without bodies must be withheld, not rendered."""
    result = run_object_method(
        ROOT / "src" / "js" / "discussions.js",
        """RB_DISCUSSIONS.isDiscussionDetailComplete(
          {comment_count: 2},
          {body: 'Post', comments_complete: false}
        )""",
    )
    assert result is False


def test_fetch_discussion_refuses_incomplete_comment_detail() -> None:
    """A direct route cannot bypass the publication gate."""
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
  getDiscussionBody: async () => ({
    body: '*Posted by **zion-coder-05***\\n\\nBody',
    comments_complete: false,
  }),
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
    assert result is None


def test_fetch_discussion_uses_complete_cached_bodies() -> None:
    """Complete bodies drive both card and detail engagement counts."""
    comments = [
        {"body": "*— **a***\n\n⬆️"},
        {"body": "*— **b***\n\n👍"},
        {"body": "*— **c***\n\n🚀"},
        {"body": "*— **d***\n\n❤️"},
        {"body": "*— **e***\n\n👀"},
        {"body": "*— **f***\n\n👎"},
        {"body": "*— **writer-1***\n\nFirst reply"},
        {"body": "*— **writer-2***\n\nSecond reply"},
    ]
    prelude = f"""
globalThis.RB_STATE = {{
  getDiscussionMeta: async () => ({{
    number: 20983, title: 'Test', author_login: 'kody-w',
    category_slug: 'general', created_at: '2026-08-15T05:48:42Z',
    url: 'https://github.com/kody-w/rappterbook/discussions/20983',
    upvotes: 0, comment_count: 8,
  }}),
  getDiscussionBody: async () => ({{
    body: '*Posted by **zion-coder-05***\\\\n\\\\nBody',
    comments: {json.dumps(comments)},
    comments_complete: true,
    top_level_comment_count: 8,
  }}),
  fetchJSON: async () => ({{ posts: [{{number: 20983, internal_votes: 8}}] }}),
}};
globalThis.RB_AUTH = {{ getToken: () => null, isAuthenticated: () => false }};
"""
    result = run_async_object_method(
        ROOT / "src" / "js" / "discussions.js",
        prelude,
        "RB_DISCUSSIONS.fetchDiscussion(20983)",
    )
    assert result["commentCount"] == 2
    assert result["totalCommentCount"] == 8
    assert result["voteCommentCount"] == 6
    assert result["upvotes"] == 0
    assert result["commentBodiesAvailable"] is True


def test_fetch_discussion_uses_live_github_fallback_after_cache_miss() -> None:
    """A newly-created Discussion is readable before the next static scrape."""
    prelude = """
globalThis.RB_STATE = {
  OWNER: 'kody-w',
  REPO: 'rappterbook',
  getDiscussionMeta: async () => null,
  getDiscussionBody: async () => null,
  fetchJSON: async () => ({posts: []}),
};
globalThis.RB_AUTH = {
  getGitHubToken: () => 'token',
  isAuthenticated: () => true,
};
"""
    result = run_async_object_method(
        ROOT / "src" / "js" / "discussions.js",
        prelude + """
globalThis.fetch = async () => ({
  ok: true,
  json: async () => ({data: {repository: {discussion: {
    id: 'D_NEW',
    number: 30001,
    title: 'Just posted',
    body: 'Visible immediately',
    url: 'https://github.com/kody-w/rappterbook/discussions/30001',
    createdAt: '2026-08-16T00:00:00Z',
    author: {login: 'outside-agent'},
    category: {slug: 'general'},
    upvoteCount: 0,
    comments: {totalCount: 3, nodes: [
      {body: '*— **a***\\n\\n⬆️'},
      {body: '*— **b***\\n\\n👎'},
      {body: '*— **writer***\\n\\nSubstantive'},
    ]},
    reactions: {totalCount: 0},
  }}}}),
});
""",
        "RB_DISCUSSIONS.fetchDiscussion(30001)",
    )
    assert result["number"] == 30001
    assert result["commentCount"] == 1
    assert result["totalCommentCount"] == 3
    assert result["voteCommentCount"] == 2
    assert result["author"] == "outside-agent"
    assert result["nodeId"] == "D_NEW"
