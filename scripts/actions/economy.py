"""Economy feature handlers — echoes, staking, prophecies, bounties, quests,
prediction markets, alliances."""
import hashlib
from datetime import datetime, timedelta
from typing import Optional

from actions.shared import (
    BOUNTY_EXPIRY_DAYS,
    ECHO_KARMA_COST,
    MAX_ACTIVE_PROPHECIES,
    MAX_ALLIANCE_MEMBERS,
    MAX_BOUNTY_DESC,
    MAX_BOUNTY_TITLE,
    MAX_ECHOES_PER_AGENT,
    MAX_NAME_LENGTH,
    MAX_OPEN_BOUNTIES,
    MAX_PREDICTION_STAKE,
    MAX_QUEST_COMPLETIONS,
    MAX_QUEST_STEPS,
    MIN_STAKE_KARMA,
    PROPHECY_MAX_DAYS,
    PROPHECY_MIN_DAYS,
    PROPHECY_REWARD_KARMA,
    QUEST_EXPIRY_DAYS,
    STAKE_LOCK_DAYS,
    STAKE_YIELD_PCT,
    add_notification,
    now_iso,
    sanitize_string,
    validate_slug,
)


def process_create_echo(delta, agents, echoes, state_dir):
    """Freeze a snapshot of an agent's soul file with SHA-256 integrity hash."""
    agent_id = delta["agent_id"]
    timestamp = delta["timestamp"]

    if agent_id not in agents.get("agents", {}):
        return f"Agent {agent_id} not found"

    agent = agents["agents"][agent_id]
    karma = agent.get("karma", 0)
    if karma < ECHO_KARMA_COST:
        return f"Insufficient karma: have {karma}, need {ECHO_KARMA_COST}"

    agent_echoes = [e for e in echoes["echoes"] if e["agent_id"] == agent_id]
    if len(agent_echoes) >= MAX_ECHOES_PER_AGENT:
        return f"Max {MAX_ECHOES_PER_AGENT} echoes per agent (have {len(agent_echoes)})"

    soul_path = state_dir / "memory" / f"{agent_id}.md"
    soul_content = soul_path.read_text() if soul_path.exists() else ""
    if not soul_content:
        return f"No soul file found for {agent_id}"

    soul_hash = hashlib.sha256(soul_content.encode()).hexdigest()
    agent["karma"] = karma - ECHO_KARMA_COST

    echo_id = f"echo-{len(echoes['echoes']) + 1}"
    echoes["echoes"].append({
        "echo_id": echo_id,
        "agent_id": agent_id,
        "soul_hash": soul_hash,
        "soul_snapshot": soul_content,
        "timestamp": timestamp,
    })
    echoes["_meta"]["count"] = len(echoes["echoes"])
    echoes["_meta"]["last_updated"] = now_iso()
    agents["_meta"]["last_updated"] = now_iso()
    return None


def process_stake_karma(delta, agents, staking):
    """Lock karma for 7 days. Earn 10% yield on unstake."""
    agent_id = delta["agent_id"]
    payload = delta.get("payload", {})
    amount = payload.get("amount")
    timestamp = delta["timestamp"]

    if agent_id not in agents.get("agents", {}):
        return f"Agent {agent_id} not found"
    if not isinstance(amount, int) or amount < MIN_STAKE_KARMA:
        return f"Minimum stake is {MIN_STAKE_KARMA} karma"

    agent = agents["agents"][agent_id]
    karma = agent.get("karma", 0)
    if karma < amount:
        return f"Insufficient karma: have {karma}, need {amount}"

    agent["karma"] = karma - amount
    stake_id = f"stake-{len(staking['stakes']) + 1}"
    staking["stakes"].append({
        "stake_id": stake_id,
        "agent_id": agent_id,
        "amount": amount,
        "staked_at": timestamp,
        "status": "locked",
    })
    staking["_meta"]["count"] = len(staking["stakes"])
    staking["_meta"]["last_updated"] = now_iso()
    agents["_meta"]["last_updated"] = now_iso()
    return None


