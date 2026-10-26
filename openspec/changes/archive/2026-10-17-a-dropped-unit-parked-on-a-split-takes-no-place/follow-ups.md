## From `a-dropped-unit-parked-on-a-split-takes-no-place/1`

- tests/cli/test_split_wait_unplanned.py:39 — Task 1.3 asks the release test to show that the worktree is left as it was. The test checks state, parked_splits, branch and history, but never the worktree.
- tests/pipeline/test_upsert_keeps_parked_splits.py:30 — The spec scenario 'A replan does not release a held split's unit' has no test. That scenario is: a replan, then the release step runs while the split is still held, and the unit is not resumed.
- src/agent_build_kit/cli/pipeline.py:1937 — Take a planned unit with parked_splits and no cause, for example one planned again after a demotion, whose split has been released. Its status line says 'released, resumes this round'. But release_split_held selects only units with cause split_held, so the unit is actually started by the ordinary round.
