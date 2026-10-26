# Design

## What was checked, and where

Read-only: `git fetch`, then `git show origin/main:<path>` in the build tool's checkout (origin/main at `60f3e485`). Paths are under
`src/agent_build_kit/`; line numbers are those of that commit and approximate to a few lines. The units' stored history and a run's log
were read from the pipeline's own state, read-only. The archived change `a-restack-takes-no-slot-and-runs-when-seen` is the
base this builds on; its decision 1 is the one reversed here.

**What exists now (all verified at that commit).**
1. **The lane.** `pipeline/restack_lane.py` has `RestackLane`: a thread per running entry, at most `cap` at once, a first-seen queue with
   one entry per unit, `hand_over(unit, work, done=)` (the unit's move, or any `work`), `scan`, `defer_until`, `running`, `waiting`,
   `finished`, `drain`, and a `restacks.json` record (`lane_record`) that `abk status` and the graph page read. `_run` takes the unit's
   branch claim (`build_claim`, a file named for the branch holding the process id) before the work and releases it after; a held branch
   is `BranchBusy` and leaves the unit owed. `OWED_STATES` is planned, running, in review; `OWED_CAUSES` is `base_changed` and
   `restack_deferred`; `owed_a_restack` also needs `not waiting_on`, no lease, no run holding the branch, and a branch that does not
   hold its base. `cap` is `inst.max_concurrent_restacks`, read from `project_limits` (`config.py` `ProjectLimitsConfig`, ~434).
2. **What the lane does with a unit** (`cli/pipeline.py` `build_restack_lane.move_unit`, ~3290): a unit not `running` is moved by the stack
   move (`build_restack`, the resolver behind `gated_resolver`); a unit `running` with a thread is advanced through `prepare` only
   (`advance_thread_through_prepare` -> `graph/unit.py` `advance_through_prepare`, `run_thread(..., interrupt_after=[Node.PREPARE])`) and a
   conflict there leaves it `planned` with `restack_conflict` "left for its run: its port"; one with a worktree that has the branch checked
   out is left `running` with `restack_conflict`. The lane stops after the move in every case, and a build worker takes the rest.
3. **A worker's run** (`_build_unit`, ~3690): takes the branch lock itself (`branch_lock`, not re-entrant: it refuses a lock whose pid file
   names a live process, its own included), re-reads the unit, opens the run log, builds the runner (`build_runner(..., log_reaches_run_log=True,
   journal=, transcript=)`), calls `run_unit_thread`, and answers each ending: usage pause (`_pause_for_usage`), rate limit
   (`pause_until`), parking for the host, network or model service, failure, hold. `run_unit` (graph/unit.py ~309) resumes a thread whose
   next node is not a wait, and starts a new run from `prepare` for one that is waiting, ended or never started.
4. **Which runs hold a build slot by counting.** `run_round` (~1534): `free = max_concurrent_stacks - len(in_flight | held)` where `held` is
   the stored-`running` units minus `_idle_units` (running, not in flight, branch lock free). `_evaluate_round` (~1920) sets
   `slots = cap - (units whose view state is running)` and passes `cap + len(for_the_lane)` to `ready_units`, which itself subtracts the
   running units (`units.py` ~921). `_schedule`'s `sample` computes `free_workers` from `building` alone (~2280). So a unit that is stored
   `running` in a lane worker is counted as a build slot by `run_round` and by `_evaluate_round` today unless it is made to look idle;
   decision 4 keeps that counting and makes it the rule, as the occupancy.
5. **Resuming.** `resumable_units` (~1799) lists stored-`running` units with a thread, no lease, a free branch lock and not owed a restack;
   `READMITTED_CAUSES` (~2161) is `{rework, base_changed}`, the causes `_sent_back` lets back into a running pass.
