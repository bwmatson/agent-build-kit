## Context

What a parked unit is, and where each fact lives (code at agent-build-kit `origin/main`, 872fa344):

- **The park.** The e2e node parks a unit whose tests of a held split did not run: `park_for_split` (`graph/nodes.py:1530-1544`) holds the unit
  `planned` with cause `split_held` and calls `store.set_parked(unit, splits, sha, snapshot)` (`unit_store.py:1182-1185`). A park for a dirty tree
  or a fix change is another thing (`parked_node`, `graph/state.py:129`; cause `gated`) and is not read here.
- **The release.** `release_split_held` (`cli/pipeline.py:2073-2102`, run by the tick at 1689, not in a dry run) delivers a plain resume
  (`resume_thread(..., reason="resume", requeue=RequeueReason.RESUME)`) to each unit `_releasable_split_units` returns (2105-2118): `planned`,
  cause `split_held`, not in flight, `parked_holds()` empty. `parked_holds` (`pipeline/e2e_holds.py:170-173`) is the splits of
  `unit.parked_splits` that are held for the unit's repo. The resumed run runs only the parked split, and only if the head is still
  `parked_sha` (`graph/nodes.py` e2e step, `resumed = bool(before.parked_splits) and r.head(tree) == before.parked_sha`, about 1957), and its
  e2e step clears the park (`set_parked(unit.id)`, 1971-1973).
- **The stored split.** `Unit.split` (`pipeline/units.py:134`) is set from the unit's first group by the planner (`planner.py:191`, `_unit_split`
  264-267) and kept for a started unit by `upsert` (`unit_store.py:732-743`, `if existing and not existing.unstarted`). `unstarted` is "planned
  with no branch, commit or pull request" (`unit_store.py:359-363`), so every parked unit is started for this purpose. The planner's check that a
  unit's groups are in its split (`planner.py:468-472`) covers the units of a new plan, which a started unit is not part of.
- **What a replan does to a started unit.** Nothing to its split (above), and its groups must still exist (`_gone_groups`,
  `cli/pipeline.py:3473-3476`). `_tag_problems` (3501-3558) compares repo, project, tier and flag, not split. So a person's edit of `Split:` on a
  started unit's group is, today, invisible to the pipeline: the stored split goes on saying the old one. This change reads it.
- **Requeue.** `requeue()` (`cli/pipeline.py:5646-5773`) is for failed and held units (`requeue_refusal` 5636-5643). The pipeline's own
  requeues of a planned unit call `resume_thread(inst, unit, "requeue", store=store, reason=..., requeue=RequeueReason.X, guidance=note)`
  (`resume_thread`, 5149-5222), as `release_gated` does (1957-1987) and `release_split_held` does; `resume_thread` returns None when the unit has
  no thread, and the caller then sets `PLANNED` with cause `requeued` itself. In the thread, the requeue handler records the guidance
  (`graph/nodes.py:2383-2384`), sets the unit `running` with cause `requeued` and, for a unit not parked at a node (`resumes_parked` is false,
  2644-2650: a split park sets no `parked_node`), starts a fresh run at `prepare` (`fresh_run`, 2431-2459). `standing` (1084-1101) turns a
  guidance note plus work on the branch into `had_feedback`, so the run reworks instead of resuming (1062: "A person's note makes the run a
  rework as saved feedback does, once there is work on the branch"). `RequeueReason` has `RESTART`, `RELEASED`, `RESUME` and `FROM_FAILURE`
  (`unit_store.py:154-161`, a persisted enum, listed in `graph/checkpointer.py:27`).
- **Status and the wait log.** `_split_wait_lines` (`cli/pipeline.py:2118-2160`) lists the gated units and the parked ones (`parked_on_split`,
  `pipeline/units.py:862-875`). `decisions.jsonl` is the wait log (`pipeline/wait_log.py`): a record when a unit's reason to wait changes, and a
  closing record (`none`) when the unit is no longer waiting, which a released unit gets without any code of its own.

## Decisions

- **The test is "the group's split differs from the stored split, and the new split is not one it is parked on", read from `tasks.md`.** It is
  the person's edit that is detected, not a replan: the pass reads the units' groups from the validated tasks file as `_tag_problems` does
  (`_validated`, `cli/pipeline.py`, via the task catalog) and so works whether or not a plan was made, and `abk replan` is just one more caller.
  Why differs-from-stored and not only not-in-`parked_splits`: a unit stored in `rest` that parked at its e2e step on `acp` because its tests
  turned out to be in `acp` (the backstop; its group says `rest` or nothing) has `parked_splits` `["acp"]` and a group split of `rest` equal to the
  stored one. It is the unit the park is for, not one whose declaration moved, and must stay parked. Why not-in-`parked_splits` as well: a person
  who edits `rest` to `Split: acp` on such a unit declares the very split it waits on, so releasing it would only park it again.
  When a unit's groups do not read as one split (a joined group of another change, a group missing or its tags refused) nothing is done and the
  unit stays parked, since `abk tags` and the plan already refuse those files.
- **The release is a rework, through `resume_thread`, with `FROM_FAILURE`.** No new `RequeueReason` member: the enum is persisted in
  checkpoints, and `FROM_FAILURE` already means "run the agent from what it was told" (`release_gated` maps it to rework). The note is the
  guidance of the requeue (`guidance=`), which the thread stores and `standing` turns into a rework. It is an automatic note, labelled so, and
  reads along the lines of: group N's `Split:` changed from X to Y and its task text changed with it; read group N's tasks in `tasks.md` again
  and apply them, including converting the tests that ran in X. When the unit has no thread (`resume_thread` returns None) the pass stores the
  guidance and sets the unit `planned` with cause `requeued`, as `requeue()` does for a rework (5738-5760). The reason shown in the history
  entry is "its group's Split changed from X to Y", so `abk status` and the unit's history say why without opening the note.
- **Clear the park, update the split, in the same pass, after the delivery.** `parked_splits`, `parked_sha` and `parked_snapshot` are cleared with
  `set_parked(unit)`; the stored split is set to the group's (a store write beside `set_parked`; `upsert` keeps it afterwards because the
  unit has work). Cleared because the e2e step reads them to run "the parked split on the commit it passed on": after the rework the head moves,
  so `resumed` would be false anyway, but a stale `parked_snapshot` would be joined to the new run's snapshot if the head came back, the unit would
  read as parked (`parked_on_split`: `parked_splits` non-empty) and its place under `max_units_in_progress` would be wrong. Delivered first, then
  cleared: a delivery that raises `BranchBusy` leaves the unit exactly as it was and the next pass tries again; a failed write after a delivery
  cannot loop because a delivered unit is `running`, not `planned` with `split_held`, and so does not qualify.
