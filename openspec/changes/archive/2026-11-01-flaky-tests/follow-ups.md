## From `flaky-tests/2`

- Skip the flake rerun when the unit-test command hit the group-1 time limit (TIMED_OUT_EXIT), with a test, so a timeout can never be reported as a flake.
- docs/architecture.md: mention that a merge-time restack meeting a flake records it and parks the child gated, not pushed, and that the fix change's own unit treats the flake as a unit-test failure.
- The flakes.jsonl entry for a flake met by the fix change's own unit stores change=""; record the fix's name there too.
- Log what `awaiting_planning` finds when it is the reason a gated unit is not released.
- src/agent_build_kit/pipeline/wiring.py:737 — `isolate` also runs on a unit-test command that hit the command time limit from group 1 (`TIMED_OUT_EXIT`). If the aborted run's output names any `FAILED x::y` that then pass alone, the timeout becomes a `FlakeFound` and the hung test is never named.
- docs/architecture.md:815 — The flake paragraph describes only the unit's node calling `on_flake`. It does not mention the merge-time restack path, which now records the flake and parks the child the same way. It also says only that the fix change's own unit 'does not wait', not that it fails unit-test with the flake's output.
- src/agent_build_kit/pipeline/wiring.py:822 — `wait_on_fix` returns None both for 'this unit builds the fix' and for 'nothing to wait on'. So the record entry for a flake met by the fix change's own unit is stored with `change=""`, although the fix change exists and is known.
- src/agent_build_kit/cli/pipeline.py:1030 — `awaiting_planning` applies to every gated unit with a requeue, not only flake-parked ones. A `Needs: X group N merged` whose target group is still in an open change but will never get a unit now holds the unit indefinitely; before, it was released. Example: a group whose boxes were all ticked by hand.

## From `flaky-tests/3`

- PythonUvProfile.repeat_command decides whether an id is in scope by comparing path strings against the command's positional words. A command given `.` or an absolute path would therefore match no ids and silently skip the repeat. No unit-test command builds paths like that today, but resolving both sides to paths, or noting the assumption in the RepeatsTests docstring, would keep a future command shape from turning the check off without anyone noticing.