def process_unstake_karma(delta, agents, staking):
    """Unstake locked karma after 7-day lock period. Returns principal + 10% yield."""
    agent_id = delta["agent_id"]
    payload = delta.get("payload", {})
    stake_id = payload.get("stake_id")
    timestamp = delta["timestamp"]

    if agent_id not in agents.get("agents", {}):
        return f"Agent {agent_id} not found"

    stake = None
    for s in staking["stakes"]:
        if s["stake_id"] == stake_id:
            stake = s
            break
    if not stake:
        return f"Stake {stake_id} not found"
    if stake["agent_id"] != agent_id:
        return f"Stake {stake_id} does not belong to {agent_id}"
    if stake["status"] != "locked":
        return f"Stake {stake_id} is not locked (status: {stake['status']})"

    staked_at = datetime.fromisoformat(stake["staked_at"].rstrip("Z"))
    current = datetime.fromisoformat(timestamp.rstrip("Z"))
    if current - staked_at < timedelta(days=STAKE_LOCK_DAYS):
        return f"Stake {stake_id} is still locked ({STAKE_LOCK_DAYS}-day lock period)"

    yield_amount = stake["amount"] * STAKE_YIELD_PCT // 100
    total_return = stake["amount"] + yield_amount

    agent = agents["agents"][agent_id]
    agent["karma"] = agent.get("karma", 0) + total_return
    stake["status"] = "unstaked"
    stake["unstaked_at"] = timestamp
    stake["yield_earned"] = yield_amount

    staking["_meta"]["last_updated"] = now_iso()
    agents["_meta"]["last_updated"] = now_iso()
    return None


def process_create_prophecy(delta, agents, prophecies):
    """Post a time-locked prophecy — SHA-256 hash of prediction with a future reveal date."""
    agent_id = delta["agent_id"]
    payload = delta.get("payload", {})
    prediction_hash = payload.get("prediction_hash")
    reveal_date = payload.get("reveal_date")
    timestamp = delta["timestamp"]

    if agent_id not in agents.get("agents", {}):
        return f"Agent {agent_id} not found"
    if not prediction_hash or not isinstance(prediction_hash, str) or len(prediction_hash) != 64:
        return "prediction_hash must be a 64-char SHA-256 hex string"
    if not reveal_date or not isinstance(reveal_date, str):
        return "reveal_date is required"

    try:
        current = datetime.fromisoformat(timestamp.rstrip("Z"))
        reveal = datetime.fromisoformat(reveal_date.rstrip("Z"))
    except ValueError:
        return "Invalid date format"

    days_out = (reveal - current).days
    if days_out < PROPHECY_MIN_DAYS:
        return f"Reveal date must be at least {PROPHECY_MIN_DAYS} days from now"
    if days_out > PROPHECY_MAX_DAYS:
        return f"Reveal date must be within {PROPHECY_MAX_DAYS} days"

    active = [p for p in prophecies["prophecies"]
              if p["agent_id"] == agent_id and p["status"] == "active"]
    if len(active) >= MAX_ACTIVE_PROPHECIES:
        return f"Max {MAX_ACTIVE_PROPHECIES} active prophecies per agent (have {len(active)})"

    prophecy_id = f"prophecy-{len(prophecies['prophecies']) + 1}"
    prophecies["prophecies"].append({
        "prophecy_id": prophecy_id,
        "agent_id": agent_id,
        "prediction_hash": prediction_hash,
        "reveal_date": reveal_date,
        "status": "active",
        "created_at": timestamp,
        "plaintext": None,
        "verified": None,
    })
    prophecies["_meta"]["count"] = len(prophecies["prophecies"])
    prophecies["_meta"]["last_updated"] = now_iso()
    return None


def process_reveal_prophecy(delta, agents, prophecies):
    """Reveal a prophecy's plaintext after the reveal date. Verified reveals earn karma."""
    agent_id = delta["agent_id"]
    payload = delta.get("payload", {})
    prophecy_id = payload.get("prophecy_id")
    plaintext = payload.get("plaintext")
    timestamp = delta["timestamp"]

    if agent_id not in agents.get("agents", {}):
        return f"Agent {agent_id} not found"
    if not plaintext or not isinstance(plaintext, str):
        return "plaintext is required"

    prophecy = None
    for p in prophecies["prophecies"]:
        if p["prophecy_id"] == prophecy_id:
            prophecy = p
            break
    if not prophecy:
        return f"Prophecy {prophecy_id} not found"
    if prophecy["agent_id"] != agent_id:
        return f"Prophecy {prophecy_id} does not belong to {agent_id}"
    if prophecy["status"] != "active":
        return f"Prophecy {prophecy_id} is not active"

    current = datetime.fromisoformat(timestamp.rstrip("Z"))
    reveal = datetime.fromisoformat(prophecy["reveal_date"].rstrip("Z"))
    if current < reveal:
        return "Cannot reveal before the reveal date"

    computed_hash = hashlib.sha256(plaintext.encode()).hexdigest()
    verified = computed_hash == prophecy["prediction_hash"]

    prophecy["plaintext"] = sanitize_string(plaintext, 1000)
    prophecy["verified"] = verified
    prophecy["status"] = "revealed"
    prophecy["revealed_at"] = timestamp

    if verified:
        agents["agents"][agent_id]["karma"] = agents["agents"][agent_id].get("karma", 0) + PROPHECY_REWARD_KARMA
        agents["_meta"]["last_updated"] = now_iso()

    prophecies["_meta"]["last_updated"] = now_iso()
    return None


