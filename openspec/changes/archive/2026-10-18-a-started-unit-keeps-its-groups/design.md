## Context

`UnitStore.upsert` (`pipeline/unit_store.py`) merges a plan into the store by unit id. After the merge, for a plan made for one change, it sets a planned unit
of that change that the plan omitted to `unplanned`. The comment above says "only a unit that never started can be dropped"; the test is
`unit.state != PLANNED`, and `StoredUnit.unstarted` (planned, with no branch, pull request, pushed commit or approval) is not read. Another path
(`unplan_vanished`) does use it. `plan_all` in `cli/pipeline.py` hides from the planner the groups of units in `_STARTED` (running, in review, failed, held,
merged, satisfied), so a planned unit with a branch is not "built" to the planner and its group can be given to a new unit. `in_progress` counts a planned or
unplanned unit that has a branch unless it is blocked or parked on a held split. `waiting_on` skips an `unplanned` dependency (it builds nothing) and holds
a unit behind a `closed` one. Nothing moves a started unit to a terminal state except a merge, a pull request closed on the host, or `satisfied`.

## Decisions

- **Retire is a new state, `retired`, not `closed`.** `closed` means the host closed the unit's pull request unmerged. The poller writes it, the dependents
  of a closed unit still wait (a closed parent holds a child for good), and the hold-and-split change reuses it for superseded units only because it
  re-points their dependents first. A retired unit has nothing to re-point to: its groups may be built elsewhere or not at all. `unplanned` is the nearest
  existing meaning (it builds nothing, and nothing waits on it), but it counts as in progress when it has work and the plan can revive it by id. So
  `retired` is treated as `unplanned` is wherever "this unit builds nothing" is read (`waiting_on`, `earlier_units`, `later_groups`, the cycle and graph
  finished sets), and unlike it is never in progress, is never revived by a plan, and counts as finished for archiving. This is the least new machinery that
  gives a terminal state the readers already know how to treat.
- **Dependents do not wait on a retired unit, and are listed.** A unit that depends on a retired one is not held. `abk retire` prints each dependent that has
  not finished, with its state, so the person sees what no longer waits. When the retired unit's groups were never built the command also forgets the
  change's recorded plan, so the next tick plans before it schedules: the planner rebuilds the dependencies of planned units, and `Needs:` lines are linked
  again on top, so a dependent is pointed at the new owner of the group before it starts. A dependent that has started and is stacked on the retired unit's
  branch is different, and the command refuses (below) rather than orphan its base.
