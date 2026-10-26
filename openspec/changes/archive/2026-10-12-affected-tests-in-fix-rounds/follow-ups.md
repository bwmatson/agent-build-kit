## From `affected-tests-in-fix-rounds/1`

- In wiring.py `run_selection`, only a selected test command may exit with the profile's no-tests-collected code, and it tells which command is lint by `index > 0`. Carrying lint as its own field in the plan entry would make that rule structural instead of positional.
- The tier1-node graph test (tests/graph/test_affected_fix_rounds.py) checks what the node passes to run_tier1. It cannot catch a change to `answering` itself, because a passing check clears the stored TIER1 feedback before the node runs. The builder said so, and the reason holds.
- src/agent_build_kit/pipeline/wiring.py:850 — `run_selection` decides which command is lint by its position (`index > 0`), so it depends on `selection` always putting the lint command first in each project's list.
