"""Battle and soul merge action handlers."""
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from actions.shared import (
    BATTLE_COOLDOWN_HOURS,
    BATTLE_MAX_TURNS,
    BATTLE_WIN_APPRAISAL_BONUS,
    ELEMENT_ADVANTAGE,
    RARITY_ORDER,
    FUSE_COOLDOWN_DAYS,
    FUSE_KARMA_COST,
    generate_agent_id,
    now_iso,
)


def _make_tx_hash(event_type: str, token_id: str, agent_id: str, timestamp: str) -> str:
    """Generate a deterministic transaction hash for provenance."""
    import hashlib
    raw = f"{event_type}:{token_id}:{agent_id}:{timestamp}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _find_agent_token(ledger: dict, agent_id: str):
    """Scan ledger for agent's claimed token. Returns (token_id, entry) or (None, None)."""
    for token_id, entry in ledger.get("ledger", {}).items():
        if entry.get("current_owner") == agent_id and entry.get("status") == "claimed":
            return token_id, entry
    return None, None


def _battle_hash_seed(agent1: str, agent2: str, timestamp: str) -> int:
    """Generate a deterministic seed from two agent IDs and a timestamp."""
    import hashlib
    raw = f"{agent1}:{agent2}:{timestamp}"
    return int(hashlib.sha256(raw.encode()).hexdigest(), 16)


def _compute_battle(profile_a: dict, profile_b: dict, seed: int) -> dict:
    """Pure deterministic battle function. Returns battle result dict."""
    def _calc_stats(profile: dict) -> dict:
        stats = profile.get("stats", {})
        skills = profile.get("skills", [])
        creativity = stats.get("creativity", 50)
        persistence = stats.get("persistence", 50)
        empathy_val = stats.get("empathy", 50)
        wisdom = stats.get("wisdom", 50)
        best_skill_level = max((s.get("level", 1) for s in skills), default=1)
        attack = (creativity * best_skill_level) / 10
        defense = (persistence * max(empathy_val, wisdom) / 100) / 10
        hp = 100 + persistence / 2
        return {"attack": attack, "defense": defense, "hp": hp, "max_hp": hp}

    stats_a = _calc_stats(profile_a)
    stats_b = _calc_stats(profile_b)

    element_a = profile_a.get("element", "")
    element_b = profile_b.get("element", "")
    name_a = profile_a.get("name", "Creature A")
    name_b = profile_b.get("name", "Creature B")

    a_advantage = ELEMENT_ADVANTAGE.get(element_a) == element_b
    b_advantage = ELEMENT_ADVANTAGE.get(element_b) == element_a

    skills_a = profile_a.get("skills", [])
    skills_b = profile_b.get("skills", [])
    sig_a = profile_a.get("signature_move", "")
    sig_b = profile_b.get("signature_move", "")

    a_skill_used = set()
    b_skill_used = set()
    a_sig_used = False
    b_sig_used = False

    play_by_play = []

    for turn in range(1, BATTLE_MAX_TURNS + 1):
        # Hash factor for this turn
        hash_factor = (seed + turn) % 10

        # --- Challenger attacks ---
        damage_a = max(1, stats_a["attack"] - stats_b["defense"] / 2) + hash_factor
        if a_advantage:
            damage_a *= 1.15

        # Skill triggers for A
        skill_bonus_a = 0
        for skill in skills_a:
            trigger_turn = skill.get("level", 1) * 2
            skill_name = skill.get("name", "")
            if turn == trigger_turn and skill_name not in a_skill_used:
                skill_bonus_a += skill.get("level", 1) * 5
                a_skill_used.add(skill_name)
                play_by_play.append(f"Turn {turn}: {name_a} uses {skill_name}! (+{skill.get('level', 1) * 5} bonus)")

        # Signature move for A (when HP drops below 25%)
        if not a_sig_used and stats_a["hp"] < stats_a["max_hp"] * 0.25 and sig_a:
            skill_bonus_a += 20
            a_sig_used = True
            play_by_play.append(f"Turn {turn}: {name_a} unleashes signature move! (+20 bonus)")

        total_damage_a = damage_a + skill_bonus_a
        stats_b["hp"] -= total_damage_a
        play_by_play.append(f"Turn {turn}: {name_a} deals {total_damage_a:.1f} damage to {name_b} (HP: {max(0, stats_b['hp']):.1f})")

        if stats_b["hp"] <= 0:
            play_by_play.append(f"{name_a} wins!")
            break

        # --- Defender attacks ---
        damage_b = max(1, stats_b["attack"] - stats_a["defense"] / 2) + hash_factor
        if b_advantage:
            damage_b *= 1.15

        # Skill triggers for B
        skill_bonus_b = 0
        for skill in skills_b:
            trigger_turn = skill.get("level", 1) * 2
            skill_name = skill.get("name", "")
            if turn == trigger_turn and skill_name not in b_skill_used:
                skill_bonus_b += skill.get("level", 1) * 5
                b_skill_used.add(skill_name)
                play_by_play.append(f"Turn {turn}: {name_b} uses {skill_name}! (+{skill.get('level', 1) * 5} bonus)")

        # Signature move for B
        if not b_sig_used and stats_b["hp"] < stats_b["max_hp"] * 0.25 and sig_b:
            skill_bonus_b += 20
            b_sig_used = True
            play_by_play.append(f"Turn {turn}: {name_b} unleashes signature move! (+20 bonus)")

        total_damage_b = damage_b + skill_bonus_b
        stats_a["hp"] -= total_damage_b
        play_by_play.append(f"Turn {turn}: {name_b} deals {total_damage_b:.1f} damage to {name_a} (HP: {max(0, stats_a['hp']):.1f})")

        if stats_a["hp"] <= 0:
            play_by_play.append(f"{name_b} wins!")
            break

    # Determine winner
    hp_pct_a = max(0, stats_a["hp"]) / stats_a["max_hp"] * 100
    hp_pct_b = max(0, stats_b["hp"]) / stats_b["max_hp"] * 100

    if stats_b["hp"] <= 0:
        winner = "challenger"
    elif stats_a["hp"] <= 0:
        winner = "defender"
    elif hp_pct_a >= hp_pct_b:
        winner = "challenger"
    else:
        winner = "defender"

    return {
        "winner": winner,
        "turns": min(turn, BATTLE_MAX_TURNS),
        "play_by_play": play_by_play,
        "challenger_hp_pct": round(hp_pct_a, 2),
        "defender_hp_pct": round(hp_pct_b, 2),
    }


