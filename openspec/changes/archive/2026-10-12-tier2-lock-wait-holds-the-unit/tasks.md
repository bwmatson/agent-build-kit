# Tasks

Acceptance: none — the lock is faked in tier 1 (a held file handle, a replaced clock, a record naming a dead process); nothing a consumer sees changes except that a queued unit is no longer failed, and no live-stack run is needed to show it.

Priority: 2

## 1. [agent-build-kit] [tier1] Wait for the tier 2 lock without a deadline, and say who holds it

Needs: tier2-lock-wait-is-configurable group 1 merged — the setting this change builds on must exist first

Done when a unit queued behind a holder of any length is never failed for waiting, the wait is logged and recorded as a span, and the lock file names its holder and ignores a stale record.

- [x] 1.1 Test: with the lock held from another file handle and the clock moved past the old 3600 seconds, `stack_lock` without a timeout keeps waiting and takes the lock when the holder lets go; no `TimeoutError` is raised.
- [x] 1.2 Test: a tier 2 runner with the lock held for longer than an hour runs its tests once the lock is free and returns its result.
- [x] 1.3 Test: while it waits, a line naming the holder's unit and how long it has held the lock is logged at once and again at each interval, and no line is logged when the lock was free.
- [x] 1.4 Test: a wait that ends records one `waited = tier2_lock` span with the unit, change and the seconds waited; a lock taken at once records none.
- [x] 1.5 Test: the holder writes its unit, process id and start time into the lock file, and the file is empty again after release, including when the body raises.
- [x] 1.6 Test: a free lock whose record names a process that is not alive is logged as stale, overwritten by the next holder, and does not delay it.
- [x] 1.7 Test: a held lock whose recorded process is not alive is not broken: the waiter keeps waiting and logs that the holder's process is gone.
- [x] 1.8 Test: `verify_one` with a wait still raises `StackBusy` when the lock stays held past it.
- [x] 1.9 Remove `DEFAULT_LOCK_TIMEOUT_SECONDS`; give `stack_lock` a `timeout` of None meaning no deadline, a `holder` and an `on_wait`; write and clear the record; pass the unit's id and a logging callback from the tier 2 runner in both of its paths; record the span.
- [x] 1.10 Add the span value beside the two existing ones (or to `WaitReason` when `unit-timeline-is-recorded` has landed), and confirm `usage_report` counts it as neither work nor a slot wait.

## 2. [agent-build-kit] [tier1] Show the holder and its age in `abk status`

Done when `abk status` names the unit holding tier 2 and for how long, shows a stale record as stale, and says nothing when the lock is free and empty.

- [x] 2.1 Test: with the lock held and a record naming a unit and a start time, the status prints `tier 2: held by <unit> for <age>` with the age worked out from the replaced clock.
- [x] 2.2 Test: with the lock free and a record naming a dead process, the status shows the record as stale and not as a holder, and does not change the file.
- [x] 2.3 Test: with the lock free and the file empty or missing, the status prints no tier 2 line.
- [x] 2.4 Test: with the lock held and the recorded process gone, the status says the holder's process is gone and that the lock is held.
- [x] 2.5 Test: reading the status does not leave the lock held, and a waiting `stack_lock` acquires it right after.
- [x] 2.6 Add the lock probe and the status line.
- [x] 2.7 Document the wait, the holder record and the status line in `docs/architecture.md` and `docs/cli.md`, and add a changelog entry.
