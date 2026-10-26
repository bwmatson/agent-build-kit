## From `status-not-wording/1`

- The change's design.md in the planning repo still leaves `reviewer_hold` out of its list of causes. The builder could not edit that file. Someone with write access to the planning repo should add `reviewer_hold`, recorded by the agent-hold label through events.on_hold and by the graph's HOLD event, so the design names the same fixed set as `Cause` and `test_the_causes_are_the_fixed_set_the_design_names`.
- There are still no cause tables for the review-node holds (escalation by class or by disagreement, needs_human), the `build_restack` writers, or the toolchain hold in `_build_unit`. The scheduling tests and the hold-path table already cover the decisions that read these causes, but a test that drives each writer and asserts the cause it records would stop one from being retagged without notice. The builder deferred this (1.5) as a follow-up.

## From `status-not-wording/2`

- Two state tuples still use bare strings: diagram.py `ACTIVE` has "failed" and archive.py `FINISHED_WITHOUT_MERGING` has ("unplanned",). Use the `UnitState` members instead.
- The tier 1 command span in wiring.py, the agent-call span in nodes.py, and runtimes/traced.py still record "ok", "failed" or "exit N" strings. These are the outcome of a command or agent call, not of a unit, so they don't belong in `UnitOutcome`. If telemetry should still use fixed sets for them, give them their own small enum.
- src/agent_build_kit/pipeline/diagram.py:58 — Two state tuples still use bare strings: `ACTIVE` in diagram.py has `"failed"`, and `FINISHED_WITHOUT_MERGING` in archive.py:40 has `("unplanned",)`. They should use `UnitState.FAILED` and `UnitState.UNPLANNED`, as every other state constant now does.
- tests/graph/test_remaining_paths.py:769 — The `adapt` test checks that the feedback source stays TIER1. Unlike the restack test, it does not go on to drive the next rework and assert that `claude:fix_checks` runs.
