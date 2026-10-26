## From `a-unit-parked-on-a-split-can-be-requeued/1`

- src/agent_build_kit/cli/pipeline.py:5860 — The new `source` wording 'an automatic note naming the splits it was parked on' is only reachable on the no-thread rework of a parked unit with no note and no saved failure, and no test checks what that path prints.
- tests/split_changed_support.py:46 — `park_after_tick` takes `*splits` but always writes the history note 'e2e tests of acp did not run', whatever splits it is given.
