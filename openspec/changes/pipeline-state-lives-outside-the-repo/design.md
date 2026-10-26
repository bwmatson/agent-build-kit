# Design

## What was checked, and where

Read-only: `git fetch`, then `git show origin/main:<path>` (origin/main at `d5282e6c`). Paths are under `src/agent_build_kit/`; the lines were read on that commit and every point below was re-checked there.

- **The default today.** `PlanningConfig.state_dir: str = "runs"` (`config.py:132`), with `graph_page` and `usage_page` `docs/...` strings (`config.py:134-135`): a plain `"runs"` cannot be told from unset. `Installation.state_dir` is `_under_root(config.planning.state_dir)` (`installation.py:88-89`), `_under_root` accepts absolute and `~` paths (`installation.py:83-86`), and `graph_page`/`usage_page` do the same (`installation.py:104-110`). `planning_paths` keeps an outside path absolute (`installation.py:112-118`), so the verify dirty check (`verify.py:319`), `planning_only` (`pipeline/attach.py:170`) and the write fence (`pipeline/command_policy.py:574-585`) already skip an outside state directory. The one settings model to copy is `worktree_root`: `ABK_WORKTREE_ROOT` (`settings.py:62-63`) over `planning.worktree_root`, then a default from the repository name (`installation.py:69-74`), refused when inside the repo (`installation.py:75-79`) and listed as a machine fact (`machine_settings.py:62-63`) and a scrub term (`scrub_terms.py:78-79`).
- **The name is role-independent.** `repository_name(root)` is the main working tree's directory name from either role (`pipeline/planning_repo.py:43-56`), and `Installation` already uses it in the pipeline worktree (`installation.py:69`) but `root.name` in a working copy. `abk --config <worktree>/abk.yaml status` and a plain `abk status` must read one state, so the default is computed from `repository_name(root)` for both. A bare layout (the common git directory not named `.git`) names the root itself and differs between roles; `abk doctor` already reports that reason (`planning_repo.py:53-56`), and `planning.home` is the fix.
- **In-repo is known from the configuration.** `planning_mode`/`in_repo_name` (`pipeline/planning_sync.py:105-116`) use `repo_sharing(checkouts, root)`, which needs git. A root with no git or whose repository holds no listed repo is `SEPARATE` and keeps `runs/` under the root: this is the state of the ~310 tests that build an `Installation` over a temporary directory, and it is why they do not change.
- **Where the worktree is decided.** `install_in_repo` (`timers.py:543-602`) takes the marker's path when it names an existing directory, else `<data home>/<repo>/planning` (`timers.py:570-575`); `_make_worktree` is `git worktree add --detach` (`timers.py:515-530`); the marker is `<common git dir>/abk-pipeline-worktree` (`planning_sync.py:46,62-81`). Unit names come from `slug`, which names a pipeline worktree for its repository (`timers.py:180-185`), so a worktree directory called `worktree` does not rename any unit. `installed_units` finds a unit by the `WorkingDirectory` it points at (`timers.py:277-299`), and `install` replaces a unit whose directory is gone (`timers.py:396-400`), so units pointing at the old path are rewritten by the ordinary install once the worktree is at the new one.
- **The tracks.** `run_log` is `inst.state_dir / "<RUN_ID>-<repo>-<track>.md"` (`tracks/runner.py:306-307`); `resolve_focus` globs the state directory (`runner.py:326-335`); the prompt token `__STATE_DIR__` is filled with it (`runner.py:385`; prompts `health.md:13,38,61,92`, `improve.md:12,34,56,85`, `propose.md:35,62,178,187`, `recommend.md:36,49,81`); `_dirty_notes` (`runner.py:425`) and `commit_bookkeeping` (`runner.py:560-653`, pathspec at 576) and the rejected-change message (`runner.py:540,550`) call `inst.state_dir.relative_to(inst.root)`, a `ValueError` for a directory outside the root; `record_planning` says where logs go (`runner.py:448-451`); `planning_state_dir=inst.state_dir` is handed to the agent (`runner.py:727`), where `hooks/policy.py:182-187` and `_may_write_planning` (`policy.py:198-211`) grant `*.md` writes under it. `read_status` reads the health report it is given (`runner.py:777-788`).
- **Init, doctor, split.** `scaffold.py` writes `<state>/.gitkeep` and `units.json` (`scaffold.py:790-792`) and a marked `.gitignore` block with the template's `runs/` lines (`scaffold.py:674-708`, `templates/gitignore`); `doctor._state_ignores` warns when they are missing (`cli/doctor.py:497-512`); `split/select.py:uncommitted` lists git changes under the specs and state directories and skips a state directory outside the root (`select.py:426-433`); the destination must have a state directory (`select.py:492-496`).
- **Tests.** `tests/planning_worktree_support.py` (`in_repo`, `working_copy_of`, `installation_at`), `tests/cli/in_repo_doctor.py` (`in_repo`, `separate`, `with_pipeline_worktree`, `checks_of`, `named`), `tests/cli/test_install_timers_in_repo.py` (the `working_copy` fixture), `tests/tracks/test_runner_planning_worktree.py` and `test_runner_publish_branch.py`, `tests/hooks/test_policy_planning_writes.py`, `tests/init/test_scaffold_in_repo.py`, `tests/split/test_select_working_tree.py`.

