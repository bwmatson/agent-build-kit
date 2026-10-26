# Proposal

## Why

`failed-units-waiting-on-a-prerequisite-free-their-slot` stops a failed unit that waits on another unit from holding a place, and leaves it
`failed` with nothing to requeue it when the wait ends: "a person still requeues it". That leaves the work half done. A failed unit's
prerequisites cannot be ones it needed to start, since everything it needed was met at its first run. They are ones added after it failed, to
unblock it: a `Needs:` line a person or a fix-change mechanism wrote, or a predecessor sent back for rework. Nobody adds one meaning "leave
this failed once it is met". So when the wait ends the unit sits `failed`, counted again, until someone notices and runs `abk requeue`. A
blocked planned unit resumes by itself at that moment (`release_gated`); a failed one is the odd case.

The user chose to keep the unit `failed` while it waits (the status shows the wait plainly) and to requeue it automatically when the wait
ends.

## What Changes

- **A wait is recorded and its end is detected.** Each pass records, on a failed unit, the units it is waiting on when `failed_waiting` first
  holds. When `waiting_on` is empty and the unit is still failed, the wait has ended.
- **Once per wait.** The record is cleared by the requeue, so a unit that fails again with no new wait is not requeued again; a prerequisite
  added later starts a new record and a new requeue.
- **The requeue is `abk requeue`'s own delivery,** in a mode chosen by a fixed rule from the store (environmental cause: resume; a saved
  tier 1 or tier 2 failure: rework; otherwise resume), with a history note naming the prerequisite. A person's recorded note stays as guidance.
- **`global_limits.wait_end_requeue`** is `auto` (default), `resume`, `rework` or `off`; `off` restores today's behaviour.
- **Left alone:** a held unit, a unit whose prerequisite was closed (it stays failed with a status line saying so), a failed unit with no wait,
  and units already parked planned and `gated` by the failure-fix and flaky-test mechanisms.
- **Reported:** the status says how many failed units were resumed when their wait ended today.

## Impact

- agent-build-kit: a pass step beside `release_gated`, two stored fields, the setting, `requeue`'s history note, the status line, the
  command, architecture and configuration documents, the pipeline and config skills, the changelog.
- Spec: `unit-scheduling` (adds three requirements). The sentences in `failed-units-waiting-on-a-prerequisite-free-their-slot` that say a
  waiting failed unit is "never requeued by the pipeline" exist only in that change's unarchived delta, so they cannot be modified here; this
  change ADDS the requirement that supersedes them, and the builder narrows those sentences in the docs it touches.
