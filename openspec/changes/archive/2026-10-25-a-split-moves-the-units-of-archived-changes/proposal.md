# Proposal

## Why

`abk planning split --repo R --to DEST` is meant to move a repo's changes, archive entries, specs, unit records and plan records. The spec says units move when "every member change is moved". The code counts only **active** moved changes: `plan_split` builds `changes_moved` and `archive_moved`, then calls `_units(source, set(changes_moved))`, so `archive_moved` is never consulted (`split/select.py:266`). A unit's `change` field is the plain change name; an archive entry's directory is `YYYY-MM-DD-<change>` (`_ARCHIVE_DATE`, `select.py:32`), so the two are never compared at all.

The effect shows on a real installation: of several hundred unit records of the moving repo, most belong to archived changes. A dry run moved only the minority that belong to active changes and refused the rest of the plan with one dependency error per edge into a unit left behind (`unit X depends_on names Y, which is neither moved nor in the destination`, `split/copy.py:147`). Applied anyway, the destination would hold the archive and the specs but none of the merged history, the source would keep orphaned unit records naming the repo (so `--remove` could never drop the repo's entry), and the runbook's cutover check would fail.

Two more cases surface once archived units are in scope: a unit whose change has no directory anywhere (the change was deleted outright), and a moved unit that depends on a merged unit of a different repo that stays in the source.

## What Changes

- **Units of moved archive entries move.** A unit's change is matched against active change directories and against archive entries with the date prefix stripped. A unit moves when every member change (its own and each `joined` one) is a moved active change or a moved archive entry. A mixed change that `--allow-mixed destination` moves brings its archive entries and units; `source` keeps them.
- **A unit with no change directory moves by its repo.** When none of a unit's member changes has a directory (active or archived), the unit moves if its `repo` (and, with `--project`, its `project`) is the moving one, and the plan reports it on its own line. It never blocks the run for being orphaned.
- **A name that is both moved and kept is refused.** If one change name resolves to directories on both sides, units of it are refused naming both.
- **A dependency on a merged unit of another repo is carried as satisfied history.** For a moved unit's `depends_on` (with `needs` and `merge_needs`) naming a unit that stays in the source, belongs to a different repo, is `merged` and whose merge is loaded, the edge is dropped from the written record and the plan prints each one. An unmerged or otherwise unfinished foreign unit, a same-repo staying unit, a `superseded_by` target and a `joined` member still refuse.
- **Staying edges into a moved merged unit stay warnings under `--remove`.** A staying unit that depends on a moved merged unit is read as satisfied history after the removal, so it is a warning there as without `--remove`; an edge into a moved unit that is not merged stays an error.
- **The joined-member check knows archive entries and no-directory changes.**
- **The plan output splits the unit count**: moved for active changes, for archived changes, by repo with no change directory, left in the source, and the dependencies dropped.
- **`--remove`** needs no new code path: it removes `plan.units_moved`, which now has the archived units; tests pin that, and pin the rule that the repo's entry goes only when no remaining unit has that repo.
- **Docs**: `docs/cli.md`, the runbook for moving a planning repo, the changelog.

## Impact

- Capability: `planning-split` (modified).
- agent-build-kit: `split/select.py` (`plan_split`, `_units`, a new `SplitPlan` field set, a refusal kind), `split/copy.py` (`preflight`, `unit_records`, a dropped-edge helper), `cli/planning_cmd.py` (`_counts`, the notes), `tests/split/`, `tests/cli/`, `tests/docs/`, `docs/cli.md`, the move runbook, `CHANGELOG.md`.
- Not in this change: a unit's `waited_on`, `promoted_from` and `split_from` ids (not read by the dangling check today), rewriting a staying unit's record, moving run logs or worktrees.