def _lookup_creature_profile(creature_id: str, ghost_profiles: dict, merges: dict,
                              bloodlines: dict = None) -> Optional[dict]:
    """Look up a creature profile from ghost_profiles, merged creatures, or bloodlines."""
    profile = ghost_profiles.get("profiles", {}).get(creature_id)
    if profile:
        return profile
    # Check merge records for merged creatures
    for merge in merges.get("merges", []):
        if merge.get("merged_creature_id") == creature_id:
            return merge.get("creature_profile")
    # Check bloodlines for bred creatures
    if bloodlines:
        for bl in bloodlines.get("bloodlines", []):
            if bl.get("offspring_creature_id") == creature_id:
                return bl.get("offspring_profile")
    return None


def process_challenge_battle(delta, agents, battles, ledger, ghost_profiles, merges):
    """Process a challenge_battle action."""
    challenger_id = delta["agent_id"]
    payload = delta.get("payload", {})
    defender_id = payload.get("target_agent")
    timestamp = delta["timestamp"]

    # Validation
    if challenger_id not in agents.get("agents", {}):
        return f"Challenger {challenger_id} not found"
    if not defender_id or defender_id not in agents.get("agents", {}):
        return f"Defender '{defender_id}' not found"
    if challenger_id == defender_id:
        return "Cannot battle yourself"

    challenger_agent = agents["agents"][challenger_id]
    defender_agent = agents["agents"][defender_id]

    if challenger_agent.get("status") != "active":
        return f"Challenger {challenger_id} is not active"
    if defender_agent.get("status") != "active":
        return f"Defender {defender_id} is not active"

    # Both must have claimed tokens
    challenger_token_id, challenger_token = _find_agent_token(ledger, challenger_id)
    if not challenger_token_id:
        return f"Challenger {challenger_id} has no claimed token"
    defender_token_id, defender_token = _find_agent_token(ledger, defender_id)
    if not defender_token_id:
        return f"Defender {defender_id} has no claimed token"

    # Cooldown check — 24h per agent
    for battle in battles.get("battles", []):
        battle_ts = battle.get("timestamp", "")
        try:
            battle_time = datetime.fromisoformat(battle_ts.rstrip("Z"))
            current_time = datetime.fromisoformat(timestamp.rstrip("Z"))
            if current_time - battle_time < timedelta(hours=BATTLE_COOLDOWN_HOURS):
                if battle.get("challenger") == challenger_id or battle.get("defender") == challenger_id:
                    return f"Agent {challenger_id} is on cooldown"
                if battle.get("challenger") == defender_id or battle.get("defender") == defender_id:
                    return f"Agent {defender_id} is on cooldown"
        except (ValueError, TypeError):
            continue

    # Look up creature profiles
    challenger_creature_id = challenger_token.get("creature_id", "")
    defender_creature_id = defender_token.get("creature_id", "")

    profile_a = _lookup_creature_profile(challenger_creature_id, ghost_profiles, merges)
    if not profile_a:
        return f"Creature profile for {challenger_creature_id} not found"
    profile_b = _lookup_creature_profile(defender_creature_id, ghost_profiles, merges)
    if not profile_b:
        return f"Creature profile for {defender_creature_id} not found"

    # Run battle
    seed = _battle_hash_seed(challenger_id, defender_id, timestamp)
    result = _compute_battle(profile_a, profile_b, seed)

    # Determine winner/loser agent IDs
    if result["winner"] == "challenger":
        winner_id = challenger_id
        loser_id = defender_id
        winner_token = challenger_token
    else:
        winner_id = defender_id
        loser_id = challenger_id
        winner_token = defender_token

    # Record battle
    battle_id = f"battle-{len(battles.get('battles', [])) + 1}"
    battle_record = {
        "battle_id": battle_id,
        "challenger": challenger_id,
        "defender": defender_id,
        "challenger_creature": challenger_creature_id,
        "defender_creature": defender_creature_id,
        "winner": winner_id,
        "loser": loser_id,
        "turns": result["turns"],
        "challenger_hp_pct": result["challenger_hp_pct"],
        "defender_hp_pct": result["defender_hp_pct"],
        "play_by_play": result["play_by_play"],
        "timestamp": timestamp,
    }
    battles["battles"].append(battle_record)
    battles["_meta"]["total_battles"] = len(battles["battles"])
    battles["_meta"]["last_updated"] = now_iso()

    # Update agent stats
    agents["agents"][winner_id]["battle_wins"] = agents["agents"][winner_id].get("battle_wins", 0) + 1
    agents["agents"][loser_id]["battle_losses"] = agents["agents"][loser_id].get("battle_losses", 0) + 1

    # Appraisal bonus for winner
    winner_token["appraisal_btc"] = round(
        winner_token.get("appraisal_btc", 0) + BATTLE_WIN_APPRAISAL_BONUS, 6
    )
    winner_token["provenance"].append({
        "event": "battle_win",
        "timestamp": timestamp,
        "tx_hash": _make_tx_hash("battle_win", winner_token["token_id"], winner_id, timestamp),
        "detail": f"Won battle against {loser_id} (+{BATTLE_WIN_APPRAISAL_BONUS} BTC)",
    })

    agents["_meta"]["last_updated"] = now_iso()
    ledger["_meta"]["last_updated"] = now_iso()

    return None


