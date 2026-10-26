## From `needs-start-on-the-parents-branch/1`

- src/agent_build_kit/pipeline/work_graph.py:243 — The `current is not None` test before `index in own_merged_lines` no longer does anything: `group_needs` only records a line after a group heading. It also tracks the group with `GROUP_HEADING`, while this loop uses `ANY_GROUP_HEADING`.

## From `needs-start-on-the-parents-branch/2`

- In tests/graph/test_needs_added_while_started.py the check `assert seen == [(RUNNING, seen[0][1])]` reads oddly because it compares the cause with itself. Splitting it into `assert [s for s, _ in seen] == [RUNNING]` plus the existing cause check would say the same thing more plainly.
- `dependency_wait` now adds "to merge" only for a parent in another repository. A same-repo parent the unit lists in `merge_before` also waits for a merge, but its wording still reads "waiting for X". The builder noted this. A later unit could make the wording follow the real gate.
