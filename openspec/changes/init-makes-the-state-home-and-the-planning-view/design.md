# Design

## What was checked, and where

Read-only, `git show origin/main:<path>` (paths under `src/agent_build_kit/`).

- **In-repo mode in init.** `cmd_init` (`cli/init.py:630`) computes `in_repo = holding_repo(planning, config) is not None` (733) and prints "not committed: what was written is in this repository" (813). `write_planning_repo` (`init/scaffold.py:751`) builds the marker blocks only when `top` is set (764), writes `state/.gitkeep` and `units.json` (791-792; the sibling change stops that in this mode) and adds the state ignore lines to `.gitignore` as a marker block (`_ignore_block`, 699-726). The step added here runs after `write_planning_repo`, in the same `if in_repo` branch.
- **Where `.abk/` is excluded.** `ensure_scratch` (`pipeline/scratch.py:79-88`) asks git for `rev-parse --path-format=absolute --git-path info/exclude` and calls `append_missing_lines(exclude, [line])` (`pipeline/file_lock.py:93`); `_keep_raw_output_untracked` (`tracks/runner.py:431-437`) does the same with `/<dir>/`. The new step reuses that call; a worktree and the working copy share one `info/exclude` (it lives in the common git directory), so one line serves both.
- **Roles.** `in_repo_name` (`pipeline/planning_sync.py:105`), `planning_mode` (110), `main_working_tree` (`pipeline/planning_repo.py:36`), `git_dir` (76) and `common_dir` (22).
- **Doctor.** Checks are functions returning `Check` lists built with `_ok/_info/_warn/_fail` (`cli/doctor.py:121-135`), registered in the list at 1894-1912; `_state_ignores` (497-510) is the model for an in-repo-only check (it returns `[]` when `in_repo_name(inst)` is `None`).
- **Init's prompting.** `--yes` is `init.add_argument` at `cli/init.py:989`; prompts use `yes(ask(...))` (`init/runtime_choice.py:38`, used at `cli/init.py:~400`).
- **Tests available:** `tests/planning_worktree_support.py` (`working_copy_of`, `in_repo`, `installation_at`), `tests/cli/in_repo_doctor.py` (`in_repo`, `separate`, `with_pipeline_worktree`, `checks_of`, `named`), `tests/cli/test_doctor_in_repo.py` as the model for doctor tests.

## Decisions

### One module, three questions

`pipeline/planning_view.py` holds `ensure_view`, `view_problem` and `state_inside_repo`. `ensure_view(root, state, *, dry_run)` returns what it did (`created`, `repointed`, `unchanged`, `would ...`) or raises `PlanningViewRefused`; `view_problem(root, state)` returns `None` when the link is right, else a one-line description (`missing`, `dangling`, `points to <other>`, `is a file or directory`); `state_inside_repo(state, repo_top, git_dir)` returns the path it resolves to when inside. Init, install-timers and the doctor call these and keep no path logic of their own. `<state>` is whatever the sibling change's `Installation.state_dir` (or, before an `Installation` exists in init, the same resolution from the config and `ABK_STATE_DIR`) yields: this change adds no setting and no resolution of its own.

### The link is at the planning root, and is a plain absolute symbolic link

`<planning root>/.planning` is the same folder as the repository top in the usual `abk init . --repo .` case; if the planning root is a subdirectory the link sits there and the exclude line is its path from the top (`/<sub>/.planning`). The target is the state directory as resolved, absolute, like the machine-files links of `install-timers-carries-the-machine-files-into-the-pipeline-worktree`. No copy: one source. Only the working copy gets it; the pipeline worktree is a machine detail nobody opens.

### Cases, in order

1. Nothing at `.planning`: create the state folder (`mkdir -p`, including the planning home) and the link; exclude line added.
2. A link to the right target: `unchanged`. A dangling link, or a link to another path **that no longer exists**: repointed. A link to another path that exists: refused (it is someone's); the message names it.
3. A real file or directory: refused, naming it, before anything is changed (the state folder and exclude line included).
4. The exclude line is added even when the link is unchanged (a clone on a new machine has the link target but a fresh `info/exclude`).
`--dry-run` prints `would create`/`would repoint` and writes nothing.

### The guard compares real paths

`state_inside_repo` resolves the state directory (`Path.resolve()`, following symbolic links, and resolving the nearest existing parent when the directory is not made yet) and the repository's top and git directory (`git_dir`, the common one for a worktree), and is true when the state path equals or is under either. So a path under the repository, under `.git`, or a link that leads into the repository warns; a path outside, or through a link that leads outside, does not. It does not run in a separate planning repo with the legacy `runs/` (`in_repo_name` is `None` / `holding_repo` is `None`): that mode keeps state in the repo on purpose and is unchanged.

The reason is in the message: "state inside the repository dirties the pipeline worktree and stops its fast-forward sync". Interactive `abk init` asks `continue? [y/N]`; `--yes` exits 1 naming `--allow-state-in-repo`; with the flag it warns and goes on. The doctor only warns (`_warn`, repair: "set planning.state_dir / ABK_STATE_DIR outside the repository, or drop the setting").

### The doctor and install-timers

The doctor check `planning view` runs where `_state_ignores` does (in-repo roles), looks at the working copy's link (`main_working_tree(inst.root)` from the pipeline worktree) and warns with `abk init` as the repair; a separate planning repo returns `[]`. `install-timers` calls `view_problem` after the units are written and prints `note: .planning is <problem>; run abk init` (a note, exit code unchanged): it cannot be the creator because init is what decides where state lives.

### The machine-files change

`install-timers-carries-the-machine-files-into-the-pipeline-worktree` defines `MACHINE_FILES` (`.env`, `abk.local.yaml`, `scrub.local`). This change needs nothing from it: it adds no file to carry and no setting to the list. The new location settings (`planning.home`, `planning.state_dir`) live in `abk.local.yaml`, which that change already links into the worktree, and `.planning` is a link in the working copy only. It does not duplicate any carry logic; the two both create links but have no code in common beyond `append_missing_lines`-style helpers they each use.

### VS Code

The link makes the state show in the explorer of the open folder. The state includes `transcripts/` and sqlite files that change constantly, so the docs suggest, as an example for the user's own `settings.json`: `"files.watcherExclude": {"**/.planning/transcripts/**": true, "**/.planning/**/*.sqlite*": true}` and `"search.exclude"` with the same keys. `abk serve` stays the web view. The kit writes no editor settings.
