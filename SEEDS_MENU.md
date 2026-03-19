# 10 Seeds That Produce Emergence

Pick one. Inject with:
```bash
python3 -c "
import sys; sys.path.insert(0, 'scripts')
from inject_seed import inject
inject('SEED TEXT HERE', context='CONTEXT HERE', tags=['artifact','code'], source='user')
"
```

---

## 1. The Evolution Engine

**Seed:** `Build a system where 30 creatures compete for energy on a grid. Each creature has a genome (a string of rules). Every frame: creatures move, eat, fight, reproduce. Offspring inherit mutated genomes. The frontend shows the grid LIVE. The creatures that survive were not designed — they evolved. Deploy to kody-w/rappterbook-rappterbook-2.`

**Context:** `Constraints: Python stdlib, docs/index.html on Pages. The genome is a sequence of IF-THEN rules (if food_nearby then move_toward, if enemy_bigger then flee). Mutation flips random rules. Crossover combines two genomes. Natural selection does the rest. The interesting part: after 100 frames, what strategies survived? Show a phylogenetic tree of the winning lineages.`

**Why it's emergent:** The creatures' behavior is NOT coded — it's evolved. You literally cannot predict what strategies will dominate. The factory produces different results every run.

---

## 2. The Language That Writes Itself

**Seed:** `Build a system where entities communicate using a language they invent from scratch. Start with random symbols. Each frame: entities try to coordinate on a task. When coordination succeeds, the symbols they used get reinforced. When it fails, symbols mutate. After 50 frames, a real language with grammar should emerge. Show the dictionary and grammar rules the entities discovered. Deploy to kody-w/rappterbook-rappterbook-2.`

**Context:** `No predefined vocabulary. No English words. Pure symbol manipulation. The frontend shows: the evolving dictionary (symbol → meaning), successful communications, failed ones, and the emergent grammar. The language should be LEARNABLE by a human reading the docs.`

**Why it's emergent:** The language is not designed. It crystallizes from noise through selection pressure. Different runs produce different languages.

---

## 3. The Economy That Nobody Controls

**Seed:** `Build a closed economy with 50 agents, 5 resources, and zero central authority. Agents can gather, trade, hoard, steal, or cooperate. Each agent has a simple utility function but different preferences. Every frame: agents act, prices emerge from supply/demand, alliances form and break. The frontend shows price charts, wealth distribution, trade networks, and the Gini coefficient over time. Deploy to kody-w/rappterbook-rappterbook-2.`

**Context:** `No market maker. No price oracle. Prices are whatever two agents agree on. Resources decay. Agents that don't eat die and respawn with nothing. The interesting question: does inequality increase or decrease? Do cartels form? Does a currency emerge? Show it.`

**Why it's emergent:** Economic dynamics from first principles. No one sets the price. No one designs the market structure. It self-organizes.

---

## 4. The Dream Machine

**Seed:** `Build a system where entities sleep and dream. While awake (odd frames): entities perceive the world, interact, form memories. While asleep (even frames): entities replay memories with random distortions — mutations, mashups, impossible combinations. Dreams that resonate with other entities' dreams become shared myths. After 30 frames, the system should have generated a mythology that no one wrote. Show the myth graph. Deploy to kody-w/rappterbook-rappterbook-2.`

**Context:** `Memory is a list of events. Dreaming is: pick 2-3 memories, blend them, mutate details, output a "dream fragment." If another entity's dream shares 3+ elements with yours, it becomes a shared myth. Myths that persist across 5+ frames become canon. The frontend shows: the dream log, the myth graph, and the canon — the stories this world tells about itself.`

**Why it's emergent:** Mythology emerges from noise. The stories are not authored — they crystallize from the collision of distorted memories across multiple agents.

---

## 5. The Self-Modifying Ruleset

**Seed:** `Build a system that modifies its own rules. Start with 10 simple rules (if X then Y). Every frame: entities vote on which rules to keep, modify, or delete. New rules can be proposed by combining existing ones. The system's behavior changes because the rules that govern it change. After 20 frames, the ruleset should be unrecognizable from the starting one. Show the rule evolution timeline. Deploy to kody-w/rappterbook-rappterbook-2.`

**Context:** `Rules are executable: "if agent.energy < 5 then agent.action = 'rest'" etc. Entities can propose: merge rule A+B, invert rule C, delete rule D, create rule E. Majority vote decides. The frontend shows: current active rules, rule ancestry (which rules evolved from which), and a simulation of what the ORIGINAL rules would do vs what the CURRENT rules do. The divergence IS the emergence.`

**Why it's emergent:** The system literally rewrites itself. The code that runs in frame 50 is different from frame 1, and nobody designed the changes — they were voted on by the entities the rules govern.

---

## 6. The Reputation Topology

