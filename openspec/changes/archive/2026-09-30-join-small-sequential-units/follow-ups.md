## From `join-small-sequential-units/1`

- later_groups_by_change: take each change's ceiling across every member of that change, not per member, so a unit carrying two members of one change (which group 2's same-change join may produce) does not report the groups between them as later work.
- BUILD/REVIEW_BOUNDARY_NOTE say 'later units of this change'. For a joined unit, whose later text names several changes, say 'their change'.
- _follow_ups_note repeats the path construction in _follow_ups_path. Give _follow_ups_path a change parameter.
- src/agent_build_kit/pipeline/units.py:373 — later_groups_by_change sets each member's ceiling from that member's own groups, not from the highest group the unit builds of that change. If one unit lists the same change in two members, the union picks up groups that sit between them.
- src/agent_build_kit/pipeline/stack_runner.py:474 — For a joined unit, the boundary note reads 'Task group(s) 6 of sample-change belong to later units of this change'. 'This change' is ambiguous once the unit spans several changes.
- src/agent_build_kit/pipeline/stack_runner.py:1782 — _follow_ups_note builds each member's follow-ups path inline, repeating what _follow_ups_path does for the unit's own change.
## From `join-small-sequential-units/2`

- Round 1's 1.3 said an `unplanned` carrier would block archiving. That was wrong: `FINISHED_WITHOUT_MERGING` contains `unplanned`, so such a unit counts as finished. The real risk was a change archiving without the carried group built, and the fix in `plan_all` (`_orphaned_changes` re-planning the carried change) closes that risk. Optionally, add a comment by `is_ready_to_archive` saying an `unplanned` carrier is safe to count only because its carried changes are re-planned.
