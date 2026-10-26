## From `test-kind-names-are-accepted-both-ways/1`

- `joins.check_joins` (joins.py:124) and `_tag_problems` (cli/pipeline.py:2575) each convert a stored unit's `tier` with `new_spelling(Place.VALUE, ...)` before comparing it to a group's `TestTier`. Task 2.3 makes the stored and planned `tier` a `TestTier`, so both conversions should be removed in that unit and not copied to new places.
- src/agent_build_kit/pipeline/work_graph.py:215 — The `tier` before-validator on `TaskGroup` duplicates the conversion `validate_tasks` already does (`new_spelling(Place.TAG, ...)` then `TestTier(tier)` at line 419). Its only remaining callers are test fixtures that still build `TaskGroup(tier="tier1")` (tests/pipeline/test_planner.py:177-179, 311-312, 388-389, 435, and the join/calibration tests).
- src/agent_build_kit/model.py:30 — `TestTier` sits in `model.py`, whose docstring covers only the `Frozen` base and its two settings.

## From `test-kind-names-are-accepted-both-ways/2`

- `MetricRecord._read_old_kind` (pipeline/metric_records.py:40-44) still calls `new_spelling(Place.VALUE, ...)` itself, because the kind sits inside an attributes dict and `read_old_kind` returns `object`. The builder's reason holds: it calls the shared table, it does not copy the converter. If `read_old_kind` later gets a typed overload (str in, str out), this call could use it too.
