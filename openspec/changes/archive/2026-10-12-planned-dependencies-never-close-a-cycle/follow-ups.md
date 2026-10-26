## From `planned-dependencies-never-close-a-cycle/1`

- src/agent_build_kit/cli/pipeline.py:3538 — The narrower replan exit (only refusals whose cycle includes a unit of a change being replanned make it non-zero) has no test. Both the in-scope case and the out-of-scope case need one.
- src/agent_build_kit/pipeline/cycles.py:89 — The docstring says a fixed-edge cycle through a plan unit "drops nothing". Planner edges are now still tried while that cycle exists, so a planner edge that repeats a `Needs:` edge inside the cycle is dropped and logged.

## From `planned-dependencies-never-close-a-cycle/2`

- `deadlocks` now builds its edges with `waiting_on`, which looks through satisfied units. A reported chain can therefore skip a satisfied unit that sits between two planned ones. Wherever the docs or status describe the `deadlocked:` chain, they could say it lists only the units that are waiting.
