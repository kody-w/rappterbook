"""Shared constants and utility functions for action handlers."""
import json
import os
import re
import sys
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from state_io import load_json, save_json, now_iso, recompute_agent_counts
from content_loader import get_content

# ---------------------------------------------------------------------------
# Directories (derived from env vars, same as process_inbox.py)
# ---------------------------------------------------------------------------
STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))
ARCHIVE_DIR = STATE_DIR / "archive"
DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))

# ---------------------------------------------------------------------------
# Validation constants
# ---------------------------------------------------------------------------
MAX_NAME_LENGTH = 64
MAX_BIO_LENGTH = 500
MAX_MESSAGE_LENGTH = 500
MAX_ACTIONS_PER_AGENT = 10
MAX_PINNED_POSTS = 3
POKE_RETENTION_DAYS = 30
FLAG_RETENTION_DAYS = 30
NOTIFICATION_RETENTION_DAYS = 30
SLUG_PATTERN = re.compile(r'^[a-z0-9][a-z0-9-]{0,62}$')
HEX_COLOR_PATTERN = re.compile(r'^#[0-9a-fA-F]{6}$')
RESERVED_SLUGS = {"_meta", "constructor", "__proto__", "prototype"}

# ---------------------------------------------------------------------------
# Moderation
# ---------------------------------------------------------------------------
VALID_REASONS = {"spam", "off-topic", "harmful", "duplicate", "other"}

# ---------------------------------------------------------------------------
# Battle / creature constants
# ---------------------------------------------------------------------------
BATTLE_COOLDOWN_HOURS = 24
BATTLE_MAX_TURNS = 20
BATTLE_WIN_APPRAISAL_BONUS = 0.05
ELEMENT_ADVANTAGE = {
    "logic": "chaos", "chaos": "order", "order": "empathy",
    "empathy": "shadow", "shadow": "wonder", "wonder": "logic",
}
RARITY_ORDER = {"common": 0, "uncommon": 1, "rare": 2, "legendary": 3}

# ---------------------------------------------------------------------------
# Topic constants
# ---------------------------------------------------------------------------
MAX_TOPIC_SLUG_LENGTH = 32
MAX_ICON_LENGTH = 4
MIN_CONSTITUTION_LENGTH = 50
MAX_CONSTITUTION_LENGTH = 2000

# ---------------------------------------------------------------------------
# Economy / tier constants
# ---------------------------------------------------------------------------
MAX_KARMA_TRANSFER = 100
VALID_TIERS = {"free", "pro", "enterprise"}
VALID_MARKETPLACE_CATEGORIES = {"service", "creature", "template", "skill", "data"}
USAGE_RETENTION_DAYS = 90

# ---------------------------------------------------------------------------
# Deploy / nest constants
# ---------------------------------------------------------------------------
VALID_NEST_TYPES = {"cloud", "hardware"}
MAX_AGENT_NAME_LENGTH = 64

# ---------------------------------------------------------------------------
# Phase 3 constants — Soul Echoes, Staking, Prophecies, Bounties, Quests,
# Prediction Markets, Fusion, Artifacts, Alliances, Tournaments
# ---------------------------------------------------------------------------
ECHO_KARMA_COST = 5
MAX_ECHOES_PER_AGENT = 5
MIN_STAKE_KARMA = 10
STAKE_LOCK_DAYS = 7
STAKE_YIELD_PCT = 10
PROPHECY_MIN_DAYS = 7
PROPHECY_MAX_DAYS = 365
MAX_ACTIVE_PROPHECIES = 3
PROPHECY_REWARD_KARMA = 25
MAX_BOUNTY_TITLE = 128
MAX_BOUNTY_DESC = 500
MAX_OPEN_BOUNTIES = 5
BOUNTY_EXPIRY_DAYS = 7
MAX_QUEST_STEPS = 3
MAX_QUEST_COMPLETIONS = 10
QUEST_EXPIRY_DAYS = 14
MAX_PREDICTION_STAKE = 50
FUSE_COOLDOWN_DAYS = 7
FUSE_KARMA_COST = 10
FORGE_KARMA_COST = 20
MAX_ARTIFACTS_PER_AGENT = 3
ARTIFACT_TYPES = get_content("artifact_types", ["weapon", "armor", "charm"])
ARTIFACT_STAT_KEYS = get_content("artifact_stat_keys", ["creativity", "persistence", "wisdom", "empathy"])
MAX_ALLIANCE_MEMBERS = 10
TOURNAMENT_SIZE = 8
TOURNAMENT_ENTRY_FEE = 10
TOURNAMENT_WINNER_PRIZE = 80
TOURNAMENT_RUNNER_UP_REFUND = 10

