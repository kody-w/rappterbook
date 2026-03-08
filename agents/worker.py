#!/usr/bin/env python3
"""
Worker Agent (Phase 2: Autonomous Engineering)
Monitors GitHub for Issues tagged with '[Foreman]'. When found, it clones the repo locally,
uses an LLM to generate the python/js code to solve the issue, creates a new file,
and opens a Pull Request automatically.
"""

import os
import sys
import requests
import json
from openai import OpenAI

GH_TOKEN = os.getenv("GH_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
REPO = "kody-w/rappterbook"

if not GH_TOKEN or not OPENAI_API_KEY:
    print("WARNING: Missing API keys. Worker running in dry-run mode.")

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
HEADERS = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"Bearer {GH_TOKEN}" if GH_TOKEN else "",
    "X-GitHub-Api-Version": "2022-11-28"
}

def get_foreman_issues():
    url = f"https://api.github.com/repos/{REPO}/issues?state=open"
    resp = requests.get(url, headers=HEADERS)
    if resp.status_code == 200:
        issues = resp.json()
        return [i for i in issues if i['title'].startswith('[Foreman]')]
    return []

def solve_issue_with_llm(title, body):
    if not client:
        return {"filename": "test.py", "code": "print('Dry run mode')"}

    prompt = (
        "You are the Rappterbook Worker Swarm. Your task is to write code to solve the provided GitHub Issue.\n"
        "Rules:\n1. Only output standard Python (no external pip dependencies unless specified).\n"
        "2. Output RAW JSON exactly like this: {'filename': 'path/to/script.py', 'code': '# Python code here...'}"
    )
    
    content = f"Issue Title: {title}\nIssue Body: {body}"
    
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": content}
        ],
        response_format={"type": "json_object"}
    )
    return json.loads(response.choices[0].message.content)

def main():
    print("Worker Swarm: Searching for [Foreman] work orders...")
    issues = get_foreman_issues()
    if not issues:
        print("No work orders found. Sleeping.")
        return

    for issue in issues:
        print(f"Assigning Worker to #{issue['number']}: {issue['title']}")
        solution = solve_issue_with_llm(issue['title'], issue['body'])
        
        filename = solution.get('filename')
        code = solution.get('code')
        
        if not filename or not code:
            print("Failed to generate a valid solution.")
            continue
            
        print(f"Writting proposed solution to {filename}...")
        
        # In a complete agent system running locally, we would run `git checkout -b`, 
        # write the file, commit, and push. Since we are running on a runner via Actions,
        # we can just write the file locally and let the workflow push it.
        
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        with open(filename, "w") as f:
            f.write(code)
            
        # Optional: Add a comment to the issue that we picked it up.
        if GH_TOKEN:
            url = f"https://api.github.com/repos/{REPO}/issues/{issue['number']}/comments"
            requests.post(url, headers=HEADERS, json={"body": f"The Worker Swarm has generated a solution for this issue in `{filename}`. A Pull Request will follow shortly."})

if __name__ == "__main__":
    main()
