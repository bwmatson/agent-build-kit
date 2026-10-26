# Design

## What was checked, and where

Read-only against the agent-build-kit checkout; paths are under `src/agent_build_kit/`.

- `pipeline/tier2.py` `stack_lock(path, timeout=DEFAULT_LOCK_TIMEOUT_SECONDS)` opens the file `a+`, then loops `fcntl.flock(handle, LOCK_EX | LOCK_NB)`,
  sleeping 0.05 seconds on `BlockingIOError`, and raises `TimeoutError(f"tier 2 is busy: waited {timeout:.0f}s for {path}")` once the deadline passes.
  `DEFAULT_LOCK_TIMEOUT_SECONDS = 3600` is a module constant with the comment "long enough for a queue of real tier 2 runs to drain".
- The lock is **an `flock` on a file, not a PID file**: the module docstring says the kernel releases it when the process dies. After acquiring, the
  holder truncates the file and writes `held since <timestamp>`; it does not truncate on release, and it records no unit and no process id.
- The timeout comes from nowhere configurable: the tier 2 runner in `pipeline/wiring.py` takes `timeout: float = DEFAULT_LOCK_TIMEOUT_SECONDS` and passes
  it to `stack_lock` in both of its paths (the repo's own tests, and the dev stack script path). `settings.py` has no setting for it. The lock file is
  `state_dir/tier2.lock` (`wiring.py`).
- The second caller is `verify_one` in `cli/pipeline.py`: it passes `timeout=wait` only when given a wait and turns `TimeoutError` into `StackBusy`.
  A round runs verification only when the lock is free (`unit-scheduling`, "Verification does not run on a stack in use"), so it never queues.
- `tier2-tests-have-their-own-time-limit` (archived) changed only the plugin that limits a single test. It did not touch the lock wait, which is why a
  unit still failed after an hour even with each test allowed thirty minutes.
- A span of waiting is a `span` ledger line whose `waited` names a bucket (`pipeline/spans.py`: `SLOT = "slot"`, `USAGE_PAUSE = "usage_pause"`); the
  slot wait is recorded by the unit's step in `cli/pipeline.py` with `spans.record_span(..., waited=spans.SLOT)`.

UNVERIFIED: whether `flock` waiters are served in arrival order. This code polls with `LOCK_NB` and never queues in the kernel, so the order in which
two waiting units acquire is whichever polls first after a release, not first come, first served. The builder checks it and either accepts it (a unit
may wait longer than another that came after it) or orders the waiters; this change does not.

UNVERIFIED: how `usage_report` buckets a `waited` value it does not know (it compares against `SLOT` and `USAGE_PAUSE` today). The builder checks that
`tier2_lock` is not counted as work or as a slot wait. The change `unit-timeline-is-recorded`, still open, turns those strings into a `WaitReason`
enum; if it lands first the new value is a member of it, and if not it is a constant beside the two.

UNVERIFIED: how the worker pool treats a worker blocked in the wait when a usage pause starts. The wait spends no model usage, so this change does not
interrupt it; the builder confirms the pause rules (`usage-pause`) already leave such a step alone.

## The choice: keep waiting, or give the unit back

Two ways to make the wait harmless.

**(a) The unit keeps waiting, with no deadline, and says so.** The step blocks in `stack_lock` as now, logs and records the wait, and runs when the lock
frees.

**(b) The unit is released to a waiting state.** At the lock it returns to `planned` with a cause such as `tier2_busy`, frees its slot, and a later
tick starts it again to retry.

**Recommended: (a).** Reasons:

- **Nothing is lost by waiting; something is by leaving.** At the lock, a unit has finished its build, its review loop and its tier 1 run; tier 2 is
  the last gate before the push (`tier2.py` docstring). Going back to `planned` means a later start re-enters a unit that is mid-pipeline: it must
  resume at the tier 2 node, as a parked unit does, and a restack or a moved base while it was away invalidates what it had done. Waiting keeps all of
  that exactly as it is.
- **The slot is not the scarce thing here.** `blocked-units-free-their-slot` (archived) frees the place of a unit that cannot run until *another unit's
  work merges*: that wait has no bound a person can see and is not progress. A unit waiting for tier 2 is waiting for a run that is already under way
  and will end within the hour; the lock is held by a unit that holds a slot itself, so the pipeline is making progress on the most important gate.
  The units that can queue are also bounded by the build slots (`max_concurrent_stacks`), so the queue cannot grow without limit. Freeing the slot for
  a unit that only comes back to the same queue would let a new unit start, finish its build and join the same queue: more waiting, not more finished
  work.
- **No new state.** (b) adds a cause and a state transition that the status, the graph, the counting rules (`A blocked unit does not hold a place` says
  which causes do not count) and the timeline would each have to describe, and a rule for whether the parked unit counts toward the limit. It would
  also interact with the usage pause, which already pauses and resumes units for a reason that is not a block. (a) reuses the span the slot wait
  already uses and adds one value.
- **A retry timer is a polling loop with a gap.** A unit released on one tick and retried on a later one can miss the moment the lock frees, and
  another unit can take it: starvation with no one at fault. (a) leaves the pipeline's own tick untouched.

What (a) costs, stated plainly: a waiting unit holds a build slot and its worktree while idle for up to an hour or more. If that shows in the time
reports (the `tier2_lock` span makes it measurable), releasing the slot is a follow-up (b) with the data to design it; it is listed under "Not included".

## No ceiling

The fixed limit is removed rather than made configurable. A ceiling would turn a slow queue back into a failed unit, the fault this change is for; and
a wedged holder is bounded elsewhere: the tier 2 command has its own time limit and each test its own, so a holder that hangs is ended by those and
frees the lock. A person who needs a unit out of the queue stops or requeues it. The wait is made visible so that a long one can be noticed and
acted on, not capped.

`tier2-lock-wait-is-configurable`, built first, makes the deadline the setting `limits.tier2_lock_wait_seconds` (default 5400); this change then makes "no deadline" the default, and the recommended fate of the setting is to stay as an optional ceiling that accepts null, to be confirmed with the person.

`stack_lock(path, timeout=None)` waits without a deadline when `timeout` is None, which the tier 2 runner now passes. `verify_one`, which takes an
optional `wait`, keeps passing it and keeps raising `StackBusy`.

## The holder record

The lock file holds one line of JSON the holder writes after acquiring and truncates before releasing: `{"unit": <unit id or a caller label>,
"pid": <process id>, "since": <ISO 8601 time with offset>}`. `stack_lock` gains a `holder` argument (the tier 2 runner passes its unit's id,
`verify_one` passes `verify <change>`). A file that is empty (free, or read in the instant between acquiring and writing) means no known holder.
This replaces the one line `held since <timestamp>`; a reader that cannot parse a line treats it as unknown rather than failing.

## The visible wait

While waiting, `stack_lock` reads the record at a fixed interval (five minutes; a module constant, not a setting) and calls an optional `on_wait`
callback with the holder and the seconds waited so far. The tier 2 runner passes one that logs
`tier 2 is busy: waiting for <unit> (held for <age>), waited <n>` through the tick's `say`. The first line is written at once, so the log shows the
wait began, then one per interval. When the lock is acquired the runner records one span with `waited="tier2_lock"` and the length of the wait (zero
waits record nothing, as the slot span does). The value is spelled like the other two (`slot`, `usage_pause`); the request's `tier 2 lock` is the same
idea in prose.

## Stale and dead holders

Because the lock is a kernel `flock`, a holder that dies releases it with its file descriptor, and the file descriptor is not inherited by
children (Python opens files non-inheritable), so a crashed run cannot wedge the tier. What remains is the *record*, which still names the dead
holder. Two cases, told apart by trying the lock:

1. **The lock is free and the record names a process that is not alive** (`os.kill(pid, 0)` raises `ProcessLookupError`; a `PermissionError` means
   alive). The record is stale: the next acquirer logs "tier 2 lock record from `<unit>` (process `<pid>`) is stale, ignored", overwrites it, and
   goes on. `abk status` shows the same as stale rather than as a holder. Nothing is broken because nothing is held.
2. **The lock is held and the recorded process is not alive.** Something else still has the file open. This is not broken: removing or truncating
   the file would let a second holder take a new lock on a new file while the first still runs the stack, which is the exact thing the lock exists to
   prevent. The waiter keeps waiting, and the log line and `abk status` say "held, but process `<pid>` of `<unit>` is gone". Whether this can happen
   at all depends on a child outliving its parent with the lock file open, which the code does not do; it is reported, never acted on.

A live holder that is wedged is shown with its age and is not broken (see "No ceiling").

## `abk status`

`abk status` already prints the pipeline's state from files, without taking locks. It gains one line when a holder is recorded: `tier 2: held by
<unit> for <age> (since <time>)`, from the record and a probe of the lock: a shared, non-blocking `flock` on a separate open of the file, released
at once. A probe that succeeds means the lock is free and the record, if any, is stale (shown as `tier 2: free (stale record from <unit>)` or
nothing). A probe that fails means held. UNVERIFIED: a probe takes the lock for an instant, so a poller's one attempt in that instant fails and
retries 0.05 seconds later; the builder confirms nothing there treats a single failed attempt as final. Where the status file is built was not
confirmed (no module under `cli/` is named for it; `docs/cli.md` documents `abk status`), so the builder finds it and the existing status tests.

## Tests, and no tier 2

The lock is a file and a clock. The tests fake the clock (the same `spans.clock` replacement the span tests use, and the loop's sleep) to pass hours
without waiting, hold the lock from a second file handle in the same process (`flock` conflicts between open file descriptions of one process), and
write records for dead pids. Nothing here needs the live stack, so both groups are `tier1` and `tasks.md` opts out of acceptance with a reason.

## Not included

Releasing the slot of a waiting unit (option (b)), ordering waiters first come, first served, listing the waiting units in `abk status`, and a
setting for the log interval.
