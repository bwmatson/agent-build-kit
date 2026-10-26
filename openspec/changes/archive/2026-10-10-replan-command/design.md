# Design

## Planning is by change

The planner is handed one change's whole `tasks.md` and returns that change's whole graph of units, with the other changes' units only as context. The
store then merges the graph by unit id. There is no planner call for one group or one unit, and there should not be one: a unit's dependencies and joins
depend on its siblings. So the command takes changes. For convenience it also accepts a unit id (`unit-priority/2`) and maps it to the change that
carries it, saying so, and the result is reported per unit, which is the level a person reads.

## The command

`abk replan [CHANGE ...] [--all] [--failed] [--forget]`

One kind of selector is required. The names are the folder names of the active changes; a unit id maps to its change. `--all` is every active change,
`--failed` every change whose record says the last plan did not succeed (still failing, or given up). With no selector the command lists every change
with its plan state (`planned`, `failing 2/3`, `given up`, `never planned`) and the usage, and plans nothing.

By default it plans now. For each selected change it removes the recorded plan (hash and attempts), runs the planner for those changes only, and
then links the `Needs:` lines, as a tick does, so the stored units are what the next tick would have produced. It first prints how many model calls it
will make. `--forget` removes the records and stops there: no call, and the next tick plans them.

It refuses a name that is not a change, a change without a `tasks.md`, and a change whose task groups have tag errors (the message a tick gives:
run `abk tags`), and plans nothing for them. The exit status is 0 when every selected change planned, 1 when any failed or was refused, and 2 for a
usage error.

## What a replan does to units

The store already guarantees the rest. A unit that has started (running, in review, failed, held) and one that has finished (merged, satisfied) keeps its
state, branch, pull request, feedback and history. A unit that is only planned takes the new shape: dependencies, estimate, groups, tier. An unstarted
planned unit the new plan no longer contains becomes `unplanned`, not deleted. A unit that took in groups of other changes keeps them. A join the plan
proposed is dropped when a unit started meanwhile, and is reported.

The command does not add to this. It reads the store before and after and prints only the differences: dependencies added and removed, merge gates
added and removed, estimate and tier changes, units that became `unplanned`, joins dropped, and each started unit it left alone ("kept:
unit-priority/1, running"). For example, "start-order-by-stack-age/1: no longer depends on unit-priority/2". Nothing is silent, and nothing is printed
for a unit that did not change.

## Why linking `Needs:` stays additive

Linking adds the dependencies the `Needs:` lines name and never removes one, because a dependency in the store may be the planner's or a person's and
the linking cannot tell. Removal is therefore a replan's job: the plan rebuilds each planned unit's dependencies and the linking adds the `Needs:` ones
back.

## The recorded plans

The file of recorded plans is written whole by each writer, and a running pass plans every round, so a command run beside a pass could lose an update.
The read-modify-write takes a file lock and the write is atomic. Two planners racing on one change produce the same stored shape as one, because the
units are written through the store's exclusive lock.

## The messages

The line that a change is giving up until its `tasks.md` changes, and the status line for a failing plan, also say to run `abk replan`, so the way out is
found where the problem is shown.

## Not included

A dry run that shows what a replan would change cannot be free, since the plan is a model call; it is left for later. So is replanning by itself when a
neighbouring change's units change: the command comes first, and how often that is needed is something the timeline data can show.