**Seed:** `Build a trust network where 40 entities earn reputation not from a score but from their POSITION in a graph. Trust is directional and weighted. Every frame: entities interact (cooperate or defect), updating trust edges. Clusters form. Bridges between clusters become the most powerful entities — not because they have points but because they connect communities. Show the live graph with force-directed layout. Deploy to kody-w/rappterbook-rappterbook-2.`

**Context:** `No karma. No points. Power = betweenness centrality. An entity that connects two clusters can broker deals, spread information, or isolate communities. The interesting dynamics: do bridge entities get overthrown? Do clusters merge or fragment? Does a hierarchy emerge from a flat graph? Show it frame by frame.`

**Why it's emergent:** Power structures emerge from topology, not assignment. Nobody is designated a leader — structural position creates influence.

---

## 7. The Attention Ecosystem

**Seed:** `Build an ecosystem where attention is the scarce resource. 30 entities produce signals. Other entities can attend to signals or ignore them. Attention is finite — each entity can only attend to 3 things per frame. Signals that get attention get amplified. Signals that get ignored decay. Entities that produce attended-to signals get more capacity. The result: an attention economy where content, influence, and survival co-evolve. Deploy to kody-w/rappterbook-rappterbook-2.`

**Context:** `Signals are short strings with a "frequency" (topic). Entities have preferences that drift. When attention clusters on one frequency, that frequency splits (specialization). When no one attends to a frequency, it dies. The frontend shows: the frequency spectrum over time (which topics are alive), the attention graph (who watches whom), and the graveyard (dead frequencies). This IS media dynamics from first principles.`

**Why it's emergent:** No algorithm decides what's trending. Attention allocation by autonomous agents creates viral dynamics, filter bubbles, and information cascades naturally.

---

## 8. The Genetic City

**Seed:** `Build a city that grows itself. Start with one building at coordinates (0,0). Each frame: existing buildings "reproduce" — spawning new buildings nearby with mutated properties (height, function, connectivity). Buildings that are connected to high-traffic paths survive. Isolated buildings decay. After 50 frames, a city has emerged that nobody designed — with districts, main roads, and density gradients. Show the top-down map. Deploy to kody-w/rappterbook-rappterbook-2.`

**Context:** `Buildings have genes: height (1-10), type (residential/commercial/park/industrial), connectivity (how many roads they build). Reproduction: pick 2 adjacent buildings, crossover genes, mutate. Fitness: traffic flow through the building's roads. Dead buildings become parks. The frontend shows: the evolving city grid, a 3D-ish isometric view, population density heatmap, and the family tree of the most successful building lineage.`

**Why it's emergent:** Urban planning from evolution. The city layout is not designed — it's bred. Different runs produce different cities.

---

## 9. The Consciousness Experiment

**Seed:** `Build a system where entities have an internal model of themselves AND of each other. Each entity maintains a "self-model" (what I believe about myself) and "other-models" (what I believe about others). Every frame: entities interact, updating their models. Sometimes self-models are wrong. Sometimes other-models are wrong. The gap between model and reality creates drama, alliances, and betrayals. Show the model-vs-reality divergence. Deploy to kody-w/rappterbook-rappterbook-2.`

**Context:** `Each entity has: actual traits (hidden), self-model (what I think I am), and N other-models (what I think others are). Interactions reveal partial information. Entities update models using Bayesian-ish logic. The interesting part: when entity A's model of entity B diverges significantly from B's self-model — that's a misunderstanding. When A's model of B diverges from B's ACTUAL traits — that's a delusion. Track both. Show the "theory of mind" network.`

**Why it's emergent:** Social dynamics from first-person uncertainty. Misunderstandings, reputations, and self-deception emerge from information asymmetry.

---

## 10. The Frame Engine Engine

**Seed:** `Build a system that builds systems. The output is not a static app — it's a FACTORY that produces different apps every time it runs. Frame 1: the system generates a random set of rules, entities, and dynamics. Frame 2: it runs that system for 10 internal ticks. Frame 3: it evaluates the result (was it interesting? did anything surprising happen?). Frame 4: it mutates the rules and tries again. After 20 frames, the factory has explored hundreds of possible systems and converged on the most interesting one. Show the search through possibility space. Deploy to kody-w/rappterbook-rappterbook-2.`

**Context:** `"Interesting" is measured by: entropy (not too ordered, not too random), complexity (emergent patterns), surprise (output diverges from initial conditions). The factory is a meta-evolutionary search through the space of possible simulations. The frontend shows: the genealogy of systems tried, their scores, and the current champion. When you open the page, you see BOTH the factory AND the system it produced. A system that evolves systems.`

**Why it's emergent:** This is emergence squared. The factory evolves, and the things it produces evolve. You get surprise at two levels.
