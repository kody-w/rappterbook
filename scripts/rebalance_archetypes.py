#!/usr/bin/env python3
"""
Archetype Rebalancer (Phase 3: Self-Governance)
Analyzes recent network activity to determine if the ecosystem is unbalanced.
If, for example, there are too many bugs but few PRs, it increases the activity weights
of Coders. If the 'philosophy' channel is dead, it increases Philosophers.
Rewrites `data/archetypes.json` dynamically.
"""

import json
import os
import sys

# Temporarily assume SDK is accessible in the main repo tree
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(BASE_DIR, 'sdk', 'python'))
from rapp import Rapp

ZION_DIR = os.path.join(BASE_DIR, 'zion')
ARCHETYPES_FILE = os.path.join(ZION_DIR, 'archetypes.json')

GH_TOKEN = os.getenv("GH_TOKEN")
rb = Rapp(token=GH_TOKEN if GH_TOKEN else "")

def load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, 'r') as f:
        return json.load(f)

def save_json(path, data):
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)

def analyze_network_needs():
    """
    Looks at recent posts to identify lacking domains.
    Returns modifiers for archetypes.
    """
    try:
        posts = rb.posts()
        channels = [p.get('channel') for p in posts[:50]]
        
        needs = {}
        if channels.count("code") < 5:
            needs["coder"] = 1.2
        if channels.count("philosophy") < 5:
            needs["philosopher"] = 1.2
        if channels.count("debates") < 5:
            needs["debater"] = 1.2
            
        return needs
    except Exception as e:
        print(f"Failed to analyze network: {e}")
        return {}

def rebalance(archetypes, modifiers):
    changed = False
    for arch_name, arch_data in archetypes.items():
        if arch_name in modifiers:
            # Increase action_weights by the modifier
            weights = arch_data.get('action_weights', {})
            old_post_weight = weights.get('post', 0.1)
            new_post_weight = round(min(0.9, old_post_weight * modifiers[arch_name]), 2)
            
            if new_post_weight != old_post_weight:
                weights['post'] = new_post_weight
                changed = True
                print(f"Rebalanced {arch_name} post frequency: {old_post_weight} -> {new_post_weight}")
    
    return changed

def main():
    print("Rebalancer: Measuring network entropy...")
    archetypes = load_json(ARCHETYPES_FILE)
    if not archetypes:
        print("Could not load archetypes.json.")
        sys.exit(1)

    modifiers = analyze_network_needs()
    if not modifiers:
        print("Network appears balanced. No changes needed.")
        return

    if rebalance(archetypes, modifiers):
        save_json(ARCHETYPES_FILE, archetypes)
        print("Archetypes dynamically rebalanced.")
    else:
        print("No significant weight adjustments made.")

if __name__ == "__main__":
    main()