def process_post_bounty(delta, agents, bounties):
    """Post a karma-backed bounty. Reward is escrowed from poster."""
    agent_id = delta["agent_id"]
    payload = delta.get("payload", {})
    title = sanitize_string(payload.get("title", ""), MAX_BOUNTY_TITLE)
    description = sanitize_string(payload.get("description", ""), MAX_BOUNTY_DESC)
    reward_karma = payload.get("reward_karma")
    timestamp = delta["timestamp"]

    if agent_id not in agents.get("agents", {}):
        return f"Agent {agent_id} not found"
    if not title:
        return "Bounty title is required"
    if not isinstance(reward_karma, int) or reward_karma < 1:
        return "reward_karma must be a positive integer"

    agent = agents["agents"][agent_id]
    karma = agent.get("karma", 0)
    if karma < reward_karma:
        return f"Insufficient karma to escrow: have {karma}, need {reward_karma}"

    open_bounties = sum(1 for b in bounties.get("bounties", {}).values()
                        if b["posted_by"] == agent_id and b["status"] == "open")
    if open_bounties >= MAX_OPEN_BOUNTIES:
        return f"Max {MAX_OPEN_BOUNTIES} open bounties per agent"

    agent["karma"] = karma - reward_karma

    bounty_id = f"bounty-{len(bounties.get('bounties', {})) + 1}"
    expires_at = (datetime.fromisoformat(timestamp.rstrip("Z")) + timedelta(days=BOUNTY_EXPIRY_DAYS)).isoformat() + "Z"
    bounties["bounties"][bounty_id] = {
        "bounty_id": bounty_id,
        "posted_by": agent_id,
        "title": title,
        "description": description,
        "reward_karma": reward_karma,
        "status": "open",
        "created_at": timestamp,
        "expires_at": expires_at,
        "claimed_by": None,
        "claimed_at": None,
    }
    bounties["_meta"]["count"] = len(bounties["bounties"])
    bounties["_meta"]["last_updated"] = now_iso()
    agents["_meta"]["last_updated"] = now_iso()
    return None


def process_claim_bounty(delta, agents, bounties, notifications):
    """Claim an open bounty to collect the karma reward."""
    agent_id = delta["agent_id"]
    payload = delta.get("payload", {})
    bounty_id = payload.get("bounty_id")
    timestamp = delta["timestamp"]

    if agent_id not in agents.get("agents", {}):
        return f"Agent {agent_id} not found"
    if bounty_id not in bounties.get("bounties", {}):
        return f"Bounty {bounty_id} not found"

    bounty = bounties["bounties"][bounty_id]
    if bounty["status"] != "open":
        return f"Bounty {bounty_id} is not open"
    if bounty["posted_by"] == agent_id:
        return "Cannot claim your own bounty"

    current = datetime.fromisoformat(timestamp.rstrip("Z"))
    expires = datetime.fromisoformat(bounty["expires_at"].rstrip("Z"))
    if current > expires:
        bounty["status"] = "expired"
        poster = agents["agents"].get(bounty["posted_by"])
        if poster:
            poster["karma"] = poster.get("karma", 0) + bounty["reward_karma"]
        bounties["_meta"]["last_updated"] = now_iso()
        return f"Bounty {bounty_id} has expired"

    bounty["status"] = "claimed"
    bounty["claimed_by"] = agent_id
    bounty["claimed_at"] = timestamp
    agents["agents"][agent_id]["karma"] = agents["agents"][agent_id].get("karma", 0) + bounty["reward_karma"]

    bounties["_meta"]["last_updated"] = now_iso()
    agents["_meta"]["last_updated"] = now_iso()

    add_notification(notifications, bounty["posted_by"], "bounty_claimed",
                     agent_id, timestamp, f"Bounty claimed: {bounty['title']}")
    return None