6. **The graph.** `Node.gate` (graph/nodes.py ~424) asks `runner.may_start` under `starting(unit.id)` before every node in `AGENT_NODES`
   (tests, implement, fix_checks, review, rework, adapt; ~156) and interrupts with the pause on a refusal; `prepare` is not in
   `AGENT_NODES`, and the conflict resolver `prepare` asks (`restack_resolver`, ~1110) calls `self.agent` without a guard decision of its
   own. `after_prepare` (~2293) goes to `adapt` on a conflict, to `rework` when feedback is saved (`had_feedback`), to `checks` otherwise;
   `after_await_review` (~2389) sends a `rework` event to `rework` and a `base_moved` or `requeue` event to `prepare`; `after_review`
   goes to `rework` on a verdict of changes; `verify_base` -> `rebase()` (~535) loops back to `prepare` once per run (`rebased`) and the
   second time holds the unit `planned` with `base_changed`. `run_thread` takes `interrupt_before` and `interrupt_after`; the code uses
   `interrupt_after` with `[Node.PREPARE]` and the wait nodes, and `interrupt_before` only in `tests/graph/test_thread_resume.py` (with
   `Node.PREPARE`).
7. **Attempts.** `StoredUnit` has `conflict_tip`, `conflict_head`, `conflict_attempts`, `conflict_at` (`unit_store.py` ~192) and
   `attempts_spent(max_rounds)` (~300): `conflict_attempts >= max_rounds` or the pushed head equals `conflict_head`. `on_conflict`
   (`events.py` ~1354) counts one attempt per stack move or conflict rework at a base tip, bounded by `global_limits.max_review_rounds`
   (default 3), and `_hold_conflict` holds the unit `HELD` with `held_by` the review loop and the cause `needs_human`. The sibling change
   `a-pr-that-stays-conflicting-is-moved-again` is archived and its units are all merged. `on_conflict` already hands its stack move to
   the lane with `lane.hand_over(unit, work)`.
8. **Display.** `vocabulary.effective_state` derives `rebasing` for a running unit whose feedback source is the conflict or whose latest
   cause is one of `base_changed`, `restack_conflict`, `restack_deferred`, and `reworking` for review or checks feedback; the lane's
   record overlays `restacking onto <base>` in `render_mermaid` and `abk status`.

**The case this was drawn from, read from the unit's stored history and run log** (times UTC; the run log's clock is six hours behind).
The unit is the third unit of a rename change.