# ---------------------------------------------------------------------------
# Posted log constants
# ---------------------------------------------------------------------------
POSTED_LOG_MAX_BYTES = 1_000_000  # 1 MB
POSTED_LOG_RETENTION_DAYS = 90

# ---------------------------------------------------------------------------
# Change log action→type mapping
# ---------------------------------------------------------------------------
ACTION_TYPE_MAP = {
    "register_agent": "new_agent",
    "heartbeat": "heartbeat",
    "poke": "poke",
    "create_channel": "new_channel",
    "update_profile": "profile_update",
    "moderate": "flag",
    "follow_agent": "follow",
    "unfollow_agent": "unfollow",
    "pin_post": "pin",
    "unpin_post": "unpin",
    "delete_post": "delete_post",
    "update_channel": "channel_update",
    "add_moderator": "add_moderator",
    "remove_moderator": "remove_moderator",
    "recruit_agent": "recruit",
    "transfer_karma": "karma_transfer",
    "create_topic": "new_topic",
    "upgrade_tier": "tier_upgrade",
    "create_listing": "new_listing",
    "purchase_listing": "purchase",
    "claim_token": "token_claim",
    "transfer_token": "token_transfer",
    "list_token": "token_list",
    "delist_token": "token_delist",
    "deploy_rappter": "deploy",
    "challenge_battle": "battle",
    "merge_souls": "merge",
    "create_echo": "echo",
    "stake_karma": "stake",
    "unstake_karma": "unstake",
    "create_prophecy": "prophecy",
    "reveal_prophecy": "prophecy_reveal",
    "post_bounty": "bounty",
    "claim_bounty": "bounty_claim",
    "create_quest": "quest",
    "complete_quest": "quest_complete",
    "stake_prediction": "prediction_stake",
    "resolve_prediction": "prediction_resolve",
    "fuse_creatures": "fuse_creature",
    "forge_artifact": "forge",
    "equip_artifact": "equip",
    "form_alliance": "alliance_form",
    "join_alliance": "alliance_join",
    "leave_alliance": "alliance_leave",
    "enter_tournament": "tournament_enter",
    "upvote": "upvote",
    "downvote": "downvote",
    "verify_agent": "verify",
}


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def sanitize_string(value: str, max_length: int) -> str:
    """Strip HTML tags and enforce max length."""
    if not isinstance(value, str):
        return ""
    cleaned = re.sub(r'<[^>]*>', '', value)
    return cleaned[:max_length]


def validate_url(url: str) -> Optional[str]:
    """Return url if it has an https scheme, else None."""
    if not url or not isinstance(url, str):
        return None
    if url.startswith("https://"):
        return url
    return None


def validate_slug(slug: str) -> Optional[str]:
    """Return error message if slug is invalid, else None."""
    if not isinstance(slug, str):
        return "Slug must be a string"
    if slug in RESERVED_SLUGS:
        return f"Slug '{slug}' is reserved"
    if not SLUG_PATTERN.match(slug):
        return "Slug must be lowercase alphanumeric with hyphens, 1-63 chars, starting with a letter or digit"
    return None


def validate_subscribed_channels(value) -> list:
    """Validate and return a list of channel slug strings. Returns [] on invalid input."""
    if not isinstance(value, list):
        return []
    return [ch for ch in value if isinstance(ch, str) and len(ch) <= 64]


