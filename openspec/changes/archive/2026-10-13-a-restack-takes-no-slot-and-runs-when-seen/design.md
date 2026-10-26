# Design

## What was checked, and where

Read-only, `git fetch` then `git show origin/main:<path>` in the agent-build-kit checkout (origin/main at `168b6b0`). Paths are under
`src/agent_build_kit/`; line numbers are those of that commit and are approximate to a few lines where a range is given. The sibling change
`a-conflict-is-resolved-in-one-session-without-holding-the-repo-lock` (spec C) checked an earlier commit; its three corrections about where
restacks run are taken as authoritative and re-confirmed below.

**Where restacks run today, and what makes each wait.**
1. **The stack-move handler, inline in the poll.** `poll_all` (`cli/pipeline.py` 2884) polls each repo and hands events to `_dispatch`;
   a `merged` event reaches `on_merged` (`pipeline/events.py` 207) and `release_children` (255), which for each child restacks inline under
   the unit's claim: `with claim(child): ... restack(branch=, old_base=, new_base=, child=, parent=)` (events.py ~344). A child that
   is `in_review` with a thread is not restacked here: `resume(child, "base_moved", new_base, "")` delivers the event instead (~320).
   `on_release` (events.py ~629) and `reconsider_depth_hold` (events.py ~600-650) call `restack` the same way. The callable is
   `build_restack` (events.py 1354), bound in `build_stack_moves` (`cli/pipeline.py` 2759, `"restack": build_restack(...)` ~2802) with
   `move=at_path(in_repo(resolved_move))` and `push=at_path(push_with_lease)`; that move rebases in the repo's own checkout and holds the
   turn through the resolver (spec C's corrections 2 and the unit-scheduling requirement it adds). Because it is inline, one conflicted
   child holds up the rest of the poll and the pass's `_refresh` (2025) for the resolver's whole run. A conflict leaves the child `planned`
   with `restack_conflict` (events.py ~1495-1506); a rate limit, an interruption or an outage leaves it `planned` with `restack_deferred`
   (~1507-1531), and "the runner's own restack retries it".
2. **A thread told its base moved takes a slot.** `nodes.py` ~2044-2085 (`on_event`, `BASE_MOVED`) writes the unit `running` with cause
   `base_changed` and sets `base` empty, with the comment "Running, so the tick resumes the thread at `prepare` in a slot".
   `resume_thread` (`cli/pipeline.py` 3347) docstring: "Nothing runs here ... the tick runs it in a slot". `resumable_units` (1503) lists a
   `running` unit with a thread, no lease and a free branch lock, and `run_round` (1313) starts at most
   `max_concurrent_stacks - len(in_flight | held)` of them. This is the path in which a restack waits for a build slot.
3. **A unit's own restack in a run takes no repo turn and no extra slot.** `build_restack_onto` (`pipeline/wiring.py` 2160) is bound
   unwrapped at ~2714 (spec C's correction 1); `prepare` (`graph/nodes.py` ~944-995) calls it with the resolver; it returns `None` when the
   base is already an ancestor (`_is_ancestor`, wiring.py 2430, used at ~2186), which is what makes a restack done earlier free for the
   run. The run holds its worker the whole time.
4. **At `verify_base` a conflict is an in-run loop.** `rebase()` (`nodes.py` ~526-535) sets `restack=True` the first time and
   `after_verify_base` (~2236-2241) routes to `prepare` in the same run; a second hold in one run leaves the unit `planned` with cause
   `base_changed`. `verify_base` itself passes `resolve=False` (nodes.py ~1785) and the agent step stays in `prepare` under the usage gate
   (the comment at ~1783).
5. **A running pass reads causes, not events.** `READMITTED_CAUSES = {REWORK, BASE_CHANGED}` (`cli/pipeline.py` 1823) is what `_sent_back`
   (1826) lets back into a pass; `restack_deferred` and `restack_conflict` are not in it, so such a unit waits for the next tick.
   `Cause` is `pipeline/unit_store.py` 70.

**The scheduler.** `_schedule` (`cli/pipeline.py` 1875) owns one `ThreadPoolExecutor(max_workers=inst.max_concurrent_stacks,
thread_name_prefix="unit")` (1913-1915), a `building` dict of futures, and a loop that waits `REFRESH_SECONDS` (300, 1810) or for a
completion, then refreshes (`_refresh`: fetch and poll), calls `run_round`, and `sample()` (1936-1966). `sample` writes one `Sample` row
(`pipeline/spans.py` 70: `running`, `in_review`, `blocked`, `queued`, `free_workers`, `limit`, `cap`) with
`free_workers = max(0, inst.max_concurrent_stacks - len(building))` (1947), and sets the gauges `abk.slots.free` and
`abk.slots.idle_with_ready`. `building` holds only build futures, so a second pool changes none of these numbers.

**Counting.** `pipeline/units.py`: `waiting_on` (497) names the unmet prerequisites; `blocked` (546) is a planned unit with a non-empty
`waiting_on`; `in_progress` (622) and `uncounted` (647) count by state and `blocked`; `_waits_for_room` (652) is the "freshly unblocked, wait
for room" rule; `start_room` (731) and `ready_units` (773) sum `in_progress`. None reads a restack. `effective_state`
(`pipeline/vocabulary.py` 144) derives `rebasing` for a `running` unit with a cause in `_REBASING_CAUSES` (187); it is a display name only.

**Usage.** `decide_start` (`pipeline/usage_guard.py` 1233) is the one decision of a start: it answers from Claude Code's own reading, the
held reading, or a fresh read, and when the read is refused or too stale it falls back to an estimate (`on_estimate`, `_decide_on_estimate`
1155). `build_may_start` / `build_usage_gate` (`pipeline/wiring.py` 1632, 1671) wrap it in the shape the runner asks for;
`Node.gate` (`graph/nodes.py` ~420) calls `runner.may_start` under `starting(unit.id)` (usage_guard.py 786) before every agent step.
`pause_in_force` and `is_paused` (`pipeline/pause.py` 62, 82) read the pause marker. The handler's resolver (`claude_resolver`,
restack.py ~643) has no gate of its own today: it relies on the pass-level guard and on the runtime's own refusal
(`AgentRateLimited`). The lane puts the gate in front of it.

**Status.** `cmd_status` (`cli/pipeline.py` 450) prints per-unit lines (failed, parked, estimate) and `_queue_full_line` (1613) prints the
limit line. There is no restack line today.

**Docs read:** `docs/architecture.md` (the pass, the slots, the handler's turn), `docs/unit-graph.md`, `docs/configuration.md` (`limits`),
`docs/cli.md` (status), the `abk-config` and `abk-pipeline` skills.

**UNVERIFIED**, marked where each is used below:
1. That a thread can be driven from `prepare` to the end of `prepare` and left positioned at the next node (`run_thread(...,
   interrupt_after=[Node.PREPARE])`), so a slot is needed only for what follows the move. `graph/unit.py` ~311 treats a thread whose next
   node is not a wait as an interrupted one a tick resumes, which suggests it can; no test I read does it for `prepare`.
2. That `build_restack` can be called for a `planned` unit that has no `parent` merge to name: it needs `old_base`, `new_base`, a `child`
   and a `parent` (for the resolver's intent text). The in-run path derives them with `own_work_starts_after` (wiring.py 2122) and
   `predecessor` (2243); the lane would do the same. Whether `predecessor` returns a unit for a base that is the trunk is not read.
3. That the merged unit's worktree and branch can be left until the last child's lane work finishes by calling the same removal
   `remove_satisfied` (events.py ~424) makes, which "reads what keeps the branch from the store and the host rather than remembering it".
4. That `file_lock` and `branch_lock` (workspaces.py 84) are safe to take from a lane thread exactly as from a build thread (they are file
   locks, `flock`, per process; nothing found ties them to a thread).
5. Whether any test pins a restack running inline in `poll_all` (for example `tests/cli/test_restack_wiring.py`,
   `tests/pipeline/test_restack.py`); the builder greps `tests/` for `on_merged`, `release_children` and `restack=` and moves what it finds
   to the lane's seam.

## Decisions

### 1. What "restack work" is, and what stays in a slot

Restack work is the part of a unit's flow whose only cause is that its base moved: getting its branch to hold the new base. It ends when
the branch holds the base (the base is an ancestor of the branch, `_is_ancestor`) or the move was refused or deferred. It does **not**
include what follows: the re-verify, the review of a resolved move, the push of a rewritten head and the rework are the unit's own build
flow and run in a worker as today. Two executors do restack work, both in the lane:

- **The stack move** (`build_restack`, events.py 1354) for a unit with no live thread state: a `planned` or `in_review` unit with no
  thread. It does what it does now, in the same order: retarget the pull request, adopt a moved host head, move, and, for an unchanged
  approved diff, tier 1 and the push with the "Restacked" comment; anything else leaves the unit `planned` with `restack_deferred` and a
  predecessor note. Tier 1 and the push are part of the stack move and run in the lane; tier 1 is a test run, not an agent run, so it is not
  usage-gated.
- **The thread's `prepare`** for a unit `running` with cause `base_changed` and a thread parked at `prepare` (the in-review child told its
  base moved). The lane resumes the thread and stops it after `prepare` (UNVERIFIED 1), leaving it positioned at the next node; the tick's
  `resumable_units` then starts it in a worker for what follows, as for any thread left mid-graph. `prepare`'s own restack is then a no-op or
  already done; the `Restacked` result, a resolved move's predecessor note and the approval are written by `prepare` exactly as now.
- **The port (`adapt`, rung c of spec C) is not restack work.** It resets the branch and ports the unit's work with the rework model; it is
  a build step and runs in a worker. A conflict the lane's step cannot settle with the first two rungs leaves the unit `planned` with
  `restack_conflict`, as the handler does after spec C, and the unit's run does the port. This is a decision, and it is the one place a
  restack's work may still need a slot; the requirement "a restack takes no slot" is about the move and the resolver, which is where
  the waiting was measured.

The alternative considered was running the whole thread (move, port, review) in the lane. Rejected: that is a build with a different
name, and it would let a burst of conflicts run unbounded agent work outside the build cap.

### 2. What is "seen", and the lane starts at the moment

Three observers hand work to the lane; none waits for a tick or a free worker.

| Seen by | When | What it hands the lane |
|---|---|---|
| the merge and base-change handlers | inside `poll_all`, at the event (`on_merged`, `on_release`, `reconsider_depth_hold`) | each child whose base moved, in event order: as a stack move for a child with no thread, and a notice (the thread has been told) for one with a thread |
| a unit's own run | when it leaves a unit `planned` for a moved base: the run's hold at a build boundary (`build_base_moved`, wiring.py ~2549, cause `base_changed`) and the second hold of `verify_base` | nothing is handed over; the unit is left `planned` with `base_changed`, and the scan below finds it at once, because the run's end triggers a scan |
| the scan | after every poll (`_refresh` and the tick's own), after every build or restack completes, after a usage pause ends | every unit that is *owed a restack* (below) and not already queued |

**Owed a restack.** A unit is owed a restack when all hold: its stored state is `planned` or `running`-parked with a thread, or `in_review`;
its cause is `base_changed` or `restack_deferred`; its branch does not hold its base (`_is_ancestor(base_of(unit), branch)` is false, a
read that takes no turn); no run holds its branch lock and no lease names it; and `waiting_on(unit, graph)` is empty. The last condition is
stated in terms of the existing helper so it holds before and after the planned changes that rewrite `waiting_on`
(`a-unit-waits-for-all-but-one-open-parent`, `needs-start-on-the-parents-branch`, `failed-units-waiting-on-a-prerequisite-free-their-slot`):
whichever units `waiting_on` names then, a unit waiting on them is not restacked by the scan, since the base it would move onto is still
being changed (the same reason `follow_predecessors`, wiring.py ~2500, does not move a unit under a predecessor that is changing).

- `restack_conflict` is not owed. It is the lane's own record that the first two rungs could not settle the conflict; retrying it would loop
  with no new information. It stays for the unit's run, which does the port. A later base move writes `base_changed` and makes it owed again.
- A stack move **off a merged base** (the handler path) is not subject to the `waiting_on` condition: the old base branch is gone or going,
  and moving off it is `release_children`'s existing rule, unchanged. What changes is who runs it and when.
- A unit `failed`, `held`, `merged`, `closed` or `satisfied` is not owed; the readmission rule, the failed units' waiting and held units
  are unchanged.

**Starting immediately** means: when work is handed over and a lane worker is free, it starts on the lane's own thread before the handler
returns; when none is free it is queued and starts the moment a lane worker finishes. The handler no longer holds the child's claim across
the move: it takes the claim only to record and hands the child over; the lane takes the claim itself on its worker (the existing
`build_claim`, which raises `BranchBusy` for a branch a run holds). A `BranchBusy` leaves the unit owed, and the scan after the holder's run
retries it.

**The merged unit's branch.** `release_children` removes the merged unit's worktree and branch after moving the children, and a child
moves with `git rebase --onto <new base> <old base>` where `old_base` is that branch. A child handed to the lane is therefore treated as
"not moved yet": the merged unit's branch is kept (the existing `building_on_it`/`not_moved` rule), and the lane, when it finishes the last
child that named it, runs the same removal `remove_satisfied` runs (UNVERIFIED 3), which reads what keeps the branch from the store and the
host.

### 3. The lane

A new module `pipeline/restack_lane.py` holds a `RestackLane`, created once per tick beside the build pool and used by the poll's handlers
and the scheduler:

- **Workers.** A `ThreadPoolExecutor(max_workers=limits.max_concurrent_restacks, thread_name_prefix="restack")`, separate from the build
  pool at `_schedule` 1913. A lane worker is never a build worker and a build worker is never a lane worker, so `free_workers` and the
  `abk.slots.*` gauges are computed from `building` alone, as now.
- **The setting.** `limits.max_concurrent_restacks`, `Annotated[int, Field(ge=1)] = 2` in `LimitsConfig` (`config.py` ~317-325, beside
  `max_units_in_progress`), so a zero, a negative number or a non-integer is refused when the config is loaded, naming the key. It is the
  most restacks that run at once across all repos. 2, because a restack is mostly git and one resolver call, the repository's turn
  serializes the git, and a larger number mainly lets a burst start many resolver runs together.
- **The queue.** First seen, first run. A unit is queued at most once, however many events name it; a second event for a unit already queued
  or running leaves it as it is, and its new base is read when it runs (`base_of` is read afresh at the start of the move, as `restack_onto`
  does). Unit priority is not consulted: a restack is short and the order only has to be stable and fair.
- **One per branch.** The lane worker takes the unit's claim (`build_claim`, the branch lock) before it does anything, so two restacks of
  one branch, or a restack and a build of it, cannot overlap. A held claim is `BranchBusy`; the unit is left owed and the scan retries.
- **The repository's turn.** The lane runs the move exactly as the handler does after spec C: the turn is taken for each phase that writes
  shared git state and not while the resolver edits files. The lane adds no turn of its own and takes none around the whole restack; a
  lane worker holding no turn is what lets a build's worktree add proceed while a resolver runs. Tier 1 and the "Restacked" comment run
  outside the turn, as now.
- **Lifetime.** The lane lives for the tick. A tick that has work in the lane does not end until it drains, as it waits for builds in flight
  today (`_schedule` waits for `building`); the loop's "while building" condition becomes "while building or the lane has work", and an
  idle pass ends as it does now. A tick with no pass (nothing to build) still creates the lane for `poll_all`'s sake and waits for it.
- **Crash.** The queue is not stored. What a crash loses is only "which units were queued"; every one of them is still owed by the
  definition above (a cause and a branch that does not hold its base), so the next tick's scan finds it. This is why owed is derived and
  not a new stored state or cause.

### 4. A running step is left alone; a restack resumes into the normal flow

A unit whose branch lock is held by a run is not owed (the lane never restacks under a running step). The existing rule is unchanged:
`build_base_moved` (wiring.py ~2549) notices at the next node boundary that the base moved or was rewritten and stops the run with cause
`base_changed`; a parent that merges during a child's build is recorded and the child is moved afterwards (`release_children`'s
`BranchBusy` branch, events.py ~357). What is new is that the stop is followed at once by a scan, so the unit is restacked in the lane
instead of waiting for a worker to restack itself on resume.

After the restack the unit proceeds in its normal flow and nothing the lane does skips a step:

- a clean move of an approved head with an unchanged diff: tier 1, the push with the lease and the "Restacked" comment (the stack move's
  existing order), the unit stays `in_review`;
- a move that needed the resolver, or a changed diff, or a head review never approved: the unit is left `planned` with `restack_deferred`,
  the predecessor note naming the files resolved, and goes through review before it is pushed, as now;
- a thread unit: left at the node after `prepare`; the tick starts it in a worker for the re-verify.

A unit that is `planned` and moved by the lane is no longer owed (its branch holds its base), so when the scheduler reaches it a worker's
`prepare` finds the base already an ancestor and does nothing. That is the point of the lane: the worker is spent on building.

A unit owed a restack is not offered to `resumable_units` or `ready_units` until the lane has moved it, deferred it or recorded a
conflict. Offering it would start a worker only to do what the lane is about to do, and the branch claim would serialize the two. A
deferred unit (usage pause) stays out of those lists only for as long as the pause stands; a build would meet the same pause at its gate.

### 5. Usage: the same guard, only for the agent step

A clean move runs no agent and spends nothing, so it is not asked of the guard: a lane restack that applies cleanly proceeds in a usage
pause. The resolver is the agent step. In the lane it is wrapped in the same gate a unit's agent steps use: before each resolver call the
lane worker calls `build_may_start()` (wiring.py 1632, which is `decide_start`, usage_guard.py 1233, by default) under `starting(unit.id)`
(usage_guard.py 786, so an admission on an estimate is attributed to the unit), and that function is the **one** decision: the same
thresholds, the same estimate when the read is refused or too stale (`on_estimate`), the same `resume_at`. A refusal:

- aborts the rebase inside the turn (spec C's rule: nothing is left half finished),
- raises `AgentRateLimited`, which `build_restack` already turns into `planned` with `restack_deferred` and a note "deferred for a rate
  limit; the runner retries it" (events.py ~1507-1531), and
- leaves the unit owed, queued again by the lane when the pause ends: the lane remembers the refusal's `resume_at` (in memory) and does
  not retry the unit's resolver before it, and a scan after the pause marker clears (`pause_in_force`, pause.py 82) retries it. If the
  process restarts, the next tick's scan retries it. No timer retries a restack on a recurring interval of its own: it is retried when
  the pause ends or at the next scan, so no "auto-retry for stopped jobs" is introduced.

The gate is put in the lane's resolver callable, so it is asked only once a conflict exists (the rebase has stopped), and the lane's
rebase is the one that is aborted. For a thread unit, `prepare` already asks the gate through `Node.gate` before its agent step; the lane
adds nothing there. Under a usage pause a clean restack still happens at once and a conflicting one waits for the pause to end, which is the
same rule as everything else.

A restack in the lane is recorded by spec B's helper as node `restack`, with the unit, change and repo filled. The lane does not write its
own ledger row for a clean move: a clean move has no agent call, as today.

### 6. Counting: a restack changes no count

A unit in the lane keeps its stored state and cause. Nothing the lane does appears in `in_progress`, `blocked`, `uncounted`, `start_room`,
`ready_units` or `_waits_for_room`, and none of them reads the lane. Precisely:

- **`max_concurrent_stacks`** counts `running` units in a worker; a lane restack is not in a worker and is not counted.
- **`max_units_in_progress`.** The lane is not a start and takes no admission. A unit being restacked is already in progress or already
  not (as `in_progress` says by state, `blocked` and, after the planned changes, `waiting_on`); the lane does not make an uncounted unit
  count or a counted unit stop counting. A planned unit with work, not blocked, waiting for room under `_waits_for_room` is restacked by
  the lane while it waits for room; when room opens its worker's `prepare` finds nothing to move. The limit stops a start, not a restack,
  as "Work already in progress continues at the limit" already says of a restack.
- **Blocked or not.** Waiting for a restack does not make a unit blocked, and a unit that is blocked (`waiting_on` non-empty) is not restacked
  by the scan. So the set of blocked units, and the "blocked not counted" line of the queue-full report, are the helpers' answer, as now.
- **`queue_full` waits.** A unit whose wait reason is `queue_full` (or `slot`, `usage_pause`) keeps it; the lane does not add a wait reason
  and a unit queued in the lane is not labelled `slot`. The decision log's `{at, unit, reason, waits_on, tick}` is unchanged.
- **Priority and handoff.** `_handoff` and priority ordering read `uncounted` and `ready_units`; both are unchanged.

### 7. Status, graph and what is recorded

- **The unit.** While a unit's restack is queued or running, the status line for it, the graph page and the chat read `restacking onto
  <base>` where they would otherwise show its stored state's name. `effective_state` already derives `rebasing` for `running` units with
  a restack cause; the lane's units reuse that name and the line adds the base. A lane record, `<state>/restacks.json`, written atomically by
  the lane (owner pid, and for each unit `{unit, base, status: running|waiting, since}`), is how `abk status` (a different process from the
  tick) and the graph page know; a record whose owner is gone is ignored and not trusted, as a stale lease is. UNVERIFIED which
  existing helper writes a state-dir record the same way (`pipeline/pause.py`'s marker and `Leases` are the models read).
- **The status line.** `cmd_status` (cli/pipeline.py 450) gains `restacks: N running, M waiting`, printed when the lane has any work or a
  unit is owed one (so `restacks: 0 running, 2 waiting` shows work found but not yet started), and omitted when both are zero. A waiting
  restack under a usage pause says so on its own line: `restack waiting: <unit> — usage pause until <time>`.
- **The slot gauge.** `sample()` (`_schedule`) is unchanged: `free_workers` and `cap` are the build pool's; `running` counts units in a
  worker or `running` in the store, so a parked thread unit counts there as today. A lane restack is not a build and is not counted
  as running, queued or blocked by the sample. The sample row gains no field (a reader that knows the row would otherwise refuse or ignore
  one it does not know). Two gauges are added, `abk.restacks.running` and `abk.restacks.waiting`, set where `sample()` sets the slot
  gauges, with no unit or change attribute.
- **The ledger.** An agent call of the lane's resolver is the `restack` node (spec B). The span of a restack's git phases is recorded as
  today (`prepare` spans; the stack move's `restack` unit context at events.py ~1560).

### 8. The once-per-run rule stays

`verify_base`'s loop back to `prepare` happens once per run, and a second hold leaves the unit `planned` with cause `base_changed`. This
does not change. What changes is only what follows the second hold: the unit is now owed a restack, so the lane moves it (rungs a and b of
spec C, under the gate) at once instead of the move waiting for a worker; the unit then waits for a worker only for its build. A conflict
the first loop settled is not a second hold (spec C).

## Interactions with the planned changes in this area

- `a-conflict-is-resolved-in-one-session-without-holding-the-repo-lock` (spec C): the lane runs the one-session step as the handler
  runs it (rungs a and b in a session of its own, rung c left to the unit's run) and the per-phase turn. Group 1 `Needs:` its group 2.
- `every-agent-call-is-recorded` (spec B): the lane's resolver rows are node `restack`. Group 2 `Needs:` its group 1.
- `a-moved-base-is-checked-by-what-it-can-affect` (spec A): changes what tier 1 a clean move runs. The lane runs the stack move as it is, so
  whatever scoped check that change specifies is what the lane runs. No `Needs:`.
- `failed-units-waiting-on-a-prerequisite-free-their-slot`, `a-unit-waits-for-all-but-one-open-parent`,
  `needs-start-on-the-parents-branch`: all touch `waiting_on`, `in_progress` and `blocked`. This change reads `waiting_on(unit, graph)` and
  nothing else about dependencies, writes no state and changes no counting helper, so each holds before and after the others and none is
  needed. UNVERIFIED: that none of them moves the handler's inline restack in `release_children`.

## Scope notes

- Docs: `docs/architecture.md` (the pass and its slots gain the lane, and the handler's inline restack is replaced; spec C already
  rewrites the turn paragraph), `docs/unit-graph.md` (the `prepare` and the base-moved rows), `docs/configuration.md`
  (`limits.max_concurrent_restacks`), `docs/cli.md` (the status line); the `abk-config` skill's `limits:` block and the `abk-pipeline`
  skill's status paragraph; `CHANGELOG.md` under `## Unreleased` as the Changelog section of `AGENTS.md` says, folding into the bullet on
  restacks if there is one.
- No existing setting changes. The lane's cap defaults to 2.
- The `restack_conflict` and `restack_deferred` causes, the readmission set and the unit states are unchanged; no migration.
