# A short dispatcher and detached unit workers

> The direction from here is [orchestration.md](orchestration.md): the same dispatcher-and-workers shape as one model with a local and a cloud deployment, each
> part an interface with an implementation per deployment. The mechanisms below (local locks, the wake file, transient systemd units) are what its local
> implementations start from.

This document describes what exists: a tick is a short **dispatcher** that decides what runs, **detached worker processes** each carry one unit's work
(build, resolve or verify), a **wake** path lets a finished worker be noticed in seconds, and one **collector** is the only thing that polls the outside world.
A tick no longer owns any build, so it exits at once and a long unit delays nothing but its own slot. Before the cutover one tick process ran every build as a
thread and lasted as long as the longest unit in it; the [history](#history) is short. Paths and function names are where the work happens.

## Goals and non-goals

**Goals**

- A unit that finishes, a merge that lands, a person's `abk requeue` and a changed configuration are acted on in seconds, not at the end of a tick.
- Merged kit code and a changed configuration take effect for the next unit that starts, without waiting for running units.
- A long unit blocks nothing but its own slot. A crashed or restarted dispatcher touches no build, and a killed worker touches one unit.
- Capacity limits (`max_concurrent_stacks`, `max_units_in_progress`, the emergency lane, per-account slots) mean the same thing and hold across processes.
- API cost does not grow with the number of workers or the polling cadence: workers read shared snapshots and never poll.

**Non-goals**

- No new scheduler policy: what is ready, in what order, under which limits, is the current logic.
- No change to a unit's graph, its checkpointer, its resume semantics or the sandbox.
- No long-running daemon and no webhook endpoint in the first version (see [options considered](#options-considered)).

## Before the cutover

- **Process model.** `abk tick` was a systemd `Type=oneshot` service started by a timer. One process ran a first round and then a loop in which a thread pool ran each unit's build graph in a worker thread;
  it woke on a build finishing or every five minutes, and exited only when nothing was in flight. Agent steps were subprocesses of those threads, so killing the tick killed every build in it, and the next tick resumed them from their checkpoints.
- **Loaded once per process:** the configuration, the kit code, the planning sync, the usage allowances and the pool size. Refreshed every round: the unit store, planned hashes, PR snapshots, pause markers and leases.
- **Evidence** (one installation's journal over about a month of ticks): idle ticks had a median of 0.5 minutes, built ticks a median of 26.9, p90 114 and a maximum of 465 minutes (7.7 hours).
- **What waited for the next tick:** a dependent on a merge edge (the tick number was fixed per process, so a merge seen during a tick counted as loaded only for a later process); a unit put back for a cause outside a fixed list, and the per-pass rebuild cap;
  once-per-tick work (allowances, landing, the planning sync, the pool size); and anything a running process never saw, such as a kit merge, a configuration edit or a person's requeue.

## The design

**One principle: process lifetime stops being code, configuration and capacity lifetime.** A short dispatcher decides; a worker lives as long as one unit's work.

```
 timer (1-2 min) ──┐                              ┌── worker: build  unit-A ──┐
 wake path  ───────┼──► dispatcher (short) ──────►├── worker: build  unit-B ──┼─► exit ─► touch runs/wake
 person: requeue,  │    lock · collect · plan ·   ├── worker: resolve proj-X ─┤
 release, approve ─┘    land · verify · admit ·   └── worker: verify change ──┘
                        spawn · exit
          shared files (flock, atomic):  units.json · unit-graphs.sqlite · locks/ · snapshots (prs, usage, pauses)
```

### 1. The dispatcher

`abk tick` is the dispatcher. It takes a non-blocking **dispatcher lock** (a second one exits at once, so overlap is harmless by design), then runs a round: planning sync, `has_work`, allowance refresh,
`environment.ensure`, `run_round` (fetch, poll, plan, reclaim, land, gates, label sweeps), admission, spawning, and exits. It never waits for a build. It runs from a timer and on demand (wake, below). Verify and archive stay in it,
except a deploy-and-test verification (up to 3,600 s per deploy), which is a `verify` worker so it cannot hold the dispatcher.

### 2. Workers

`abk worker <kind> <unit>` runs one piece of work, started by the dispatcher as a **transient systemd unit** (`systemd-run --user --collect --unit abk-<installation>-worker-<unit>-<n>`), with a
`Popen(start_new_session=True)` fallback where the user manager is not available. A `build` worker loads the current kit code and configuration, takes the branch lock, runs the unit's graph to its next wait (review, a park, a failure or done),
records the outcome, releases the lock, **pokes the dispatcher** and exits. The kinds are `build`, `resolve` (the resolution lane, limited by `max_concurrent_resolutions`; it was `restack` when the lane only restacked, and it also runs a comment run) and `verify`.

Each worker is its own cgroup. A memory ceiling (`MemoryMax`) and a CPU weight can be set per worker, and an out-of-memory kill takes one worker, not every build in a process.

### 3. Wake on events; the timer is the fallback

A systemd path unit watches `runs/wake` and starts a dispatcher when it changes. Workers touch it on exit; `abk requeue`, `abk attach release`, `abk approve` and the hold and release actions of `abk serve` touch it; a refresh
request from a worker (below) touches it with a flag. The one- or two-minute timer remains the fallback and the forge polling cadence. The time from a unit finishing to the next admission is seconds.

### 4. Workers never poll: one collector, many readers

Everything a worker needs to *know* about the outside world comes from **snapshots written by one collector**, the dispatcher, through one small read API that returns the value and its age (`snapshots.pr(repo, number)`,
`snapshots.usage(account)`, `snapshots.pauses()`): the PR and review state (`runs/prs-<repo>.json`, with a collected-at time per repo), per-account usage readings and allowances (`usage-cache.<label>.json`,
`claude.json`, `usage-allowances`), the forge rate-limit and backoff state, the usage and network pause markers, and the held e2e splits.

- A worker's agent-step guard decides from the cached reading and its age. When the reading is too old it does **not** call the usage endpoint: it records a refresh request (a flag in the wake file) and waits or proceeds as
  the guard rule says, and the dispatcher refreshes under the existing minimum-interval governor and `try_file_lock` (single flight).
- "Is my PR merged", "what do the checks say" and "is the hold label gone" are read from the PR snapshot, never fetched by the worker.
- What a worker may still do against a forge is **act**: push, open or update a pull request, post a comment or a label, and read the review notes for its own rework (one request per rework, `review_notes`), through the existing
  resilient forge client with its transport rate limiting.
- One collector means API cost does not scale with the number of workers or the polling cadence, the 429 backoff is one decision for everyone, and the refresh cadence can be raised without multiplying calls. A poll costs
  about six GraphQL calls for a GitHub repo with 569 pull requests (the cost grows with merged history, because the listing is not open-only and has no conditional requests) and about one list call for an Azure DevOps repo with 80;
  cheaper listing is independent of this design and can follow it.
- A drift test pins the rule: worker entry-point modules may not import the forge list and poll functions or the usage endpoint reader, only the snapshot reader.

### 5. Slots and admission without a pool

There is no in-memory pool. Occupancy comes from durable facts: **live branch locks**, identified by pid **and process start time** (as leases already are, so a reused pid cannot hold a slot), plus leases, per
project and per account, against the unchanged limits. An account's `project_limits` is one of them:
`max_concurrent_stacks`, `max_concurrent_resolutions` and `emergency_extra` are counted for the account
across its projects, beside each project's own cap, and its `max_units_in_progress` replaces the
project's value for the account's slot. Admission and a **`starting` marker** (a worker id and a short time to live) are written under one **admission lock**, so two dispatchers can never exceed a limit; a worker that
never started leaves its unit `planned` when the marker expires.

### 6. Readmission is store state

There is no list of readmitting causes, no per-pass rebuild cap and no "not started again in this pass". A unit sent back is `planned` again with its attempt counters and backoff persisted, as the rework and fix-round counters and the
park backoff (1, 2, 5, 10 and 30 minutes) already are. Loop protection is a per-unit rebuild budget over a time window, recorded in `units.json`, so a base that keeps moving still cannot loop.

### 7. Freshness by construction, and the merge-edge rule

Each worker is a new process, so it imports the current kit code and reads the current configuration. Limit changes apply at the next
admission. The merge-edge rule keys on the worker, not the tick: a dependent starts when its parent's merge is visible and, for a kit parent, when the kit HEAD recorded for the worker contains the merge commit.
There is no tick-number rule.

### 8. Resolve, verify and the locks

The resolution lane runs as `resolve` workers (a restack, a moved-base run or a comment run). `repo_turn` (the per-repo git flock) and `e2e.lock` work across processes. A conflicted restack holds `repo_turn` through the resolver's model run; as a separate
process this blocks only that repo's git operations, and narrowing it is a later change, not a prerequisite.

### 9. Resume and failure

The checkpointer and the `running_node` and `parked_node` semantics are unchanged, and one writer per unit is the branch lock. A worker's exit status maps to unit states through `reconcile_running` and `reclaim_stranded`. A dead worker is
found by the dispatcher (a dead pid or a start-time mismatch, or systemd reporting the transient unit inactive) and the unit is resumed. Restarting the dispatcher no longer touches any build; restarting a worker affects one unit.

### 10. Observability and operations

- `abk status` lists one line per live branch-lock holder: the unit (or the branch when no unit names it), the pid and the start time in UTC, and for a transient systemd unit its CPU seconds and memory. It is read from the branch locks.
- The dispatcher takes the ledger samples (`running`, `queued`, `free_workers`, `limit`, `cap`) from the locks.
- `journalctl --user -u 'abk-*-worker-*'` is the raw log. `abk doctor` checks the transient-unit path (linger, `systemd-run`, the path unit installed). `abk install-timers` installs the wake path unit.

### 11. What was deleted

The build thread pool and `_pool_size`; the scheduling loop's in-process five-minute rounds (the dispatcher runs short rounds instead); the readmitting-causes list and the per-pass rebuild cap; the running-tick record of the loaded kit code and the
tick-number merge rule; the invariant that a tick cannot exit while a build runs; and the reliance on the timer not starting a second tick.

## Shared files

Already safe across processes: `units.json` (flock plus atomic writes), pause markers, usage caches, `planned.json`, leases, `e2e.lock`, `prs-<repo>.json` (written under a lock), the admission lock, and the branch-lock identity with a start time (the last two fixed by the first step of the history). The `Poller` snapshot and `land_units` are kept to the dispatcher, because they are not designed for several writers.

## History

Built in steps: the foundations (branch-lock identity, the admission lock, slot occupancy computed from locks), the worker entry point and spawner, the dispatcher mode of `abk tick`, resolve and verify workers, then the cutover that deleted the build thread pool and the pass-scoped rules and removed the `workers.mode` switch.

## Options considered

- **A long-running daemon.** It moves the code and configuration staleness into a process that has to restart itself, and the dispatcher with a wake path gives the same latency without it. It can be added on top later.
- **Per-repo or per-concern timers.** They keep one process owning builds, so a long build still blocks its own repo's maintenance.
- **Letting today's ticks overlap.** The code anticipates it, but admission and the PR snapshot race, and merged code still needs a new process.
- **A reloadable, drainable single process.** An in-flight build still holds the drain for hours.
- **Push events and cheaper polling.** Independent of this design: an open-PR listing, `since` and conditional requests lower the cost of the collector, and a webhook endpoint could replace its polling later.

## Decisions made and open questions

Decided: the design above, reached directly; transient systemd units as the spawner with a `Popen` fallback; the wake mechanism as a path unit watching `runs/wake`; workers never poll; a dispatcher lock, an admission lock and a start-time-aware branch lock; the merge-edge rule keyed on the worker; verify as a worker kind.

Open:

- Whether `verify` and `land_units` stay in the dispatcher, beyond the deploy-and-test part moved to a worker.
- The default per-worker memory ceiling and CPU weight.
- The value of the dispatcher timer (one or two minutes) once wake works, given the forge polling cost above.
- What a worker does when its snapshot is too old and no refresh arrives: wait, proceed with a warning, or fail the step.

Not traced while writing this: the delivery path for removing an `agent-hold` label, some per-node locks in `wiring.py`, and the manual overlap case (a person running `abk tick` beside the timer's); the `Poller`'s backoff counter is read from the code and not exercised.

## References

- [architecture.md](../architecture.md), "The flow" and "Building a unit"; [unit-graph.md](unit-graph.md), "Concurrency"; [sandbox-design.md](sandbox-design.md) for the confinement every worker's agent step runs under.
