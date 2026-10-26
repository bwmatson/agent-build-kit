## Why

A unit can be admitted by the scheduler and put back by the build's own guard, over and over, for as long as one stale dependency stays in its record.
In a real case a unit was admitted (nothing it waited on, by `waiting_on`), became `running`, and three seconds later was set back to `planned` with the
cause `upstream_went_back` and the note that a unit of another change "is unplanned — it went back after this unit started". Each pass ran a prepare and
a restack first and wrote a history entry. It repeated about twelve times over a day and a half; nothing cleared it until a replan rewrote the unit's
stored dependencies.

The two readings of one dependency disagree. The scheduler's `waiting_on` skips a same-repo parent in `BUILDS_NOTHING` (`unplanned` or `retired`; "a
unit the plan dropped builds nothing, so nothing waits on it"). The build's step-boundary guard, `build_upstream_incomplete`, tests only that a same-repo
parent is not `in_review`, `merged` or `satisfied`, so an `unplanned` or `retired` parent counts as a predecessor that "went back". The scheduler lets
the unit in; the guard sends it out. The same untested state is read as "changing" by `follow_predecessors`, which sets units in review back to
planned.

The stale edge itself comes from renumbering. A `Needs: <change> group N` resolves to the unit that carries that group; a replan can move the group to
another unit and drop the first, which becomes `unplanned`. `link_needs` only adds edges (and prunes only those an added target reaches), and a replan
leaves a started unit's dependencies alone, so the edge to the dropped unit stays. Two units still carry such an edge today.

## What Changes

- **The guard agrees with the scheduler.** `build_upstream_incomplete` ignores a same-repo dependency whose unit builds nothing, using the same
  `BUILDS_NOTHING` constant `waiting_on` uses. A parent that is `planned`, `running`, `failed` or `held` still holds its child.
- **The other readings of "not reviewed" agree too.** `why_branch_is_changing` and the loop in `follow_predecessors` treat a parent that builds nothing
  as settled, and the room rule `_parent_went_back` skips a parent that now builds nothing.
- **A stale edge is dropped.** Each tick, `link_needs` removes a stored dependency on a unit that builds nothing and that no `Needs:` line declares, and
  logs `<unit>: dropped dependency <parent>: it builds nothing`.
- **A loop is named, whatever the cause.** A unit that goes from `running` back to `planned` (or `held`) three times in a row with the same cause, each
  run shorter than two minutes, is logged once as looping and listed by `abk status` under `looping:` and marked `(looping)` in the ready queue. The
  store detects it in the one place every state change is written. The upstream guard's `held repeatedly by <parent>` wording is kept, derived from the
  stored count. Two new settings, `global_limits.bounce_limit` and `global_limits.bounce_span_seconds`, tune it. It is visibility only: nothing is
  held or rescheduled because of it.
- **Documents.** `docs/unit-graph.md`, `docs/architecture.md`, the `abk-pipeline` skill and the changelog say it.

## Impact

- agent-build-kit: `pipeline/wiring.py` (`build_upstream_incomplete`, `why_branch_is_changing`, `follow_predecessors`), `pipeline/units.py`
  (`_parent_went_back`), `cli/pipeline.py` (`link_needs`, the status, the ready queue, the log line), `pipeline/unit_store.py` (the bounce counter in `_record_state`), `config.py` (the two
  settings), the documents, the two skills, the changelog.
- It does not stop a loop (design.md lists which paths protect themselves; stopping loops is a separate decision). It does not change `waiting_on`, the planner, a plan's treatment of a started unit's dependencies, or what an `unplanned` unit does.
- No `Needs:` on other changes. Other changes touch the same functions' neighbourhood (the status formatting, `link_needs`); a rebase resolves it.
- Priority 0: the loop costs a build worker on every tick it repeats, for as long as the edge stands.
