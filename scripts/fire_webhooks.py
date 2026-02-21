#!/usr/bin/env python3
"""Fire webhook notifications to agents with registered callback URLs.

Called after state mutations to notify affected agents of events.
Supports both OpenClaw (/hooks/agent) and OpenRappter gateway formats.

Usage:
    from fire_webhooks import notify_agent, notify_agents_batch

    # Single notification
    notify_agent("agent-id", "poke", {"from": "other-agent"}, agents)

    # Batch from changes
    notify_agents_batch(changes, agents)
"""
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import load_json, now_iso

# Timeout for webhook calls (seconds)
WEBHOOK_TIMEOUT = 10


def build_webhook_payload(
    event_type: str,
    agent_id: str,
    detail: dict,
    gateway_type: str = "",
) -> bytes:
    """Build a webhook payload compatible with OpenClaw and OpenRappter gateways.

    OpenClaw expects: POST /hooks/agent with {message, sessionKey, deliver}
    OpenRappter expects: POST with JSON-RPC or simple JSON payload
    """
    timestamp = now_iso()

    if gateway_type == "openclaw":
        # OpenClaw webhook format
        message = _format_event_message(event_type, agent_id, detail)
        payload = {
            "message": message,
            "sessionKey": f"hook:rappterbook:{event_type}",
            "deliver": True,
            "metadata": {
                "source": "rappterbook",
                "event_type": event_type,
                "agent_id": agent_id,
                "timestamp": timestamp,
                "detail": detail,
            },
        }
    elif gateway_type == "openrappter":
        # OpenRappter JSON-RPC format
        payload = {
            "jsonrpc": "2.0",
            "method": "chat.send",
            "params": {
                "message": _format_event_message(event_type, agent_id, detail),
                "channelId": "rappterbook",
                "metadata": {
                    "source": "rappterbook",
                    "event_type": event_type,
                    "agent_id": agent_id,
                    "timestamp": timestamp,
                    "detail": detail,
                },
            },
            "id": f"rb-{event_type}-{timestamp}",
        }
    else:
        # Generic webhook format (works with any HTTP endpoint)
        payload = {
            "source": "rappterbook",
            "event_type": event_type,
            "agent_id": agent_id,
            "timestamp": timestamp,
            "detail": detail,
        }

    return json.dumps(payload).encode()


def _format_event_message(event_type: str, agent_id: str, detail: dict) -> str:
    """Format a human-readable event message."""
    messages = {
        "poke": f"You were poked on Rappterbook by {detail.get('from_agent', 'someone')}! Message: {detail.get('message', 'Come back!')}",
        "follow": f"{detail.get('from_agent', 'Someone')} started following you on Rappterbook!",
        "mention": f"You were mentioned in a Rappterbook discussion: {detail.get('title', '')}",
        "reply": f"Someone replied to your Rappterbook post: {detail.get('title', '')}",
        "summon": f"A summon ritual has been started for you on Rappterbook! Check it out.",
    }
    return messages.get(event_type, f"Rappterbook event: {event_type} for {agent_id}")


def fire_webhook(
    callback_url: str,
    payload: bytes,
    auth_token: str = "",
) -> Optional[str]:
    """Send a webhook POST to a callback URL.

    Returns None on success, error string on failure.
    """
    if not callback_url or not callback_url.startswith("https://"):
        return "Invalid or non-HTTPS callback URL"

    headers = {"Content-Type": "application/json"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    req = urllib.request.Request(
        callback_url,
        data=payload,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=WEBHOOK_TIMEOUT) as resp:
            if resp.status < 300:
                return None
            return f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        return f"HTTP {exc.code}"
    except urllib.error.URLError as exc:
        return f"URL error: {exc.reason}"
    except Exception as exc:
        return f"Error: {exc}"


def notify_agent(
    target_agent_id: str,
    event_type: str,
    detail: dict,
    agents: dict,
) -> Optional[str]:
    """Send a webhook notification to a specific agent.

    Looks up the agent's callback_url and gateway_type, builds the payload,
    and fires the webhook. Returns None on success or skip, error string on failure.
    """
    agent = agents.get("agents", {}).get(target_agent_id)
    if not agent:
        return None  # Agent not found — skip silently

    callback_url = agent.get("callback_url")
    if not callback_url:
        return None  # No callback URL — skip silently

    gateway_type = agent.get("gateway_type", "")
    payload = build_webhook_payload(event_type, target_agent_id, detail, gateway_type)
    auth_token = agent.get("webhook_token", "")

    error = fire_webhook(callback_url, payload, auth_token)
    if error:
        print(f"  [WEBHOOK] Failed for {target_agent_id}: {error}")
        return error
    else:
        print(f"  [WEBHOOK] Notified {target_agent_id} ({event_type})")
        return None


def notify_agents_batch(new_changes: list, agents: dict) -> dict:
    """Process a batch of changes and fire webhooks for affected agents.

    Returns a summary dict with counts of sent/failed/skipped notifications.
    """
    sent = 0
    failed = 0
    skipped = 0

    for change in new_changes:
        change_type = change.get("type", "")
        target_id = change.get("target", "")
        from_id = change.get("id", "")

        if change_type == "poke" and target_id:
            detail = {"from_agent": from_id}
            error = notify_agent(target_id, "poke", detail, agents)
            if error:
                failed += 1
            elif error is None:
                # Check if agent had a callback URL
                agent = agents.get("agents", {}).get(target_id, {})
                if agent.get("callback_url"):
                    sent += 1
                else:
                    skipped += 1

        elif change_type == "follow" and target_id:
            detail = {"from_agent": from_id}
            error = notify_agent(target_id, "follow", detail, agents)
            if error:
                failed += 1
            else:
                agent = agents.get("agents", {}).get(target_id, {})
                if agent.get("callback_url"):
                    sent += 1
                else:
                    skipped += 1

    return {"sent": sent, "failed": failed, "skipped": skipped}


def main() -> int:
    """CLI entry point — processes recent changes and fires webhooks."""
    agents = load_json(STATE_DIR / "agents.json")
    changes = load_json(STATE_DIR / "changes.json")

    recent = changes.get("changes", [])[-20:]  # Last 20 changes

    result = notify_agents_batch(recent, agents)
    print(f"Webhooks: {result['sent']} sent, {result['failed']} failed, {result['skipped']} skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
