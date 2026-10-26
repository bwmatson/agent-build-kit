# Proposal

## Why

The kit plans itself in the repository it builds, and every other in-repo installation does the same. The pipeline writes its tracking state (`units.json`, verdicts, verified, `prs-*`, usage files, transcripts, the checkpointer database, the generated graph and cost pages) into `planning.state_dir`, default `runs/`, of whichever checkout runs it, which is the pipeline worktree (`timers.py:567-583`). Nothing commits that state: the tick commits nothing, and the documents expect an "operator" that a detached worktree does not have. So:

- the state is invisible on the default branch, in the working copy and in an editor;
- its modified tracked files keep the worktree's `git merge --ff-only` one squash-merge away from stopping (`planning_sync.py`);
- the one thing the state genuinely needs, a clean checkout of the default branch to read specs from, is tangled with it.

The state is application data, not source. It belongs in the user's data directory, next to the unit worktrees, and not in git at all.

## What changes

- **Where the state lives (group 1).** `planning.state_dir` becomes optional; in the in-repo roles (the working copy and the pipeline worktree) the default is `<planning home>/state`, `planning.home` defaulting to `<data home>/<repository name>/planning`. Both can be set by environment (`ABK_PLANNING_HOME`, `ABK_STATE_DIR`), by the ignored `abk.local.yaml`, or by the tracked `abk.yaml` (which `abk doctor` flags and `abk config --migrate` moves). The generated pages default into `<state>/pages/`. The pipeline worktree moves to `<planning home>/worktree`, and `abk install-timers` migrates one in the old place.
- **Where the tracks write (group 2).** New `planning.reports_dir` for the run logs and `tracked-issues.md`, which stay in the repository and are committed as today. Every place that assumed they sit in the state directory (`relative_to(root)`, the commit pathspec, the agent write grant, the prompts) follows `reports_dir`.
- **Init, doctor, split and documents (group 3).** `abk init` stops writing state files and ignore lines in this mode; `abk doctor` stops asking for the `runs/` ignore lines and warns when files under `runs/` are still tracked; `abk planning split` refuses two plans that would share a state directory; the documents and specs say where the state is; a runbook moves an existing installation.

## Capabilities

### New Capabilities

- `planning-state-home`: where the state, the pages and the pipeline worktree live, how it is configured, and how an old worktree is migrated.
- `track-reports-dir`: where the tracks write and commit their reports, independent of the state directory.
- `planning-state-external-checks`: what `abk init`, `abk doctor` and `abk planning split` do when the state is outside the repository, and the migration runbook.

### Modified Capabilities

None as deltas: the existing `planning-state-paths`, `planning-split` and `planning-worktree` specs are amended in the text of the documents task (their statements that state is committed or sits in `runs/`), because their requirements are about behaviour that is unchanged for the other layouts.

## Impact

`config.py` (`PlanningConfig`), `settings.py`, `installation.py`, `machine_settings.py`, `scrub_terms.py`, `timers.py`, `cli/init.py`, `cli/doctor.py`, `tracks/runner.py`, `tracks/prompts/*.md`, `hooks/policy.py`, `init/scaffold.py`, `templates/gitignore`, `templates/planning-orientation.md`, `split/select.py`, the documents and `CHANGELOG.md`. No change to the state's file formats.
