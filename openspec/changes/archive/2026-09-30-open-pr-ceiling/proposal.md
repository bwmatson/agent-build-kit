# Proposal

## Why

Two limits shape how much work is in flight. `max_concurrent_stacks` bounds units
being built at once, and `stack_depth_cap` bounds how far a chain runs ahead of
review. Neither bounds the thing that actually accumulates: pull requests waiting
for a person. The code says so on purpose — the concurrency cap limits "how many
units are being built at once — not how many PRs await review, which is
deliberately unbounded."

That was a reasonable default when building was the scarce thing. It is not now.
Reviewing is the constraint: units fail in the review loop, the review round cap
had to be raised, and the usage window is spent mostly on review and rework. A
pipeline that keeps producing while the queue grows converts agent time into a
backlog, and a backlog rots — every merge below a waiting pull request costs it a
rebase, a conflict resolution and a fresh review round.

We watched all of it in one day: six pull requests open at once, three of them
conflicted by merges that landed beneath them, one of them conflicted twice. The
work was done well; there was simply more of it than anyone could land, and the
cost of holding it grew with the queue.

There is a second half to the same cost. When slots are free, they are filled in
the order units were planned, and a unit with an open pull request that needs a
rework is simply `planned`, like one that has never run. A pull request with
failing checks waited for a slot behind units that had not started, because it
belonged to the change planned last. Every hour it waits is an hour in which more
merges beneath it, and the person who asked for the change is waiting too.

## What Changes

- **`limits.max_open_prs`, default 5**, configurable per installation and counted
  across the workspace, like the concurrency cap and for the same reason: it is one
  person's attention being rationed, not one repository's.
- **At the ceiling, no new unit starts.** Work already in flight finishes and opens
  its pull request as normal — a built unit whose pull request is refused would
  leave the work stranded, which is worse than a queue one over the line. So the
  count can exceed the ceiling briefly, and the ceiling is a gate on starting, not
  a promise about the number.
- **Work on pull requests that are already open is never blocked.** A rework, a
  restack, a review round and a push all continue at the ceiling, because none of
  them adds a pull request and all of them are how the queue drains. Only a unit
  that would open a *new* one waits.
- **Free slots go to existing work first.** Among the units that may start, those
  with an open pull request come first, then those resuming a build that was
  paused or held part-way, then units that have never run; within each, the order
  units were planned in, as now. This orders the units the other rules allow — it
  does not let a unit past the ceiling, the depth cap or a dependency.
- **The pipeline says when it is holding for this reason.** "Nothing ready to
  build" reads as idleness; at the ceiling it should say the queue is full and name
  the count, both in a tick's log and in `abk status`.

## Impact

- **agent-build-kit**: the readiness rules and the order they return units in, the
  configuration and its validation,
  and one line each in the tick log and the status output.
- Installations get a default they can raise. A workspace that wants today's
  unbounded behaviour sets it high deliberately.
- The visible effect is fewer units started while a queue is full, and therefore
  fewer stale branches to rebase when something merges — which is the whole point:
  the tokens saved are the ones that would have gone on carrying work rather than
  producing it.
