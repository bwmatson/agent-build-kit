# Design

## What already holds

Usage is checked at step boundaries. `checkpoint(next_step)` calls `may_start()` and,
when the window is full, records the unit `planned` with `paused before <step>` and a
`resume_from`, returning an outcome of `paused`. Nothing samples usage while a step
runs, and nothing kills a running agent for usage. That is the right design: a step
half-done is worth more than a step stopped politely, and the pipeline's own rule is
that in-flight work finishes.

`reclaim_stale` covers the other interruption — a tick killed by a signal — by
committing what the run left and requeueing at the step it was in. So a mid-step stop
already survives, and survives with its partial work.

## The case that is not covered

An agent refused for usage does not always exit non-zero. It can report the refusal in
prose and finish cleanly, and then:

- the runtime sees a successful run, because the exit code says so;
- the refusal classifier never looks, because it classifies failed exits;
- the runner counts commits, finds none, and fails the unit.

The information needed to tell that apart from a genuine empty run is not in the
agent's output at all — it is in the account's usage, which the pipeline already reads
and caches for the guard. So the check is a cached reading at a point already reached,
not a new call, and certainly not a probe during the step.

## Deliberately defensive

No instance of this has been observed, and the change says so rather than implying
otherwise. It is worth building for an asymmetry: if the case never happens the
classification is dead code that costs one cached read, and if it happens once it costs
a rebuild plus a person's time working out that the log has the answer and the store
does not.

The alternative — parsing the agent's prose for a refusal — was rejected. It would
depend on a vendor's wording, would break silently when that wording changes, and every
runtime would need its own version. The usage reading is the pipeline's own fact.

## Why the same shape as a boundary pause

Reusing `planned` plus a note beginning `paused before <step>` means the graph, the
coming state labels and the resume all work with no changes: the graph derives
`paused: usage` from that prefix, and a `planned` unit is already a candidate for the
pass the pause scheduled. A new state or wording would need each of those taught about
it, for a case that is by definition rare.

## Boundaries

This change does not: interrupt a step, read usage during a step, alter a threshold or
the ramp, change what `reclaim_stale` does, or decide anything about a step that ends
empty while the window is healthy — that is the companion change about a unit whose work
is already done.