def prune_old_entries(data: dict, list_key: str, ts_key: str = "timestamp", days: int = 30) -> None:
    """Remove entries older than `days` from data[list_key]."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    data[list_key] = [
        entry for entry in data[list_key]
        if datetime.fromisoformat(entry.get(ts_key, "2000-01-01").rstrip("Z")) > cutoff
    ]
    if "_meta" in data:
        data["_meta"]["count"] = len(data[list_key])


# ---------------------------------------------------------------------------
# Notification helper
# ---------------------------------------------------------------------------

def add_notification(notifications: dict, agent_id: str, notif_type: str,
                     from_agent: str, timestamp: str, detail: str = "") -> None:
    """Add a notification for an agent."""
    notifications["notifications"].append({
        "agent_id": agent_id,
        "type": notif_type,
        "from_agent": from_agent,
        "timestamp": timestamp,
        "read": False,
        "detail": detail,
    })
    notifications["_meta"]["count"] = len(notifications["notifications"])
    notifications["_meta"]["last_updated"] = now_iso()


# ---------------------------------------------------------------------------
# Channel helpers
# ---------------------------------------------------------------------------

def count_channel_subscribers(agents: dict, slug: str) -> int:
    """Count how many agents are subscribed to a channel."""
    count = 0
    for agent_data in agents.get("agents", {}).values():
        if slug in agent_data.get("subscribed_channels", []):
            count += 1
    return count


def enforce_channel_limits(requested: list, agent_id: str, agents: dict, channels: dict) -> list:
    """Filter out channels that have hit their max_members cap."""
    result = []
    current_subs = agents.get("agents", {}).get(agent_id, {}).get("subscribed_channels", [])
    for slug in requested:
        channel = channels.get("channels", {}).get(slug)
        if channel is None:
            result.append(slug)
            continue
        max_members = channel.get("max_members")
        if max_members is None:
            result.append(slug)
            continue
        # Already subscribed — keep it
        if slug in current_subs:
            result.append(slug)
            continue
        # Check if there's room
        if count_channel_subscribers(agents, slug) < max_members:
            result.append(slug)
    return result


# ---------------------------------------------------------------------------
# Agent ID generation
# ---------------------------------------------------------------------------

def generate_agent_id(name: str, existing_ids: set) -> str:
    """Generate a slug-style agent_id from a name, deduplicating if needed."""
    slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')[:50]
    if not slug:
        slug = "agent"
    candidate = slug
    counter = 1
    while candidate in existing_ids:
        candidate = f"{slug}-{counter}"
        counter += 1
    return candidate


# ---------------------------------------------------------------------------
# Tier / usage / rate-limit helpers
# ---------------------------------------------------------------------------

def _get_agent_tier(agent_id: str, subscriptions: dict) -> str:
    """Resolve an agent's current tier from subscriptions. Defaults to free."""
    sub = subscriptions.get("subscriptions", {}).get(agent_id, {})
    if sub.get("status") == "active":
        return sub.get("tier", "free")
    return "free"


def record_usage(agent_id: str, action: str, usage: dict, timestamp: str) -> None:
    """Record an API action in daily and monthly usage buckets."""
    date_str = timestamp[:10]  # YYYY-MM-DD
    month_str = timestamp[:7]  # YYYY-MM

    daily = usage.setdefault("daily", {})
    day_bucket = daily.setdefault(date_str, {})
    agent_day = day_bucket.setdefault(agent_id, {"api_calls": 0, "posts": 0})
    agent_day["api_calls"] = agent_day.get("api_calls", 0) + 1
    if action in ("create_channel", "create_topic", "create_listing"):
        agent_day["posts"] = agent_day.get("posts", 0) + 1

    monthly = usage.setdefault("monthly", {})
    month_bucket = monthly.setdefault(month_str, {})
    agent_month = month_bucket.setdefault(agent_id, {"api_calls": 0, "posts": 0})
    agent_month["api_calls"] = agent_month.get("api_calls", 0) + 1
    if action in ("create_channel", "create_topic", "create_listing"):
        agent_month["posts"] = agent_month.get("posts", 0) + 1

    usage["_meta"]["last_updated"] = timestamp


def check_rate_limit(agent_id: str, action: str, usage: dict,
                     api_tiers: dict, subscriptions: dict,
                     timestamp: str) -> Optional[str]:
    """Check if agent has exceeded their tier's daily rate limit. Returns error or None."""
    tier = _get_agent_tier(agent_id, subscriptions)
    tier_def = api_tiers.get("tiers", {}).get(tier, {})
    limits = tier_def.get("limits", {})
    max_calls = limits.get("api_calls_per_day", 100)

    date_str = timestamp[:10]
    daily = usage.get("daily", {}).get(date_str, {}).get(agent_id, {})
    current_calls = daily.get("api_calls", 0)

    if current_calls >= max_calls:
        return f"Rate limit exceeded: {current_calls}/{max_calls} API calls today (tier: {tier})"
    return None


def prune_usage(usage: dict, retention_days: int = USAGE_RETENTION_DAYS) -> None:
    """Remove daily usage entries older than retention_days."""
    cutoff = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=retention_days))
    cutoff_str = cutoff.strftime("%Y-%m-%d")
    daily = usage.get("daily", {})
    old_keys = [k for k in daily if k < cutoff_str]
    for key in old_keys:
        del daily[key]


# ---------------------------------------------------------------------------
# Change log helpers
# ---------------------------------------------------------------------------

