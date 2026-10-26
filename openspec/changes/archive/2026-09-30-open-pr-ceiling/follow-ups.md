## From `open-pr-ceiling/1`

- test_one_short_of_the_ceiling_starts_one_new_unit_not_all should assert `builder.started == ["new/1"]` rather than accept either unit.
- Pin the "queue is full: N open pull requests and K being built, ceiling M" log wording with a status or tick test in which a RUNNING unit with no PR fills the ceiling.
- Rewrap the remaining overlong line in step 3 of src/agent_build_kit/skills/abk-pipeline/SKILL.md.
- tests/cli/test_tick_scheduling.py:816 — The new tick test accepts either new unit being started (`builder.started[0] in ("new/1", "new/2")`), but round 1 asked it to pin that the first planned unit starts.
- src/agent_build_kit/pipeline/units.py:346 — No test covers the new "and K being built" wording in the log line, which `_queue_full_line` emits when builds with no PR fill the room.
- src/agent_build_kit/skills/abk-pipeline/SKILL.md:118 — The rewrapped step 3 still leaves one line ("when the tasks for one are visible right there in `tasks.md`, and ends `in_review` with a PR — or ...") well past the paragraph's width.
