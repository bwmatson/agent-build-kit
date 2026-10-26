## Context

Written against agent-build-kit `origin/main` (`9fcda68b`) and `runs/units.json`. All units of `tier2-splits-replace-runtime-tags` are merged, but
the change is not archived, so its requirements are not main specs; this change ADDS capabilities that refer to them by name and MODIFIES one
main requirement (the join conditions in `unit-joining`).

## What was checked, and where

- `pipeline/work_graph.py`: the heading regex takes `[repo] [kind] [flag]`; the lines inside a group are read one regex each (`Priority:`,
  `Separate:`, `Independent:`, `Needs:`), a line before the first heading is the default for `Priority:` only, and a stray line of a group that
  could not be read is reported. `validate_tasks(path, *, repos, projects)` returns the groups and the errors; the `Split:` line is read there.
- `pipeline/planner.py` and `pipeline/joins.py`: `check_joins` refuses a join when `(repo, tier)` differ and when `project` differs, for both an
  existing unit and a new group; `_check_groups` validates the groups of a unit. `Unit` has `repo`, `tier`, `project`; it has no split.
- `pipeline/units.py`: `in_progress` is false for a planned unit with the cause `split_held` (the parked one), true for a planned unit with work
  and not blocked; `ready_units` draws on the room only for a unit not in progress. `pipeline/vocabulary.py` has `WaitReason`.
- `cli/pipeline.py`: `_evaluate_round` builds the view in which a unit the round must not start (`started`, `--only`, a lease, `awaits_release`,
  a backoff) is shown as `held` and put in `excluded`; `_planned_wait` gives a planned unit its reason in this order: lease, backoff, blocked on
  a unit, `awaits_release` or too deep, usage pause, ready, queue full, slot. `release_split_held` and `_holds_of_parked` read the state file and
  the configuration through `repo_holds(config, repo, state_dir)` and never ask a gate; `_split_wait_lines` prints the parked units' lines.
- `pipeline/e2e_holds.py`: `repo_holds(...)` gives the splits held now for one repo, each `Hold` with its reason and origins; `hold_text`.
- `runs/units.json`: `the-whole-moved-base-flow-runs-in-the-restack-lane` units 1 to 8 and `limits-split-into-global-and-project` units 8, 9, 10
  and 13 are planned with no pull request. Group 7 of the first edits (no `Needs:` is added: a rebase resolves the overlap) `run_round`, `_evaluate_round`, `resumable_units`, `ready_units`' running
  count and `_planned_wait`'s `queue_full` reading; group 9 of the second replaces `_queue_full_line` and the `({unit.repo})` formatting of the
  status. Group 10 and 13 of the second edit the graph renderer and the documents this change also describes (text only).

## Decisions

### The declaration is a line in the group, `Split: <name>`

It sits where `Needs:` and `Priority:` sit: a line on its own inside a group, after the heading, key case-insensitive, the value one split name
(lowercase letters, digits and underscores, or `rest`). A bare line is chosen over a fourth heading tag because the heading's third tag is the
flag (`contract`, `narrow`, `acceptance`) and a split is neither; a line is also what the author edits when a split is renamed. A `Split:` line
above the first group is refused (unlike `Priority:`, a default split would hide which groups run where). A second line, or a value with a comma or
a space, is refused with the one-split rule and "write one group for each split". A `Split:` in a unit-test group is refused ("a unit-test group
has no tier 2"). A name that is not declared for the group's repo (`e2e_splits(repo, config)`) is refused naming the declared ones; a repo that
declares none refuses every name except `rest`, and `rest` written out is accepted and the same as no line. A `Split:` in a group whose heading
could not be read is reported as `Priority:` is.

### One split to a unit

`TaskGroup.split` is `rest` when the line is absent. `Unit.split` is recorded when the unit is planned, from its groups, and joins refuse groups
or units of another split (the same refusal text as for another repo or kind, naming the split). A unit's groups therefore share one split and
the unit has one, which is what lets a unit be gated whole. Hold-the-whole-unit and divide-by-split are the same rule seen from the author: the
author writes a mixed test as two groups, and the planner never merges them back.

### The gate reads the held set the parking reads

The held set for a unit is `repo_holds(config, repo, state_dir).held` for the unit's repo, the set `release_split_held` already reads: the
configuration's `hold` (with `hold: false` winning), the state file and an entry a gate wrote; nothing asks a gate from the start decision. A
gate that lifts a hold does so by removing its entry or letting it expire, and the next round reads that, which is what "started by the round that
sees the hold released" means. A unit whose split is not declared for its repo any more (the configuration changed after planning) is not gated and
`abk tier2 check` warns.

### Where the gate sits

In `_evaluate_round`, beside the other reasons a planned never-started unit is left out: the unit is shown `held` in the view and in `excluded`,
so `ready_units` neither starts it nor lends its priority, and a unit depending on it waits on it as on any unbuilt unit (`waiting_on`). Only an
unstarted unit (`StoredUnit.unstarted`: no pull request, branch or pushed commit) is gated; a unit with work, a rework, a resume or one parked
at tier 2 is never held back by this. It is not counted because `in_progress` is already false for a unit with no work, and `start_room` and the
slot counts read units in progress and running only. The wait reason is given in `_planned_wait` after the dependency reasons (a unit that waits
on a parent is blocked first; the split reason is what remains once the parent merges) and before the usage pause and ready reasons, because a
usage pause is not what holds it. The graph draws it as `blocked` (waiting, not startable) and its description says "Waiting on a unit it depends
on, or on a held tier 2 split".

### The check, and what stays

The gate trusts the declaration, since the real membership of a test is known only from the built code. `abk tier2 check`, which already lists each
split's tests, also lists the unit's own tests (the tests its groups' tasks add or change, as the tier 2 run finds them) and warns when an own test
is in a split other than its group's, naming the group and both splits. The unit then parks at tier 2 exactly as today; nothing here changes that
path, so a wrong or missing declaration costs what it costs now and is never worse.

## Alternatives rejected

- **Derive the split from the tests.** The tests may not exist when the unit is started; the point of the change is not to start.
- **Split a mixed group automatically.** The planner cannot know which task belongs to which split; refusing and asking for two groups keeps
  the author's intent.
- **A fourth heading tag.** The third tag is the flag; a split is not exclusive with a flag (an acceptance group may be in a split).
- **Count a gated unit as in progress.** It has no work and would use a slot to wait.

## UNVERIFIED

- Whether re-planning refreshes `Unit.split` of an unstarted unit whose group's `Split:` line was edited; group 1 reads `reconcile` in
  `unit_store.py` and either makes it so or says the unit is replanned.
- How `abk tier2 check` finds a unit's own tests; group 3 reads the same function the tier 2 run uses (`own_tests.py`).
- The names `Unit.split` and `WaitReason.SPLIT`; a collision with the review tier fields of `a-unit-over-its-tier-is-held-and-split` (a different
  "split": a unit divided for size) is possible in prose only, since that change's field names are its own; the user-facing word here is always
  "tier 2 split".
