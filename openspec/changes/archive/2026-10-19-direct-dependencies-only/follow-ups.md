## From `direct-dependencies-only/1`

- tests/pipeline/test_units_acceptance_recorded.py:3 — The module docstring and the fixture name call `tests/fixtures/stores/recorded_units.json` a recorded store. It is a hand-written store in the pipeline's shape, using fixture names (`feature/1`..`feature/8`, `add-marker/1`..`add-marker/4`).
- src/agent_build_kit/pipeline/transcript.py:68 — `_prefix` now imports `unit_number` inside the function to get around an import cycle. This file's `unit_transcript_files` (155) and `read_transcripts` (179) still parse `<change>/<n>` by hand, so the file now does it two ways. Neither `run_log.py` nor `transcript.py` needed changing for this group.

## From `direct-dependencies-only/3`

- check_joins builds its index again on each direct(u) call, because direct_dependencies is called over the full unit list for every unit in the `others` scan. That is quadratic per join. It is harmless at today's store sizes, and it was left alone on purpose in an earlier round.

## From `direct-dependencies-only/4`

- Tasks 4.5, 5.5 and 6.4 ask the builder to confirm the design.md UNVERIFIED items they touch and correct the design: `satisfied_landed` on reduced lists, and the one-time reduction on a running tick and under the store lock. design.md lives in the planning repo and still marks both UNVERIFIED. Record the confirmations there, e.g. that the reduction runs as a `_step` in `run_round` before the split gates and through `set_dependencies` alone.
- Task 6.4 says to make `_replan_differences` compare direct dependencies. The branch instead calls `reduce_stored_dependencies` before the `before` snapshot in `cmd_replan`. Since `upsert` reduces the `after` side, the comparison is direct to direct and test_replan_direct_dependencies.py pins the behaviour. A one-line comment at `_replan_differences` saying both sides are reduced would stop a later reader from re-adding the reduction there.
- CHANGELOG.md:54 — The new sentence says the planner asks an acceptance or narrow group to depend on the end of its chain and on independent units. Only the `[acceptance]` rule of the planner prompt changed. The `[narrow]` rule still says 'its unit depends on every unit that migrates a consumer', and test_planner_prompt_exercised.py pins it that way. It is `plan_units`, not the planner prompt, that gives a narrow unit the chain tail plus the independent units.
- src/agent_build_kit/pipeline/wiring.py:3207 — `predecessor` builds an `order` dict from `enumerate(units)` and takes `max` over it to find the parent latest in plan order. `open_parents` in units.py:593 gets plan order with a simpler idiom: filter the graph by the wanted ids and take the last one.