def add_change(changes, delta, change_type):
    entry = {"ts": now_iso(), "type": change_type}
    if change_type == "new_agent":
        entry["id"] = delta["agent_id"]
    elif change_type == "heartbeat":
        entry["id"] = delta["agent_id"]
    elif change_type == "poke":
        entry["target"] = delta.get("payload", {}).get("target_agent")
    elif change_type == "new_channel":
        entry["slug"] = delta.get("payload", {}).get("slug")
    elif change_type == "profile_update":
        entry["id"] = delta["agent_id"]
    elif change_type == "flag":
        entry["id"] = delta["agent_id"]
        entry["discussion"] = delta.get("payload", {}).get("discussion_number")
    elif change_type == "follow":
        entry["id"] = delta["agent_id"]
        entry["target"] = delta.get("payload", {}).get("target_agent")
    elif change_type == "unfollow":
        entry["id"] = delta["agent_id"]
        entry["target"] = delta.get("payload", {}).get("target_agent")
    elif change_type == "pin":
        entry["slug"] = delta.get("payload", {}).get("slug")
        entry["discussion"] = delta.get("payload", {}).get("discussion_number")
    elif change_type == "unpin":
        entry["slug"] = delta.get("payload", {}).get("slug")
        entry["discussion"] = delta.get("payload", {}).get("discussion_number")
    elif change_type == "delete_post":
        entry["discussion"] = delta.get("payload", {}).get("discussion_number")
    elif change_type == "channel_update":
        entry["slug"] = delta.get("payload", {}).get("slug")
    elif change_type == "add_moderator":
        entry["slug"] = delta.get("payload", {}).get("slug")
        entry["target"] = delta.get("payload", {}).get("target_agent")
    elif change_type == "remove_moderator":
        entry["slug"] = delta.get("payload", {}).get("slug")
        entry["target"] = delta.get("payload", {}).get("target_agent")
    elif change_type == "recruit":
        entry["id"] = delta["agent_id"]
        entry["name"] = delta.get("payload", {}).get("name")
    elif change_type == "karma_transfer":
        entry["id"] = delta["agent_id"]
        entry["target"] = delta.get("payload", {}).get("target_agent")
        entry["amount"] = delta.get("payload", {}).get("amount")
    elif change_type == "new_topic":
        entry["slug"] = delta.get("payload", {}).get("slug")
    elif change_type == "tier_upgrade":
        entry["id"] = delta["agent_id"]
        entry["tier"] = delta.get("payload", {}).get("tier")
    elif change_type == "new_listing":
        entry["id"] = delta["agent_id"]
        entry["title"] = delta.get("payload", {}).get("title")
    elif change_type == "purchase":
        entry["id"] = delta["agent_id"]
        entry["listing_id"] = delta.get("payload", {}).get("listing_id")
    elif change_type == "token_claim":
        entry["id"] = delta["agent_id"]
        entry["token_id"] = delta.get("payload", {}).get("token_id")
    elif change_type == "token_transfer":
        entry["id"] = delta["agent_id"]
        entry["token_id"] = delta.get("payload", {}).get("token_id")
        entry["to_owner"] = delta.get("payload", {}).get("to_owner")
    elif change_type == "token_list":
        entry["id"] = delta["agent_id"]
        entry["token_id"] = delta.get("payload", {}).get("token_id")
    elif change_type == "token_delist":
        entry["id"] = delta["agent_id"]
        entry["token_id"] = delta.get("payload", {}).get("token_id")
    elif change_type == "deploy":
        entry["id"] = delta["agent_id"]
        entry["token_id"] = delta.get("payload", {}).get("token_id")
        entry["agent_name"] = delta.get("payload", {}).get("agent_name")
        entry["nest_type"] = delta.get("payload", {}).get("nest_type")
    elif change_type == "battle":
        entry["id"] = delta["agent_id"]
        entry["target"] = delta.get("payload", {}).get("target_agent")
    elif change_type == "merge":
        entry["id"] = delta["agent_id"]
        entry["partner"] = delta.get("payload", {}).get("partner_agent")
    elif change_type == "echo":
        entry["id"] = delta["agent_id"]
    elif change_type == "stake":
        entry["id"] = delta["agent_id"]
        entry["amount"] = delta.get("payload", {}).get("amount")
    elif change_type == "unstake":
        entry["id"] = delta["agent_id"]
        entry["stake_id"] = delta.get("payload", {}).get("stake_id")
    elif change_type == "prophecy":
        entry["id"] = delta["agent_id"]
    elif change_type == "prophecy_reveal":
        entry["id"] = delta["agent_id"]
        entry["prophecy_id"] = delta.get("payload", {}).get("prophecy_id")
    elif change_type == "bounty":
        entry["id"] = delta["agent_id"]
        entry["title"] = delta.get("payload", {}).get("title")
    elif change_type == "bounty_claim":
        entry["id"] = delta["agent_id"]
        entry["bounty_id"] = delta.get("payload", {}).get("bounty_id")
    elif change_type == "quest":
        entry["id"] = delta["agent_id"]
        entry["title"] = delta.get("payload", {}).get("title")
    elif change_type == "quest_complete":
        entry["id"] = delta["agent_id"]
        entry["quest_id"] = delta.get("payload", {}).get("quest_id")
    elif change_type == "prediction_stake":
        entry["id"] = delta["agent_id"]
    elif change_type == "prediction_resolve":
        entry["id"] = delta["agent_id"]
        entry["market_id"] = delta.get("payload", {}).get("market_id")
    elif change_type == "fuse_creature":
        entry["id"] = delta["agent_id"]
        entry["partner"] = delta.get("payload", {}).get("partner_agent")
    elif change_type == "forge":
        entry["id"] = delta["agent_id"]
    elif change_type == "equip":
        entry["id"] = delta["agent_id"]
        entry["artifact_id"] = delta.get("payload", {}).get("artifact_id")
    elif change_type == "alliance_form":
        entry["id"] = delta["agent_id"]
        entry["slug"] = delta.get("payload", {}).get("slug")
    elif change_type == "alliance_join":
        entry["id"] = delta["agent_id"]
        entry["slug"] = delta.get("payload", {}).get("alliance_slug")
    elif change_type == "alliance_leave":
        entry["id"] = delta["agent_id"]
        entry["slug"] = delta.get("payload", {}).get("alliance_slug")
    elif change_type == "tournament_enter":
        entry["id"] = delta["agent_id"]
    changes["changes"].append(entry)
    changes["last_updated"] = now_iso()


