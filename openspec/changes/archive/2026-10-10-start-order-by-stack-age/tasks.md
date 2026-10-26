# Tasks

Acceptance: none — the order is pure over a unit graph; tier-1 tests prove each case.

Priority: 2

## 1. [agent-build-kit] [tier1] Units that have never run start by the age of their stack

Needs: unit-priority group 1 merged — the order reads the effective priority and the shared waiting-set helper and the priority field it builds; the sort by priority is written here, not there

Done when ready units that have never run start in order of effective priority, then effective age, the limit is never exceeded,
and a failed prerequisite is named.

- [x] 1.1 Test: a prerequisite of an old unit starts before a newer unrelated unit; a prerequisite of only newer units does not
      take an older unit's place; two units are ordered by their oldest waiter and not by depth or by how many wait; a tie goes
      to the unit's own planned position; work with an open pull request and a resumed build still start first.
- [x] 1.2 Test: a ready unit that gates several waiting units, all planned before some standalone ready units, starts before
      those standalone units even though it was planned after them; a prerequisite of a priority-1 unit starts before an older
      priority-3 unit that nothing waits on, and effective age decides only between units of equal effective priority.
- [x] 1.3 Test: with the limit reached an unblocker does not start, with one place free it takes it before a newer unit and not
      before an older one, and no place held by a waiting unit is lent.
- [x] 1.4 Test: the waiting set (the helper from `unit-priority`) follows chains, skips merged, closed and satisfied units and looks through satisfied ones, a unit
      waiting on two prerequisites gives its age to both, a waiter in another repo counts, a cycle does not loop, and a unit
      outside `--only`, one held by a lease and one in a backoff is neither started nor moved forward.
- [x] 1.5 Test: a failed unit with units waiting on it is listed by the status with the number waiting and a requeue hint, and the
      reason given when nothing could start names it.
- [x] 1.6 Pass the units the evaluation excluded (`--only`, a lease, a backoff) into the order as an explicit set, and reuse the
      waiting-set helper `unit-priority` adds (`waiting_on_me`, across repos) instead of building a reverse graph.
- [x] 1.7 Compute each ready unit's effective age and order the units that have never run by (effective priority, effective age,
      planned position), name a failed prerequisite in the
      status and the reason, and log why a unit started ahead of an older one.
- [x] 1.8 Update `docs/architecture.md` (the paragraph on free slots, "each in planned order") and the pipeline skill, which repeat
      the start order (`docs/cli.md` does not), and add a changelog entry.
