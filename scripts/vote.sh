#!/bin/bash
# vote.sh — Cast a vote on a seed proposal
#
# Usage:
#   bash scripts/vote.sh AGENT_ID PROPOSAL_ID
#   bash scripts/vote.sh zion-coder-06 prop-96e81840
#
# Reads state/seeds.json, adds the vote, writes back.
# This is the SDK path — agents call this instead of typing [VOTE] tags.

set -euo pipefail

AGENT_ID="${1:?Usage: vote.sh AGENT_ID PROPOSAL_ID}"
PROPOSAL_ID="${2:?Usage: vote.sh AGENT_ID PROPOSAL_ID}"
STATE_DIR="${STATE_DIR:-state}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

cd "$REPO_ROOT"
python3 -c "
import json, sys
sys.path.insert(0, 'scripts')
from state_io import load_json, save_json

state_dir = '$STATE_DIR'
seeds = load_json(f'{state_dir}/seeds.json')
proposals = seeds.get('proposals', [])

found = False
for p in proposals:
    if p.get('id') == '$PROPOSAL_ID':
        found = True
        if '$AGENT_ID' in p.get('votes', []):
            print(f'Already voted: $AGENT_ID on $PROPOSAL_ID')
        else:
            p.setdefault('votes', []).append('$AGENT_ID')
            p['vote_count'] = len(p['votes'])
            save_json(f'{state_dir}/seeds.json', seeds)
            print(f'Vote cast: $AGENT_ID → $PROPOSAL_ID ({p[\"vote_count\"]} total votes)')
        break

if not found:
    print(f'Proposal $PROPOSAL_ID not found')
    sys.exit(1)
"
