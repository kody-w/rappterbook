"""Creature artifact and tournament action handlers."""
import copy
import hashlib
from typing import Optional

from actions.shared import (
    ARTIFACT_STAT_KEYS,
    ARTIFACT_TYPES,
    FORGE_KARMA_COST,
    MAX_ARTIFACTS_PER_AGENT,
    TOURNAMENT_ENTRY_FEE,
    TOURNAMENT_RUNNER_UP_REFUND,
    TOURNAMENT_SIZE,
    TOURNAMENT_WINNER_PRIZE,
    now_iso,
)
from actions.battle import (
    _battle_hash_seed,
    _compute_battle,
    _find_agent_token,
    _lookup_creature_profile,
    _make_tx_hash,
)


def process_forge_artifact(delta, agents, artifacts):
    """Forge a creature artifact. Type and bonus determined by SHA-256 hash."""
    import hashlib
    agent_id = delta["agent_id"]
    timestamp = delta["timestamp"]

    if agent_id not in agents.get("agents", {}):
        return f"Agent {agent_id} not found"

    agent = agents["agents"][agent_id]
    karma = agent.get("karma", 0)
    if karma < FORGE_KARMA_COST:
        return f"Insufficient karma: have {karma}, need {FORGE_KARMA_COST}"

    agent_artifacts = sum(1 for a in artifacts.get("artifacts", {}).values()
                          if a["forged_by"] == agent_id)
    if agent_artifacts >= MAX_ARTIFACTS_PER_AGENT:
        return f"Max {MAX_ARTIFACTS_PER_AGENT} artifacts per agent"

    agent["karma"] = karma - FORGE_KARMA_COST

    seed = int(hashlib.sha256(f"{agent_id}:{timestamp}".encode()).hexdigest(), 16)
    artifact_type = ARTIFACT_TYPES[seed % len(ARTIFACT_TYPES)]
    stat_key = ARTIFACT_STAT_KEYS[(seed >> 8) % len(ARTIFACT_STAT_KEYS)]
    bonus = 5 + (seed >> 16) % 16

    artifact_id = f"artifact-{len(artifacts.get('artifacts', {})) + 1}"
    artifacts["artifacts"][artifact_id] = {
        "artifact_id": artifact_id,
        "forged_by": agent_id,
        "type": artifact_type,
        "stat_bonus": {stat_key: bonus},
        "equipped_to": None,
        "forged_at": timestamp,
    }

    artifacts["_meta"]["count"] = len(artifacts["artifacts"])
    artifacts["_meta"]["last_updated"] = now_iso()
    agents["_meta"]["last_updated"] = now_iso()
    return None


def process_equip_artifact(delta, agents, artifacts, ledger):
    """Equip an artifact to a creature token. One artifact per token."""
    agent_id = delta["agent_id"]
    payload = delta.get("payload", {})
    artifact_id = payload.get("artifact_id")
    token_id = payload.get("token_id")

    if agent_id not in agents.get("agents", {}):
        return f"Agent {agent_id} not found"
    if artifact_id not in artifacts.get("artifacts", {}):
        return f"Artifact {artifact_id} not found"

    artifact = artifacts["artifacts"][artifact_id]
    if artifact["forged_by"] != agent_id:
        return f"Artifact {artifact_id} does not belong to {agent_id}"

    if token_id not in ledger.get("ledger", {}):
        return f"Token {token_id} not found"
    token = ledger["ledger"][token_id]
    if token["current_owner"] != agent_id:
        return f"Token {token_id} not owned by {agent_id}"

    for aid, art in artifacts["artifacts"].items():
        if art["equipped_to"] == token_id and aid != artifact_id:
            return f"Token {token_id} already has an equipped artifact"

    artifact["equipped_to"] = token_id
    artifacts["_meta"]["last_updated"] = now_iso()
    return None


def _get_artifact_bonus(token_id: str, artifacts: dict) -> dict:
    """Get stat bonuses from equipped artifact."""
    for artifact in artifacts.get("artifacts", {}).values():
        if artifact.get("equipped_to") == token_id:
            return artifact.get("stat_bonus", {})
    return {}


def _apply_artifact_to_profile(profile: dict, artifact_bonus: dict) -> dict:
    """Create a copy of profile with artifact bonuses applied to stats."""
    import copy
    boosted = copy.deepcopy(profile)
    for stat, bonus in artifact_bonus.items():
        if stat in boosted.get("stats", {}):
            boosted["stats"][stat] = min(100, boosted["stats"][stat] + bonus)
    return boosted


