## Why

A unit that has started (it has a branch, a commit, a pull request or an approval) can be lost track of by a replan, and nothing lets a person end it.
In a real case a unit was planned and parked on a held tier 2 split, with a local branch and two earlier runs, and carried task group 16. A replan after
the group was narrowed left that unit out of the plan. `UnitStore.upsert` demotes a planned unit the plan omits to `unplanned`, and its comment says only a
unit that never started can be dropped, but the code tests `state != planned` and never `unstarted`. The same plan gave group 16 to a new unit. The new unit
was built and merged. The old one stayed `unplanned` with its branch, still counted against the limit on units in progress and still parked on the split.

Three things failed. The demotion applied to a unit with work. Nothing stops two units that have not finished from carrying one group; the planner prompt
marks a started unit's groups `(built by <unit>)`, which is advice to a model and not a rule. And there is no way out: `abk requeue` takes only failed or
held units, there is no command that ends a started unit, and the store is not to be edited by hand. A unit like this holds its place until someone does.

## What Changes

- **A new command, `abk retire UNIT`**, ends a unit that has not finished and is not running a step. It is the main part of this change. The unit gets the
  new terminal state `retired`: it holds no place, nothing waits on it, its change can be archived without it, and the status and graph show it as retired.
  Its groups are released. When they are carried by another unit nothing else happens to them; when no unit carries them (the work was never built) the
  command says which groups become unowned, refuses unless `--reason` is given, and the next replan plans them again. An open pull request is closed with
  the reason. The branch and worktree are kept unless `--delete-branch` is given, and a branch with commits that were never pushed is deleted only with
  `--discard-unpushed` as well, after the command prints how many commits that is. `--dry-run` prints what would happen. The history records the state, the
  reason and that the command did it.
- **The status shows the way out.** `abk status` lists each group carried by two units that have not finished and each `unplanned` unit that holds work,
  with the `abk retire` line to run.
- **A replan keeps a started unit the plan omits.** Demotion to `unplanned` applies only to a unit that never started, as the code comment says. A planned
  unit with work that the plan leaves out stays as it is, and the replan prints `kept: <unit> has work; not in the plan` and the `abk retire` line.
- **A group has one owner among the units that have not finished.** `upsert` refuses a plan that gives a group to a unit while a started unit that has not
  finished carries it. The whole change plan is refused, nothing is written for the change, and `abk replan` names both units and the group and exits 1.
  A group released by `abk retire`, or carried by a merged, closed, satisfied or retired unit, is free. Unstarted units are reshaped, joined and split as
  before.

## Impact

- agent-build-kit: `pipeline/units.py` (the state, `in_progress`, `waiting_on`, `later_groups`), `pipeline/unit_store.py` (the demotion rule, the
  ownership check, `retire`), `pipeline/vocabulary.py` and `pipeline/diagram.py` (the style), `pipeline/archive.py`, `pipeline/planner.py` (retired ids),
  `cli/pipeline.py` (`plan_all`, `abk replan`, `abk status`, `retry_closes`), a new `cli/retire_cmd.py`, the documents, the `abk-pipeline` and `abk-authoring`
  skills and the changelog.
- It adds one state and one command and changes no setting. No pull request, branch or worktree is removed unless the person asks.
- The change `a-dropped-unit-parked-on-a-split-takes-no-place` is not edited. Prevention and retirement make its rule needed less often, and it still
  covers a planned or unplanned unit parked on a split that nobody retires. The two can be built in either order.
- Priority 2: the failure holds a place in the queue indefinitely and cannot be cleared without editing the store.