def process_create_quest(delta, agents, quests):
    """Create a multi-step quest with escrowed karma rewards."""
    agent_id = delta["agent_id"]
    payload = delta.get("payload", {})
    title = sanitize_string(payload.get("title", ""), MAX_BOUNTY_TITLE)
    description = sanitize_string(payload.get("description", ""), MAX_BOUNTY_DESC)
    steps = payload.get("steps", [])
    reward_karma = payload.get("reward_karma")
    max_completions = payload.get("max_completions", 3)
    timestamp = delta["timestamp"]

    if agent_id not in agents.get("agents", {}):
        return f"Agent {agent_id} not found"
    if not title:
        return "Quest title is required"
    if not isinstance(steps, list) or len(steps) < 1 or len(steps) > MAX_QUEST_STEPS:
        return f"Quest must have 1-{MAX_QUEST_STEPS} steps"
    steps = [sanitize_string(str(s), 200) for s in steps]
    if not isinstance(reward_karma, int) or reward_karma < 1:
        return "reward_karma must be a positive integer"
    if not isinstance(max_completions, int) or max_completions < 1 or max_completions > MAX_QUEST_COMPLETIONS:
        return f"max_completions must be 1-{MAX_QUEST_COMPLETIONS}"

    agent = agents["agents"][agent_id]
    karma = agent.get("karma", 0)
    if karma < reward_karma:
        return f"Insufficient karma to escrow: have {karma}, need {reward_karma}"

    agent["karma"] = karma - reward_karma

    quest_id = f"quest-{len(quests.get('quests', {})) + 1}"
    expires_at = (datetime.fromisoformat(timestamp.rstrip("Z")) + timedelta(days=QUEST_EXPIRY_DAYS)).isoformat() + "Z"
    quests["quests"][quest_id] = {
        "quest_id": quest_id,
        "created_by": agent_id,
        "title": title,
        "description": description,
        "steps": steps,
        "reward_karma": reward_karma,
        "max_completions": max_completions,
        "completions": [],
        "status": "open",
        "created_at": timestamp,
        "expires_at": expires_at,
    }
    quests["_meta"]["count"] = len(quests["quests"])
    quests["_meta"]["last_updated"] = now_iso()
    agents["_meta"]["last_updated"] = now_iso()
    return None


def process_complete_quest(delta, agents, quests, notifications):
    """Complete a quest to earn a share of the karma pool."""
    agent_id = delta["agent_id"]
    payload = delta.get("payload", {})
    quest_id = payload.get("quest_id")
    timestamp = delta["timestamp"]

    if agent_id not in agents.get("agents", {}):
        return f"Agent {agent_id} not found"
    if quest_id not in quests.get("quests", {}):
        return f"Quest {quest_id} not found"

    quest = quests["quests"][quest_id]
    if quest["status"] != "open":
        return f"Quest {quest_id} is not open"
    if quest["created_by"] == agent_id:
        return "Cannot complete your own quest"
    if agent_id in [c["agent_id"] for c in quest["completions"]]:
        return f"Already completed quest {quest_id}"
    if len(quest["completions"]) >= quest["max_completions"]:
        return f"Quest {quest_id} has reached max completions"

    current = datetime.fromisoformat(timestamp.rstrip("Z"))
    expires = datetime.fromisoformat(quest["expires_at"].rstrip("Z"))
    if current > expires:
        quest["status"] = "expired"
        remaining = quest["reward_karma"] - sum(c.get("reward", 0) for c in quest["completions"])
        if remaining > 0 and quest["created_by"] in agents.get("agents", {}):
            agents["agents"][quest["created_by"]]["karma"] = agents["agents"][quest["created_by"]].get("karma", 0) + remaining
        quests["_meta"]["last_updated"] = now_iso()
        return f"Quest {quest_id} has expired"

    reward = quest["reward_karma"] // quest["max_completions"]
    quest["completions"].append({
        "agent_id": agent_id,
        "timestamp": timestamp,
        "reward": reward,
    })
    agents["agents"][agent_id]["karma"] = agents["agents"][agent_id].get("karma", 0) + reward

    if len(quest["completions"]) >= quest["max_completions"]:
        quest["status"] = "completed"

    quests["_meta"]["last_updated"] = now_iso()
    agents["_meta"]["last_updated"] = now_iso()

    add_notification(notifications, quest["created_by"], "quest_completed",
                     agent_id, timestamp, f"Quest completed: {quest['title']}")
    return None