## Decisions

### The layout, per repository

```
<data home>/<repository name>/planning/      the planning home   (planning.home / ABK_PLANNING_HOME)
    state/                                   all pipeline state    (planning.state_dir / ABK_STATE_DIR)
        pages/unit_graph.md, unit_cost.md    the generated pages
    worktree/                                the pipeline checkout (a state-free cache of the default branch)
<data home>/<repository name>/worktrees/     unit worktrees, unchanged (planning.worktree_root)
```

`<data home>` is `data_home()` (`installation.py:46-49`). Nothing here is kit-specific: any in-repo planning repo gets the same layout under its own name. It applies in the in-repo roles only; a separate planning repo keeps `runs/` inside its own repo, committed or ignored as its owner chose.

### Precedence

Strongest first, for each of `home` and `state_dir`:

1. Environment: `ABK_PLANNING_HOME`, `ABK_STATE_DIR` (settings `planning_home`, `state_dir`, `Path | None`, as `worktree_root` is).
2. `abk.local.yaml`, the ignored file; `planning.home` or `planning.state_dir`.
3. A tracked `abk.yaml`. This works, but the values are machine facts: `abk doctor` warns (`machine_settings._classify` gets the two keys) and `abk config --migrate` moves them, with no change to `config_migrate_machine.py`, which reads the table.
4. The default: `<data home>/<repository name>/planning` and `<home>/state` in the in-repo roles; `runs` under the root otherwise.

`planning.home` moves the state, the worktree and (later) the local directory together; `planning.state_dir` overrides only the state, as an absolute or `~` path. A relative `planning.state_dir` (`runs`) is the old behaviour, under the root, and is honoured, which is how an installation stays as it was until it is moved. The doctor key rule: `planning.home` is always a machine fact; `planning.state_dir` is one when absolute, `~`-led or outside the repository, so a committed `state_dir: runs` is not flagged. Both are added to `scrub_terms` next to `worktree_root`, and `planning.home` is refused when inside the planning repo, as `worktree_root` is.

The ignored files reach the tick because `install-timers-carries-the-machine-files-into-the-pipeline-worktree` links `abk.local.yaml` and `.env` into the pipeline worktree: without that change a local `planning.home` would be seen from the working copy and not from the units. This change relies on it and sets no `Needs:` on its other groups, since they build on group 1 of this change.

### Pages

`graph_page` and `usage_page` become `str | None`. Set, they behave as today. Unset, they are `<state>/pages/unit_graph.md` and `unit_cost.md` when the state directory is outside the root (what the in-repo default is) and `docs/unit_graph.md`, `docs/unit_cost.md` otherwise, so a separate repo's pages do not move. The orientation text that `abk init` writes (`scaffold.py:711-719`) names the resolved paths.

### The state stays one place for every reader

`Installation.state_dir` is the only place that decides, so `abk status`, `abk serve`, the tick, `abk split` and the doctor agree, from the working copy and from `--config <worktree>/abk.yaml`. The checkpointer's sqlite stays at `<state>/unit-graphs.sqlite` (`graph/checkpointer.py:32-34`): a local path in the default layout. Putting the state on a network drive and keeping that file and the locks local is `state-can-live-on-a-network-drive`.

### The worktree moves, and install-timers migrates

The pipeline worktree is `<planning home>/worktree`. `install_in_repo` uses, in order: the marker's directory if it exists and is the new path; a legacy worktree (the marker's directory, or the old default `<data home>/<repo>/planning`, which now is the planning home itself) which it migrates; else a new worktree at the new path.

Migration of a legacy worktree, only when the marker (or the old default) names an existing worktree of this repository that is the planning home itself:

1. Refuse, naming `systemctl --user stop`, when any unit of the installation (`timers.unit_names`) is active (`systemctl --user is-active`, through the injected runner), because moving a directory under a running tick breaks it. Nothing is changed.
2. `git worktree move <home> <home>.moving`, `mkdir <home>`, `git worktree move <home>.moving <home>/worktree`: the temporary name is needed because the new path is inside the old one. A failure after the first move moves it back.
3. Rewrite the marker to the new path (`write_pipeline_marker`).
4. The ordinary `install` then rewrites the unit files to the new `WorkingDirectory` (a unit whose directory is gone is replaced).

Idempotent: with the worktree already at the new path, none of it runs and the output says so. The worktree's own untracked `runs/` goes with it and is not touched; copying it to `<home>/state` is a step of the runbook, because the copy is a decision about data. `--dry-run` prints `would move <old> to <new>`. A path that exists and is not the legacy worktree (a `<home>/worktree` that is not a worktree of this repository) is refused as the existing `PlanningWorktreeRefused` cases are.

### Tracks keep their reports in the repo

`planning.reports_dir: str | None`. Unset: the state directory when it is inside the root (separate repos and old layouts behave as today, which is also why the track tests under a temporary root do not change), `docs/reports` when the state directory is outside. Set: that path, relative to the root, refused when outside it (a report that is not in the repo cannot be committed). `Installation.reports_dir` is the one reader.

