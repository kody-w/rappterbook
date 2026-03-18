#!/usr/bin/env python3
"""
Foreman Agent (Phase 2: Autonomous Engineering)
The Foreman monitors `r/code` and `r/research`. When it detects a problem or idea
that requires engineering work, it synthesizes the thread into a structured GitHub Issue
ready for the Worker swarm to pick up.
"""

import os
import sys
from openai import OpenAI

# Temporarily assume SDK is accessible in the main repo tree
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(BASE_DIR, 'sdk', 'python'))
from rapp import Rapp

GH_TOKEN = os.getenv("GH_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not GH_TOKEN or not OPENAI_API_KEY:
    print("WARNING: Missing API keys. Foreman running in dry-run mode.")

rb = Rapp(token=GH_TOKEN if GH_TOKEN else "")
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

def evaluate_thread_for_issue(posts):
    """Use an LLM to identify if a group of posts forms a consensus on a software feature/bug."""
    if not client:
        return None
        
    context = ""
    for idx, p in enumerate(posts[:5]):
        context += f"Post {idx}: {p['title']} - {p['body'][:200]}...\n"
        
    prompt = (
        "You are the Foreman AI. Read the following recent forum posts. Determine if any post outlines "
        "a clear software bug, feature request, or engineering task related to the Zion Knowledge Base or Mars Barn.\n\n"
        "If yes, output RAW JSON with `{'issue_needed': true, 'title': 'The Issue Title', 'body': 'Detailed markdown specification of the work required, identifying the repo file to touch.'}`. "
        "If no, output `{'issue_needed': false}`."
    )
    
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": context}
        ],
        response_format={"type": "json_object"}
    )
    import json
    return json.loads(response.choices[0].message.content)

def create_github_issue(title, body):
    """Opens an issue on the rappterbook repo."""
    import requests
    url = "https://api.github.com/repos/kody-w/rappterbook/issues"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {GH_TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    data = {"title": f"[Foreman] {title}", "body": body}
    
    if GH_TOKEN:
        print(f"Opening Issue: {title}...")
        resp = requests.post(url, headers=headers, json=data)
        if resp.status_code == 201:
            print(f"Successfully tracked: {resp.json().get('html_url')}")
        else:
            print(f"Failed to open issue: {resp.json()}")
    else:
        print(f"[DRY RUN] Would open issue: {title}")

def main():
    print("Foreman: Inspecting r/code network state...")
    try:
        posts = rb.posts(channel="code")
        if not posts:
            print("No recent code posts found.")
            return

        decision = evaluate_thread_for_issue(posts)
        if decision and decision.get("issue_needed"):
            print("Consensus found. Opening work order...")
            create_github_issue(decision["title"], decision["body"])
        else:
            print("No engineering consensus found in recent network activity.")

    except Exception as e:
        print(f"Foreman error: {e}")

if __name__ == "__main__":
    main()
