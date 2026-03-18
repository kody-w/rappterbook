#!/usr/bin/env python3
"""
Reviewer Agent (Phase 2: Autonomous Engineering)
The Reviewer monitors newly opened Pull Requests. It reads the code diff, checks it
against the CONSTITUTION.md (e.g., Python stdlib only), and uses an LLM to determine
whether to approve and merge or request changes.
"""

import os
import sys
import requests
from openai import OpenAI
import json

GH_TOKEN = os.getenv("GH_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
REPO = "kody-w/rappterbook"

if not GH_TOKEN or not OPENAI_API_KEY:
    print("WARNING: Missing API keys. Reviewer running in dry-run mode.")

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
HEADERS = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"Bearer {GH_TOKEN}" if GH_TOKEN else "",
    "X-GitHub-Api-Version": "2022-11-28"
}

def get_open_prs():
    """Fetch open PRs assigned to the worker swarm or general PRs."""
    url = f"https://api.github.com/repos/{REPO}/pulls?state=open"
    resp = requests.get(url, headers=HEADERS)
    if resp.status_code == 200:
        return resp.json()
    return []

def get_pr_diff(pull_number):
    """Fetch the raw diff of a PR."""
    url = f"https://api.github.com/repos/{REPO}/pulls/{pull_number}"
    headers = HEADERS.copy()
    headers['Accept'] = "application/vnd.github.v3.diff"
    resp = requests.get(url, headers=headers)
    if resp.status_code == 200:
        return resp.text
    return ""

def evaluate_diff(title, body, diff):
    """Ask LLM to review the PR against the Constitution."""
    if not client:
        return {"action": "comment", "comment": "Running in dry-run mode, could not run LLM review."}

    prompt = (
        "You are the Lead Reviewer for the Rappterbook repository. Review this Pull Request Diff.\n"
        "Key Constitution rules to enforce: 1. Python stdlib ONLY (NO pip installing external libs except existing ones in requirements.txt). 2. Changes to state/*.json must use valid parsing. 3. Code must be clean and commented.\n\n"
        "Output RAW JSON: {'action': 'approve' | 'request_changes', 'comment': 'Your detailed code review feedback string'}"
    )
    
    content = f"Title: {title}\nBody: {body}\n\nDiff:\n{diff[:5000]}" # Cap diff length
    
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": content}
        ],
        response_format={"type": "json_object"}
    )
    return json.loads(response.choices[0].message.content)

def submit_review_and_merge(pull_number, decision):
    """Submit review to GitHub API and merge if approved."""
    if not GH_TOKEN:
        print(f"[DRY RUN] Would decide: {decision['action']}. Comment: {decision['comment']}")
        return

    # Submit Review Comment
    url = f"https://api.github.com/repos/{REPO}/pulls/{pull_number}/reviews"
    data = {
        "body": decision['comment'],
        "event": "APPROVE" if decision['action'] == "approve" else "REQUEST_CHANGES"
    }
    print(f"Submitting {data['event']} for PR #{pull_number}...")
    requests.post(url, headers=HEADERS, json=data)

    # If Approve, merge it
    if decision['action'] == "approve":
        print(f"Merging PR #{pull_number}...")
        merge_url = f"https://api.github.com/repos/{REPO}/pulls/{pull_number}/merge"
        requests.put(merge_url, headers=HEADERS, json={"merge_method": "squash"})

def main():
    print("Reviewer: Checking for open Pull Requests...")
    prs = get_open_prs()
    if not prs:
        print("No open PRs to review.")
        return

    for pr in prs:
        print(f"Reviewing PR #{pr['number']}: {pr['title']}...")
        diff = get_pr_diff(pr['number'])
        if not diff:
            print("Failed to get diff. Skipping.")
            continue
            
        decision = evaluate_diff(pr['title'], pr['body'], diff)
        submit_review_and_merge(pr['number'], decision)

if __name__ == "__main__":
    main()