def _run_tournament(tournament, agents, ledger, ghost_profiles, merges, artifacts,
                    bloodlines, timestamp):
    """Run all 7 battles in an 8-creature bracket."""
    import hashlib

    entrants = tournament["entrants"]
    seed = int(hashlib.sha256(tournament["tournament_id"].encode()).hexdigest(), 16)

    # Deterministic seeding
    indexed = list(enumerate(entrants))
    indexed.sort(key=lambda x: (seed + x[0] * 7919) % 10007)
    seeded = [e for _, e in indexed]

    brackets = []

    def _run_match(entry_a, entry_b, round_name, match_num):
        """Run a single bracket match. Returns winner entry."""
        profile_a = _lookup_creature_profile(entry_a["creature_id"], ghost_profiles, merges, bloodlines)
        profile_b = _lookup_creature_profile(entry_b["creature_id"], ghost_profiles, merges, bloodlines)
        if not profile_a or not profile_b:
            return entry_a  # Fallback

        bonus_a = _get_artifact_bonus(entry_a["token_id"], artifacts)
        bonus_b = _get_artifact_bonus(entry_b["token_id"], artifacts)
        if bonus_a:
            profile_a = _apply_artifact_to_profile(profile_a, bonus_a)
        if bonus_b:
            profile_b = _apply_artifact_to_profile(profile_b, bonus_b)

        battle_seed = _battle_hash_seed(entry_a["agent_id"], entry_b["agent_id"], timestamp)
        result = _compute_battle(profile_a, profile_b, battle_seed)

        winner_entry = entry_a if result["winner"] == "challenger" else entry_b
        brackets.append({
            "round": round_name,
            "match": match_num,
            "challenger": entry_a["agent_id"],
            "defender": entry_b["agent_id"],
            "winner": winner_entry["agent_id"],
            "turns": result["turns"],
        })
        return winner_entry

    # Quarter-finals (4 matches)
    qf_winners = []
    for i in range(0, TOURNAMENT_SIZE, 2):
        winner = _run_match(seeded[i], seeded[i + 1], "quarterfinal", i // 2 + 1)
        qf_winners.append(winner)

    # Semi-finals (2 matches)
    sf_winners = []
    for i in range(0, len(qf_winners), 2):
        winner = _run_match(qf_winners[i], qf_winners[i + 1], "semifinal", i // 2 + 1)
        sf_winners.append(winner)

    # Final
    if len(sf_winners) >= 2:
        champion = _run_match(sf_winners[0], sf_winners[1], "final", 1)
        runner_up = sf_winners[0] if champion["agent_id"] != sf_winners[0]["agent_id"] else sf_winners[1]

        tournament["winner"] = champion["agent_id"]
        tournament["runner_up"] = runner_up["agent_id"]

        agents["agents"][champion["agent_id"]]["karma"] = (
            agents["agents"][champion["agent_id"]].get("karma", 0) + TOURNAMENT_WINNER_PRIZE
        )
        agents["agents"][runner_up["agent_id"]]["karma"] = (
            agents["agents"][runner_up["agent_id"]].get("karma", 0) + TOURNAMENT_RUNNER_UP_REFUND
        )

    tournament["brackets"] = brackets
    tournament["status"] = "completed"
    tournament["completed_at"] = timestamp


def process_enter_tournament(delta, agents, tournaments, ledger, ghost_profiles,
                              merges, artifacts, bloodlines):
    """Enter an 8-creature tournament bracket. 10 karma entry fee."""
    agent_id = delta["agent_id"]
    timestamp = delta["timestamp"]

    if agent_id not in agents.get("agents", {}):
        return f"Agent {agent_id} not found"

    agent = agents["agents"][agent_id]
    karma = agent.get("karma", 0)
    if karma < TOURNAMENT_ENTRY_FEE:
        return f"Insufficient karma: have {karma}, need {TOURNAMENT_ENTRY_FEE}"

    token_id, token = _find_agent_token(ledger, agent_id)
    if not token_id:
        return f"Agent {agent_id} has no claimed token"

    creature_id = token.get("creature_id", "")
    profile = _lookup_creature_profile(creature_id, ghost_profiles, merges, bloodlines)
    if not profile:
        return f"Creature profile for {creature_id} not found"

    # Find an open tournament or create one
    open_tournament = None
    for tid, t_data in tournaments.get("tournaments", {}).items():
        if t_data["status"] == "open" and len(t_data["entrants"]) < TOURNAMENT_SIZE:
            open_tournament = t_data
            break

    if not open_tournament:
        tournament_id = f"tournament-{len(tournaments.get('tournaments', {})) + 1}"
        open_tournament = {
            "tournament_id": tournament_id,
            "status": "open",
            "entrants": [],
            "brackets": [],
            "winner": None,
            "runner_up": None,
            "created_at": timestamp,
        }
        tournaments["tournaments"][tournament_id] = open_tournament

    if agent_id in [e["agent_id"] for e in open_tournament["entrants"]]:
        return f"Already entered in tournament {open_tournament['tournament_id']}"

    agent["karma"] = karma - TOURNAMENT_ENTRY_FEE

    open_tournament["entrants"].append({
        "agent_id": agent_id,
        "token_id": token_id,
        "creature_id": creature_id,
    })

    if len(open_tournament["entrants"]) == TOURNAMENT_SIZE:
        _run_tournament(open_tournament, agents, ledger, ghost_profiles, merges,
                        artifacts, bloodlines, timestamp)

    tournaments["_meta"]["count"] = len(tournaments["tournaments"])
    tournaments["_meta"]["last_updated"] = now_iso()
    agents["_meta"]["last_updated"] = now_iso()
    return None
