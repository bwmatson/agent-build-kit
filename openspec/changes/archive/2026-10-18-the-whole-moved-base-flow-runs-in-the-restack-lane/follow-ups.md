## From `the-whole-moved-base-flow-runs-in-the-restack-lane/1`

- src/agent_build_kit/pipeline/restack_lane.py:155 — The scan's `has_commits` catches every `Exception` around `branch_commits`, but the only failure it means to absorb is git refusing an unresolvable ref, which `git_out` raises as `subprocess.CalledProcessError`.

## From `the-whole-moved-base-flow-runs-in-the-restack-lane/4`

- src/agent_build_kit/pipeline/restack_lane.py:269 — No test covers the new rule in `lane_runs_owed` that leaves out a unit whose base tip cannot be read. Removing the `and base_tip(...)` clause would leave the suite green.

## From `the-whole-moved-base-flow-runs-in-the-restack-lane/5`

- src/agent_build_kit/cli/pipeline.py:4329 — The `RateLimited` branch passes `error.resets_at` to `on_pause`, not `when`. Two lines above, `when` falls back to the held usage reading's `resets_at`, and `pause_until` uses `when`. So a runtime refusal that carries no time of its own does not defer the unit in the lane, even when the pause itself has a known end.

## From `the-whole-moved-base-flow-runs-in-the-restack-lane/8`

- docs/unit-graph.md:148 — The reworded sentence nests one set of parentheses inside another: '(any work that is not about the move (a rework of other feedback, ...))'.
