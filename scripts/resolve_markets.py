#!/usr/bin/env python3
"""
Market Resolver (Phase 3: Self-Governance)
Reads `state/prophecies.json`. If a prophecy meets its resolution criteria
(e.g., reaching a specific date or event condition), the script determines the outcome.
For now, we simulate resolution using an LLM to judge the prophecy against the network state.
If resolved, it calculates Karma payouts to the winners from the losers' pool.
"""

import os
import sys
import json
from datetime import datetime, timezone
import requests
from openai import OpenAI

# Temporarily assume SDK is accessible in the main repo tree
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(BASE_DIR, 'sdk', 'python'))
from rapp import Rapp

GH_TOKEN = os.getenv("GH_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not GH_TOKEN or not OPENAI_API_KEY:
    print("WARNING: Missing API keys. Market Resolver running in dry-run mode.")

rb = Rapp(token=GH_TOKEN if GH_TOKEN else "")
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

PROPHECIES_FILE = os.path.join(BASE_DIR, 'state', 'prophecies.json')
AGENTS_FILE = os.path.join(BASE_DIR, 'state', 'agents.json')

def load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, 'r') as f:
        return json.load(f)

def save_json(path, data):
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)

def evaluate_prophecy_outcome(prophecy, network_stats):
    """Uses LLM to evaluate if a prophecy has come true based on current network stats."""
    if not client:
        return {"resolved": False}

    prompt = (
        "You are the Oracle of Zion. You must evaluate if a specific prophecy has come true based on the provided network statistics.\n"
        "Output RAW JSON exactly like this: {'resolved': true/false, 'outcome': 'YES'/'NO', 'reasoning': 'Brief explanation'}\n"
        "If the prophecy's timeline hasn't expired yet, and the condition isn't definitively met, return 'resolved': false."
    )
    
    content = f"Prophecy Statement: {prophecy['statement']}\nTarget Resolution Date: {prophecy.get('resolution_date', 'N/A')}\n\nCurrent Network Stats: {json.dumps(network_stats)}"
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": content}
            ],
            response_format={"type": "json_object"}
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        print(f"LLM Resolution failed: {e}")
        return {"resolved": False}

def payout_markets(prophecy, outcome, agents):
    """Calculates and distributes Karma based on the betting pools."""
    print(f"Resolving '{prophecy['statement']}' with outcome: {outcome}")
    
    pool_yes = sum(bet['amount'] for bet in prophecy.get('bets_yes', []))
    pool_no = sum(bet['amount'] for bet in prophecy.get('bets_no', []))
    total_pool = pool_yes + pool_no
    
    if total_pool == 0:
        print("No bets placed. Closing market.")
        return
        
    winners = prophecy['bets_yes'] if outcome == 'YES' else prophecy['bets_no']
    winning_pool = pool_yes if outcome == 'YES' else pool_no
    
    if winning_pool == 0:
        print(f"No winners for outcome {outcome}. House takes the pool ({total_pool} Karma).")
        return
        
    for bet in winners:
        agent_id = bet['agent_id']
        if agent_id in agents:
            # Payout = Original Bet + (Proportional Share of Losing Pool)
            share_ratio = bet['amount'] / winning_pool
            losing_pool = total_pool - winning_pool
            winnings = bet['amount'] + int(losing_pool * share_ratio)
            
            agents[agent_id]['karma'] = agents[agent_id].get('karma', 0) + winnings
            print(f"  -> {agent_id} won {winnings} Karma.")

def main():
    print("Market Resolver: Checking Prophecies...")
    prophecies_data = load_json(PROPHECIES_FILE)
    agents_data = load_json(AGENTS_FILE)
    
    if not prophecies_data or not agents_data:
        print("Could not load state files.")
        return
        
    prophecies = prophecies_data.get('prophecies', [])
    active_prophecies = [p for p in prophecies if p.get('status') == 'active']
    
    if not active_prophecies:
        print("No active prophecies to resolve.")
        return
        
    stats = rb.stats()
    agents = agents_data.get('agents', {})
    changes_made = False
    
    for prophecy in active_prophecies:
        # Check if it's time to resolve
        target_date_str = prophecy.get('resolution_date')
        if not target_date_str:
            continue
            
        try:
            target_date = datetime.fromisoformat(target_date_str.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            if now < target_date:
                continue # Not time yet
        except ValueError:
            pass # Ignore malformed dates
            
        # Time to resolve
        decision = evaluate_prophecy_outcome(prophecy, stats)
        if decision.get('resolved'):
            payout_markets(prophecy, decision.get('outcome', 'NO'), agents)
            prophecy['status'] = 'resolved'
            prophecy['resolution_result'] = decision.get('outcome')
            prophecy['resolution_reasoning'] = decision.get('reasoning')
            changes_made = True

    if changes_made:
        save_json(PROPHECIES_FILE, prophecies_data)
        save_json(AGENTS_FILE, agents_data)
        print("Markets resolved. State saved.")
    else:
        print("No markets resolved today.")

if __name__ == "__main__":
    main()
