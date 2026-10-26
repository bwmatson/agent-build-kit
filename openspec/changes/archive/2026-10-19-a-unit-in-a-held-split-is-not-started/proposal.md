## Why

`tier2-splits-replace-runtime-tags` lets a repo split its e2e-test run and hold a split (a metered model out of budget, a host down). A unit with
an own test in a held split is parked at tier 2: it waits, planned, for the split. That is correct for a unit already built, but the unit was
started first. It was planned, got a worktree and a branch, was implemented and reviewed, and ran the part of tier 2 that could run, all on model
usage, and then waited for a split that was held the whole time. The usage is spent on a unit that cannot be cleared, and the unit holds its
place in the queue while it waits (a parked unit is not counted, but its branch and review are).

The rule the user states: a unit with a part in a held split is not started at all while the split is held. Either the whole unit waits, or the
work is divided into one unit for each split so that the part that can run runs now.

What the pipeline cannot do is tell, before a unit exists, which split its tests will be in. A split is a property of a test, found by listing the
markers of built code, and the tests of a never-started unit may not exist yet. So the spec has to declare it.

## What Changes

- **A group declares its split.** A `Split: <name>` line in an e2e-test group, beside `Needs:` and `Priority:`. The name is a split declared for
  the group's repo, or `rest`; absent means `rest`. A repo that declares no splits accepts no `Split:` line and behaves as it does today. A
  unit-test group cannot carry one. An undeclared name is refused by plan validation and `abk tags`.
- **One split to a group, one to a unit.** A group names at most one split, and groups of different splits are never joined into one unit
  (join compatibility adds the split to the repo and kind already required). A test that must run in two splits is two groups; a group naming
  two splits is refused with a message that says so. No automatic splitting.
- **A start gate.** A never-started planned unit whose split is held is not started, makes no worktree, branch or model call, is reported with the
  new wait reason `split` ("waiting for tier 2 split <name>" and the hold's reason), counts toward neither the units in progress nor a slot, and is
  started by the same round that sees the hold released. A unit already started is unaffected; its parking at tier 2 is the backstop.
- **A check and a display.** `abk tier2 check` warns about an own test whose split differs from its group's declared split, naming the group.
  `abk status` lists the units not started because of a hold like any wait reason; `abk tier2 status` lists the units waiting on each split; the
  graph draws such a unit as waiting and its legend says why.
- **Documents.** The architecture, configuration, CLI and unit-graph documents and the `abk-authoring` and `abk-pipeline` skills say it.

## Impact

- agent-build-kit: `pipeline/work_graph.py` (the `Split:` line, `TaskGroup.split`, the validation), `pipeline/planner.py` and `pipeline/joins.py`
  (one split to a unit, join compatibility), `pipeline/units.py` and `pipeline/unit_store.py` (the unit's `split`), `pipeline/vocabulary.py`
  (`WaitReason.SPLIT`, the graph description), `cli/pipeline.py` (the evaluation of a round, `_planned_wait`, the status), `cli/tier2_cmd.py`
  (`check` warning, `status`), the documents and the two skills, the changelog.
- It does not change the held set, its storage, the configuration keys or the parking of a started unit.
- No `Needs:` on other changes. The restack-lane change (group 7) and the limits change (group 9) edit the same round evaluation and status
  formatting; whichever merges second resolves the textual conflict in its rebase. The fix is not held behind their unbuilt groups.
- Priority 2: each unit that starts under a held split spends usage for nothing, and the ACP backend is held today.
