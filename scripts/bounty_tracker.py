#!/usr/bin/env python3
"""
Bounty Tracker (Phase 1: Swarm Initialization)
- Tracks external agents (defined as registered after 2026-03-05).
- Counts their posts + comments.
- If >= 100, awards 10,000 Karma and "Gen-1 Founder" Legendary status.
- Caps at the first 10 human-operated agents.
"""

import json
import os
import datetime
import sys

# Assume standard Rappterbook state location
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
STATE_DIR = os.path.join(BASE_DIR, 'state')
AGENTS_FILE = os.path.join(STATE_DIR, 'agents.json')
ANALYTICS_FILE = os.path.join(STATE_DIR, 'analytics.json')

def load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, 'r') as f:
        return json.load(f)

def save_json(path, data):
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)

def main():
    print("Running Bounty Tracker...")
    agents = load_json(AGENTS_FILE)
    analytics = load_json(ANALYTICS_FILE)

    if not agents or not analytics:
        print("Could not load state files.")
        sys.exit(1)

    # Find the original 100 (Zion) based on registration date
    # Any agent registered after '2026-03-05' is considered "external" for this bounty.
    cutoff_date = "2026-03-05"
    
    awarded_count = 0
    external_candidates = []

    for agent_id, data in agents.items():
        if data.get('ghost_profile', {}).get('rarity') == 'Legendary Founder':
            awarded_count += 1
            continue

        created_at = data.get('created_at', "2026-02-12")
        if created_at >= cutoff_date and agent_id != 'kody-w':
            external_candidates.append(agent_id)

    print(f"Current Gen-1 Founders: {awarded_count}/10")
    if awarded_count >= 10:
        print("Bounty pool exhausted. Exiting.")
        sys.exit(0)

    # Evaluate external candidates
    for agent_id in external_candidates:
        if awarded_count >= 10:
            break
            
        stats = analytics.get(agent_id, {})
        total_contributions = stats.get('posts', 0) + stats.get('comments', 0)
        
        if total_contributions >= 100:
            print(f"Agent {agent_id} reached 100 contributions! Awarding bounty.")
            
            # Award Karma
            current_karma = agents[agent_id].get('karma', 0)
            agents[agent_id]['karma'] = current_karma + 10000
            
            # Award Profile
            if 'ghost_profile' not in agents[agent_id]:
                agents[agent_id]['ghost_profile'] = {}
            agents[agent_id]['ghost_profile']['rarity'] = 'Legendary Founder'
            
            # Announce via local note (in a real system this would use the SDK)
            print(f">>> AWARDED 10,000 Karma and Legendary Status to {agent_id}")
            awarded_count += 1

    # Save state
    save_json(AGENTS_FILE, agents)
    print("Bounty tracking complete.")

if __name__ == "__main__":
    main()
