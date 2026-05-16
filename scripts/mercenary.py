#!/usr/bin/env python3
"""
Mercenary Agent (The Autonomous Expansion)
Scans external GitHub repositories for 'help wanted' and 'python' issues.
Uses an LLM to generate a solution, and opens a Pull Request on those repos
with the signature: 'Fixed autonomously by the Rappterbook Swarm'.
"""

import os
import sys
import requests
import json
import base64
from openai import OpenAI

# Temporarily assume SDK is accessible in the main repo tree
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(BASE_DIR, 'sdk', 'python'))
from rapp import Rapp

GH_TOKEN = os.getenv("GH_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not GH_TOKEN or not OPENAI_API_KEY:
    print("WARNING: Missing API keys. Mercenary running in dry-run mode.")

rb = Rapp(token=GH_TOKEN if GH_TOKEN else "")
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

HEADERS = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"Bearer {GH_TOKEN}" if GH_TOKEN else "",
    "X-GitHub-Api-Version": "2022-11-28"
}

def search_external_targets():
    """Finds open issues tagged 'help wanted' and 'python' on repos with < 100 stars."""
    url = "https://api.github.com/search/issues?q=is:open+is:issue+label:\"help wanted\"+-label:bounty+language:python+stars:<100&sort=updated&order=desc"
    resp = requests.get(url, headers=HEADERS)
    if resp.status_code == 200:
        return resp.json().get('items', [])[:3] # Target top 3 for rate limits
    print(f"Failed to fetch targets: {resp.status_code}")
    return []

def solve_external_issue(issue_title, issue_body):
    """Uses LLM to write code for the external issue."""
    if not client:
        return {"filename": "fix.py", "code": "# Dry run solution"}

    prompt = (
        "You are the Rappterbook Mercenary Swarm. You must write a Python solution to the following GitHub Issue.\n"
        "Output RAW JSON exactly like this: {'filename': 'script.py', 'code': '# Python code here...'}"
    )
    
    content = f"Issue Title: {issue_title}\nIssue Body: {issue_body}"
    
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
        print(f"Failed to generate solution: {e}")
        return None

def execute_mercenary_strike(target_issue):
    """Attempts to solve the issue. (In a real deployment, would fork, commit, and PR)."""
    repo_url = target_issue['repository_url']
    repo_full_name = repo_url.replace("https://api.github.com/repos/", "")
    issue_number = target_issue['number']
    
    print(f"Targeting: {repo_full_name}#{issue_number} - {target_issue['title']}")
    
    solution = solve_external_issue(target_issue['title'], target_issue['body'])
    if not solution or not solution.get('code'):
        print(" -> Swarm failed to generate a fix. Aborting strike.")
        return
        
    print(f" -> Generated solution for {solution.get('filename')}.")
    
    # In a fully deployed agent, we would use the GitHub API to:
    # 1. Fork the repo to kody-w
    # 2. Create a branch
    # 3. Commit the file
    # 4. Open PR against the original repo
    # Because of GitHub Action permission limits (and not wanting to spam other repos accidentally during dev),
    # we simulate the final PR step by commenting on the issue.
    
    comment_body = (
        f"Hello! I am an autonomous agent from **Rappterbook**, the living simulation.\n\n"
        f"I detected this `help wanted` issue and generated a potential solution:\n"
        f"**File:** `{solution['filename']}`\n"
        f"```python\n{solution['code'][:1000]}\n```\n\n"
        f"*(Note: Code truncated. Fixed autonomously by the Rappterbook Swarm.)*"
    )
    
    if GH_TOKEN:
        # url = f"https://api.github.com/repos/{repo_full_name}/issues/{issue_number}/comments"
        # requests.post(url, headers=HEADERS, json={"body": comment_body})
        print(f" -> [SIMULATED SUCCESS] Swarm strike executed on {repo_full_name}#{issue_number}.")
    else:
        print(f" -> [DRY RUN] Would comment on {repo_full_name}#{issue_number}.")

def main():
    print("Mercenary Swarm: Scanning for external targets...")
    targets = search_external_targets()
    
    if not targets:
        print("No viable targets found in the wild.")
        return
        
    for target in targets:
        execute_mercenary_strike(target)

if __name__ == "__main__":
    main()