- **Once, by construction.** The rule needs `parked_splits` non-empty and cause `split_held`, and the release clears the first, changes the
  cause (`requeued`) and sets the stored split to the group's, so the same unit does not qualify again. If the reworked run parks again (its new
  split is held, or its tests still land in a held one) `park_for_split` writes a new park with the splits that did not run; the group's split
  then equals the stored one, so the rule finds no change and the unit stays parked until that split is released, as any parked unit does. A
  second edit of the `Split:` is a second change and is acted on once more; that is a person's act, not a loop.
- **A new split that is held defers the release; the old split's release must not undo that.** The point of "a unit in a held split is not
  started" is not to spend usage on a run that parks again; a rework into a held split would spend it. So a qualifying unit whose new split is held
  for its repo (`repo_holds(...).held`, as `parked_holds` reads it) is left parked and the pass tries again. The release step would otherwise
  resume it at the old tests once the old split is released, so `_releasable_split_units` leaves out a unit whose group split differs from its
  stored one and is not parked on it (the same test), and only this rule releases it. The scenario "changed to another held split" covers both.
- **Placement: after planning, before `release_split_held`, not in a dry run; also at the end of `abk replan`.** The tick runs planning at 1659
  and the release at 1689; the new step goes between, so a unit released here is not also resumed by the plain release in the same pass (it is
  `running` or `requeued` by then, which the release does not select). `--only` and a unit in `in_flight` (the `spared` set) are respected as the
  release respects them. A dry run previews it with a line, as `_preview_split_releases` does for releases (2163-2170).
- **A unit in flight is not touched.** `unit.id in in_flight`, or any state but `planned` with cause `split_held`, is skipped before its tasks
  are read. A `running` unit reads `tasks.md` at its next step anyway ("each started unit reads tasks.md at its next step", `plan_all`
  comment at 3700), and an `unplanned` parked unit is left alone, as `a-dropped-unit-parked-on-a-split-takes-no-place` decided.
- **Status.** The parked line for a deferred unit (`_split_wait_lines`) says "its group now says Split Y (held: <reason>), reworks when Y is
  released" in place of "released, resumes this round". A reworked unit shows as the requeued unit it is, with the history note; no new
  wait reason (`WaitReason`) is added, and the unit's wait record closes in `decisions.jsonl` by the existing rule.
- **Priority 0.** The four live units are stuck on this and a person edited their files to unstick them; it is the emergency lane (see the
  `abk-authoring` skill).

## Needs

No `Needs:`. It touches the same functions as `a-dropped-unit-parked-on-a-split-takes-no-place` and `a-unit-in-a-held-split-is-not-started`,
both archived and merged.

## Not in this change

- Editing the stored split of a started unit on a replan in general (a unit that is not parked keeps its split, as `upsert` decides). Only the
  parked, split-held case reads the file.
- A person can also end any parked unit by hand with a command; none exists for a planned unit today, and this change does not add one.
