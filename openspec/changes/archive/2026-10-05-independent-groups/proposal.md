# Proposal

## Why

The planner turns a change's task groups into units in order, and each unit
depends on the one before it (`depends_on=(units[-1].id,)`). That is right for
work that builds on earlier work, and wrong for work that does not: a platform
group that only adds a receiver, beside application groups that will send to
it, shares no code with them, and a unit in another repo has nothing to stack
on.

Because the order is the only thing a change can express, the options today
are to wait, or to split the work into a second change just to get it built in
parallel. The second distorts the specs: two changes describe one piece of
work, and the link between them has to be written as a `Needs:` line after the
fact. The author knows which groups are independent when writing the tasks; it
should be said there.

## What Changes

- **`Independent: <reason>`** on a task group says the group does not depend on
  any earlier group of its change. The reason is required, as for `Separate:`.
- **The planner honours it.** The group's unit has no dependency on the previous
  unit, so it is ready as soon as the change is planned, and runs in parallel
  with the others where slots allow.
- **The chain closes around it.** The group after an independent one depends on
  the last unit before the independent one, as if it were not there. The
  exceptions are groups that by definition follow everything: a `[narrow]` group
  and an `[acceptance]` group depend on all units of the change, independent or
  not.
- **It is never joined.** An independent group is not combined into the unit
  before it, nor are others combined into its unit, since joining is a form of
  ordering.
- **`abk tags` checks it.** The line needs a reason, the first group may not
  carry it (there is nothing to be independent of), and it cannot be combined with
  `[contract]`, `[narrow]` or `[acceptance]` on the same group.
- **The graph page shows it** as a unit with no edge from its predecessor.
