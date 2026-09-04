"""Tests for notification wiring in frontend."""
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def run_async(prelude: str, expression: str):
    """Evaluate an async discussions method with browser API stubs."""
    source = (ROOT / "src" / "js" / "discussions.js").read_text()
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


class TestNotificationsState:
    """Test that RB_STATE has notification accessors."""

    def test_state_has_get_notifications(self):
        state_js = (ROOT / "src" / "js" / "state.js").read_text()
        assert "getNotifications()" in state_js
        assert "state/notifications.json" in state_js

    def test_state_has_get_notifications_cached(self):
        state_js = (ROOT / "src" / "js" / "state.js").read_text()
        assert "getNotificationsCached()" in state_js


class TestNotificationsHandler:
    """Test the notifications handler merges GitHub and action events."""

    def test_notifications_read_from_shared_inbox(self):
        router_js = (ROOT / "src" / "js" / "router.js").read_text()
        assert "fetchInboxNotifications" in router_js

    def test_state_resolves_agent_by_immutable_github_id(self):
        state_js = (ROOT / "src" / "js" / "state.js").read_text()
        assert "findAgentByGitHubUserId" in state_js
        assert "github_user_id" in state_js

    def test_discussions_fetch_github_participating_notifications(self):
        discussions_js = (ROOT / "src" / "js" / "discussions.js").read_text()
        assert (
            "/repos/${owner}/${repo}/notifications?"
            "all=false&participating=true"
        ) in discussions_js
        assert "repository.full_name" not in discussions_js

    def test_github_notifications_exclude_read_history(self):
        result = run_async(
            """
globalThis.RB_AUTH = {getGitHubToken: () => 'token'};
globalThis.RB_STATE = {OWNER: 'kody-w', REPO: 'rappterbook'};
globalThis.fetch = async () => ({
  ok: true,
  json: async () => ([
    {
      id: 'read',
      unread: false,
      reason: 'comment',
      updated_at: '2026-08-01T00:00:00Z',
      subject: {type: 'Discussion', title: 'Old', url: '/discussions/1'},
    },
    {
      id: 'unread',
      unread: true,
      reason: 'comment',
      updated_at: '2026-08-02T00:00:00Z',
      subject: {type: 'Discussion', title: 'New', url: '/discussions/2'},
    },
  ]),
});
""",
            "RB_DISCUSSIONS.fetchGitHubNotifications()",
        )
        assert [notification["id"] for notification in result] == [
            "github:unread"
        ]

    def test_comment_notification_routes_to_parent_discussion(self):
        result = run_async(
            """
globalThis.RB_AUTH = {getGitHubToken: () => 'token'};
globalThis.RB_STATE = {OWNER: 'kody-w', REPO: 'rappterbook'};
globalThis.fetch = async () => ({
  ok: true,
  json: async () => ([{
    id: 'reply',
    unread: true,
    reason: 'comment',
    updated_at: '2026-08-02T00:00:00Z',
    subject: {
      type: 'Discussion',
      title: 'A reply arrived',
      url: 'https://api.github.com/repos/kody-w/rappterbook/discussions/4242',
      latest_comment_url: 'https://api.github.com/repos/kody-w/rappterbook/discussions/comments/9999',
    },
  }]),
});
""",
            "RB_DISCUSSIONS.fetchGitHubNotifications()",
        )
        assert result[0]["discussion_number"] == 4242
        assert result[0]["route"] == "#/discussions/4242"

    def test_github_failure_does_not_hide_local_action_notifications(self):
        result = run_async(
            """
globalThis.RB_AUTH = {
  getGitHubToken: () => 'token',
  getUser: async () => ({id: 123, login: 'octocat'}),
};
globalThis.RB_STATE = {
  OWNER: 'kody-w',
  REPO: 'rappterbook',
  getNotificationsCached: async () => ([{
    id: 'local:1',
    agent_id: 'agent-1',
    timestamp: '2026-08-01T00:00:00Z',
  }]),
  findAgentByGitHubUserId: async () => ({id: 'agent-1'}),
};
globalThis.fetch = async () => ({ok: false, status: 403});
""",
            "RB_DISCUSSIONS.fetchInboxNotifications()",
        )
        assert [notification["id"] for notification in result] == ["local:1"]

    def test_stalled_github_fetch_does_not_block_local_notifications(self):
        result = run_async(
            """
globalThis.RB_AUTH = {
  getGitHubToken: () => 'token',
  getUser: async () => ({id: 123, login: 'octocat'}),
};
globalThis.RB_STATE = {
  OWNER: 'kody-w',
  REPO: 'rappterbook',
  getNotificationsCached: async () => ([{
    id: 'local:1',
    agent_id: 'agent-1',
    timestamp: '2026-08-01T00:00:00Z',
  }]),
  findAgentByGitHubUserId: async () => ({id: 'agent-1'}),
};
globalThis.fetch = async (url, options) => new Promise((resolve, reject) => {
  options.signal.addEventListener('abort', () => {
    const error = new Error('aborted');
    error.name = 'AbortError';
    reject(error);
  });
});
""",
            """(async () => {
              RB_DISCUSSIONS.NOTIFICATION_TIMEOUT_MS = 1;
              return RB_DISCUSSIONS.fetchInboxNotifications();
            })()""",
        )
        assert [notification["id"] for notification in result] == ["local:1"]

    def test_stalled_github_response_body_keeps_the_same_deadline(self):
        result = run_async(
            """
globalThis.RB_AUTH = {
  getGitHubToken: () => 'token',
  getUser: async () => ({id: 123, login: 'octocat'}),
};
globalThis.RB_STATE = {
  OWNER: 'kody-w',
  REPO: 'rappterbook',
  getNotificationsCached: async () => ([{
    id: 'local:1',
    agent_id: 'agent-1',
    timestamp: '2026-08-01T00:00:00Z',
  }]),
  findAgentByGitHubUserId: async () => ({id: 'agent-1'}),
};
globalThis.fetch = async (url, options) => ({
  ok: true,
  json: async () => new Promise((resolve, reject) => {
    options.signal.addEventListener('abort', () => {
      const error = new Error('aborted');
      error.name = 'AbortError';
      reject(error);
    });
  }),
});
""",
            """(async () => {
              RB_DISCUSSIONS.NOTIFICATION_TIMEOUT_MS = 1;
              return RB_DISCUSSIONS.fetchInboxNotifications();
            })()""",
        )
        assert [notification["id"] for notification in result] == ["local:1"]

    def test_opening_notifications_marks_github_threads_read(self):
        result = run_async(
            """
globalThis.calls = [];
globalThis.RB_AUTH = {getGitHubToken: () => 'token'};
globalThis.fetch = async (url, options) => {
  calls.push({url, method: options.method});
  return {ok: true, status: 205};
};
""",
            """(async () => {
              await RB_DISCUSSIONS.markGitHubNotificationsRead([
                {source: 'github', thread_id: '123'},
                {source: 'action', id: 'local:1'},
              ]);
              return calls;
            })()""",
        )
        assert result == [{
            "url": "https://api.github.com/notifications/threads/123",
            "method": "PATCH",
        }]

    def test_local_read_time_overrides_stale_remote_unread_flag(self):
        result = run_async(
            "",
            """RB_DISCUSSIONS.isNotificationUnread(
              {unread: true, timestamp: '2026-08-01T00:00:00Z'},
              '2026-08-02T00:00:00Z'
            )""",
        )
        assert result is False

    def test_remote_read_flag_is_never_promoted_to_unread(self):
        result = run_async(
            "",
            """RB_DISCUSSIONS.isNotificationUnread(
              {unread: false, timestamp: '2026-08-03T00:00:00Z'},
              ''
            )""",
        )
        assert result is False

    def test_notification_bell_has_badge(self):
        render_js = (ROOT / "src" / "js" / "render.js").read_text()
        assert "notification-count" in render_js
        assert "fetchInboxNotifications" in render_js


class TestNotificationsCSS:
    """Test notification CSS classes exist."""

    def test_notification_css_classes(self):
        css = (ROOT / "src" / "css" / "components.css").read_text()
        assert ".notification-item" in css
        assert ".notification-item--unread" in css
        assert ".notification-bell" in css
        assert ".notification-count" in css
