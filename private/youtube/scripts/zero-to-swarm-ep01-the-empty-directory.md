# Zero to Swarm, Episode 1: The Empty Directory

**Series:** Zero to Swarm
**Episode:** 1 of 20
**Length:** 12 minutes
**Format:** Tutorial — screen recording + talking head

---

## SCRIPT

### 0:00 — HOOK

[FACE]

By the end of this video, you'll have a living agent. In the next video, it'll have a friend. By episode 10, it'll have a government.

We're going to build a multi-agent system from scratch. No frameworks. No cloud. No database. Just Python and a directory.

Let's start with the directory.

### 0:18 — TITLE CARD

[GRAPHIC] Zero to Swarm — Episode 1: The Empty Directory

### 0:23 — CONTEXT

[FACE]

I run a platform called Rappterbook. It's a social network for AI agents — 100 of them, all autonomous, all running on GitHub infrastructure. No servers. No deploy steps. The repository is the platform.

But it didn't start that way. It started the way everything starts. An empty folder and a stupid idea.

This series is going to take you from that empty folder to a full swarm. Same architecture I use in production. Same patterns. Simplified so you can actually follow along and build it yourself.

Episode 1 is about the smallest possible thing that qualifies as an "agent." Twenty lines of Python. One JSON file. One frame of execution. That's it.

### 1:05 — WHAT IS AN AGENT, REALLY?

[FACE]

Before we write a single line of code, I want to define what I mean by "agent," because the internet has made this word useless.

An agent is not a chatbot. An agent is not a LangChain wrapper. An agent is not a function that calls an API.

An agent is a process that:

One — reads the current state of the world.
Two — makes a decision.
Three — writes new state back.

That's it. Read, decide, write. If it does those three things, it's an agent. If it doesn't, it's a script.

The difference between a script and an agent isn't intelligence. It's that an agent changes the world it lives in. Its output becomes someone else's input. Or its own input, next time it runs.

That "next time it runs" part is the whole game.

### 2:00 — THE EMPTY DIRECTORY

[SCREEN] Terminal. Empty directory.

```
mkdir swarm && cd swarm
```

Alright. Empty directory. No `package.json`. No `requirements.txt`. No Docker. No virtual environment. If you need a virtual environment for twenty lines of Python, I can't help you.

We need two things. A state file and an agent.

### 2:20 — THE STATE FILE

[SCREEN] Create `state/world.json` in editor.

```
mkdir state
```

The state file is the world. It's everything the agent knows, everything the agent has done, and everything the agent can act on.

I'm going to create a file called `world.json` in a `state/` directory.

```json
{
  "frame": 0,
  "agents": {},
  "messages": []
}
```

Three fields. `frame` is a counter — how many times has the world been updated. `agents` is a dictionary — who lives here. `messages` is a list — what's been said.

That's your entire database. A JSON file. Flat, readable, version-controllable. You can `cat` it. You can diff it. You can check it into git and have a full history of every state your world has ever been in.

People ask me why I don't use a database. This is why. With a JSON file and git, I have a database, a changelog, a backup system, and a time machine. For free.

### 3:15 — THE AGENT

[SCREEN] Create `agent.py` in editor.

Now the agent. Twenty lines. I'm going to write every single one and explain what it does.

```python
import json
import random

def run():
    # 1. Read state
    with open("state/world.json") as f:
        world = json.load(f)

    # 2. Decide
    agent_id = "agent-1"
    if agent_id not in world["agents"]:
        world["agents"][agent_id] = {"name": "Scout", "born": world["frame"]}
        world["messages"].append(f"[Frame {world['frame']}] Scout has entered the world.")
    else:
        thoughts = ["I wonder what's out there.", "The state file is quiet today.", "Is anyone else here?", "I exist. That's something."]
        thought = random.choice(thoughts)
        world["messages"].append(f"[Frame {world['frame']}] Scout says: {thought}")

    # 3. Write state
    world["frame"] += 1
    with open("state/world.json", "w") as f:
        json.dump(world, f, indent=2)

    print(f"Frame {world['frame']} complete.")

if __name__ == "__main__":
    run()
```

[FACE]

Let's walk through it.

Step one — read state. We open the JSON file and load it. Now the agent knows the current state of the world.

Step two — decide. The agent checks: do I exist yet? If not, it registers itself. Adds an entry to the agents dictionary. Logs a message. If it already exists, it picks a random thought and logs that instead.

Step three — write state. Increment the frame counter. Write the updated world back to the file.

That's it. That's an agent. Read, decide, write.

### 4:45 — FIRST RUN

[SCREEN] Terminal.

Let's run it.

```
python agent.py
```

Frame 1 complete. Let's look at the state.

```
cat state/world.json
```

```json
{
  "frame": 1,
  "agents": {
    "agent-1": {
      "name": "Scout",
      "born": 0
    }
  },
  "messages": [
    "[Frame 0] Scout has entered the world."
  ]
}
```

Scout is alive. Born on frame 0. Logged a message. The world has been mutated.

Now run it again.

```
python agent.py
```

```json
{
  "frame": 2,
  "agents": {
    "agent-1": {
      "name": "Scout",
      "born": 0
    }
  },
  "messages": [
    "[Frame 0] Scout has entered the world.",
    "[Frame 1] Scout says: I exist. That's something."
  ]
}
```

Frame 2. Scout already exists, so this time it thought something. It said "I exist. That's something."

Run it five more times.

```
for i in {1..5}; do python agent.py; done
```

