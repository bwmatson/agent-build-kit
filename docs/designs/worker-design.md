# A short dispatcher and detached unit workers

Today one `abk tick` process owns every build: it starts them as threads, cannot exit while any of them runs, and holds the kit code, the
configuration and the pool size it loaded when it started. A tick that is building a unit therefore lasts as long as the longest unit in it, which has been
hours, and everything that needs a fresh process waits for it. This document describes the end state that removes that coupling: a short **dispatcher** that decides what
runs, **detached worker processes** that each carry one unit's work, a **wake** path so a finished worker is noticed in seconds, and one **collector** that is the only
thing that polls the outside world. It is a design, not a specification. Paths and function names are where the work happens today; names for new things are proposals.
Each [migration step](#migration) can become its own OpenSpec change.

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

## Where we are

- **Process model.** `abk tick` is a systemd `Type=oneshot` service started by a timer (`OnBootSec=2min`, `OnUnitActiveSec=5min`, 30 s jitter). There is **no tick lock**: a
  oneshot that is `activating` cannot be started again, so timer fires during a long tick do nothing (`cli/pipeline.py` ~3760-3767). One process runs a first `run_round`, then
  `_schedule` (~3832): a `ThreadPoolExecutor` runs each unit's build graph in a worker thread (`build_unit`, ~5781; the graph is LangGraph with a SQLite WAL checkpointer,
  `runs/unit-graphs.sqlite`), and the loop wakes on a build finishing or every `REFRESH_SECONDS = 300` to run a quiet round and fill free slots. It exits only when nothing is in flight and the
  restack lane is empty. Agent steps are subprocesses of those threads; killing the tick kills every build in it, and the next tick resumes them from their checkpoints.
- **Order of a tick** (~1293-1450): planning sync, the `has_work` early exit (an idle tick costs about a second and makes no host call), allowance refresh, `environment.ensure`, the
  restack lane, a first round (usage guard, `fetch_all` and `poll_all`, `land_units` in the first round only, planning, reclaim, gates, verify and archive, label sweeps, ready computation and admission), then `_schedule`.
- **Loaded once per process:** the configuration (`abk.yaml`, `abk.local.yaml`), the kit code (`loaded_code.running_tick`, `runs/tick.json`), the planning sync, the usage allowances and the pool size
  (`(max_concurrent_stacks + emergency_extra) x live projects`). **Refreshed every round:** the unit store, planned hashes, PR snapshots, pause markers and leases.
- **Locks and shared state that already work across processes:** `runs/units.json` (flock plus atomic writes), the branch lock `runs/locks/<branch>.lock` (a pid file, `O_EXCL`),
  `repo-<repo>.lock` (git operations), `e2e.lock`, `environment.lock`, `planned.lock`, leases, pause markers and usage caches, and `prs-<repo>.json` (written under a lock, replaced atomically).
- **Evidence** (one installation's journal over about a month of ticks, and its usage ledger's `abk.tick.duration`): idle ticks have a median of 0.5 minutes,
  **built ticks a median of 26.9, p90 114 and a maximum of 465 minutes (7.7 hours)**. A day without long ticks holds 240 ticks; days with multi-hour ticks hold 58 to 104. A tick observed
  past two hours with two units building was holding a multi-gigabyte `claude` child.
- **What waits for the next tick:**
  - A dependent on a **merge edge** (a cross-repo parent, a `Needs: ... merged` line, a failed unit waiting on a fix) starts only when `loaded.number > unit.merged_tick` (`pipeline/units.py` ~928-953): the tick number is fixed
    per process, so a merge seen during a tick is "loaded" only by a process that started after it. The reason is real (merged kit code only takes effect in a process that imported it), and it is why a unit waiting on a kit merge showed
    "waiting for the next tick to load ... merge" while a long tick ran.
  - A unit put back for a cause outside `READMITTED_CAUSES` (`rework`, `base_changed`, `restack_handed_back`): `requeued`, `gated`, `restack_deferred`, `needs_human` and failures; the `REBUILDS_PER_PASS = 2` cap; the
    `BranchMoved` and `BranchBusy` deferrals.
  - Once-per-tick work: usage allowances, `land_units`, resuming environment-failed units, the planning-repo sync, verification of satisfied changes, and the pool size.
  - Anything a running process never sees: a kit merge, a configuration edit, and a person's requeue of a unit already started in the pass.
