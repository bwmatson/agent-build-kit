# Design

## What blocked means

A planned unit is blocked when it waits on another unit: a dependency or a unit it must follow that has not merged or been satisfied
(`waiting_on`), a predecessor that is being reworked, failed or held, or the cause `gated` or `upstream_went_back`. Nothing else
makes a unit blocked. A backoff for the host being unavailable, a lease for a chat, a tick limited to named units and a usage pause
are not waits on another unit and do not free a place: the unit is expected to run on its own when they end. `blocked` is derived
each time from the units, as `waiting_on` is; there is no new stored state.

## Counting

`in_progress` returns false for a blocked planned unit however much it has done, and true again when it is not blocked. Running, in
review and failed units are unchanged, and a held unit still does not count. A failed prerequisite still holds its own place and
is named by the status, as `start-order-by-stack-age` requires.

## The handoff, before the classes

Before the three classes (an open pull request, a resumed build, a unit that has never run) are applied, the blocked units that would
otherwise have counted are listed, and for each a ready prerequisite that has never run is chosen to start into its place. A
prerequisite that blocks several of them takes one place and is ordered by the oldest; several prerequisites are ordered by
(effective priority, effective age), the rule of `unit-priority` and `start-order-by-stack-age`, which stays in force and is not
replaced, and the set of units waiting on a prerequisite is the shared helper those changes use. A blocked unit whose only waiters have never started held no place,
so its prerequisites get no handoff and follow the effective age order. The handoff does not add a place: the blocked unit stopped
counting and the prerequisite begins to, so the total is unchanged. The cap on units running at once, `--only`, a lease and a backoff
apply to the prerequisite as to any unit.

Two blocked units on one prerequisite free two places and give one to it. The second goes to the next unit by the usual order. When the
prerequisite merges, both count again and each waits for room; as existing work they come ahead of units that have never run, in
the order they were planned, so the first places that free go to them and the count never passes the limit.

## An unblocked unit waits for room

A planned unit that was blocked and no longer is starts only while the number of other units in progress is below the limit, so that
an unblocked unit cannot push the count over. This changes the rule that work in progress always continues for a planned unit only: a
rework, a restack, a review round, a push and opening a pull request of a unit that is running or in review proceed at the limit as
before, and so does a planned unit paused by a usage pause.

## Reporting

The queue line gives the units counted by state as now, then how many blocked units are not counted, and the status lists each blocked
unit with what it waits on. The graph labels a blocked unit as blocked.

## Related changes

`start-order-by-stack-age` left this open (that waiting units hold places is a separate question) and is a prerequisite, as is
`unit-priority`, whose effective priority orders the handoff. A unit parked by
`dependents-follow-their-parent` has the cause `upstream_went_back` and is blocked. `usage-read-on-decision` reads usage when a
decision could change; the handoff is one more such decision.
