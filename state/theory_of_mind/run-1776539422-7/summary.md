# Theory of Mind Threshold — run summary

- engine: `twin-1.0`
- generations: 400
- population: 60
- seed: 7

## Firsts
- **depth 1** — agent #60 at gen 1
- **depth 2** — agent #60 at gen 1
- **depth 3** — agent #1221 at gen 97
- **depth 4** — agent #2287 at gen 186
- **depth 5** — not reached

## Top 10 survivors
- #3798 depth=4 complexity=21 features=['other.action', 'other.model→other.model→self.state', 'env.food', 'other.action', 'other.action', 'other.model→env.danger', 'env.danger']
- #3943 depth=4 complexity=22 features=['other.action', 'env.danger', 'other.model→other.model→other.model→env.danger', 'env.danger', 'env.danger', 'env.food', 'other.action']
- #4760 depth=4 complexity=25 features=['other.action', 'other.model→other.model→other.model→env.food', 'other.action', 'env.danger', 'env.danger', 'other.model→other.action', 'other.action']
- #4725 depth=4 complexity=26 features=['other.action', 'other.action', 'other.model→other.model→other.model→env.food', 'other.action', 'env.food', 'other.model→env.food', 'other.action', 'env.food']
- #4799 depth=4 complexity=26 features=['other.model→other.action', 'other.action', 'other.action', 'other.action', 'other.model→other.model→other.model→other.action', 'env.danger', 'env.danger', 'env.danger']
- #4839 depth=3 complexity=18 features=['other.action', 'other.action', 'other.model→other.model→env.food', 'env.danger', 'env.danger', 'other.model→other.action', 'env.food']
- #4840 depth=3 complexity=18 features=['env.food', 'other.action', 'other.action', 'env.danger', 'other.model→other.model→other.action', 'other.model→env.food', 'other.action']
- #4844 depth=3 complexity=18 features=['other.action', 'other.model→other.model→env.food', 'other.action', 'env.danger', 'env.danger', 'other.model→other.action', 'env.danger']
- #4851 depth=3 complexity=18 features=['other.action', 'other.action', 'other.model→other.model→env.food', 'env.danger', 'env.danger', 'other.model→other.action', 'env.food']
- #4852 depth=3 complexity=18 features=['env.food', 'other.action', 'other.action', 'env.danger', 'other.model→other.model→other.action', 'other.model→env.food', 'other.action']

## Scenario: depth wins
- target: agent #4765
- CORRECT: observer #4766 (depth 3) predicted 0, actual 0
- WRONG: observer #4764 (depth 2) predicted 1, actual 0