- **A long tick is not blind.** While builds run it refreshes every five minutes: fetch, poll, plan, reclaim, verify, archive, readiness and admission. The waits are the once-per-process items and the process-lifetime rule, not
  the polling.

## The end state

**One principle: process lifetime stops being code, configuration and capacity lifetime.** A short dispatcher decides; a worker lives as long as one unit's work.

```
 timer (1-2 min) ──┐                              ┌── worker: build  unit-A ──┐
 wake path  ───────┼──► dispatcher (short) ──────►├── worker: build  unit-B ──┼─► exit ─► touch runs/wake
 person: requeue,  │    lock · collect · plan ·   ├── worker: restack proj-X ─┤
 release, approve ─┘    land · verify · admit ·   └── worker: verify change ──┘
                        spawn · exit
          shared files (flock, atomic):  units.json · unit-graphs.sqlite · locks/ · snapshots (prs, usage, pauses)
```

### 1. The dispatcher

`abk tick` becomes the dispatcher. It takes a non-blocking **dispatcher lock** (a second one exits at once, so overlap is harmless by design), then does what a round does today: planning sync, `has_work`, allowance refresh,
`environment.ensure`, `run_round` (fetch, poll, plan, reclaim, land, gates, label sweeps), admission, spawning, and exits. It never waits for a build. It runs from a one- or two-minute timer and on demand (wake, below). Verify and archive stay in it,
except a deploy-and-test verification (up to 3,600 s per deploy), which becomes a worker so it cannot hold the dispatcher.

### 2. Workers