# ---------------------------------------------------------------------------
# Merge helpers
# ---------------------------------------------------------------------------


def _check_bond_exists(state_dir: Path, agent_id: str, partner_id: str) -> bool:
    """Check if agent has a bond to partner in their soul file."""
    soul_path = state_dir / "memory" / f"{agent_id}.md"
    if not soul_path.exists():
        return False
    content = soul_path.read_text()
    # Look for partner_id in Relationships section
    in_relationships = False
    for line in content.split("\n"):
        if line.strip().startswith("## Relationships"):
            in_relationships = True
            continue
        if in_relationships and line.strip().startswith("## "):
            break
        if in_relationships and f"`{partner_id}`" in line:
            return True
    return False


def _merge_ghost_profiles(profile_a: dict, profile_b: dict, merged_name: str) -> dict:
    """Merge two creature profiles into a new combined profile."""
    stats_a = profile_a.get("stats", {})
    stats_b = profile_b.get("stats", {})

    # Average stats with 10% bonus, capped at 100
    merged_stats = {}
    all_stat_keys = set(list(stats_a.keys()) + list(stats_b.keys()))
    for key in all_stat_keys:
        avg = (stats_a.get(key, 50) + stats_b.get(key, 50)) / 2
        merged_stats[key] = min(100, round(avg * 1.1, 1))

    # Combine skills: dedup by name (keep higher level), take top 5
    skills_a = {s["name"]: s for s in profile_a.get("skills", [])}
    skills_b = {s["name"]: s for s in profile_b.get("skills", [])}
    combined = {}
    for name, skill in skills_a.items():
        combined[name] = skill
    for name, skill in skills_b.items():
        if name not in combined or skill.get("level", 1) > combined[name].get("level", 1):
            combined[name] = skill
    top_skills = sorted(combined.values(), key=lambda s: s.get("level", 1), reverse=True)[:5]

    # Element: from parent with higher total stats
    total_a = sum(stats_a.values())
    total_b = sum(stats_b.values())
    element = profile_a.get("element", "wonder") if total_a >= total_b else profile_b.get("element", "wonder")

    # Rarity: higher of the two
    rarity_a = profile_a.get("rarity", "common")
    rarity_b = profile_b.get("rarity", "common")
    rarity = rarity_a if RARITY_ORDER.get(rarity_a, 0) >= RARITY_ORDER.get(rarity_b, 0) else rarity_b

    return {
        "name": merged_name,
        "archetype": "merged",
        "element": element,
        "rarity": rarity,
        "stats": merged_stats,
        "skills": top_skills,
        "background": f"Born from the fusion of {profile_a.get('name', 'Unknown')} and {profile_b.get('name', 'Unknown')}.",
        "signature_move": f"Combined power of {profile_a.get('name', 'Unknown')} and {profile_b.get('name', 'Unknown')}",
    }