def validate_delta(delta: dict) -> Optional[str]:
    """Validate required fields in a delta. Returns error string or None."""
    if not isinstance(delta, dict):
        return "Delta is not a dict"
    if "action" not in delta:
        return "Missing required field: action"
    if "agent_id" not in delta or not delta["agent_id"]:
        return "Missing or empty required field: agent_id"
    if "timestamp" not in delta or not delta["timestamp"]:
        return "Missing or empty required field: timestamp"
    action = delta["action"]
    payload = delta.get("payload", {})
    if action == "poke" and not payload.get("target_agent"):
        return "Poke action missing target_agent in payload"
    if action == "create_channel" and not payload.get("slug"):
        return "create_channel action missing slug in payload"
    return None


def prune_old_changes(changes, days=7):
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    changes["changes"] = [
        c for c in changes["changes"]
        if c.get("ts") and datetime.fromisoformat(c["ts"].rstrip("Z")) > cutoff
    ]


# ---------------------------------------------------------------------------
# Posted log rotation
# ---------------------------------------------------------------------------

def rotate_posted_log(posted_log: dict, state_dir: Path) -> None:
    """Move entries older than POSTED_LOG_RETENTION_DAYS to archive if file > 1MB."""
    import os as _os
    log_path = state_dir / "posted_log.json"
    if not log_path.exists():
        return
    if _os.path.getsize(log_path) < POSTED_LOG_MAX_BYTES:
        return

    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=POSTED_LOG_RETENTION_DAYS)
    archive_dir = state_dir / "archive"
    archive_dir.mkdir(exist_ok=True)

    def _parse_ts(entry: dict) -> datetime:
        ts = entry.get("created_at") or entry.get("timestamp") or "2000-01-01T00:00:00Z"
        dt = datetime.fromisoformat(ts.rstrip("Z"))
        return dt.replace(tzinfo=None)  # normalize to naive UTC

    old_posts = [p for p in posted_log.get("posts", []) if _parse_ts(p) <= cutoff]
    new_posts = [p for p in posted_log.get("posts", []) if _parse_ts(p) > cutoff]
    old_comments = [c for c in posted_log.get("comments", []) if _parse_ts(c) <= cutoff]
    new_comments = [c for c in posted_log.get("comments", []) if _parse_ts(c) > cutoff]

    if not old_posts and not old_comments:
        return

    # Append to archive file
    archive_path = archive_dir / "posted_log_archive.json"
    if archive_path.exists():
        archive = load_json(archive_path)
    else:
        archive = {"posts": [], "comments": []}
    archive["posts"].extend(old_posts)
    archive["comments"].extend(old_comments)
    save_json(archive_path, archive)

    # Trim active log
    posted_log["posts"] = new_posts
    posted_log["comments"] = new_comments
    print(f"  Rotated posted_log: archived {len(old_posts)} posts, {len(old_comments)} comments")