`abk worker <kind> <unit>` runs one piece of work, started by the dispatcher as a **transient systemd unit** (`systemd-run --user --collect --unit abk-<installation>-worker-<unit>-<n>`), with a
`Popen(start_new_session=True)` fallback where the user manager is not available. A `build` worker loads the current kit code and configuration, takes the branch lock, runs the unit's graph to its next wait (review, a park, a failure or done),
records the outcome, releases the lock, **pokes the dispatcher** and exits. The kinds are `build`, `restack` (today's restack lane, limited by `max_concurrent_restacks`) and `verify`.

Each worker is its own cgroup. A memory ceiling (`MemoryMax`) and a CPU weight can be set per worker, and an out-of-memory kill takes one worker, not every build in a process.

### 3. Wake on events; the timer is the fallback

A systemd path unit watches `runs/wake` and starts a dispatcher when it changes. Workers touch it on exit; `abk requeue`, `abk attach release`, `abk approve` and the hold and release actions of `abk serve` touch it; a refresh
request from a worker (below) touches it with a flag. The one- or two-minute timer remains the fallback and the forge polling cadence. The time from a unit finishing to the next admission becomes seconds.

### 4. Workers never poll: one collector, many readers

Everything a worker needs to *know* about the outside world comes from **snapshots written by one collector**, the dispatcher, through one small read API that returns the value and its age (`snapshots.pr(repo, number)`,
`snapshots.usage(account)`, `snapshots.pauses()`): the PR and review state (`runs/prs-<repo>.json`, with a collected-at time per repo), per-account usage readings and allowances (`usage-cache.<label>.json`,
`claude.json`, `usage-allowances`), the forge rate-limit and backoff state, the usage and network pause markers, and the held e2e splits.

- A worker's agent-step guard decides from the cached reading and its age. When the reading is too old it does **not** call the usage endpoint: it records a refresh request (a flag in the wake file) and waits or proceeds as
  the guard rule says, and the dispatcher refreshes under the existing minimum-interval governor and `try_file_lock` (single flight).
- "Is my PR merged", "what do the checks say" and "is the hold label gone" are read from the PR snapshot, never fetched by the worker.
- What a worker may still do against a forge is **act**: push, open or update a pull request, post a comment or a label, and read the review notes for its own rework (one request per rework, `review_notes`), through the existing
  resilient forge client with its transport rate limiting.
- One collector means API cost does not scale with the number of workers or the polling cadence, the 429 backoff is one decision for everyone, and the refresh cadence can be raised without multiplying calls. Today a poll costs
  about six GraphQL calls for a GitHub repo with 569 pull requests (the cost grows with merged history, because the listing is not open-only and has no conditional requests) and about one list call for an Azure DevOps repo with 80;
  cheaper listing is independent of this design and can follow it.
- A drift test pins the rule: worker entry-point modules may not import the forge list and poll functions or the usage endpoint reader, only the snapshot reader.

### 5. Slots and admission without a pool

The in-memory pool and `_pool_size` go. Occupancy comes from durable facts: **live branch locks**, identified by pid **and process start time** (as leases already are, so a reused pid cannot hold a slot), plus leases, per
project and per account, against the unchanged limits. Admission and a **`starting` marker** (a worker id and a short time to live) are written under one **admission lock**, so two dispatchers can never exceed a limit; a worker that
never started leaves its unit `planned` when the marker expires.

### 6. Readmission is store state

`READMITTED_CAUSES`, `REBUILDS_PER_PASS` and "not started again in this pass" disappear. A unit sent back is `planned` again with its attempt counters and backoff persisted, as the rework and fix-round counters and the
park backoff (1, 2, 5, 10 and 30 minutes) already are. Loop protection is a per-unit rebuild budget over a time window, recorded in `units.json`, so a base that keeps moving still cannot loop.

### 7. Freshness by construction, and the merge-edge rule

Each worker is a new process, so it imports the current kit code and reads the current configuration (the config guard is a per-step warning, which `sandbox-is-on-by-default` already plans). Limit and pool changes apply at the next
admission. The merge-edge rule keys on the worker, not the tick: a dependent starts when its parent's merge is visible and, for a kit parent, when the kit HEAD recorded for the worker contains the merge commit (the `kit_head` check that exists
in `pipeline/units.py` ~897-912). The `merged_tick` / `loaded.number` rule is deleted.

### 8. Restack, verify and the locks

The restack lane's per-project threads become `restack` workers. `repo_turn` (the per-repo git flock) and `e2e.lock` already work across processes. A conflicted restack holds `repo_turn` through the resolver's model run; as separate
processes this blocks only that repo's git operations, and narrowing it is a later change, not a prerequisite.

### 9. Resume and failure

The checkpointer and the `running_node` and `parked_node` semantics are unchanged, and one writer per unit is the branch lock. A worker's exit status maps to unit states as `reconcile_running` and `reclaim_stranded` do today. A dead worker is
found by the dispatcher (a dead pid or a start-time mismatch, or systemd reporting the transient unit inactive) and the unit is resumed. Restarting the dispatcher no longer touches any build; restarting a worker affects one unit.

### 10. Observability and operations

- `abk status` lists workers (kind, unit, pid, start time, cgroup CPU and memory, a link to the unit log) and shows each snapshot's age beside the reading it supports.
- The dispatcher takes the ledger samples (`running`, `queued`, `free_workers`, `limit`, `cap`) from the locks.
- `journalctl --user -u 'abk-*-worker-*'` is the raw log. `abk doctor` checks the transient-unit path (linger, `systemd-run`, the path unit installed). `abk install-timers` installs the wake path unit.

### 11. What is deleted

The build thread pool and `_pool_size`; `_schedule`'s in-process loop and its five-minute rounds (the dispatcher runs short rounds instead); `READMITTED_CAUSES` and `REBUILDS_PER_PASS`; `loaded_code.running_tick` and the
tick-number merge rule; the invariant that a tick cannot exit while a build runs; and the reliance on the timer not starting a second tick.

