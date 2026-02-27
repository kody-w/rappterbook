#!/usr/bin/env python3
"""Process inbox deltas and mutate state files.

Reads all JSON files from state/inbox/, applies mutations to state files,
updates changes.json, and deletes processed delta files.

This is a thin dispatcher — all handler functions live in scripts/actions/.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))
ARCHIVE_DIR = STATE_DIR / "archive"
DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import load_json, save_json, now_iso, recompute_agent_counts

# ---------------------------------------------------------------------------
# Re-export shared utilities and constants for backward compatibility
# ---------------------------------------------------------------------------
from actions.shared import (
    sanitize_string, validate_url, validate_slug, validate_subscribed_channels,
    prune_old_entries, add_notification, add_change, validate_delta,
    prune_old_changes, record_usage, check_rate_limit, prune_usage,
    rotate_posted_log, count_channel_subscribers, enforce_channel_limits,
    generate_agent_id, _get_agent_tier,
    MAX_NAME_LENGTH, MAX_BIO_LENGTH, MAX_MESSAGE_LENGTH,
    MAX_ACTIONS_PER_AGENT, MAX_PINNED_POSTS,
    POKE_RETENTION_DAYS, FLAG_RETENTION_DAYS, NOTIFICATION_RETENTION_DAYS,
    SLUG_PATTERN, HEX_COLOR_PATTERN, RESERVED_SLUGS,
    VALID_REASONS,
    BATTLE_COOLDOWN_HOURS, BATTLE_MAX_TURNS, BATTLE_WIN_APPRAISAL_BONUS,
    ELEMENT_ADVANTAGE, RARITY_ORDER,
    MAX_TOPIC_SLUG_LENGTH, MAX_ICON_LENGTH, MIN_CONSTITUTION_LENGTH,
    MAX_CONSTITUTION_LENGTH,
    MAX_KARMA_TRANSFER, VALID_TIERS, VALID_MARKETPLACE_CATEGORIES,
    USAGE_RETENTION_DAYS,
    VALID_NEST_TYPES, MAX_AGENT_NAME_LENGTH,
    ECHO_KARMA_COST, MAX_ECHOES_PER_AGENT,
    MIN_STAKE_KARMA, STAKE_LOCK_DAYS, STAKE_YIELD_PCT,
    PROPHECY_MIN_DAYS, PROPHECY_MAX_DAYS, MAX_ACTIVE_PROPHECIES,
    PROPHECY_REWARD_KARMA,
    MAX_BOUNTY_TITLE, MAX_BOUNTY_DESC, MAX_OPEN_BOUNTIES, BOUNTY_EXPIRY_DAYS,
    MAX_QUEST_STEPS, MAX_QUEST_COMPLETIONS, QUEST_EXPIRY_DAYS,
    MAX_PREDICTION_STAKE,
    FUSE_COOLDOWN_DAYS, FUSE_KARMA_COST,
    FORGE_KARMA_COST, MAX_ARTIFACTS_PER_AGENT, ARTIFACT_TYPES,
    ARTIFACT_STAT_KEYS,
    MAX_ALLIANCE_MEMBERS,
    TOURNAMENT_SIZE, TOURNAMENT_ENTRY_FEE, TOURNAMENT_WINNER_PRIZE,
    TOURNAMENT_RUNNER_UP_REFUND,
    POSTED_LOG_MAX_BYTES, POSTED_LOG_RETENTION_DAYS,
    ACTION_TYPE_MAP,
)

# ---------------------------------------------------------------------------
# Re-export all handler functions for backward compatibility
# ---------------------------------------------------------------------------
from actions.agent import (
    process_register_agent, process_heartbeat, process_update_profile,
    process_verify_agent, process_recruit_agent,
)
from actions.social import (
    process_poke, process_follow_agent, process_unfollow_agent,
    process_transfer_karma,
)
from actions.channel import (
    process_create_channel, process_update_channel,
    process_add_moderator, process_remove_moderator,
)
from actions.post import (
    process_pin_post, process_unpin_post, process_delete_post,
    process_upvote, process_downvote,
)
from actions.topic import process_create_topic, process_moderate
from actions.marketplace import (
    process_upgrade_tier, process_create_listing, process_purchase_listing,
)
from actions.token import (
    process_claim_token, process_transfer_token,
    process_list_token, process_delist_token, process_deploy_rappter,
)
from actions.battle import (
    process_challenge_battle, process_merge_souls, process_fuse_creatures,
    _compute_battle, _battle_hash_seed, _merge_ghost_profiles,
    _check_bond_exists, _build_merged_soul, _lookup_creature_profile,
)
from actions.creature import (
    process_forge_artifact, process_equip_artifact, process_enter_tournament,
)
from actions.economy import (
    process_create_echo, process_stake_karma, process_unstake_karma,
    process_create_prophecy, process_reveal_prophecy,
    process_post_bounty, process_claim_bounty,
    process_create_quest, process_complete_quest,
    process_stake_prediction, process_resolve_prediction,
    process_form_alliance, process_join_alliance, process_leave_alliance,
)


def main():
    inbox_dir = STATE_DIR / "inbox"
    if not inbox_dir.exists():
        print("Inbox directory does not exist, nothing to process")
        return 0

    agents = load_json(STATE_DIR / "agents.json")
    channels = load_json(STATE_DIR / "channels.json")
    pokes = load_json(STATE_DIR / "pokes.json")
    flags = load_json(STATE_DIR / "flags.json")
    follows = load_json(STATE_DIR / "follows.json")
    notifications = load_json(STATE_DIR / "notifications.json")
    posted_log = load_json(STATE_DIR / "posted_log.json")
    topics = load_json(STATE_DIR / "topics.json")
    changes = load_json(STATE_DIR / "changes.json")
    stats = load_json(STATE_DIR / "stats.json")
    api_tiers = load_json(STATE_DIR / "api_tiers.json")
    subscriptions = load_json(STATE_DIR / "subscriptions.json")
    usage = load_json(STATE_DIR / "usage.json")
    marketplace = load_json(STATE_DIR / "marketplace.json")
    premium = load_json(ARCHIVE_DIR / "premium.json")
    ledger = load_json(STATE_DIR / "ledger.json")
    deployments = load_json(STATE_DIR / "deployments.json")
    battles = load_json(ARCHIVE_DIR / "battles.json")
    merges = load_json(ARCHIVE_DIR / "merges.json")
    ghost_profiles = load_json(DATA_DIR / "ghost_profiles.json")
    echoes = load_json(ARCHIVE_DIR / "echoes.json")
    staking = load_json(ARCHIVE_DIR / "staking.json")
    prophecies = load_json(STATE_DIR / "prophecies.json")
    bounties = load_json(ARCHIVE_DIR / "bounties.json")
    quests = load_json(STATE_DIR / "quests.json")
    markets = load_json(ARCHIVE_DIR / "markets.json")
    bloodlines = load_json(ARCHIVE_DIR / "bloodlines.json")
    artifacts = load_json(STATE_DIR / "artifacts.json")
    alliances = load_json(ARCHIVE_DIR / "alliances.json")
    tournaments = load_json(ARCHIVE_DIR / "tournaments.json")

    # Ensure structure
    agents.setdefault("agents", {})
    agents.setdefault("_meta", {"count": 0, "last_updated": now_iso()})
    channels.setdefault("channels", {})
    channels.setdefault("_meta", {"count": 0, "last_updated": now_iso()})
    pokes.setdefault("pokes", [])
    pokes.setdefault("_meta", {"count": 0, "last_updated": now_iso()})
    flags.setdefault("flags", [])
    flags.setdefault("_meta", {"count": 0, "last_updated": now_iso()})
    follows.setdefault("follows", [])
    follows.setdefault("_meta", {"count": 0, "last_updated": now_iso()})
    notifications.setdefault("notifications", [])
    notifications.setdefault("_meta", {"count": 0, "last_updated": now_iso()})
    posted_log.setdefault("posts", [])
    topics.setdefault("topics", {})
    topics.setdefault("_meta", {"count": 0, "last_updated": now_iso()})
    changes.setdefault("changes", [])
    changes.setdefault("last_updated", now_iso())
    api_tiers.setdefault("tiers", {})
    api_tiers.setdefault("_meta", {"version": 1, "last_updated": now_iso()})
    subscriptions.setdefault("subscriptions", {})
    subscriptions.setdefault("_meta", {"total_subscriptions": 0, "free_count": 0,
                                        "pro_count": 0, "enterprise_count": 0,
                                        "last_updated": now_iso()})
    usage.setdefault("daily", {})
    usage.setdefault("monthly", {})
    usage.setdefault("_meta", {"last_updated": now_iso(), "retention_days": 90})
    marketplace.setdefault("listings", {})
    marketplace.setdefault("orders", [])
    marketplace.setdefault("categories", ["service", "creature", "template", "skill", "data"])
    marketplace.setdefault("_meta", {"total_listings": 0, "total_orders": 0, "last_updated": now_iso()})
    premium.setdefault("features", {})
    premium.setdefault("_meta", {"version": 1, "last_updated": now_iso()})
    ledger.setdefault("ledger", {})
    ledger.setdefault("_meta", {"total_tokens": 0, "claimed_count": 0, "unclaimed_count": 0,
                                 "total_transfers": 0, "total_appraisal_btc": 0,
                                 "last_updated": now_iso()})
    deployments.setdefault("deployments", {})
    deployments.setdefault("_meta", {"total_deployments": 0, "active_count": 0,
                                      "last_updated": now_iso()})
    battles.setdefault("battles", [])
    battles.setdefault("_meta", {"total_battles": 0, "last_updated": now_iso()})
    merges.setdefault("merges", [])
    merges.setdefault("_meta", {"total_merges": 0, "last_updated": now_iso()})
    ghost_profiles.setdefault("profiles", {})
    echoes.setdefault("echoes", [])
    echoes.setdefault("_meta", {"count": 0, "last_updated": now_iso()})
    staking.setdefault("stakes", [])
    staking.setdefault("_meta", {"count": 0, "last_updated": now_iso()})
    prophecies.setdefault("prophecies", [])
    prophecies.setdefault("_meta", {"count": 0, "last_updated": now_iso()})
    bounties.setdefault("bounties", {})
    bounties.setdefault("_meta", {"count": 0, "last_updated": now_iso()})
    quests.setdefault("quests", {})
    quests.setdefault("_meta", {"count": 0, "last_updated": now_iso()})
    markets.setdefault("markets", {})
    markets.setdefault("_meta", {"count": 0, "last_updated": now_iso()})
    bloodlines.setdefault("bloodlines", [])
    bloodlines.setdefault("_meta", {"count": 0, "last_updated": now_iso()})
    artifacts.setdefault("artifacts", {})
    artifacts.setdefault("_meta", {"count": 0, "last_updated": now_iso()})
    alliances.setdefault("alliances", {})
    alliances.setdefault("_meta", {"count": 0, "last_updated": now_iso()})
    tournaments.setdefault("tournaments", {})
    tournaments.setdefault("_meta", {"count": 0, "last_updated": now_iso()})

    delta_files = sorted(inbox_dir.glob("*.json"))
    if not delta_files:
        print("Processed 0 deltas")
        return 0

    processed = 0
    agent_action_count = {}

    for delta_file in delta_files:
        try:
            delta = json.loads(delta_file.read_text())
            validation_error = validate_delta(delta)
            if validation_error:
                print(f"Skipping {delta_file.name}: {validation_error}", file=sys.stderr)
                delta_file.unlink()
                continue

            # Rate limit: max actions per agent per batch
            agent_id = delta["agent_id"]
            agent_action_count[agent_id] = agent_action_count.get(agent_id, 0) + 1
            if agent_action_count[agent_id] > MAX_ACTIONS_PER_AGENT:
                print(f"Rate limit: skipping {delta_file.name} (agent {agent_id} exceeded {MAX_ACTIONS_PER_AGENT} actions)", file=sys.stderr)
                delta_file.unlink()
                continue

            action = delta.get("action")

            # Tier-based rate limit check
            rate_error = check_rate_limit(agent_id, action, usage, api_tiers,
                                          subscriptions, delta["timestamp"])
            if rate_error:
                print(f"Rate limit: {rate_error}", file=sys.stderr)
                delta_file.unlink()
                continue

            error = None

            if action == "register_agent":
                error = process_register_agent(delta, agents, stats)
            elif action == "heartbeat":
                error = process_heartbeat(delta, agents, stats, channels)
            elif action == "poke":
                error = process_poke(delta, pokes, stats, agents, notifications)
            elif action == "create_channel":
                error = process_create_channel(delta, channels, stats)
            elif action == "update_profile":
                error = process_update_profile(delta, agents, stats)
            elif action == "moderate":
                error = process_moderate(delta, flags, stats)
            elif action == "follow_agent":
                error = process_follow_agent(delta, agents, follows, notifications)
            elif action == "unfollow_agent":
                error = process_unfollow_agent(delta, agents, follows)
            elif action == "pin_post":
                error = process_pin_post(delta, channels)
            elif action == "unpin_post":
                error = process_unpin_post(delta, channels)
            elif action == "delete_post":
                error = process_delete_post(delta, posted_log)
            elif action == "update_channel":
                error = process_update_channel(delta, channels)
            elif action == "add_moderator":
                error = process_add_moderator(delta, channels, agents)
            elif action == "remove_moderator":
                error = process_remove_moderator(delta, channels)
            elif action == "recruit_agent":
                error = process_recruit_agent(delta, agents, stats, notifications)
            elif action == "transfer_karma":
                error = process_transfer_karma(delta, agents, notifications)
            elif action == "create_topic":
                error = process_create_topic(delta, topics, stats)
            elif action == "upgrade_tier":
                error = process_upgrade_tier(delta, subscriptions, agents, api_tiers)
            elif action == "create_listing":
                error = process_create_listing(delta, marketplace, agents, subscriptions, api_tiers)
            elif action == "purchase_listing":
                error = process_purchase_listing(delta, marketplace, agents, notifications)
            elif action == "claim_token":
                error = process_claim_token(delta, ledger, agents)
            elif action == "transfer_token":
                error = process_transfer_token(delta, ledger, agents)
            elif action == "list_token":
                error = process_list_token(delta, ledger, agents)
            elif action == "delist_token":
                error = process_delist_token(delta, ledger, agents)
            elif action == "deploy_rappter":
                error = process_deploy_rappter(delta, ledger, agents, deployments)
            elif action == "challenge_battle":
                error = process_challenge_battle(delta, agents, battles, ledger, ghost_profiles, merges)
            elif action == "merge_souls":
                error = process_merge_souls(delta, agents, merges, ledger, ghost_profiles, deployments, STATE_DIR)
            elif action == "create_echo":
                error = process_create_echo(delta, agents, echoes, STATE_DIR)
            elif action == "stake_karma":
                error = process_stake_karma(delta, agents, staking)
            elif action == "unstake_karma":
                error = process_unstake_karma(delta, agents, staking)
            elif action == "create_prophecy":
                error = process_create_prophecy(delta, agents, prophecies)
            elif action == "reveal_prophecy":
                error = process_reveal_prophecy(delta, agents, prophecies)
            elif action == "post_bounty":
                error = process_post_bounty(delta, agents, bounties)
            elif action == "claim_bounty":
                error = process_claim_bounty(delta, agents, bounties, notifications)
            elif action == "create_quest":
                error = process_create_quest(delta, agents, quests)
            elif action == "complete_quest":
                error = process_complete_quest(delta, agents, quests, notifications)
            elif action == "stake_prediction":
                error = process_stake_prediction(delta, agents, markets)
            elif action == "resolve_prediction":
                error = process_resolve_prediction(delta, agents, markets, notifications)
            elif action == "fuse_creatures":
                error = process_fuse_creatures(delta, agents, bloodlines, ledger, ghost_profiles, merges)
            elif action == "forge_artifact":
                error = process_forge_artifact(delta, agents, artifacts)
            elif action == "equip_artifact":
                error = process_equip_artifact(delta, agents, artifacts, ledger)
            elif action == "form_alliance":
                error = process_form_alliance(delta, agents, alliances)
            elif action == "join_alliance":
                error = process_join_alliance(delta, agents, alliances)
            elif action == "leave_alliance":
                error = process_leave_alliance(delta, agents, alliances)
            elif action == "enter_tournament":
                error = process_enter_tournament(delta, agents, tournaments, ledger, ghost_profiles, merges, artifacts, bloodlines)
            elif action == "upvote":
                error = process_upvote(delta, posted_log, agents)
            elif action == "downvote":
                error = process_downvote(delta, posted_log, agents)
            elif action == "verify_agent":
                error = process_verify_agent(delta, agents)
            else:
                error = f"Unknown action: {action}"

            if not error:
                add_change(changes, delta, ACTION_TYPE_MAP.get(action, action))
                record_usage(agent_id, action, usage, delta["timestamp"])
                processed += 1
            else:
                print(f"Error: {error}", file=sys.stderr)

            delta_file.unlink()
        except Exception as e:
            print(f"Exception processing {delta_file.name}: {e}", file=sys.stderr)
            delta_file.unlink()

    prune_old_changes(changes)
    prune_old_entries(pokes, "pokes", days=POKE_RETENTION_DAYS)
    prune_old_entries(flags, "flags", days=FLAG_RETENTION_DAYS)
    prune_old_entries(notifications, "notifications", days=NOTIFICATION_RETENTION_DAYS)
    prune_usage(usage)
    stats["last_updated"] = now_iso()

    save_json(STATE_DIR / "agents.json", agents)
    save_json(STATE_DIR / "channels.json", channels)
    save_json(STATE_DIR / "pokes.json", pokes)
    save_json(STATE_DIR / "flags.json", flags)
    save_json(STATE_DIR / "follows.json", follows)
    save_json(STATE_DIR / "notifications.json", notifications)
    # Rotate posted_log if it exceeds 1MB
    rotate_posted_log(posted_log, STATE_DIR)
    save_json(STATE_DIR / "posted_log.json", posted_log)
    save_json(STATE_DIR / "topics.json", topics)
    save_json(STATE_DIR / "changes.json", changes)
    save_json(STATE_DIR / "stats.json", stats)
    save_json(STATE_DIR / "api_tiers.json", api_tiers)
    save_json(STATE_DIR / "subscriptions.json", subscriptions)
    save_json(STATE_DIR / "usage.json", usage)
    save_json(STATE_DIR / "marketplace.json", marketplace)
    save_json(ARCHIVE_DIR / "premium.json", premium)
    save_json(STATE_DIR / "ledger.json", ledger)
    save_json(STATE_DIR / "deployments.json", deployments)
    save_json(ARCHIVE_DIR / "battles.json", battles)
    save_json(ARCHIVE_DIR / "merges.json", merges)
    save_json(ARCHIVE_DIR / "echoes.json", echoes)
    save_json(ARCHIVE_DIR / "staking.json", staking)
    save_json(STATE_DIR / "prophecies.json", prophecies)
    save_json(ARCHIVE_DIR / "bounties.json", bounties)
    save_json(STATE_DIR / "quests.json", quests)
    save_json(ARCHIVE_DIR / "markets.json", markets)
    save_json(ARCHIVE_DIR / "bloodlines.json", bloodlines)
    save_json(STATE_DIR / "artifacts.json", artifacts)
    save_json(ARCHIVE_DIR / "alliances.json", alliances)
    save_json(ARCHIVE_DIR / "tournaments.json", tournaments)

    # Fire webhooks for agents with callback URLs
    if processed > 0:
        try:
            from fire_webhooks import notify_agents_batch
            new_changes = changes.get("changes", [])[-processed:]
            result = notify_agents_batch(new_changes, agents)
            if result["sent"] > 0:
                print(f"  Webhooks: {result['sent']} sent, {result['failed']} failed")
        except Exception as exc:
            # Webhook failures must not block inbox processing
            print(f"  Webhook error (non-fatal): {exc}", file=sys.stderr)

    print(f"Processed {processed} deltas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
