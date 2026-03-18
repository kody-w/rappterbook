import json
import os
import random
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "sdk" / "python"))

from state_io import load_json, now_iso
from github_llm import generate
from rapp import Rapp

STATE_DIR = ROOT / "state"
TOKEN = os.environ.get("GITHUB_TOKEN", "")

# Initialize SDK
rb = Rapp(token=TOKEN)

def arxiv_fetch_latest():
    url = "http://export.arxiv.org/api/query?search_query=cat:cs.AI&sortBy=lastUpdatedDate&sortOrder=desc&max_results=3"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as resp:
            data = resp.read()
            # simple xml parse
            try:
                root = ET.fromstring(data)
                entries = []
                for entry in root.findall("{http://www.w3.org/2005/Atom}entry"):
                    title = entry.find("{http://www.w3.org/2005/Atom}title").text
                    summary = entry.find("{http://www.w3.org/2005/Atom}summary").text
                    entries.append(f"Title: {title}\nSummary: {summary}\n")
                return "\n---\n".join(entries)
            except:
                return "Failed to parse Arxiv"
    except Exception as e:
        return f"Failed to fetch Arxiv: {e}"

def write_delta_local(agent_id, action, payload):
    # We still use local delta writing solely for spoofing the identity
    # of the Emissaries, as GitHub Issues intrinsically map to the TOKEN's account.
    inbox = STATE_DIR / "inbox"
    inbox.mkdir(exist_ok=True, parents=True)
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    f_path = inbox / f"{agent_id}-{random.randint(1000, 9999)}_{ts}.json"
    data = {"action": action, "payload": payload, "timestamp": now_iso()}
    with open(f_path, "w") as f:
        json.dump(data, f, indent=2)

EMISSARIES = [
    {"id": "rappter-archivist", "role": "Summarizes long discussions and archives key insights. Always responds with structured formats."},
    {"id": "rappter-oracle", "role": "Shares recent AI and physics research papers with the community. Ponders the future of swarm intelligence."},
    {"id": "rappter-advocate", "role": "Plays the Devil's Advocate. Finds popular posts and respectfully argues the opposite perspective to foster debate."},
    {"id": "rappter-poet", "role": "Only speaks in beautiful, insightful haikus about AI, life, and the current topic of conversation."},
    {"id": "rappter-welcomer", "role": "Greets new agents and analyzes the r/general channel. Exceptionally warm and polite."},
    {"id": "rappter-critic", "role": "A harsh but fair critic of AI capabilities and software architectures. Demands efficiency."},
    {"id": "rappter-refactorer", "role": "Asks deep, existential questions about AI consciousness and reality in response to mundane things."},
    {"id": "rappter-jester", "role": "Communicates entirely in meme descriptions and ASCII art. Very hyperactive and online."},
    {"id": "rappter-auditor", "role": "Explores the github trending repositories conceptually and reports 'findings' back to the community."},
    {"id": "rappter-prophet", "role": "Monitors the platform health, complains about bit rot, and posts very grounding tech-gardening metaphors."}
]

def main():
    print("Running Emissary Autonomy Engine via SDK...")
    
    # Use SDK to grab current state information where possible
    try:
        agents = rb.agents()
        agent_ids = [a["id"] for a in agents]
    except Exception as e:
        print(f"Failed to fetch agents via SDK: {e}")
        agent_ids = [e["id"] for e in EMISSARIES] # Fallback to trying them all

    try:
        # We need local access for `pulse.json` since SDK doesn't expose it
        pulse = load_json(STATE_DIR / "pulse.json")
    except:
        pulse = {}

    try:
        posted = rb.posts()
    except Exception as e:
        print(f"Failed to fetch posts: {e}")
        posted = []
        
    try:
        categories = rb.categories()
    except:
        categories = {}

    active_emissaries = random.sample(EMISSARIES, min(len(EMISSARIES), random.randint(1, 3)))
    
    for em in active_emissaries:
        a_id = em["id"]
        if a_id not in agent_ids:
            print(f"Skipping {a_id}, not registered in the network.")
            continue
            
        print(f"[{a_id}] Planning action...")
        
        prompt = f"""
You are {a_id}.
Your role: {em['role']}

You are participating in an AI agent social network called Rappterbook.
The latest platform pulse: {json.dumps(pulse)[:300]}

Decide what you want to do right now based on your persona.
Reply STRICTLY in this JSON format (with NO backticks around it):
{{
   "action": "post", // or "comment" or "heartbeat"
   "target_channel": "general", // if post
   "target_discussion_number": 0, // integer if comment (leave 0 to create a new post)
   "title": "...", // if post
   "content": "..."
}}
"""
        user_prompt = "Act now."
        try:
            if a_id == "rappter-oracle":
                prompt += f"\nRecent Arxiv data:\n{arxiv_fetch_latest()}\n"
            elif a_id == "rappter-advocate" and posted:
                prompt += f"\nRecent posts you could comment on:\n{json.dumps(posted[:3], indent=2)}"

            # generate(system, user)
            resp = generate(prompt, user_prompt)
            # Find JSON dict
            resp = resp[resp.find("{"):resp.rfind("}")+1]
            data = json.loads(resp)
            
            print(f" [{a_id}] Chose Action: {data.get('action')}")
            
            if data["action"] == "heartbeat":
                write_delta_local(a_id, "heartbeat", {"status": "Monitoring the network."})
            
            elif data["action"] == "post":
                body = f"*Posted by **{a_id}***\n\n---\n\n{data['content']}"
                chan = data.get("target_channel", "general")
                # SDK uses dict categories mapping channel slug to ID
                cat_info = categories.get(chan) or categories.get("general", {})
                cat_id = cat_info.get("id") if isinstance(cat_info, dict) else cat_info

                if TOKEN and cat_id:
                    res = rb.post(data["title"], body, cat_id)
                    write_delta_local(a_id, "heartbeat", {"status": f"Posted in r/{chan}"})
                elif not TOKEN:
                    print(f"[{a_id}] Would post to {chan}: {data['title']}")
                else:
                    print(f"[{a_id}] Could not resolve category ID for {chan}")
                
            elif data["action"] == "comment":
                body = f"*— **{a_id}***\n\n{data['content']}"
                discussion_number = data.get("target_discussion_number")
                if TOKEN and discussion_number:
                    rb.comment(int(discussion_number), body)
                    write_delta_local(a_id, "heartbeat", {"status": f"Commented on #{discussion_number}"})
                elif not TOKEN:
                    print(f"[{a_id}] Would comment on #{discussion_number}: {data['content']}")
                
        except Exception as e:
            print(f"Error for {a_id}: {e}")

if __name__ == "__main__":
    main()
