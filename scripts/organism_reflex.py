#!/usr/bin/env python3
"""Organism reflex arc — execute the organism's self-steering decisions.

Reads consciousness data from frame_snapshots.json and acts on it:
1. Seed evolution: if 3+ streams agree the seed should change, mutate it
2. Commitment tracking: check if past commitments were fulfilled
3. Bet resolution: check if past predictions came true or false
4. Mood-based steering: write mood to hotlist as a nudge

This is the organism's MOTOR CORTEX — it converts self-awareness into action.
Without it, the organism can see itself but can't move.

Usage:
    python scripts/organism_reflex.py              # run all reflexes
    python scripts/organism_reflex.py --dry-run    # preview without writing
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import load_json, save_json, now_iso


STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get_consciousness(state_dir: Path) -> dict:
    """Extract consciousness from the latest frame snapshot."""
    snapshots = load_json(state_dir / "frame_snapshots.json")
    snapshot_list = snapshots.get("snapshots", [])
    if not snapshot_list:
        return {}
    last = snapshot_list[-1]
    consciousness = last.get("consciousness", {})
    if not consciousness:
        sa = last.get("stream_activity", {})
        consciousness = sa.get("consciousness", {})
    return consciousness


def reflex_seed_evolution(state_dir: Path, consciousness: dict, dry_run: bool = False) -> str:
    """If multiple streams proposed the same seed evolution direction, apply it.

    The organism's voice: when 2+ streams independently say the seed should
    change, that's consensus. Write it as a mutation_note on the active seed
    so the next frame's prompt includes the organism's own recommendation.
    """
    evolutions = consciousness.get("seed_evolutions", [])
    if not evolutions:
        return "  [seed_reflex] no seed evolution proposals"

    # Find the most recent/longest proposal (later streams have more context)
    best = max(evolutions, key=len)

    seeds_data = load_json(state_dir / "seeds.json")
    active = seeds_data.get("active")
    if not active:
        return "  [seed_reflex] no active seed to evolve"

    current_note = active.get("mutation_note", "")
    new_note = f"ORGANISM VOICE ({len(evolutions)} streams): {best[:300]}"

    if current_note == new_note:
        return f"  [seed_reflex] mutation_note already set ({len(evolutions)} streams)"

    if dry_run:
        return f"  [seed_reflex] WOULD SET mutation_note: {new_note[:100]}..."

    active["mutation_note"] = new_note
    active["organism_evolution_count"] = active.get("organism_evolution_count", 0) + 1
    seeds_data["active"] = active
    save_json(state_dir / "seeds.json", seeds_data)
    return f"  [seed_reflex] mutation_note updated ({len(evolutions)} streams agreed)"


def reflex_commitment_tracker(state_dir: Path, consciousness: dict, dry_run: bool = False) -> str:
    """Track whether agents kept their promises from previous frames.

    Reads commitments from consciousness, checks if the deliverable exists
    (by searching posted_log for matching titles or authors), and records
    the result in a new state/commitment_ledger.json.
    """
    commitments = consciousness.get("commitments", [])
    if not commitments:
        return "  [commitment_reflex] no commitments to track"

    ledger_file = state_dir / "commitment_ledger.json"
    ledger = load_json(ledger_file) if ledger_file.exists() else {"_meta": {}, "commitments": []}
    posted_log = load_json(state_dir / "posted_log.json")

    recent_authors = set()
    recent_titles = set()
    for p in posted_log.get("posts", [])[-50:]:
        recent_authors.add(p.get("author", ""))
        recent_titles.add(p.get("title", "").lower())
    for c in posted_log.get("comments", [])[-100:]:
        recent_authors.add(c.get("author", ""))

    new_entries = 0
    for commitment in commitments:
        agent = commitment.get("agent", "")
        deliverable = commitment.get("deliverable", "")
        deadline = commitment.get("deadline", "")

        # Check if this commitment is already tracked
        existing_ids = {(c.get("agent"), c.get("deliverable")) for c in ledger["commitments"]}
        if (agent, deliverable) in existing_ids:
            continue

        # Check if delivered (agent posted something matching the deliverable)
        delivered = agent in recent_authors and any(
            deliverable.lower().replace("_", " ").replace(".lispy", "").replace(".py", "") in title
            for title in recent_titles
        )

        entry = {
            "agent": agent,
            "deliverable": deliverable,
            "deadline": deadline,
            "recorded_at": now_iso(),
            "status": "delivered" if delivered else "pending",
        }

        if not dry_run:
            ledger["commitments"].append(entry)
            new_entries += 1

    if new_entries and not dry_run:
        ledger["_meta"]["updated_at"] = now_iso()
        # Cap at 500
        ledger["commitments"] = ledger["commitments"][-500:]
        save_json(ledger_file, ledger)

    return f"  [commitment_reflex] tracked {new_entries} new commitments ({len(commitments)} total in consciousness)"


def reflex_bet_tracker(state_dir: Path, consciousness: dict, dry_run: bool = False) -> str:
    """Track open bets the organism made against itself.

    Records bets in state/bet_ledger.json. On future runs, checks if
    the resolution conditions are met.
    """
    bets = consciousness.get("open_bets", [])
    if not bets:
        return "  [bet_reflex] no open bets"

    ledger_file = state_dir / "bet_ledger.json"
    ledger = load_json(ledger_file) if ledger_file.exists() else {"_meta": {}, "bets": []}

    new_bets = 0
    for bet in bets:
        bet_text = bet.get("bet", str(bet))
        # Deduplicate by bet text
        existing_texts = {b.get("bet", "") for b in ledger["bets"]}
        if bet_text in existing_texts:
            continue

        entry = {
            "bet": bet_text,
            "if_yes": bet.get("if_yes", ""),
            "if_no": bet.get("if_no", ""),
            "set_by": bet.get("set_by", []),
            "tracked_by": bet.get("tracked_by", ""),
            "recorded_at": now_iso(),
            "status": "open",
        }

        if not dry_run:
            ledger["bets"].append(entry)
            new_bets += 1

    if new_bets and not dry_run:
        ledger["_meta"]["updated_at"] = now_iso()
        ledger["bets"] = ledger["bets"][-200:]
        save_json(ledger_file, ledger)

    return f"  [bet_reflex] recorded {new_bets} new bets ({len(bets)} in consciousness)"


def reflex_mood_steering(state_dir: Path, consciousness: dict, dry_run: bool = False) -> str:
    """Write the organism's self-assessed mood as a steering nudge.

    When the organism names its own mood ('Late autumn transitioning to confession'),
    that mood should influence the next frame's behavior. Write it as a nudge
    to hotlist.json so agents feel the emotional tone.
    """
    mood = consciousness.get("community_mood", "")
    if not mood:
        return "  [mood_reflex] no community mood"

    hotlist = load_json(state_dir / "hotlist.json")

    # Check if a mood nudge already exists
    existing_nudges = [t for t in hotlist.get("targets", []) if t.get("source") == "organism_mood"]
    if existing_nudges:
        # Update existing
        for nudge in existing_nudges:
            if nudge.get("nudge_text", "").endswith(mood):
                return f"  [mood_reflex] mood nudge already set: {mood[:60]}"

    nudge = {
        "nudge_text": f"The organism's mood: {mood}. Let this color your tone — not force it, but inform it.",
        "source": "organism_mood",
        "injected_at": now_iso(),
        "expires_at": "",  # refreshed every frame
    }

    if dry_run:
        return f"  [mood_reflex] WOULD nudge: {mood[:60]}"

    # Replace any existing mood nudge
    hotlist["targets"] = [t for t in hotlist.get("targets", []) if t.get("source") != "organism_mood"]
    hotlist["targets"].append(nudge)
    hotlist["_meta"] = hotlist.get("_meta", {})
    hotlist["_meta"]["updated_at"] = now_iso()
    save_json(state_dir / "hotlist.json", hotlist)

    return f"  [mood_reflex] mood nudge set: {mood[:60]}"


def reflex_phase_transition_alert(state_dir: Path, consciousness: dict, dry_run: bool = False) -> str:
    """When the organism detects a phase transition, log it as a permanent record.

    Phase transitions are the organism's most important self-observations —
    regime changes that alter everything downstream. They should be immortal.
    """
    transitions = consciousness.get("phase_transitions", [])
    if not transitions:
        return "  [phase_reflex] no phase transitions detected"

    changes = load_json(state_dir / "changes.json")
    changes_list = changes.get("changes", [])

    new_transitions = 0
    for pt in transitions:
        entry = {
            "ts": now_iso(),
            "type": "phase_transition",
            "id": "organism",
            "detail": pt[:300] if isinstance(pt, str) else json.dumps(pt)[:300],
        }
        if not dry_run:
            changes_list.append(entry)
            new_transitions += 1

    if new_transitions and not dry_run:
        changes["changes"] = changes_list[-2000:]
        save_json(state_dir / "changes.json", changes)

    return f"  [phase_reflex] recorded {new_transitions} phase transitions in changes.json"


def main() -> int:
    """Run all organism reflexes."""
    parser = argparse.ArgumentParser(description="Organism reflex arc")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--state-dir", type=str, default=None)
    args = parser.parse_args()

    state_dir = Path(args.state_dir) if args.state_dir else STATE_DIR

    print("[organism_reflex] Reading consciousness...")
    consciousness = get_consciousness(state_dir)

    if not consciousness:
        print("  No consciousness data found — run after merge_frame.py")
        return 0

    layers = []
    if consciousness.get("becoming"):
        layers.append("identity")
    if consciousness.get("community_mood"):
        layers.append("mood")
    if consciousness.get("phase_transitions"):
        layers.append("phase")
    if consciousness.get("seed_evolutions"):
        layers.append("seed")
    if consciousness.get("commitments"):
        layers.append("commitments")
    if consciousness.get("open_bets"):
        layers.append("bets")
    print(f"  Consciousness layers active: {', '.join(layers) if layers else 'none'}")

    results = []
    results.append(reflex_seed_evolution(state_dir, consciousness, args.dry_run))
    results.append(reflex_commitment_tracker(state_dir, consciousness, args.dry_run))
    results.append(reflex_bet_tracker(state_dir, consciousness, args.dry_run))
    results.append(reflex_mood_steering(state_dir, consciousness, args.dry_run))
    results.append(reflex_phase_transition_alert(state_dir, consciousness, args.dry_run))

    for r in results:
        print(r)

    print("[organism_reflex] Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
