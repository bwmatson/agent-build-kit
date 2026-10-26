# Proposal

## Why

A tick does: pause and usage checks, refresh (fetch and poll), convert in-flight units,
plan, link needs, verify and archive finished changes, reclaim stranded units, then
evaluate and submit builds. The loop that keeps slots full inside a pass repeats only the
refresh and the evaluate. A pass lasts as long as its longest unit, an hour or more for a
large one, and the timer cannot start another tick while it runs. So for that hour:

- a change written after the pass began has no units, is missing from the graph page, and
  its ready work waits although a slot is free (this was seen with one unit running against
  a cap of two and three new changes unplanned);
- a change whose units have all merged is not verified or archived;
- a stranded unit whose run was killed is not reclaimed;
- the usage guard is not asked again before more units start.

- a unit whose thread was resumed by an event while the pass runs (a reviewer's comment, a
  requeue, a restack) is marked running and then waits, with no agent on it, until the next tick
  starts; meanwhile it counts as holding a slot, so with the cap reached nothing else starts. This
  was seen: a unit sat running for most of an hour after a review comment, with one other unit
  building and seven ready units waiting.

These are one defect, work that a tick picks up is not picked up by the loop, and the two
sequences are written separately, so each new step added to the tick has to be remembered
for the loop.

## What Changes

- **A round** is one function holding the shared sequence: refresh, convert in-flight units,
  plan, link needs, verify, archive, reclaim stranded units, check the usage guard, then
  start the resumable units (threads resumed by an event or left partway) and evaluate and
  submit what fits in the free slots.
- **A slot is held by a run, not by a state.** A `running` unit with no run on it and a thread to
  resume is work waiting to start, not a unit occupying a slot: the round starts it, and the
  concurrency cap counts only runs actually in flight.
- **The tick runs one round** at its start (after its pause checks, as now), and **the
  pass runs one round on every refresh interval.** The timer stays a oneshot every five
  minutes; while a pass runs, the loop is the trigger.
- **Rounds are safe to repeat and to run beside builds.** Planning skips an unchanged
  change by its hash. Verification and archive act only on changes whose units have all
  merged. Reclaim skips any unit a build in this pass holds or has just been handed. A round
  never touches a running unit's state, branch or pull request.
- **Verification is not run on top of a stack in use.** Verification deploys and runs
  live-stack tests, so a round runs it only when the live-stack lock is free, and otherwise
  leaves the change to the next round instead of waiting.
- **The guard is asked every round.** A round that finds the usage window spent stops
  submitting and records the pause, as a tick does; the builds in flight continue, as now.
- **A failure in a round does not end the pass.** Each step is guarded and logged, and
  tried again at the next round.
- **Dry run and `--only` stay tick-only,** and mean the same as now.
