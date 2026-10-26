# Design

## Three classes, and the third reordered

Ready units already start in three classes: a unit with an open pull request, then a unit resuming a build paused or held before a
pull request, then a unit that has never run. The first two keep the order they have, by when they were planned. Only the third
changes.

## The effective age

For a ready unit that has never run, the set of units waiting on it comes from the shared helper `unit-priority` adds
(`waiting_on_me`): the reverse of the dependency and merge-before edges, across repos (a cross-repo dependency makes a waiter just
as a same-repo one does; the dependents lookup the restack uses stops at the unit's own repo, so it is not reused), followed
through chains, skipping merged, closed and satisfied units and looking through satisfied ones, with a visited set so a cycle
cannot loop. This change does not build a second reverse graph, so there is one definition of who waits on a unit. The unit's effective age is the earliest planned position among itself and that set. Units start in
increasing order of effective age, so a prerequisite of a unit planned long ago starts before newer units, and a prerequisite of
only newer units waits for its turn among the others. Ties go to the unit's own planned position. A unit that nothing waits on
has its own age. The order does not look at how long a chain is or how many units are in it.

A unit that waits on two prerequisites gives its age to both. A dependent counts whether it is idle in a place or not yet started,
since what matters is how long it has been waiting for the work.

## Priority comes first

Inside the class of units that have never run, the order is (effective priority, effective age, planned position).
`unit-priority` defines the priority and its effective value; this change adds the age as the tie-break between units of equal
effective priority, where that change leaves the planned position. A prerequisite of a priority-1 unit therefore goes ahead of an
older priority-3 unit that nothing waits on, whatever the ages. Between units of the same effective priority the age rule is
unchanged, and when no unit has a priority the order is the age order alone.

## The limit

The order decides only which ready unit takes a place that is free. The limit on units in progress is not exceeded, no place held by
a waiting unit is lent, and the cap on units running at once is unchanged. A prerequisite still waits for a place to free; that idle
waiting units hold places is handled by `blocked-units-free-their-slot`, which builds on this order.

## What is excluded from the order

A unit outside the ones named by `--only` is not started and is not moved forward by a unit that waits on it. Neither is a
unit that a lease holds for a chat or that a backoff keeps from starting. The round's evaluation turns all three into `held`
units before it picks the ready ones, so from the units alone the age calculation cannot tell them from a unit that is held
for another reason and does wait. The exclusion set is therefore passed in explicitly: the evaluation names the units it
excluded, and the calculation neither starts them nor takes an age or a priority from them as waiters. The same set is the helper's `excluded`
argument.

## A failed prerequisite

A failed unit is never started by this order; it holds its place and needs a requeue. When it has units waiting on it, the status
lists it with the number waiting and says to requeue it, and the reason given when nothing could start names it instead of saying
only that nothing is ready.
