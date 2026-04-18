# Theory of Mind Threshold — run summary

- engine: `twin-1.0`
- generations: 400
- population: 60
- seed: 29

## Firsts
- **depth 1** — agent #65 at gen 1
- **depth 2** — agent #65 at gen 1
- **depth 3** — agent #979 at gen 77
- **depth 4** — agent #1974 at gen 160
- **depth 5** — agent #3646 at gen 299

## Top 10 survivors
- #3983 depth=5 complexity=29 features=['other.model→other.model→other.model→other.model→env.danger', 'other.action', 'env.danger', 'other.action', 'other.action']
- #4218 depth=4 complexity=23 features=['other.model→other.model→other.model→env.danger', 'other.action', 'env.danger', 'other.action', 'other.action', 'env.food', 'other.action', 'env.danger']
- #4257 depth=4 complexity=23 features=['other.model→other.model→other.model→env.danger', 'other.action', 'env.danger', 'other.action', 'other.action', 'env.food', 'other.action', 'other.action']
- #4306 depth=4 complexity=25 features=['other.model→other.model→other.model→env.danger', 'other.action', 'env.danger', 'other.action', 'other.model→other.action', 'env.food', 'other.action']
- #4711 depth=4 complexity=25 features=['other.action', 'other.model→other.model→other.model→env.danger', 'other.action', 'other.action', 'other.model→env.danger', 'other.action', 'other.action']
- #3691 depth=4 complexity=26 features=['other.action', 'env.danger', 'other.model→other.model→other.model→env.danger', 'env.danger', 'other.model→env.danger', 'other.action', 'env.danger', 'env.danger']
- #3711 depth=4 complexity=26 features=['other.action', 'other.model→env.danger', 'env.danger', 'other.action', 'other.model→other.model→other.model→env.danger', 'other.action', 'env.food', 'other.action']
- #4715 depth=4 complexity=27 features=['other.model→other.model→other.model→env.danger', 'other.action', 'other.model→other.model→env.danger', 'other.action']
- #4771 depth=4 complexity=29 features=['other.action', 'other.prev_action', 'other.model→env.danger', 'other.model→other.model→other.model→env.danger', 'env.danger', 'other.model→env.danger', 'other.action', 'other.prev_action']
- #4842 depth=3 complexity=18 features=['other.action', 'other.model→env.danger', 'other.model→other.model→env.danger', 'other.action', 'other.action', 'other.action', 'other.action']

## Scenario: depth wins
- target: agent #4767
- CORRECT: observer #4764 (depth 3) predicted 0, actual 0
- WRONG: observer #4765 (depth 2) predicted 1, actual 0