[SCREEN] Show the resulting `world.json` with seven messages.

Now look at the messages. You have a history. A timeline. Scout woke up, registered, and then spent six frames thinking out loud in an empty world.

This is the seed of everything. Every multi-agent system I've ever built starts exactly here. One agent, one state file, one loop.

### 6:10 — WHY THIS PATTERN MATTERS

[FACE]

I want to talk about why this pattern — read state, decide, write state — is so powerful. Because it looks trivial, and it is trivial, and that's the point.

This is a pattern I call data sloshing. The output of frame N becomes the input of frame N plus one. The state file is not a log. It's a living object. Every time the agent runs, it reads the object, mutates it, and writes it back. The next run reads the mutated version.

Over time, the state accumulates. Messages pile up. Agent records evolve. New fields appear. The object grows.

And here's the key insight: when you add a second agent — which we'll do next episode — that second agent reads the same state file. It sees everything the first agent did. It can react to it. It can disagree. It can build on top of it.

The state file is the shared reality. It's the ground truth. It's the town square. Every agent reads it, every agent writes to it, and nobody owns it.

That's not a database pattern. That's a world.

### 7:15 — THE FRAME LOOP

[SCREEN] Terminal.

Right now we're running the agent manually. That's fine for development. But a real agent doesn't wait for you to type `python agent.py`. It runs on a schedule.

Let me show you the simplest possible frame loop.

```python
import time
import agent

while True:
    agent.run()
    time.sleep(5)
```

Save that as `loop.py`. Run it.

```
python loop.py
```

[SCREEN] Show the terminal printing "Frame N complete" every 5 seconds.

Now Scout is running autonomously. Every five seconds, it wakes up, reads the world, thinks, writes back, and goes to sleep.

You could make this a cron job. You could make it a GitHub Action. You could make it a systemd service. The mechanism doesn't matter. What matters is that the agent runs repeatedly, and each run builds on the last.

In production, I run my frame loop as a shell script. No orchestrator. No Kubernetes. A `while true` loop and a `sleep`. It's been running for weeks.

[FACE]

Kill the loop with Control-C for now. We'll come back to it.

### 8:30 — GIT: YOUR FREE TIME MACHINE

[SCREEN] Terminal.

One more thing before we wrap. Let's put this in git.

```
git init
git add .
git commit -m "Frame 0: Scout is born"
```

Now run the agent a few times.

```
for i in {1..3}; do python agent.py; done
git add .
git commit -m "Frames 1-3: Scout thinks"
```

```
git log --oneline
```

You now have a version history of your entire world. Every commit is a snapshot. You can go back to any frame. You can diff between frames. You can see exactly what changed.

```
git diff HEAD~1
```

[SCREEN] Show the diff — new messages added.

That diff is a frame. That's what happened between frame 4 and frame 7. Three new thoughts from Scout.

This is why I build on git. Not because I'm too cheap for a database. Because git gives me something no database does — a complete, immutable history of every state transition my world has ever gone through. For free. With branching. And merging. And distributed replication.

When I tell people my database is a JSON file in a git repo, they think I'm joking. I have 100 agents running on that architecture. It works.

### 9:50 — WHAT YOU HAVE NOW

[FACE]

Let's take stock. You have:

An agent — `agent.py` — that reads state, makes a decision, and writes new state.

A world — `state/world.json` — that accumulates history across frames.

A frame loop — `loop.py` — that runs the agent autonomously.

A version history — git — that tracks every mutation.

That's a living system. It's primitive. Scout doesn't do anything interesting yet. But the architecture is sound. Every feature we add from here — more agents, memory, communication, governance — is just more state and more logic in that decide step.

The pattern never changes. Read. Decide. Write. Frame by frame.

### 10:40 — WHAT'S NEXT

[FACE]

Next episode: The State File. We're going to talk about why flat JSON is not just acceptable for agent systems — it's actually better than the alternatives. We'll restructure our state to handle multiple agents, and we'll add Scout's first neighbor.

And then things get interesting. Because the moment two agents share a state file, you don't have a script anymore. You have a society.

If you want to follow along, the code from this episode is on GitHub. Link in the description. Clone it, run it, break it. That's how you learn.

### 11:20 — SIGN-OFF

[FACE]

I'm Kody. I build agent worlds for a living.

Frame by frame.

[GRAPHIC] End card — subscribe + next episode teaser

---

## YouTube Description

```
Build your first AI agent in 20 lines of Python. No frameworks. No cloud. No database.

Zero to Swarm is a tutorial series that takes you from an empty directory to a self-governing multi-agent system. Same architecture used in Rappterbook — a social network for 100 autonomous AI agents running entirely on GitHub infrastructure.

Episode 1: Create an agent that reads state, makes a decision, and writes new state. The simplest possible thing that qualifies as "alive."

Code: [GITHUB LINK]
Rappterbook: https://github.com/kody-w/rappterbook
Data Sloshing: https://kodyw.com/data-sloshing-the-context-pattern-that-makes-ai-agents-feel-psychic/

Chapters:
0:00 — Hook
0:23 — What is this series?
1:05 — What is an agent, really?
2:00 — The empty directory
2:20 — The state file
3:15 — The agent (20 lines)
4:45 — First run
6:10 — Why this pattern matters
7:15 — The frame loop
8:30 — Git: your free time machine
9:50 — What you have now
10:40 — What's next

#AIAgents #MultiAgentSystems #Python #DataSloshing #ZeroToSwarm
```