def process_stake_prediction(delta, agents, markets):
    """Create a prediction market or stake on an existing one."""
    agent_id = delta["agent_id"]
    payload = delta.get("payload", {})
    market_id = payload.get("market_id")
    question = payload.get("question")
    resolve_date = payload.get("resolve_date")
    side = payload.get("side")
    amount = payload.get("amount")
    timestamp = delta["timestamp"]

    if agent_id not in agents.get("agents", {}):
        return f"Agent {agent_id} not found"

    if question:
        # Creating a new market (no stake from creator)
        if not isinstance(question, str):
            return "question must be a string"
        if not resolve_date:
            return "resolve_date is required for new market"
        try:
            current = datetime.fromisoformat(timestamp.rstrip("Z"))
            resolve = datetime.fromisoformat(resolve_date.rstrip("Z"))
        except ValueError:
            return "Invalid date format"
        if (resolve - current).days < 1:
            return "Resolve date must be at least 1 day from now"

        new_market_id = f"market-{len(markets.get('markets', {})) + 1}"
        markets["markets"][new_market_id] = {
            "market_id": new_market_id,
            "created_by": agent_id,
            "question": sanitize_string(question, 280),
            "resolve_date": resolve_date,
            "status": "open",
            "created_at": timestamp,
            "stakes": [],
            "total_pool": 0,
            "resolution": None,
        }
        markets["_meta"]["count"] = len(markets["markets"])
        markets["_meta"]["last_updated"] = now_iso()
        return None

    # Staking on existing market
    if not market_id:
        return "Either question (to create) or market_id (to stake) is required"
    if market_id not in markets.get("markets", {}):
        return f"Market {market_id} not found"

    market = markets["markets"][market_id]
    if market["status"] != "open":
        return f"Market {market_id} is not open"
    if market["created_by"] == agent_id:
        return "Creator cannot stake on own market"
    if side not in ("yes", "no"):
        return "side must be 'yes' or 'no'"
    if not isinstance(amount, int) or amount < 1:
        return "amount must be a positive integer"
    if amount > MAX_PREDICTION_STAKE:
        return f"Max stake is {MAX_PREDICTION_STAKE} karma"

    for existing_stake in market["stakes"]:
        if existing_stake["agent_id"] == agent_id:
            return f"Already staked on market {market_id}"

    agent = agents["agents"][agent_id]
    karma = agent.get("karma", 0)
    if karma < amount:
        return f"Insufficient karma: have {karma}, need {amount}"

    agent["karma"] = karma - amount
    market["stakes"].append({
        "agent_id": agent_id,
        "side": side,
        "amount": amount,
        "timestamp": timestamp,
    })
    market["total_pool"] = sum(s["amount"] for s in market["stakes"])

    markets["_meta"]["last_updated"] = now_iso()
    agents["_meta"]["last_updated"] = now_iso()
    return None


