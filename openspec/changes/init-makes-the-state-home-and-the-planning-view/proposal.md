# Proposal

## Why

`pipeline-state-lives-outside-the-repo` moves the pipeline's state to `<planning home>/state` (default `data_home()/<repo>/planning/state`), outside the repository. That is right for git (nothing dirties the worktree) and wrong for a person: the files are no longer in the workspace folder the editor has open. Two things are missing:

- **A way to see the state.** An ignored link `<repo>/.planning -> <planning home>/state` makes the folder, the generated pages and the run logs browsable in the explorer. The person wants `abk init` to own it, not `install-timers`: init already lays out the in-repo mode (`write_planning_repo`, `init/scaffold.py:751-810`, `holding_repo`, `scaffold.py:656`) and is where a person is when they decide where state lives.
- **A guard.** The state directory is configurable (`planning.state_dir`, `ABK_STATE_DIR`). Pointed inside the repository it brings back what the move removed: dirty files in the pipeline worktree that stop its fast-forward (`planning_sync.py:_sync_worktree` 186-221, `_clear_landed_files` 165-183 only clears a file that landed byte for byte). Nothing warns today.

## What Changes

- **`abk init`, in-repo mode,** creates the planning home's `state/` folder, creates `<planning root>/.planning` as a symbolic link to it, and adds `/.planning` to the repository's local `info/exclude` (the mechanism `pipeline/scratch.py:ensure_scratch` 79-88 and `tracks/runner.py:_keep_raw_output_untracked` 432-437 use, through `append_missing_lines`, `pipeline/file_lock.py:93`). Idempotent; repairs a dangling link; refuses to replace a real file or directory (or a link to elsewhere) named `.planning`, naming it. `abk install-timers` creates nothing: it checks the link and names `abk init` as the repair.
- **`abk doctor`** warns, in the working copy and the pipeline worktree roles, when the link is missing, dangling or points elsewhere, with the repair line; a separate planning repo gets no check.
- **The guard.** `abk init` and `abk doctor` warn when the effective state directory resolves, by real path, inside the repository's working tree or git directory. `abk init --yes` refuses in that case unless `--allow-state-in-repo`; interactively it asks. A separate planning repo with its legacy `runs/` is unchanged and not warned about.
- **Docs and changelog:** `docs/init.md` and the planning section of `docs/configuration.md` say what `.planning` is, suggest `files.watcherExclude` / `search.exclude` entries and name `abk serve` as the web view.

## Impact

- Capability: `planning-state-view` (new).
- agent-build-kit: a new `pipeline/planning_view.py`, `cli/init.py` (flag, step, install-timers check), `cli/doctor.py`, `tests/`, `docs/init.md`, `docs/configuration.md`, `CHANGELOG.md`.
- Not in this change: where the state lives or how its directory is resolved (`pipeline-state-lives-outside-the-repo`), network drives (`state-can-live-on-a-network-drive`), task progress files (`task-progress-is-tracked-in-the-state-home-and-archived-to-the-repo`); a link for a separate planning repo; a Windows junction fallback.