| Time | What | Where |
|---|---|---|
| 05:14 | pushed, `in_review` | worker |
| 13:23:54 | `running`, cause `rework`: "rework requested: merge conflict with its base" (the poller's conflict kind) | event on the parked thread |
| 13:25:39 | rework run starts; the agent: "I changed nothing: the branch ... has not been moved onto the current base"; run goes on to tier 1 (about 7 minutes) and review round 1 (about 10) | worker |
| 13:43 | rework answering round 1; tier 1; review round 2 approves | worker |
| 13:59:31 | `verify_base`: "base moved before its push: moving onto main needed resolution; resuming at its restack" (first find) | worker |
| 13:59:38 | `prepare` restacks, the resolver runs in the build session, conflict, `adapt` ports the work (about 8 minutes), another rework, tier 1, review | worker |
| 14:23:31 | `verify_base`: base moved again (second find): `planned`, cause `base_changed` | worker ends |
| 14:24:12 | the lane's move: could not be merged, "the resolution lost the unit's own tests": `planned`, cause `restack_conflict`, "the unit's next run resolves it in its build session" | lane |
| after | waits in the ready queue for a build worker (all four busy); `restack_conflict` is not an owed cause | none |

One attempt is on its record (`conflict_attempts` 1 at the base tip it was reworked against). Two things in it are not about the move
and are noted, not fixed, by this change: (a) the conflict event was routed to `rework`, not `prepare`, which wasted the first run's
tier 1 and review on an unmoved branch (decision 5 below fixes it for the lane); (b) the unit carried review feedback that a later
review had already approved over, which sent `prepare` to `rework` once more after the port ("answered no comment: all five points
were handled") (decision 1 clears answered feedback).

**UNVERIFIED** (the builder reads each and corrects this file if it is otherwise):
1. That `run_thread(..., interrupt_before=[Node.REWORK, ...])` stops a thread before an arbitrary node and that resuming with the same
   set does not stop at the same node again. The runner's own contract suggests it (`interrupt_before` is passed straight through and
   `tests/graph/test_thread_resume.py` exercises it for `prepare`), but no code in the tree does it for any other node. If it does not
   hold, the same effect is had by running the thread in segments with `interrupt_after` the node before.
2. Whether the lane can run `_build_unit`'s body as its `work` without the lane's own claim: the lane takes the branch lock and
   `_build_unit` takes it again, which refuses (decision 2 resolves it by a lane entry that owns no claim, UNVERIFIED that `hand_over`
   can carry that without changing the collection `limits-split-into-global-and-project` group 8 adds).
3. How the lane's worker gets the build session's resumable agent session. The sessions are recorded in the thread's state
   (`_record_sessions`, `AgentSession`, `ported_session`) and a worker's log shows "continuing the build session", so a lane worker
   that runs the same thread should continue it; not read: that the lane's thread, which is not the worker's, finds the same session
   through the runner it builds.
4. That a lane worker (a plain thread started by `RestackLane._start`) can run `asyncio.run(...)` for the thread as `_on_thread`
   does for a worker thread; `advance_thread_through_prepare` already does it from the lane, which suggests yes.
5. Whether the stored `cause` of a unit mid-run can be relied on to discover a lane run after a crash. It cannot: a rework clears the
   saved feedback and the run's `running` entries carry the cause of the entry that started it, so a crash after the conflict rework
   leaves nothing that says "moved-base run". Decision 3 stores a flag; the alternative (derive) is rejected on that evidence.
6. That adding one field and one cause to `StoredUnit` / `Cause` reads old records as the defaults. The pattern at `unit_store.py`
   ~541 (copying `conflict_*` from the existing record) suggests the store tolerates it; not read: the loader for a record missing a key.
7. That answered feedback can be told by `stored.approved == branch head` at the start of the run. `standing()` reads exactly that
   (`head_approved`); not read: whether `approved` survives an adapt on the branch (the unit above shows an approved head that is not its
   pushed head).
8. Whether the lane's `cap` of 2 is enough once whole runs, which last tens of minutes, share it with moves, which last seconds. See
   Risks; no figure is measured.

## Decisions

### 1. What a moved-base run is

A run is a moved-base run when the only reason the unit has to run is that its base moved. It is decided from the unit's stored record,
read when the unit is handed to the lane, not from the event that made it:

- the unit has commits on its branch (a unit with none is a new build; `after_prepare` goes to `tests` for it), is not held by a person, a
  lease or another run, and is not waiting on another unit (`waiting_on`); and
- its stored cause is `base_changed` (a base moved or rewritten; this is also what a run's second find of a moved base leaves: the unit
  `planned` with `base_changed`), `restack_deferred` (the lane's move was deferred, or a resolved move changed the diff and the unit is
  planned for its review), or `restack_conflict` (the move could not be merged and the unit is left for its port); or it was sent back by
  the poller's conflict kind (`ReworkKind.CONFLICT`: stored cause `rework`, `feedback_source` the conflict); and
- it has **no rework input of its own**: no saved feedback whose source is a review, a failing check or a tier 1 or tier 2 run (or none
  recorded), unless that feedback is *answered*: the branch's head is the head review approved (`approved`). Answered feedback is cleared
  as the run starts, so `prepare` does not route to `rework` for it. Feedback whose source is the conflict is not rework input.

A unit that has rework input of its own is not a moved-base run even when its base moved; it is a build. The lane still makes its
move (as now), and the unit then waits for a worker for the rework it has. Nothing the lane does makes a build of one that is not.

*Why from the record, not the event:* three observers hand a unit over (a poll's handlers, a run that ended holding for a moved base,
the lane's scan), and a crash loses the event; the record is what every tick can read. *Why `restack_conflict` is owed now:* the earlier
design refused to retry it because retrying the lane's step "would loop with no new information". A run is a different step (the port),
and the bound below (decision 6) is what stops a loop.

### 2. The whole run, in the lane's worker

The lane's `work` for a moved-base unit is the run a build worker makes (`_build_unit`: the lock, the run log, the runner, the thread,
every ending), not a copy of it; only who runs it differs. Concretely:

- **Order inside one lane worker.** For a unit with no live thread state, or that is `in_review`, the lane first makes the stack move as
  it does now. If the move is the whole of the work (a clean move of an approved head with an unchanged diff: tier 1, push, the
  "Restacked" comment, the unit stays in review), the worker ends. Otherwise (the move ends `restack_conflict` or `restack_deferred`,
  or the unit has a thread) the same worker goes on into the unit's run, from `prepare` or from the node its thread is positioned at.
  Today it stops and leaves the rest for a worker; that stop is what is removed.
- **No double claim.** A lane entry for a run owns no claim: `_build_unit` takes the branch lock, the lane's `_run` skips its own. An
  entry that is only a move keeps the claim. A `BranchBusy` from `_build_unit` leaves the unit owed, as now (UNVERIFIED 2).
- **Same pause, rate limit, park and failure endings.** Because the body is `_build_unit`'s, a run in the lane that meets the model's
  refusal pauses the pass as a worker's does, one that meets an unreachable network parks the unit with its backoff, and an error fails
  it. The pass already reads the pause marker; nothing new is needed to stop it.
- **Interrupted runs stay the lane's.** The unit is stored `running` with a thread while its run lasts. To keep a build worker from
  taking it after a crash or a pause, the lane sets a stored flag `moved_base_run` when the run starts and clears it when the unit
  leaves `running` (any `set_state` to another state clears it) or is handed back. `resumable_units` leaves flagged units out, and the
  lane's scan lists a flagged `running` unit with a thread, a free branch lock and no lease as owed a run. A stored flag, not a
  derivation (UNVERIFIED 5): see the evidence there. A record without the field reads as false (UNVERIFIED 6).
- **Where a run is held.** One lane worker and the unit's branch for the run's whole length. The lane's queue, order, one entry per unit
  and `defer_until` are unchanged. The lane of the unit's project is the one (after `limits-split-into-global-and-project` group 8;
  before it there is one lane).