- **Who may be retired.** Any unit whose state is `planned`, `unplanned`, `failed`, `held` or `in_review`. Refused: a finished unit (merged, closed,
  satisfied, retired); a `running` unit; a unit whose branch lock is held by a live process or that has a live lease, naming the holder, because a person
  stops that first; and a unit that a started same-repo dependent is stacked on (it has a branch and its base is this unit's branch), naming the dependent.
  A refusal changes nothing and exits 1.
- **The reason rule.** For each group the unit carries, the command looks at the other units that carry it. A group is "carried" when one of them has built it
  (merged or satisfied) or still owns it (see Ownership); the command says by whom. A group no such unit carries is "unowned": the work was not built.
  Retiring a unit with an unowned group needs `--reason`, because it drops wanted work; without it the command prints the groups and refuses. With a
  reason, the groups are listed as released and will be planned again. A unit whose groups are all carried needs no reason, but one is welcome, and it is
  stored when given.
- **Archiving.** An unfinished unit makes a change unarchivable, and a retired one must not. But retiring a unit whose groups were never built must not let
  the change archive with those groups missing. So a retired unit counts as finished in `is_ready_to_archive` only when every group it carried is also carried by
  a merged or satisfied unit; otherwise the change waits for the unit the replan plans for them. This is computed from the units alone.
- **Record.** The history gains one entry: state `retired`, cause `retired` (a new `Cause`), note the reason (or "retired" with none), and `by: "abk retire"`.
  A person's name is not recorded because the file is committed and shared. The unit's thread is deleted as a satisfied unit's is, so a later step cannot
  resume it. Its pull request, branch and worktree are not touched by the state write.
- **Pull request.** If the unit has an open pull request, it is closed with the reason by the same call a satisfied unit uses (`close_pr`: post the reason,
  then close, so the explanation is never missing). A failure to close is kept as `close_pending` and `retry_closes` repeats it each pass, which now also
  accepts a `retired` unit. The unit stays retired either way and the failure is printed.
- **Branch and worktree are kept by default.** `--delete-branch` removes the worktree (never forced; a tree with uncommitted changes is refused up front),
  then the local branch, then the remote branch through the forge's best-effort delete when the branch was pushed. The commits not pushed are those after the unit's
  last recorded pushed commit, or after its base when none was pushed. If there are any, `--delete-branch` alone refuses before changing anything and
  prints the count; adding `--discard-unpushed` accepts the loss. Every refusal is decided before the first change, so the command is all-or-nothing up to
  the state write; a failure afterwards (the host down) leaves the unit retired, says what remains, and exits 1.
- **Dry run.** `--dry-run` runs the same checks, prints each thing the command would do, the groups released, the dependents, the pull request and the
  branch steps, writes nothing and exits as the real command would (1 for a refusal, 0 otherwise).
- **A plan may not reuse a retired id.** The planner is shown retired ids as taken and `plan_round` refuses a plan that uses one (a `PlannerError`, so it
  takes an attempt as any invalid plan does). Otherwise the unit ids the model chooses (`<change>/<n>`) could collide with a retired unit's record and
  its groups would be owned by a record that never builds.
- **Ownership.** A unit owns its groups (its own and joined) while its state is `planned`, `running`, `in_review`, `failed` or `held`, or `unplanned` and it
  has work (a branch, pull request, pushed commit or approval). Merged, closed, satisfied and retired units, and `unplanned` units without work, own nothing
  for this purpose. `upsert` runs the check on the store as it would be after the merge and refuses, with `GroupOwned`, any group that two owners carry
  when at least one is started (not `unstarted`) and the pair is new in this plan: a unit that is new, or that did not carry the group before, is the claimant.
  A collision already in the store (a legacy one) is not refused, so no replan is blocked by history; it is listed by the status instead.
- **Refuse the whole change plan, not just the group.** Dropping the claim on the group leaves a unit with fewer groups, perhaps none, and dependencies and
  `Needs:` lines that point at a unit that is no longer what the plan described; a retry by the planner would produce the same collision because the
  cause is in the store, not in the model's answer. So `plan_all` catches `GroupOwned`, writes nothing for the change, logs the pair and the way out for
  each group, and records the plan as failed with every attempt spent (as an oversized group is, `GroupTooLarge`), with the owners' ids in the record. The
  tick does not ask the model again until something changes. `abk replan` plans it again on demand, exits 1, and `abk replan` with no argument lists the change
  as "given up" with the reason. `abk retire` forgets any plan record that names the retired unit, so the tick that follows plans the change.
- **Explicit regroupings are not affected.** The hold-and-split change supersedes a held unit by setting it `closed` with a cause and writing its pieces in
  one store write; closed is finished here, and its groups are free, so the pieces never collide with it. `abk replan --failed`, joins and `Needs:` linking
  do not move a group between units that have started. A join takes in only unstarted units, as before. `abk retire` is the explicit way to release the
  groups of a started unit.
- **The status shows the signpost.** `abk check` is OpenSpec validation and has no unit data, so the listing belongs to `abk status`, which already lists
  units a person must act on (`no recorded cause:`, blocked units). Two lists: groups carried by two owners (above), and `unplanned` units that hold work.
  Each line carries the command to run. When two units collide on a group the line suggests retiring the one further from done (`unplanned`, then
  `planned`, then `failed` or `held`, then `running` or `in review`; the later in plan order on a tie), and says it is a suggestion. When the unit's groups are
  all carried by a merged unit it adds "nothing is lost: its groups are in <unit>".
- **No web action.** The web interface's actions (`requeue`, `hold`, `release`, `approve`) are unchanged. Retiring is a command only.

## Needs

No `Needs:` between this change's own groups, and none on other changes. The unbuilt changes that edit the same files do so for other reasons:
`a-dropped-unit-parked-on-a-split-takes-no-place` widens one condition of `in_progress`; `a-unit-in-a-held-split-is-not-started` and
`a-unit-over-its-tier-is-held-and-split` add fields to `Unit` and a supersede path to the store; `limits-split-into-global-and-project` and
`the-whole-moved-base-flow-runs-in-the-restack-lane` edit the status and round evaluation. This change reads no value those add, and the ownership
check treats `closed` as finished, so a superseded unit frees its groups whether or not the split change is built. The overlap is textual and the
second change to merge resolves it in its rebase.

## Relation to a-dropped-unit-parked-on-a-split-takes-no-place

That change makes an `unplanned` unit parked on a held split hold no place. It is not edited or replaced. With this change the planner no longer demotes
a unit with work, so fewer such units arise, and `abk retire` ends the ones that do. A planned or unplanned unit parked on a split that a person chooses to
leave alone still holds no place under that rule, and a retired unit holds none by being finished. The two changes can be built independently, in either
order.

## Risks

- **A refused plan blocks a change until a person acts.** That is the intent for a collision with a started unit, and the message carries the command. A
  change whose plan is refused for another reason is not affected.
- **A unit that depended on a retired one starts at once.** The replan that follows a retire of unbuilt work runs before scheduling in the same tick and
  re-points `Needs:` dependents; a dependency the planner had chosen itself is rebuilt for planned units. A dependent already started refuses the retire.
- **`retired` is one more state for every reader.** The readers that treat `unplanned` as "builds nothing" are named in the requirements and each has a
  test; a reader that is missed would show a retired unit as unknown, not run it, since only `planned` units start.
