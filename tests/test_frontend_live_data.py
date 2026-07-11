"""Behavioral tests for feed freshness and GitHub auth/live data paths."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node is required")


def _run_async_javascript(path: Path, body: str, prelude: str):
    """Evaluate a source file and one async test body."""
    script = (
        f"{prelude}\n"
        f"{path.read_text(encoding='utf-8')}\n"
        "(async () => {\n"
        f"{body}\n"
        "})().catch(error => { console.error(error); process.exit(1); });\n"
    )
    result = subprocess.run(
        [NODE, "-e", script],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_recent_posts_survive_shard_lag_without_monolith_fetch() -> None:
    """A current logged post remains visible as an external GitHub link."""
    discussions = ROOT / "src" / "js" / "discussions.js"
    prelude = """
      const requests = [];
      const RB_STATE = {
        OWNER: 'kody-w', REPO: 'rappterbook',
        fetchJSON: async path => {
          requests.push(path);
          return { posts: [{
            number: 20659, title: '[IDEA] Fresh', author: 'alice',
            channel: 'general', timestamp: '2026-07-11T00:00:00Z'
          }] };
        },
        getDiscussionMeta: async () => null,
        getDiscussionBody: async () => { throw new Error('body shard should not load'); }
      };
      const RB_AUTH = { hasGitHubCapability: () => false };
    """
    body = """
      const posts = await RB_DISCUSSIONS.fetchRecent(null, 10);
      console.log(JSON.stringify({ posts, requests }));
    """

    result = _run_async_javascript(discussions, body, prelude)

    assert len(result["posts"]) == 1
    assert result["posts"][0]["cacheAvailable"] is False
    assert result["posts"][0]["url"].endswith("/discussions/20659")
    assert result["requests"] == ["state/posted_log.json"]


def test_graphql_uses_only_github_token() -> None:
    """A platform JWT is never sent to api.github.com."""
    discussions = ROOT / "src" / "js" / "discussions.js"
    prelude = """
      let authorization = null;
      const RB_AUTH = {
        getGitHubToken: () => 'github-token',
        getToken: () => 'platform-jwt'
      };
      const RB_STATE = { OWNER: 'kody-w', REPO: 'rappterbook' };
      const fetch = async (url, options) => {
        authorization = options.headers.Authorization;
        return { ok: true, json: async () => ({ data: { viewer: { login: 'alice' } } }) };
      };
    """
    body = """
      await RB_DISCUSSIONS.graphql('query { viewer { login } }');
      console.log(JSON.stringify({ authorization }));
    """

    result = _run_async_javascript(discussions, body, prelude)

    assert result["authorization"] == "bearer github-token"


def test_live_comments_accept_empty_authoritative_response() -> None:
    """A successful empty live response does not fall back to stale comments."""
    discussions = ROOT / "src" / "js" / "discussions.js"
    prelude = """
      const RB_AUTH = { getGitHubToken: () => 'github-token' };
      const RB_STATE = { OWNER: 'kody-w', REPO: 'rappterbook' };
    """
    body = """
      RB_DISCUSSIONS.graphql = async () => ({
        repository: { discussion: { comments: { nodes: [] } } }
      });
      const result = await RB_DISCUSSIONS._fetchCommentsLive(42);
      console.log(JSON.stringify(result));
    """

    result = _run_async_javascript(discussions, body, prelude)

    assert result == {"comments": [], "voteCount": 0, "voters": []}


def test_oauth_callback_uses_code_then_github_token_routes() -> None:
    """Redirect OAuth exchanges code before validating the GitHub token."""
    auth = ROOT / "src" / "js" / "auth.js"
    prelude = """
      const values = new Map();
      const localStorage = {
        getItem: key => values.has(key) ? values.get(key) : null,
        setItem: (key, value) => values.set(key, String(value)),
        removeItem: key => values.delete(key)
      };
      const sessionValues = new Map();
      const sessionStorage = {
        getItem: key => sessionValues.has(key) ? sessionValues.get(key) : null,
        setItem: (key, value) => sessionValues.set(key, String(value)),
        removeItem: key => sessionValues.delete(key)
      };
      const calls = [];
      const fetch = async (url, options) => {
        calls.push({ url, body: JSON.parse(options.body) });
        if (url.endsWith('/api/auth/token')) {
          return { ok: true, json: async () => ({ access_token: 'github-token' }) };
        }
        return {
          ok: true,
          json: async () => ({ token: 'github-token', user: { login: 'alice' } })
        };
      };
      const window = {
        location: {
          search: '?code=oauth-code', origin: 'https://kody-w.github.io',
          pathname: '/rappterbook/', hash: ''
        },
        history: { replaceState: () => {} }
      };
    """
    body = """
      RB_AUTH._updateUI = () => {};
      const success = await RB_AUTH.handleCallback();
      console.log(JSON.stringify({
        success,
        routes: calls.map(call => call.url.split('/api')[1]),
        firstBody: calls[0].body,
        githubToken: sessionStorage.getItem('rb_github_token'),
        platformToken: sessionStorage.getItem('rb_jwt')
      }));
    """

    result = _run_async_javascript(auth, body, prelude)

    assert result == {
        "success": True,
        "routes": ["/auth/token", "/auth/github"],
        "firstBody": {"code": "oauth-code"},
        "githubToken": "github-token",
        "platformToken": None,
    }


def test_platform_jwt_does_not_unlock_github_write_controls() -> None:
    """A non-GitHub session is not presented as Discussion-write capable."""
    auth = ROOT / "src" / "js" / "auth.js"
    prelude = """
      const values = new Map();
      const localStorage = {
        getItem: key => values.has(key) ? values.get(key) : null,
        setItem: (key, value) => values.set(key, String(value)),
        removeItem: key => values.delete(key)
      };
      const sessionValues = new Map([['rb_jwt', 'platform-only']]);
      const sessionStorage = {
        getItem: key => sessionValues.has(key) ? sessionValues.get(key) : null,
        setItem: (key, value) => sessionValues.set(key, String(value)),
        removeItem: key => sessionValues.delete(key)
      };
    """
    body = """
      console.log(JSON.stringify({
        authenticated: RB_AUTH.isAuthenticated(),
        githubCapable: RB_AUTH.hasGitHubCapability()
      }));
    """

    result = _run_async_javascript(auth, body, prelude)

    assert result == {"authenticated": False, "githubCapable": False}


def test_legacy_persistent_token_migrates_to_session_storage() -> None:
    """Existing users are signed out persistently without losing the current tab."""
    auth = ROOT / "src" / "js" / "auth.js"
    prelude = """
      const values = new Map([['rb_github_token', 'legacy-token']]);
      const localStorage = {
        getItem: key => values.has(key) ? values.get(key) : null,
        setItem: (key, value) => values.set(key, String(value)),
        removeItem: key => values.delete(key)
      };
      const sessionValues = new Map();
      const sessionStorage = {
        getItem: key => sessionValues.has(key) ? sessionValues.get(key) : null,
        setItem: (key, value) => sessionValues.set(key, String(value)),
        removeItem: key => sessionValues.delete(key)
      };
    """
    body = """
      const token = RB_AUTH.getGitHubToken();
      console.log(JSON.stringify({
        token,
        persistent: localStorage.getItem('rb_github_token'),
        session: sessionStorage.getItem('rb_github_token')
      }));
    """

    result = _run_async_javascript(auth, body, prelude)

    assert result == {
        "token": "legacy-token",
        "persistent": None,
        "session": "legacy-token",
    }


def test_frontend_has_no_monolithic_discussion_cache_fallback() -> None:
    """List and detail reads remain shard-bounded."""
    source = (
        (ROOT / "src" / "js" / "discussions.js").read_text()
        + (ROOT / "src" / "js" / "state.js").read_text()
    )

    assert "state/discussions_cache.json" not in source


def test_misleading_live_mode_toggle_is_removed() -> None:
    """Fresh detail fallback is automatic instead of exposing an inert toggle."""
    source = (
        (ROOT / "src" / "js" / "app.js").read_text()
        + (ROOT / "src" / "js" / "router.js").read_text()
        + (ROOT / "src" / "html" / "index.html").read_text()
    )

    assert "data-mode-toggle" not in source
