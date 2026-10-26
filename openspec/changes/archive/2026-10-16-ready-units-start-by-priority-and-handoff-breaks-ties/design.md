## Context

`ready_units` (`pipeline/units.py`) builds `handoff = _handoff(ready, graph, excluded)`, sorts the remainder by `_start_key` and iterates
`[*handoff, *rest]`. So every handoff unit precedes every other ready unit, including open-pull-request reworks and more urgent new units.

## Decisions

- **One sort, not two lists.** `_handoff` stays the chooser of which units take a freed place (priority and age order, one unit per freed place, one
  place per blocked unit). `ready_units` then sorts all ready units once by `_start_key`, which takes the chosen ids and, for rank 2, returns
  `(2, urgency, 0 if handed off else 1, age)`. Ranks 0 and 1 are unchanged. The sort is stable, so equal keys keep the planned order.
- **Only the order changes.** The loop, `drawn`, `counted`, `_waits_for_room` and `max_concurrent` are untouched. A handoff unit that is offered later
  still finds its place, because the blocked unit it replaces is already uncounted; a more urgent unit that arrives first takes a place from the
  count like any other, so a full queue still blocks everyone and nothing is reserved.
- **Status.** `_ready_queue_lines` already has the evaluated `ready` list, the view and `excluded`. `_handoff` becomes the public `handoff_units`
  (same signature, a pure function) and the status calls it on that list, appending ` (handoff)` after the reason. Recomputing is exact because the
  status evaluates with the limits off, so `ready` is the full ready list `ready_units` saw. The alternative, returning the set from `ready_units`,
  would change its return type for every caller.

## Needs

No `Needs:`. The unbuilt changes `a-unit-in-a-held-split-is-not-started`, `a-dropped-unit-parked-on-a-split-takes-no-place`,
`the-whole-moved-base-flow-runs-in-the-restack-lane` and `limits-split-into-global-and-project` (groups 9, 10, 13) touch the ready filter, the
counts, the status lines or the documents; the overlap is textual, and this change reads none of what they add.
