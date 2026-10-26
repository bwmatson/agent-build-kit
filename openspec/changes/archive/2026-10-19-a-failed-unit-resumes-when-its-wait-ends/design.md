# Design

## What was checked, and where

Read-only against agent-build-kit: `origin/main` for `src/agent_build_kit/` paths, and
`origin/spec/failed-units-waiting-on-a-prerequisite-free-their-slot/1` (PR #260, in review) for `failed_waiting`.

- `pipeline/units.py` (that branch) `failed_waiting(unit, graph)` (line 656) is `state == FAILED and bool(waiting_on(unit, graph))`;
  `failed_waiting_units(graph)` (661); `waiting_on` (497) is what the scheduler and the graph ask; `in_progress` (622) returns false for a
  waiting failed unit. This change reads `failed_waiting`/`waiting_on` and needs that unit to be merged.
- `cli/pipeline.py` (main) `run_round`: after the usage check, `_step("gating sent-back units", gate_sent_back, ...)` and
  `_step("releasing gated units", release_gated, inst, store, in_flight=spared)` (1243-1244). `release_gated` (1474) is the model: a planned
  unit with cause `gated` and a stored `gated_requeue` whose `waiting_on` is empty is delivered through `resume_thread(..., reason=mode,
  requeue=why)` and skipped on `BranchBusy` or when in flight. A step that raises is logged and the rest run.
- `requeue(inst, unit_id, mode, *, say, note)` (3773) is `abk requeue`'s and the web UI's single function: it refuses anything but failed or
  held, refuses a note on a resume, refuses rework with no saved failure and no note, parks a unit with unmet `waiting_on` as planned and
  `gated` (3811-3826), and otherwise delivers through `resume_thread` or sets planned with cause `requeued` and the history note
  `requeued: resuming where it stopped` / `reworking from ...` / `starting over`.
- `pipeline/unit_store.py`: `RequeueReason` (102) has `RESTART`, `RELEASED`, `RESUME`, `FROM_FAILURE`; `FeedbackSource` (122) has `NONE`,
  `REVIEW`, `CI`, `CONFLICT`, `TIER1`, `TIER2`; `StoredUnit` (164) carries `feedback`, `feedback_source`, `feedback_from_person`, `guidance`
  (a person's `--note`, "shown ahead of `feedback` in the next prompt and cleared where the rework commit is made"), `step`, `gated_requeue`
  and a history whose last entry gives `cause`; `Cause` (70) has `FAILED`, `TOOLCHAIN`, `ENVIRONMENT`, `HOST_UNAVAILABLE`,
  `NETWORK_UNAVAILABLE`, `SERVICE_UNAVAILABLE`, `GATED`, `REQUEUED`. Store setters are one line each (`set_gated_requeue`, 764).
- `config.py` `LimitsConfig` (306-): where a `limits.*` setting is declared, as a `StrEnum` or typed field with a comment.
- `docs/cli.md` `abk requeue` (354-): the three modes, the guidance on when each fits, a person's note, and "A unit with a `Needs: … merged`
  line whose dependency has not merged ... the next tick delivers the requeue in the mode it was given".
- The branch of `needs-start-on-the-parents-branch/2` is not on `origin` yet (UNVERIFIED: its code). Its tasks (group 2, 2.1 and 2.4) make
  the gated requeue and its release read `waiting_on` instead of `unmet_gates`; `main` already has the gated requeue, `gated_requeue` and
  `release_gated` for the `merged` form.

## The trigger

A new pass step, `requeue_wait_ended(inst, store, *, in_flight)`, runs right after `release_gated` in `run_round`, so it shares the usage
check's ordering, the `in_flight` exclusion and the "a step that raises is logged" rule. One step does both halves, each pass:

1. **Record.** For a unit in `FAILED` for which `failed_waiting(unit, units)` holds, set the stored field `waited_on` to the ids of the units
   `waiting_on` names, if it is empty or differs (a second prerequisite joins the record). A unit in any state but `FAILED` has `waited_on`
   cleared, so a held, requeued or closed unit carries no marker.
2. **Detect.** For a `FAILED` unit with a non-empty `waited_on` and an empty `waiting_on`, the wait has ended. Look up each recorded id:
   if every one is merged, satisfied with its work landed, or (same repo) in review, requeue it as below; otherwise (a prerequisite closed,
   or no longer in the store) leave it failed, replace the marker by `wait_ended: closed` and print the status line. Either way `waited_on` is
   cleared, so the end is acted on once.

Why a stored marker and not just "failed and `waiting_on` empty": that is every failed unit with no wait, which today waits for a person. Only
the transition identifies a unit that was waiting. The marker is set by the same pass step that detects, so a wait shorter than a pass is not
seen, and the unit is not requeued; it then fails as an ordinary failure, which is correct since nothing was observed to wait on. UNVERIFIED:
whether a poll (`pipeline/events.py` handlers) can move a prerequisite from not-reviewed to merged between the pass's record and detect steps
on the same unit; the step reads `store.all()` once, so it sees either state, and a later pass finishes the detect.

**Exactly once per wait.** The requeue clears `waited_on`. The unit then fails again: it is `failed` with `waited_on` empty, `failed_waiting`
false (its prerequisites are merged), and the step does nothing. A prerequisite added later makes `failed_waiting` true, the record step sets
`waited_on` again, and when that wait ends the unit is requeued again: that is a new wait, not a loop. A unit requeued while `waiting_on` was
non-empty is parked by `requeue` as planned and `gated` and is no longer failed, so its marker is cleared and `release_gated` owns it.

## The mode

The mode comes from fields the store already has, in this order, so the same record always gives the same mode:

1. `global_limits.wait_end_requeue` is `resume` or `rework`: that mode. `rework` with no saved failure and no person's guidance falls back to
   `resume`, as `requeue` would otherwise refuse it. `off`: the step does nothing, and the status does not count.
2. `auto`, the default: the cause of the failure. A history last-entry cause of `TOOLCHAIN`, `ENVIRONMENT`, `HOST_UNAVAILABLE`,
   `NETWORK_UNAVAILABLE` or `SERVICE_UNAVAILABLE` is the environment's failure: **resume**, which `docs/cli.md` gives as the right mode for
   "a missing tool, a flaky check" and which redoes nothing the agent already did.
3. Otherwise a saved failure whose `feedback_source` is `TIER1` or `TIER2` and whose `feedback` is non-empty is a check that failed on
   real errors: **rework**, which `docs/cli.md` gives as the right mode when "resuming runs the same check on the same branch and fails the same
   way with the agent none the wiser". A resume here would fail the same way as before unless the prerequisite fixed it, and when it did
   the rework's agent finds nothing to change and its next checks pass.
4. Anything else (no saved failure, a source of `REVIEW`, `CI` or `CONFLICT`, which a pass handles by their own paths): **resume**.

`restart` is never chosen: it forgets the failure, and no stored field says the attempt itself was wrong.

**A person's note.** `guidance` is on the record and is not changed by the step. A rework shows it ahead of the saved failure, as for
`abk requeue --note`; a resume does not run the agent, so it stays in the record for the next run that does. The rule above ignores it: it
does not turn a resume into a rework, because "the person recorded a note" says what to tell the agent, not what failed. UNVERIFIED: the
note is not cleared by a resume (`StoredUnit.guidance` is cleared at the rework commit only); the builder reads `unit_store.py` and
`resume_thread` to confirm.

UNVERIFIED: whether a prerequisite that is a fix for a check failure should resume rather than rework. The store does not record that the
prerequisite was added for the failure, so the rule cannot know; the setting is how an installation overrides it.

## What the requeue does

The step calls `requeue(inst, unit.id, mode, say=log, note="")`'s delivery, with one new keyword `because`: a history note replacing the
default, `requeue: its wait ended (waiting on <change> group <n> is now merged)`, naming each recorded prerequisite and its state (`merged`
or `in review`) as `dependency_wait` and `group_names` write them. It therefore:

- delivers into the thread with `resume_thread(..., reason=mode, requeue=why)`, or, with no thread, sets the unit `planned` with cause
  `requeued`: the same two outcomes as a person's requeue, with the thread, branch, feedback and guidance kept;
- raises nothing a person's requeue would refuse: the mode was chosen so none applies, `BranchBusy` leaves the unit failed with its marker
  and the next pass tries again, and a unit in `in_flight` is skipped;
- goes through the usage gate and the slot rules like any resume. The step only places an event on the thread; the build runs when a tick
  starts it, the usage check (`_may_build`) ends a round before any build, and `max_concurrent_stacks` and the depth caps apply as for any
  resumed unit. `max_units_in_progress` only stops units that have never started, so the requeue is not held by it; the unit counts again from the
  moment its wait ends (the first rule of `failed-units-waiting-on-a-prerequisite-free-their-slot`), still failed until the step runs in the same pass.

Group 2 of `needs-start-on-the-parents-branch` feeds the gated requeue from `waiting_on`; a unit requeued by a person while it waits is
parked there and delivered by `release_gated`. This change adds an automatic requeue for the other direction (a unit that stayed failed),
and calls only `requeue`, whose `waits` check it does not change. **No `Needs:` on that unit is added:** the step reads `waiting_on` only,
and `requeue`'s signature change here is additive. UNVERIFIED: that unit's branch (not on `origin`); if it moves `requeue`'s gated branch
into another function, the builder's one added keyword moves with it.

## Interactions

- **Held** units are never requeued: the step looks at `FAILED` only, and a held unit's marker is cleared. A unit held after its wait began
  keeps nothing; released to `failed`, it is judged afresh.
- **Closed, merged, satisfied:** never.
- **A prerequisite that was closed.** `waiting_on` keeps a closed parent as a wait (it is not in `REVIEWED` and has not landed) until the
  `Needs:` line is removed or the plan changes, so the wait does not usually end that way; when it does end (the line is removed, the
  dependent re-planned) the recorded prerequisite is closed. The unit was waiting for something that never came, and the person who
  removed the line or the closure should decide: the unit is not resumed and the status says `wait ended: <change> group <n> closed, requeue
  to retry`. A plain failure keeps waiting for a person too, so this is the case the user's reasoning does not cover. UNVERIFIED:
  `waiting_on`'s treatment of a closed parent; the builder reads it and, if a closed parent is already dropped from the waits, the record
  step's lookup of the recorded ids is what finds it.
- **A plain failure** with no `Needs:` and no dependency change has no marker and waits for a person, as today. `no auto-retry for stopped
  jobs` is narrowed, not removed: a requeue happens only at a wait's end, once per wait, never on a timer.
- **The failure-fix and flaky-test mechanisms** park a unit as `planned` with cause `gated` and resume it themselves when the fix is in
  review; that unit is not `failed`, so this step never looks at it and they are unaffected. A unit that failed, then got a `Needs:` line
  on the fix, is this change's case.
- **`a-unit-waits-for-all-but-one-open-parent`** (planned, unstarted) changes which parents a planned, unstarted unit waits for. It is written
  in terms of `waiting_on`, as is this change: the wait ends when `waiting_on` is empty, whatever the set of parents it names then. No `Needs:`.
- **The caps and the limit** are unchanged: the unit counts from the moment its wait ends, as the earlier change says, and the requeue only
  resumes work already begun.

## Status

A unit waiting is `failed, waiting on X` and a requeued one reads as any requeued unit: nothing changes there. The status adds the line
`failed units resumed when their wait ended: N today`, N the number of such requeues whose history entry (note beginning `requeue: its wait
ended`) falls on the local day, derived from the history, so no counter is stored; it is left out when N is zero and with `off`. A unit left
failed because a prerequisite closed prints under its failed line: `wait ended: <prerequisite> closed, requeue to retry`, from the stored
`wait_ended` value, cleared by any requeue.

## Stored fields

Two optional fields on `StoredUnit`: `waited_on: tuple[str, ...] = ()` and `wait_ended: str = ""`, setters beside `set_gated_requeue`.
A store written before them loads (defaults); an older release reading one drops them, as `_tolerate_other_releases` does for empty values
(UNVERIFIED: that validator refuses a non-empty unknown field, which the builder checks before choosing between a field and a history entry).

## Docs

`docs/cli.md` `abk requeue` gains "automatic requeue when a wait ends": when, the mode rule, the closed case and the setting.
`docs/architecture.md` says the requeue of a failed unit is by a person or when its wait ends. `docs/configuration.md` and the `abk-config`
skill give `global_limits.wait_end_requeue`. The `abk-pipeline` skill's failed-unit guidance names the new step and the status line. One changelog
bullet under `## Unreleased`.

## Related changes

`failed-units-waiting-on-a-prerequisite-free-their-slot` (PR #260): required, and its "never requeued automatically" is superseded here.
`needs-start-on-the-parents-branch` (unit 2 running): independent, see above. `tier2-failures-in-untouched-tests-are-fixed-once` and the
flaky-test park: unaffected.