## Shared files

Already safe across processes: `units.json` (flock plus atomic writes), pause markers, usage caches, `planned.json`, leases, `e2e.lock`, `prs-<repo>.json` (written under a lock). To fix as part of the migration:
the admission lock, and the branch-lock identity with a start time. The `Poller` snapshot and `land_units` are kept to the dispatcher, because they are not designed for several writers.

## Migration

The route is straight to the end state; the `workers.mode` switch is the mechanism for getting there safely, not an interim improvement.

1. **Foundations the end state needs.** Branch-lock identity with a start time; the admission lock and the `starting` marker; slot occupancy computed from locks and leases (one pure function the thread pool also uses, so both modes agree);
   the `prs-<repo>.json` lock; and the snapshot read API with `request_refresh()`, with the existing in-thread readers moved onto it (the usage guard's per-step decisions, the PR-state reads in the graph nodes), so thread mode and worker mode read the
   same cached source.
2. **The worker entry point and the spawner.** `abk worker build <unit>` running `build_unit` (it already re-reads the unit under the branch lock, `cli/pipeline.py` ~5934-5950), the transient-unit spawner with the `Popen` fallback, the worker's
   exit poke, and the wake path unit in `install-timers`.
3. **The dispatcher mode of `abk tick`**, behind `workers.mode: threads | processes` (default `threads` until proven): admission and spawning instead of `submit`, and no waiting.
4. **Restack and verify workers**, then the status, doctor and ledger changes.
5. **Cut over** one repo, then the rest, then delete the thread pool and the pass-scoped rules.

Tests: the controlled builder in `tests/tick_pass.py` generalised to a fake spawner; a two-dispatcher race test for admission; a killed-worker resume test; the merge-edge test rewritten around the worker's kit HEAD; and the drift test for the collector rule.

## Options considered

- **A long-running daemon.** It moves the code and configuration staleness into a process that has to restart itself, and the dispatcher with a wake path gives the same latency without it. It can be added on top later.
- **Per-repo or per-concern timers.** They keep one process owning builds, so a long build still blocks its own repo's maintenance.
- **Letting today's ticks overlap.** The code anticipates it, but admission and the PR snapshot race, and merged code still needs a new process.
- **A reloadable, drainable single process.** An in-flight build still holds the drain for hours.
- **Push events and cheaper polling.** Independent of this design: an open-PR listing, `since` and conditional requests lower the cost of the collector, and a webhook endpoint could replace its polling later.

## Decisions made and open questions

Decided: the end state above, reached directly; workers never poll; a dispatcher lock, an admission lock and a start-time-aware branch lock; the merge-edge rule keyed on the worker; verify as a worker kind.

Open:

- Transient systemd units or `Popen` as the default spawner, and the behaviour where the user manager is not available (a WSL install without systemd, macOS, where `install-timers` is not supported today).
- The wake mechanism: a path unit watching `runs/wake`, or `systemctl --user start` of the dispatcher from each trigger.
- Whether `verify` and `land_units` stay in the dispatcher, beyond the deploy-and-test part moved to a worker.
- The default per-worker memory ceiling and CPU weight.
- The value of the dispatcher timer (one or two minutes) once wake works, given the forge polling cost above.
- What a worker does when its snapshot is too old and no refresh arrives: wait, proceed with a warning, or fail the step.

Not traced while writing this: the delivery path for removing an `agent-hold` label, some per-node locks in `wiring.py`, and the manual overlap case (a person running `abk tick` beside the timer's); the `Poller`'s backoff counter and the exact meaning of
`loaded.number` are read from the code and not exercised.

## References

- [architecture.md](../architecture.md), "The flow" and "Building a unit"; [unit-graph.md](unit-graph.md), "Concurrency"; [sandbox-design.md](sandbox-design.md) for the confinement every worker's agent step runs under.
