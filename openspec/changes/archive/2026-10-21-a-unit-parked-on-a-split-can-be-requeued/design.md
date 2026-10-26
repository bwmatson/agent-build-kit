## Context

Code at agent-build-kit `origin/main` (e0d26911):

- **The refusal.** `requeue_refusal(unit)` (`src/agent_build_kit/cli/pipeline.py:5765-5772`) is called by `requeue()` (5775 on) before anything else;
  the web UI calls the same function (`docs/cli.md` "Requeue is `abk requeue`'s own function"). `cmd_requeue` (5481-5509) maps the flags to a mode
  (`resume`, `rework`, `restart`) and reads `--note`/`--note-file`; the parser is at 5993-6015 (its help says "give a failed or held unit another go").
- **The checks after it.** A note with `resume` is refused (5805-5810); `rework` with neither a saved failure nor a note is refused (5816-5822).
- **The delivery.** `requeue()` waits on unmet dependencies (`waiting_on`), then calls `resume_thread(inst, unit, "requeue", store=store, reason=,
  requeue=, guidance=note)` (`resume_thread`, 5277-5345). It returns None for a unit with no thread; `BranchBusy` means a step holds the branch
  ("is being built"). With no thread `requeue()` stores the guidance (unless `restart`) and sets `PLANNED` with cause `requeued` and a history note
  (`reworking from ...`, `starting over`, `resuming where it stopped`). In the thread the requeue handler records the guidance, sets the unit running
  and, for a unit not parked at a node, starts a fresh run at `prepare`; a note plus work on the branch makes the run a rework (`standing`).
- **What a park is.** `parked_on_split` (`pipeline/units.py:862-875`): planned with cause `split_held`, or planned/unplanned with non-empty
  `parked_splits` whose cause is not another. `parked_holds` (`pipeline/e2e_holds.py:170-173`) is the parked splits held now for the unit's repo, with
  their `Hold` (reason, until); `hold_text` renders one. `set_parked(unit_id)` with no splits clears the three park fields
  (`unit_store.py:1186-1189`). `release_split_changed` (`cli/pipeline.py:2150-2208`) is the existing release-as-rework: deliver, then
  `set_parked(unit.id)`, so a delivery refused with `BranchBusy` changes nothing.
- **Wait record.** `decisions.jsonl` (`pipeline/wait_log.py`) closes a unit's wait record when the unit stops waiting; `requeue()` already clears
  `wait_ended` through `_requeued` (5925-5930). A unit parked on a split has a `SPLIT` wait record that the requeue's state change ends.
- **Pull request and run.** `StoredUnit.pr` is `None` until a pull request is opened (`unit_store.py:253`); `unstarted` reads branch, `pr`, `pushed` and
  `approved` (380). A live run is a step holding the unit's branch lock (`BranchBusy`, `pipeline/workspaces.py:38`) or the unit in the tick's
  in-flight set.

## Decisions

- **A parked unit is a unit `parked_on_split` is true of and that is `planned`.** The test is the one `_split_wait_lines` and the status use, so a
  unit the status calls "waiting for e2e-test split" is the unit this accepts. An `unplanned` unit with parked splits (dropped from the plan) is not
  accepted: it is left alone by decision of `a-dropped-unit-parked-on-a-split-takes-no-place`, and a requeue would run work the plan no longer has.
- **`requeue_refusal` grows a `parked` branch, in the same function, so the web UI gets it too.** It still refuses by state first (`running`,
  `in_review`, `merged`, `unplanned`, a plain `planned` unit with no park), now with the message extended only where it is about a parked unit. It
  additionally refuses a parked unit that has a pull request (`unit.pr is not None`; there is one to orphan), and one in flight: the check is the
  delivery's own, `BranchBusy`, which `requeue()` already turns into "is being built; requeue it again once it has stopped" and leaves the unit as it
  was. No new notion of in flight is invented for a unit with no thread.
- **The mode decides.** `rework` and `restart` accept a parked unit; `resume` accepts it only when none of its parked splits is held
  (`parked_holds` empty), and then does exactly what `release_split_held` does (`resume_thread(... reason="resume", requeue=RESUME)`, with the
  no-thread fallback `PLANNED`/`requeued`) and clears nothing itself: the e2e step clears the park when it runs. A plain requeue while a parked split
  is held is refused with: `<unit> is parked on e2e-test split <names> (held: <reason>[; <reason>]); give --rework with a note saying what changed,
  or release the split`. A plain requeue of a unit whose group's `Split:` now differs from its stored split is refused too, saying the pass reworks it
  (the existing rule decides; resuming it would run the old tests, which is why `_releasable_split_units` leaves it out).
- **`--rework` on a parked unit needs neither a saved failure nor a note.** The check at 5816-5822 ("no saved failure to rework from") is skipped for
  a parked unit: the person is asking for the agent to run again on what is on the branch. Without a note the history says so (`reworking on the
  person's request`); the unit has work on its branch but no guidance and no feedback, so `standing` would resume rather than rework, and the
  requeue therefore stores an automatic one-line guidance, labelled automatic, saying the unit was parked on <splits> and the person asked for the
  agent to run again, to read the group's tasks and the failing or mis-tagged tests. With a note the note is the guidance, as for any rework.
  `--restart` clears feedback and runs from the agent's step, as for a failed unit, and stores a note when given.
- **Clearing, after the delivery.** As `release_split_changed` does: deliver first, then `set_parked(unit.id)`, drop the `split_held` cause by the
  requeue's own state change (`requeued`), and let the wait record close by the existing rule. A delivery that raises `BranchBusy` leaves the unit
  with its park and every field it had. The stored split is not touched: the group did not move, only the code is to change (the tag fix is the
  builder's, and the next e2e step re-evaluates which split the tests are in).
- **History.** The entry is `requeued: reworking, parked on <splits>` plus the person's note excerpt, `guidance_excerpt` (first 200 characters), as
  the other requeues do, naming every split in `parked_splits` and not only held ones.
- **Delivery with a thread and the mode-specific flow are unchanged**, including a `Needs:` wait: a parked unit that also waits on an unmet
  dependency goes `planned`/`gated` with the saved requeue, as `requeue()` does today, and its park fields are cleared then, since the unit will not
  resume at its e2e step.
- **Status after.** The unit is no longer parked: `abk status` shows it as a requeued planned unit (queued, or running once the tick starts it), no
  `waiting for e2e-test split` line, and the history shows the note. No new wait reason.
- **Priority 0.** A live unit is stuck on it and no command ends its park.

## Needs

No `Needs:`. It builds on `a-parked-unit-follows-its-groups-split` and `a-dropped-unit-parked-on-a-split-takes-no-place`, both archived and merged.

## Not in this change

- Reading the unit's tag, test file or `Split:` to decide that the park was a mistake; the person says so by asking for a rework.
- Un-parking by a command that does not run the agent (a plain requeue after the release is the existing resume).
- Parked units that are `unplanned`, or parked for a dirty tree (`parked_node`, cause `gated`), which `requeue` already handles.