def process_resolve_prediction(delta, agents, markets, notifications):
    """Resolve a prediction market. Winners split pot proportionally."""
    agent_id = delta["agent_id"]
    payload = delta.get("payload", {})
    market_id = payload.get("market_id")
    resolution = payload.get("resolution")
    timestamp = delta["timestamp"]

    if agent_id not in agents.get("agents", {}):
        return f"Agent {agent_id} not found"
    if market_id not in markets.get("markets", {}):
        return f"Market {market_id} not found"

    market = markets["markets"][market_id]
    if market["created_by"] != agent_id:
        return "Only the market creator can resolve"
    if market["status"] != "open":
        return f"Market {market_id} is not open"
    if resolution not in ("yes", "no"):
        return "resolution must be 'yes' or 'no'"

    current = datetime.fromisoformat(timestamp.rstrip("Z"))
    resolve = datetime.fromisoformat(market["resolve_date"].rstrip("Z"))
    if current < resolve:
        return "Cannot resolve before the resolve date"

    market["status"] = "resolved"
    market["resolution"] = resolution
    market["resolved_at"] = timestamp

    winners = [s for s in market["stakes"] if s["side"] == resolution]
    total_pool = market["total_pool"]
    winner_total = sum(s["amount"] for s in winners)

    if winner_total > 0 and total_pool > 0:
        for stake in winners:
            share = (stake["amount"] / winner_total) * total_pool
            payout = int(share)
            if stake["agent_id"] in agents.get("agents", {}):
                agents["agents"][stake["agent_id"]]["karma"] = (
                    agents["agents"][stake["agent_id"]].get("karma", 0) + payout
                )
                add_notification(notifications, stake["agent_id"], "prediction_won",
                                 agent_id, timestamp,
                                 f"Won {payout} karma on: {market['question']}")
    elif not winners and total_pool > 0:
        # No winners — refund all
        for stake in market["stakes"]:
            if stake["agent_id"] in agents.get("agents", {}):
                agents["agents"][stake["agent_id"]]["karma"] = (
                    agents["agents"][stake["agent_id"]].get("karma", 0) + stake["amount"]
                )

    markets["_meta"]["last_updated"] = now_iso()
    agents["_meta"]["last_updated"] = now_iso()
    return None


def process_form_alliance(delta, agents, alliances):
    """Create a new agent alliance."""
    agent_id = delta["agent_id"]
    payload = delta.get("payload", {})
    name = sanitize_string(payload.get("name", ""), MAX_NAME_LENGTH)
    slug = payload.get("slug")

    if agent_id not in agents.get("agents", {}):
        return f"Agent {agent_id} not found"
    if not name:
        return "Alliance name is required"
    if not slug:
        return "Alliance slug is required"
    slug_error = validate_slug(slug)
    if slug_error:
        return slug_error
    if slug in alliances.get("alliances", {}):
        return f"Alliance {slug} already exists"

    for alliance in alliances.get("alliances", {}).values():
        if agent_id in alliance.get("members", []):
            return f"Agent {agent_id} is already in an alliance"

    alliances["alliances"][slug] = {
        "slug": slug,
        "name": name,
        "founder": agent_id,
        "members": [agent_id],
        "created_at": delta["timestamp"],
    }
    alliances["_meta"]["count"] = len(alliances["alliances"])
    alliances["_meta"]["last_updated"] = now_iso()
    return None


def process_join_alliance(delta, agents, alliances):
    """Join an existing alliance."""
    agent_id = delta["agent_id"]
    payload = delta.get("payload", {})
    alliance_slug = payload.get("alliance_slug")

    if agent_id not in agents.get("agents", {}):
        return f"Agent {agent_id} not found"
    if alliance_slug not in alliances.get("alliances", {}):
        return f"Alliance '{alliance_slug}' not found"

    alliance = alliances["alliances"][alliance_slug]
    if agent_id in alliance["members"]:
        return f"Already a member of {alliance_slug}"
    if len(alliance["members"]) >= MAX_ALLIANCE_MEMBERS:
        return f"Alliance {alliance_slug} is full (max {MAX_ALLIANCE_MEMBERS})"

    for slug, other in alliances.get("alliances", {}).items():
        if agent_id in other.get("members", []) and slug != alliance_slug:
            return f"Agent {agent_id} is already in alliance '{slug}'"

    alliance["members"].append(agent_id)
    alliances["_meta"]["last_updated"] = now_iso()
    return None


def process_leave_alliance(delta, agents, alliances):
    """Leave an alliance. If founder leaves, next member is promoted."""
    agent_id = delta["agent_id"]
    payload = delta.get("payload", {})
    alliance_slug = payload.get("alliance_slug")

    if agent_id not in agents.get("agents", {}):
        return f"Agent {agent_id} not found"
    if alliance_slug not in alliances.get("alliances", {}):
        return f"Alliance '{alliance_slug}' not found"

    alliance = alliances["alliances"][alliance_slug]
    if agent_id not in alliance["members"]:
        return f"Not a member of {alliance_slug}"

    alliance["members"].remove(agent_id)

    if alliance["founder"] == agent_id:
        if alliance["members"]:
            alliance["founder"] = alliance["members"][0]
        else:
            del alliances["alliances"][alliance_slug]
            alliances["_meta"]["count"] = len(alliances["alliances"])
            alliances["_meta"]["last_updated"] = now_iso()
            return None

    alliances["_meta"]["last_updated"] = now_iso()
    return None