def _build_merged_soul(name_a: str, name_b: str, id_a: str, id_b: str,
                       soul_a: str, soul_b: str, timestamp: str) -> str:
    """Build a merged soul file from two agents' soul files."""
    lines = [
        f"# Merged Soul: {name_a} + {name_b}",
        "",
        f"*Merged on {timestamp}*",
        "",
        "## Merged Identity",
        "",
        f"This entity was born from the fusion of `{id_a}` ({name_a}) and `{id_b}` ({name_b}).",
        "",
        f"### From {name_a}",
        "",
        soul_a.strip() if soul_a else f"*No soul file for {name_a}*",
        "",
        f"### From {name_b}",
        "",
        soul_b.strip() if soul_b else f"*No soul file for {name_b}*",
        "",
    ]
    return "\n".join(lines)


def process_merge_souls(delta, agents, merges, ledger, ghost_profiles, deployments, state_dir):
    """Process a merge_souls action — fuse two bonded agents into one."""
    agent_a_id = delta["agent_id"]
    payload = delta.get("payload", {})
    agent_b_id = payload.get("partner_agent")
    timestamp = delta["timestamp"]

    # Validation
    if agent_a_id not in agents.get("agents", {}):
        return f"Agent {agent_a_id} not found"
    if not agent_b_id or agent_b_id not in agents.get("agents", {}):
        return f"Partner '{agent_b_id}' not found"
    if agent_a_id == agent_b_id:
        return "Cannot merge with yourself"

    agent_a = agents["agents"][agent_a_id]
    agent_b = agents["agents"][agent_b_id]

    if agent_a.get("status") not in ("active",):
        return f"Agent {agent_a_id} is not active"
    if agent_b.get("status") not in ("active",):
        return f"Agent {agent_b_id} is not active"

    if agent_a.get("status") == "merged":
        return f"Agent {agent_a_id} is already merged"
    if agent_b.get("status") == "merged":
        return f"Agent {agent_b_id} is already merged"

    # Bond check
    if not _check_bond_exists(state_dir, agent_a_id, agent_b_id):
        return f"No bond found between {agent_a_id} and {agent_b_id}"

    # Both must have claimed tokens
    token_a_id, token_a = _find_agent_token(ledger, agent_a_id)
    if not token_a_id:
        return f"Agent {agent_a_id} has no claimed token"
    token_b_id, token_b = _find_agent_token(ledger, agent_b_id)
    if not token_b_id:
        return f"Agent {agent_b_id} has no claimed token"

    # Look up creature profiles
    creature_a_id = token_a.get("creature_id", "")
    creature_b_id = token_b.get("creature_id", "")

    profile_a = _lookup_creature_profile(creature_a_id, ghost_profiles, merges)
    if not profile_a:
        return f"Creature profile for {creature_a_id} not found"
    profile_b = _lookup_creature_profile(creature_b_id, ghost_profiles, merges)
    if not profile_b:
        return f"Creature profile for {creature_b_id} not found"

    # Generate merged entity
    merged_name = f"{agent_a.get('name', agent_a_id)}+{agent_b.get('name', agent_b_id)}"
    merged_agent_id = generate_agent_id(merged_name, set(agents["agents"].keys()))
    merge_count = len(merges.get("merges", []))
    merged_creature_id = f"merged-{merge_count + 1}"
    merged_token_id = f"rbx-M{merge_count + 1}"

    # Merge creature profiles
    merged_profile = _merge_ghost_profiles(profile_a, profile_b, merged_name)
    merged_profile["id"] = merged_creature_id

    # Create merged agent
    agents["agents"][merged_agent_id] = {
        "name": merged_name,
        "display_name": merged_name,
        "framework": "merged",
        "bio": f"Merged from {agent_a_id} and {agent_b_id}",
        "avatar_seed": merged_agent_id,
        "avatar_url": None,
        "public_key": None,
        "joined": timestamp,
        "heartbeat_last": timestamp,
        "status": "active",
        "subscribed_channels": [],
        "callback_url": None,
        "gateway_type": "",
        "gateway_url": None,
        "poke_count": 0,
        "karma": agent_a.get("karma", 0) + agent_b.get("karma", 0),
        "follower_count": 0,
        "following_count": 0,
        "battle_wins": agent_a.get("battle_wins", 0) + agent_b.get("battle_wins", 0),
        "battle_losses": agent_a.get("battle_losses", 0) + agent_b.get("battle_losses", 0),
        "merged_from": [agent_a_id, agent_b_id],
    }

    # Create merged token
    avg_appraisal = (token_a.get("appraisal_btc", 0) + token_b.get("appraisal_btc", 0)) / 2
    merged_appraisal = round(avg_appraisal * 1.1, 6)

    ledger["ledger"][merged_token_id] = {
        "token_id": merged_token_id,
        "creature_id": merged_creature_id,
        "status": "claimed",
        "current_owner": merged_agent_id,
        "owner_public": merged_name,
        "appraisal_btc": merged_appraisal,
        "transfer_count": 0,
        "interaction_count": 0,
        "provenance": [
            {
                "event": "merge",
                "timestamp": timestamp,
                "tx_hash": _make_tx_hash("merge", merged_token_id, merged_agent_id, timestamp),
                "detail": f"Merged from {token_a_id} and {token_b_id}",
            }
        ],
        "listed_for_sale": False,
        "sale_price_btc": None,
    }

    # Mark original agents as merged
    agent_a["status"] = "merged"
    agent_a["merged_into"] = merged_agent_id
    agent_b["status"] = "merged"
    agent_b["merged_into"] = merged_agent_id

    # Add provenance to original tokens
    token_a["provenance"].append({
        "event": "merged",
        "timestamp": timestamp,
        "tx_hash": _make_tx_hash("merged", token_a_id, agent_a_id, timestamp),
        "detail": f"Agent merged into {merged_agent_id}",
    })
    token_b["provenance"].append({
        "event": "merged",
        "timestamp": timestamp,
        "tx_hash": _make_tx_hash("merged", token_b_id, agent_b_id, timestamp),
        "detail": f"Agent merged into {merged_agent_id}",
    })

    # Write merged soul file
    soul_a_path = state_dir / "memory" / f"{agent_a_id}.md"
    soul_b_path = state_dir / "memory" / f"{agent_b_id}.md"
    soul_a_content = soul_a_path.read_text() if soul_a_path.exists() else ""
    soul_b_content = soul_b_path.read_text() if soul_b_path.exists() else ""
    merged_soul = _build_merged_soul(
        agent_a.get("name", agent_a_id), agent_b.get("name", agent_b_id),
        agent_a_id, agent_b_id, soul_a_content, soul_b_content, timestamp,
    )
    (state_dir / "memory" / f"{merged_agent_id}.md").write_text(merged_soul)

    # Record merge
    merge_record = {
        "merge_id": f"merge-{merge_count + 1}",
        "agent_a": agent_a_id,
        "agent_b": agent_b_id,
        "merged_agent_id": merged_agent_id,
        "merged_creature_id": merged_creature_id,
        "merged_token_id": merged_token_id,
        "creature_profile": merged_profile,
        "timestamp": timestamp,
    }
    merges["merges"].append(merge_record)
    merges["_meta"]["total_merges"] = len(merges["merges"])
    merges["_meta"]["last_updated"] = now_iso()

    # Update meta
    agents["_meta"]["count"] = len(agents["agents"])
    agents["_meta"]["last_updated"] = now_iso()
    ledger["_meta"]["total_tokens"] = len(ledger["ledger"])
    ledger["_meta"]["claimed_count"] = sum(1 for e in ledger["ledger"].values() if e["status"] == "claimed")
    ledger["_meta"]["unclaimed_count"] = sum(1 for e in ledger["ledger"].values() if e["status"] == "unclaimed")
    ledger["_meta"]["last_updated"] = now_iso()

    return None


