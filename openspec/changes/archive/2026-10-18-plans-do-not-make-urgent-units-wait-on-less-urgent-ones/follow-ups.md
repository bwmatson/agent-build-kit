## From `plans-do-not-make-urgent-units-wait-on-less-urgent-ones/4`

- src/agent_build_kit/cli/pipeline.py:685 — The `priority:` line calls `priority_note(unit, units)` with no `excluded` set, but the ready queue (`_ready_queue_lines` through `_evaluate_round`) leaves out waiters held by another tab's lease. So when a lease holds a more urgent waiter, the two lines now disagree.
- src/agent_build_kit/pipeline/work_graph.py:683 — Both constructors in `inverted_groups` always set `needed_by_line`, so its `= 0` default only lets a future constructor forget the field without any error.

## From `plans-do-not-make-urgent-units-wait-on-less-urgent-ones/5`

- docs/unit-graph.md:159 — The sentence on `abk status` still gives the ready-queue reasons as `planned order`, its own priority, or the priority it takes from the unit that waits on it. Since `priority_note` was added, those lines also show `promoted from <unit>` and `from <unit>`, but the doc only gives those strings for the graph page.
- src/agent_build_kit/skills/abk-authoring/SKILL.md:199 — The skill says 'such a group is promoted: the prerequisite is raised to its dependent's priority' and doesn't say this only happens while the prerequisite's unit has not started.
- tests/skills/test_priority_rule_text.py:14 — `_section` is a new heading-to-next-heading extractor. `tests/test_authoring_skill_describes_behaviour.py:11` (`raw_section`) already does the same thing inline for one fixed heading.