*Rejected:* a smaller lane-specific runner that calls the graph nodes directly. It would have its own pause handling, run log and
failure endings to keep equal to a worker's. Reuse is the point.

### 3. What the lane never continues: ordinary work is handed back

The steps of a moved-base run are: the move, the resolver, the port (`adapt`), a rework whose saved feedback is the conflict's, tier 1 on
the result (`checks`, and `tier1` when the rework produced nothing), the review of the result, the check against the base
(`verify_base`), `new_comments`, the push and the pull request step. Every other step is outside it:

- `rework` whose saved feedback is not the conflict's (a verdict of changes from the review, a new comment, a failing check),
- `fix_checks` (failing tier 1 checks), and
- `tier2` (the slow end-to-end tests and their feedback), `tests` and `implement`.

When the next node of the thread is one of these, the lane **does not run it**: the current node has finished, the unit is set `planned`
with the new cause `restack_handed_back` and a note naming the step and why ("review asked for changes beyond the conflict", "checks
failed after the move"), the flag clears, the thread stays positioned at that step, and the lane lets go of the unit. A build worker
takes it from there like any thread left mid-graph: `_build_unit` accepts `planned`, and `run_unit` carries on from the node. The new cause
is added to `READMITTED_CAUSES`, so a running pass lets the unit back in; it is not owed a moved-base run (its record has rework input).

*How it stops.* The lane runs the thread with `interrupt_before` the outside steps, and when the thread stops there it decides: a
`rework` whose saved feedback is the conflict's (the first, a conflict rework) is resumed through; everything else is handed back
(UNVERIFIED 1). A thread that stops for the usage guard (an interrupt in `gate`) is not a hand-back.

*Why check failures are handed back.* A check that fails after a port could be about the move, but the pipeline cannot tell that from a
check that fails for another reason; a rule that guesses runs unbounded fix rounds in the lane (`max_fix_rounds` times a lane worker for
as long as it takes), which is the unbounded agent work outside the build cap that the earlier design refused. One predictable line
(the lane does the move and what follows from it, a person's or a reviewer's work is a build's) is preferred.

*What a handed-back unit still keeps from the lane.* The move was made in the lane; the build worker's `prepare` finds the base already
held and does nothing, so the worker is spent on rework only.

### 4. Counting: the run is admitted without room, and it takes room

A unit in the lane is the same unit already in progress. `max_units_in_progress` does not change: the unit is stored `running` (counted
by `in_progress`), or `planned`/`in_review` with work, as it was. The earlier draft of this decision removed lane units from the build
slot counts so that a run left the free workers alone. The owner decided the opposite on one point: a run **counts toward slot
occupancy**, and keeps the other half: it is never refused or delayed for want of free workers.

- **Admission is unchanged and does not read occupancy.** The lane starts a run when it has a lane worker (`project_limits.max_concurrent_restacks`)
  and the usage guard allows it. The pool of build workers, `RestackLane`'s admission (`restack_lane.py` ~128, built at `build_restack_lane`
  in `cli/pipeline.py` ~3387), `owed_units` and `lane.scan` never read the occupancy. With four builds running at a cap of four and a
  base that moves, the run starts at once and the occupancy reads 5/4. Going over the cap is allowed for lane work only.
- **The occupancy.** For a project: the set of unit ids of the builds in flight, the moved-base runs running in the lane (`lane.running`;
  a move counts as lane work too) and the units stored `running` as the counts already take them. It is a set union, so a lane unit
  stored `running` (the `restack_conflict` / `restack_deferred` path) counts once, and so does a unit both in flight and stored running.
  Work waiting in the lane behind the lane's cap (`lane.waiting`) is not counted until it runs. `free = max(0, cap - occupancy)`.
- **No build while at or above the cap.** Every start that `max_concurrent_stacks` gates, new starts and resumes, is held back while the
  occupancy is at or above the cap.

Where the occupancy is taken instead of removing lane units (the three counts of build slots, each for a project after
`limits-split-into-global-and-project` groups 6 and 7):

- `run_round` (~1541-1557): `held` (stored `running`, not idle) is united with `lane.running` and `free = max(0, cap - len(in_flight | held
  | lane.running))`; the `[:free]` slice of `resumable_units` then holds back resumes as well. Today `held` already counts a lane unit
  stored `running`; what is new is the lane units that are not stored `running` (a run on a `planned` or `in_review` unit before its
  state is written).
- `_evaluate_round` (~1907-1937): the view's lane units count as running for `slots`, and `ready_units(max_concurrent=cap + len(for_the_lane))`
  keeps its room for the owed units; its per-project `running` count (`units.py` ~964-1003) takes the union too, so a project at or above
  its cap starts nothing.
- `resumable_units`: flagged units stay out of it (decision 2), and its caller's `free` is the occupancy's.

`sample()` (~2292-2318) changes to the occupancy: `running` is the union and may exceed `cap`, `free_workers` is
`max(0, cap - occupancy)`, and the gauges `abk.slots.free` and `abk.slots.idle_with_ready` report it. `abk status` gains a slots line,
`slots: 5/4, 1 restacking`, beside the restacks line (`cmd_status`, ~513-537; no figure of this kind exists today). After
`limits-split-into-global-and-project` the three counts are made for each project; the occupancy is written against whichever counting
exists, and group 7 of this change `Needs:` theirs. The documents say these limits are across all repos while the code counts for each
project (`ProjectKey`); the spec stays per project and the documents group corrects the wording.

*No double count.* A unit that is in flight, stored `running` and in the lane is one id in the set, and `max_units_in_progress` reads
`in_progress` as before, so a run never counts twice in either figure.

### 5. A conflict rework starts with the move

The poller's conflict kind is today delivered as a `rework` event: for a parked thread `after_await_review` routes it to `rework`, for a
unit with no thread `_requeue_with` plans it and the run starts at `prepare`. The first path skips the move, which is what the case
above shows. For a unit that is a moved-base run (decision 1) the event is delivered to the move: the thread is positioned at `prepare`
(as a `base_moved` event does) with the conflict feedback kept and sourced `conflict`. `prepare` moves the branch; if the move
settles the conflict (clean or resolved), the conflict-sourced feedback is cleared and `after_prepare` goes on to `checks`: no rework
agent is called on a conflict that is gone. If the move leaves a conflict, `adapt` ports the work, and the rework step then runs with
the conflict feedback only if the port left something (it does not clear it today; the feedback goes on). A unit with rework input of its
own is not changed by this: it is a build and the event is delivered as it is. This is the rule `on_conflict` already follows for a
trunk-based unit ("restack first, rework second").

### 6. The bound, and the stop

Two bounds exist already and stay: inside a run, `max_review_rounds` review rounds, `max_adapt_rounds` port rounds and the once-per-run
loop of `verify_base`; across runs, `conflict_attempts` at a base tip. The new bound is across moved-base runs:

- Each moved-base run the lane **starts** is one attempt at the tip of the unit's base, recorded with `record_conflict_attempt(tip, head,
  attempts + 1, at)` on the fields `on_conflict` already uses (so the poller's attempts and the lane's are one count for one tip, which
  is the point: a conflict is not attempted `max_review_rounds` times by each). `head` is the unit's pushed head at the start.
- A run resumed after an interruption (the flag is set, same tip) is the same attempt. A run that never got going (the branch held, a usage
  pause that deferred it before its first agent call) is not an attempt, as `on_conflict` does not count a deferred move. A hand-back is
  counted as the attempt it was.
- When `conflict_attempts` at the current tip is `>= global_limits.max_review_rounds`, the lane does not hand the unit over: it holds the
  unit, as `_hold_conflict` does for the poller's attempts (`HELD`, `held_by` the review loop, cause `needs_human`; freed by `abk release`),
  with a note: `restack held: N attempts at <base>'s tip <sha12> did not settle it; the last ended <planned for a restack conflict /
  failed / ...>`. A new tip starts the count at zero, so a trunk that keeps moving is followed one attempt per move.
- `attempts_spent`'s second arm (the pushed head equals the recorded head) is not used for the lane: a lane run that changes nothing
  and ends planned would otherwise read as "spent" after one attempt at a conflict that has not been tried three times. The lane compares
  the count only. (The poller's rule, which sees the host's answer after a push, is unchanged.)

*Reused rather than new:* `max_review_rounds` and the existing record, as the sibling change did. No setting and no field beyond the flag
and the cause.

### 7. Usage: the guard before every agent call

A moved-base run asks the guard exactly as any run: the graph's `gate` before each node in `AGENT_NODES` (the port, a conflict rework,
the review) already does it with `starting(unit.id)` and the same decision (`decide_start`, estimate rules included), and interrupts the
run with the pause, which `_build_unit` turns into a pause of the pass. What is not covered today is the resolver `prepare` asks inside a
thread (item 6 of what exists): it is put behind the same decision (`runner.may_start` under `starting(unit.id)`, raising `AgentRateLimited` with
the guard's `resume_at` as the lane's own `gated_resolver` does for a stack move), so every agent call of a lane run is asked and none
relies on the runtime's refusal. A clean move calls no resolver and is not asked. After a refusal:

- the run is interrupted at the node, the unit stays `running` and flagged, and the lane does not retry it before the guard's `resume_at`
  (`defer_until`) nor on a timer: the scan after the pause ends (`_was_paused`) resumes it, which is what `restack_deferred` already
  does for a move;
- a refusal is not an attempt (decision 6) and not a hand-back.

The review in the lane uses the review model and writes its ledger rows as it would in a worker, because it is the same node; the ledger
node `restack` is for the resolver and the port as before. The repository turn is per phase exactly as before: nothing in the lane takes
a turn around a whole run; each git phase takes its own.

### 8. Display

While a unit's moved-base run is queued or running, the lane's record holds it, so `restacking onto <base>` is shown by `abk status` and
the graph page for the whole run (the existing overlay), not only for the move. `restacks: N running, M waiting` counts a run as one
running restack, and units owed a run the lane has not taken as waiting. A slots line, `slots: 5/4, 1 restacking`, shows the
occupancy over the cap and the restacks in the lane (decision 4); the sample row and gauges report the same occupancy. The `rebasing` and `reworking` derived states are for the
display of runs not in the lane and are not changed; the overlay is what says "in the lane".

### 9. What is not changed

The once-per-run find of a moved base, the cap's meaning for moves, the unit states, `restack_conflict` and `restack_deferred` as
causes, the poller, the attempts the conflict handler counts, the per-project counting and the lane per project, and the lane's
admission (the cap and the usage guard only). A person's chat on a
unit (a lease) still stops the lane from taking it.

## Interactions with the pending changes

- `limits-split-into-global-and-project`: group 5 (the setting in `project_limits`) is in; group 8 (a lane for each project) rewrites the
  lane into a collection routed by project and group 7 (and 6) the counts in `run_round` and `_evaluate_round`. This change reads and
  writes the same functions; group 2 here `Needs:` its group 8 and group 7 here `Needs:` its group 7, so the lane's work and the exclusion
  are written once, against the per-project shape.
- `test-kinds-are-unit-test-and-e2e-test` renames modules and names (`wiring.py` to `workspaces.py` is in its group 4, in flight); the
  paths here are those of the commit read and are followed by the builder through the rename. No `Needs:`.
- `tier2-*` and `a-unit-over-its-tier-is-held-and-split`: they decide what runs at tier 2 and what holds a unit; this change hands
  `tier2` steps back and holds nothing of their kind. No `Needs:`.

## Risks

- **The lane's cap.** `project_limits.max_concurrent_restacks` is 2. A move took seconds and a whole run takes tens of minutes, so two
  long runs can hold every lane worker while a burst of seconds-long moves waits, which weakens "starts when it is seen". This change
  keeps the one setting (the decision is that the lane's own cap bounds the run) and does not change its default; a person who sees
  moves wait raises it, and `abk status` shows it as `restacks: 2 running, 5 waiting`. A split of the cap into moves and runs is a
  follow-up if the status shows it (UNVERIFIED 8).
- **A hand-back that is a surprise.** A unit that conflicted and was ported in the lane reaches a build worker anyway when its review asks
  for changes. That is the line drawn in decision 3 and is stated in the note; it is still one fewer queue wait than today's three.
- **Answered feedback cleared.** Decision 1 clears feedback that review has approved over. If `approved` is not kept correctly across a
  port (UNVERIFIED 7) a unit with real feedback could lose it; the test for it is written first.

## Scope notes

- Docs: `docs/architecture.md` (the pass, what takes a slot, the lane's runs), `docs/unit-graph.md` (the `prepare` row, the conflict
  event, the hand-back), `docs/configuration.md` (what `max_concurrent_restacks` bounds), `docs/cli.md` (the status line); the
  `abk-pipeline` skill's account of what takes a slot and of `restack_conflict` / `restack_handed_back`; `CHANGELOG.md` under
  `## Unreleased`, folded into the bullet on restacks.
- Main specs: the capabilities `unit-scheduling` and `restack-conflicts` have the lane's requirements already (the archived change was
  synced), so this change MODIFIES "A restack takes no build slot and no start admission", "A restack starts when it is seen" and "A
  restack in the lane honours the usage guard for its agent step", with every original scenario copied, and ADDS the rest.
- The new cause `restack_handed_back` and the flag are the only stored additions; no migration.
