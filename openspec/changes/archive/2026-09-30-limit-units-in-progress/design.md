# Design

## What is there now

`units.open_pr_count` counts units with a pull request that is not merged,
closed or satisfied; `builds_heading_for_pr` adds running units with none yet;
`new_start_room` subtracts both from `max_open_prs`, and `ready_units` starts
at most that many units without a pull request. A unit with a pull request is
always allowed through, and `_start_rank` orders the rest: open pull request,
then a paused build, then new.

## In progress

One predicate, `in_progress(unit)`, replaces the two counts:

- **counts:** `running`, `in_review`, `held`, `failed`; and `planned` when the
  unit has a pull request or a step to resume from — reworks, resumes, units
  held before a step. Also any state other than those below while a pull
  request is open, so a pull request on an `unplanned` unit is not lost from
  the count.
- **does not count:** `merged`, `closed`, `satisfied`; `unplanned` without a
  pull request; `planned` with neither a pull request nor a step to resume —
  new work, including new work blocked on a dependency.

"Started" is read from the store's own fields, the pull request number and the
resume step, so no forge call and no branch inspection is needed.

## Where it gates

`ready_units` is still the one place that answers "what may start". The room
for new starts is `max_units_in_progress - count(in_progress)`. A ready unit
that is itself in progress (a rework, a resume) is never held back by the
limit — it is already counted, and starting it adds nothing. A ready unit that
has never started is admitted only while there is room, in `_start_rank` order.

So a unit can never finish and then wait: the only thing the limit refuses is
the first step of a unit that has done nothing yet.

## Removing the old setting

`max_open_prs` goes, with `Installation.max_open_prs`, `open_pr_count`,
`builds_heading_for_pr` and `new_start_room`. No installation sets it yet, so
no alias is kept: the schema forbids unknown keys, and one that named it would
be told so at load like any other misspelling.

## Saying so

The existing "queue is full" line becomes: `N units in progress, limit M — …`
listing the in-progress units by state (in review, reworking, paused, failed),
so a failed unit holding a place is visible as the reason nothing new starts.
The same in `abk status`.