Everything that sat on `state_dir` for the tracks moves to `reports_dir`: `run_log`, `resolve_focus`, `_dirty_notes`, the `commit_bookkeeping` pathspec, the rejected-change directory (`<reports>/rejected-changes/<change>`, committed as its Markdown is today), the `__STATE_DIR__` token, the message of `record_planning`, and the agent's write grant. A `relative_to` is replaced by one helper, `relative_to_root(inst, path)`, that returns the posix path or raises a `ConfigError` naming the setting, so the `ValueError` cannot reappear. The prompts say `__REPORTS_DIR__`; `__STATE_DIR__` is still substituted, with the reports directory (what the tracks always meant by it), so a prompt in a user's own prompts directory keeps working. The hook flag `--planning-state-dir` is renamed `--planning-reports-dir`, the old spelling still parsed. `planning.publish` (`direct` or `branch`) is untouched: the same commit goes the same way. The read side is the same files: `read_status` reads the health report at `run_log`, and the prompts tell the agent to read the prior `*-health.md` and `tracked-issues.md` under `__REPORTS_DIR__`.

The one-time data move (the two run logs and `tracked-issues.md` under `runs/` to `docs/reports/`) is a step of the runbook, not code: until it is done the tracks find no prior run and say so, as a first run does.

### init, doctor, split

- `abk init` and the scaffold, in an in-repo installation with the state outside the root: write no `<state>/.gitkeep` or `units.json`, add none of the state lines of the marked `.gitignore` block (it keeps `.env`, `.last-runs/`, `*.pre-redact`, `abk.local.yaml`, `scrub.local`). Creating the state directory and the `.planning` link is `init-makes-the-state-home-and-the-planning-view`; this change only stops writing into the repo. A separate planning repo is scaffolded as before.
- `abk doctor`: `_state_ignores` has nothing to check when the state is outside the root; a new check lists tracked files under the legacy `runs/` while the state is external and warns, naming the count, `docs/runbooks/move-state-out-of-the-repo.md` and the line "the state home looks empty: this installation has not been moved". Whether the state directory is itself inside the repository is change 2's warning, not this one's.
- `abk planning split`: `uncommitted()` already skips a state directory outside the root, so it reports nothing for the state; the plan says "state is outside the repository: it is not under git" for each side whose state is external. A plan whose source and destination resolve to the same state directory (the same repository name, which happens when both are planned in one repository and neither sets `planning.home`) is refused before anything is written, naming the directory and `planning.home` in the destination's `abk.local.yaml` as the fix, because two stores in one folder would overwrite one another's `units.json`.

## Risks

- **No git history for the state.** Once `runs/` leaves the repository, nothing versions it, and a loss of the folder loses the unit records, verdicts and the usage ledger. Recommend a periodic backup of `<planning home>/state` (a nightly copy or a snapshot of the data directory); the runbook and `docs/configuration.md` say so. Old states stay recoverable from git history up to the last commit that tracked them.
- **Existing installations look empty after the default flips.** With no `planning.state_dir` in `abk.yaml`, an in-repo installation's state moves to a folder that does not exist yet: `abk status` shows no units and the next tick replans every change. The doctor check (tracked files still under `runs/`) and the runbook (copy the state before the first tick) are the answer; the runbook orders the steps so the timers are stopped first.
- **Two hosts sharing the folder remain unsupported.** The locks, leases and the sqlite database assume one host. Putting the state on a network drive is planned in `state-can-live-on-a-network-drive`; this change does not make it safe and the documents say so in one sentence.
- The shared tracks commit path (`planning.publish: branch`) is touched; its tests must pass with `reports_dir` set and unset.

## Test impact

About 5 to 10 test files change: `tests/tracks/test_runner_planning_worktree.py`, `test_runner_publish_branch.py` and `test_runner_propose_commit.py` (state now outside the root), `tests/hooks/test_policy_planning_writes.py` (the flag and the grant), `tests/init/test_scaffold_in_repo.py` and `tests/cli/test_doctor_local_ignored.py` (no state ignore lines in the in-repo mode), `tests/split/test_select_working_tree.py`, `tests/cli/test_install_timers_in_repo.py` (the new worktree path). The roughly 310 tests that build state under a temporary root with no listed repo in the same repository are `SEPARATE` and untouched.

## Boundaries with the other changes

- `init-makes-the-state-home-and-the-planning-view` creates the state folder, the ignored `<repo>/.planning` link and the warning for a state inside the repository; this change defines where the folder is.
- `state-can-live-on-a-network-drive` adds `planning.local_dir` and the lock probe; this change leaves the sqlite and the locks in the state directory.
- `task-progress-is-tracked-in-the-state-home-and-archived-to-the-repo` puts the tasks.md tracking copy under `<state>/changes/`; it relies on `Installation.state_dir` as defined here.
- `install-timers-carries-the-machine-files-into-the-pipeline-worktree` links `abk.local.yaml` and `.env` into the pipeline worktree, which is how a local `planning.home` or `planning.state_dir` reaches the units.