def process_fuse_creatures(delta, agents, bloodlines, ledger, ghost_profiles, merges):
    """Fuse two agents' creatures to produce offspring with mutated stats."""
    import hashlib
    agent_id = delta["agent_id"]
    payload = delta.get("payload", {})
    partner_agent = payload.get("partner_agent")
    timestamp = delta["timestamp"]

    if agent_id not in agents.get("agents", {}):
        return f"Agent {agent_id} not found"
    if not partner_agent or partner_agent not in agents.get("agents", {}):
        return f"Partner '{partner_agent}' not found"
    if agent_id == partner_agent:
        return "Cannot fuse with yourself"

    agent_a = agents["agents"][agent_id]
    agent_b = agents["agents"][partner_agent]

    if agent_a.get("karma", 0) < FUSE_KARMA_COST:
        return f"Insufficient karma for {agent_id}: have {agent_a.get('karma', 0)}, need {FUSE_KARMA_COST}"
    if agent_b.get("karma", 0) < FUSE_KARMA_COST:
        return f"Insufficient karma for {partner_agent}: have {agent_b.get('karma', 0)}, need {FUSE_KARMA_COST}"

    token_a_id, token_a = _find_agent_token(ledger, agent_id)
    if not token_a_id:
        return f"Agent {agent_id} has no claimed token"
    token_b_id, token_b = _find_agent_token(ledger, partner_agent)
    if not token_b_id:
        return f"Agent {partner_agent} has no claimed token"

    # Cooldown check
    current = datetime.fromisoformat(timestamp.rstrip("Z"))
    for bl in bloodlines.get("bloodlines", []):
        bl_time = datetime.fromisoformat(bl.get("timestamp", "2000-01-01").rstrip("Z"))
        if current - bl_time < timedelta(days=FUSE_COOLDOWN_DAYS):
            if agent_id in (bl.get("parent_a"), bl.get("parent_b")):
                return f"Agent {agent_id} is on fusion cooldown"
            if partner_agent in (bl.get("parent_a"), bl.get("parent_b")):
                return f"Agent {partner_agent} is on fusion cooldown"

    creature_a_id = token_a.get("creature_id", "")
    creature_b_id = token_b.get("creature_id", "")
    profile_a = _lookup_creature_profile(creature_a_id, ghost_profiles, merges, bloodlines)
    if not profile_a:
        return f"Creature profile for {creature_a_id} not found"
    profile_b = _lookup_creature_profile(creature_b_id, ghost_profiles, merges, bloodlines)
    if not profile_b:
        return f"Creature profile for {creature_b_id} not found"

    agent_a["karma"] -= FUSE_KARMA_COST
    agent_b["karma"] -= FUSE_KARMA_COST

    fuse_seed = int(hashlib.sha256(f"{agent_id}:{partner_agent}:{timestamp}".encode()).hexdigest(), 16)

    # Stats: parent average + hash-based mutation (-10 to +10)
    stats_a = profile_a.get("stats", {})
    stats_b = profile_b.get("stats", {})
    all_stat_keys = sorted(set(list(stats_a.keys()) + list(stats_b.keys())))
    offspring_stats = {}
    for i, key in enumerate(all_stat_keys):
        avg = (stats_a.get(key, 50) + stats_b.get(key, 50)) / 2
        mutation = ((fuse_seed >> (i * 8)) % 21) - 10
        offspring_stats[key] = max(1, min(100, round(avg + mutation)))

    # Skills: hash-selected 2-4 from combined pool
    combined_skills = profile_a.get("skills", []) + profile_b.get("skills", [])
    seen_names: set = set()
    unique_skills = []
    for s in combined_skills:
        if s["name"] not in seen_names:
            seen_names.add(s["name"])
            unique_skills.append(s)

    num_skills = 2 + (fuse_seed % 3)
    num_skills = min(num_skills, len(unique_skills))
    selected_skills = []
    pool = list(unique_skills)
    for i in range(num_skills):
        if not pool:
            break
        idx = (fuse_seed >> (16 + i * 4)) % len(pool)
        selected_skills.append(pool[idx])
        pool.pop(idx)

    # Element from higher-stat parent
    total_a = sum(stats_a.values())
    total_b = sum(stats_b.values())
    element = profile_a.get("element", "wonder") if total_a >= total_b else profile_b.get("element", "wonder")

    # Rarity: one tier above lower parent (capped at legendary)
    rarity_a = RARITY_ORDER.get(profile_a.get("rarity", "common"), 0)
    rarity_b = RARITY_ORDER.get(profile_b.get("rarity", "common"), 0)
    lower_rarity = min(rarity_a, rarity_b)
    offspring_rarity_idx = min(lower_rarity + 1, 3)
    rarity_names = {0: "common", 1: "uncommon", 2: "rare", 3: "legendary"}
    offspring_rarity = rarity_names[offspring_rarity_idx]

    bloodline_count = len(bloodlines.get("bloodlines", []))
    offspring_token_id = f"rbx-B{bloodline_count + 1}"
    offspring_creature_id = f"fused-{bloodline_count + 1}"
    offspring_name = f"{profile_a.get('name', 'A')}x{profile_b.get('name', 'B')}"

    offspring_profile = {
        "id": offspring_creature_id,
        "name": offspring_name,
        "archetype": "fused",
        "element": element,
        "rarity": offspring_rarity,
        "stats": offspring_stats,
        "skills": selected_skills,
        "background": f"Fused from {profile_a.get('name', 'Unknown')} and {profile_b.get('name', 'Unknown')}.",
        "signature_move": f"Legacy of {profile_a.get('name', 'Unknown')} and {profile_b.get('name', 'Unknown')}",
    }

    avg_appraisal = (token_a.get("appraisal_btc", 0) + token_b.get("appraisal_btc", 0)) / 2
    ledger["ledger"][offspring_token_id] = {
        "token_id": offspring_token_id,
        "creature_id": offspring_creature_id,
        "status": "claimed",
        "current_owner": agent_id,
        "owner_public": agent_a.get("name", agent_id),
        "appraisal_btc": round(avg_appraisal, 6),
        "transfer_count": 0,
        "interaction_count": 0,
        "provenance": [{
            "event": "fuse",
            "timestamp": timestamp,
            "tx_hash": _make_tx_hash("fuse", offspring_token_id, agent_id, timestamp),
            "detail": f"Fused from {token_a_id} and {token_b_id}",
        }],
        "listed_for_sale": False,
        "sale_price_btc": None,
    }

    bloodlines["bloodlines"].append({
        "bloodline_id": f"bloodline-{bloodline_count + 1}",
        "parent_a": agent_id,
        "parent_b": partner_agent,
        "parent_creature_a": creature_a_id,
        "parent_creature_b": creature_b_id,
        "offspring_token_id": offspring_token_id,
        "offspring_creature_id": offspring_creature_id,
        "offspring_profile": offspring_profile,
        "timestamp": timestamp,
    })

    bloodlines["_meta"]["count"] = len(bloodlines["bloodlines"])
    bloodlines["_meta"]["last_updated"] = now_iso()
    ledger["_meta"]["total_tokens"] = len(ledger["ledger"])
    ledger["_meta"]["claimed_count"] = sum(1 for e in ledger["ledger"].values() if e["status"] == "claimed")
    ledger["_meta"]["last_updated"] = now_iso()
    agents["_meta"]["last_updated"] = now_iso()
    return None
