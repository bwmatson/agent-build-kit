# Proposal

## Why

Today the planning repo and the code repos it manages are always different repositories. The kit's own specs, configuration and state therefore live in
another installation's planning repo, and a workspace for the kit has to open two folders to see what it is building. Nothing forbids one repository
playing both roles, but about a dozen mechanisms assume it does not:

- Every tick and track returns the planning root to its default branch (`restore_default_branch`, `pull_planning`). In a checkout a person is editing,
  that switches their branch or fails, and git cannot check the default branch out in two worktrees at once.
- Verify refuses a checkout with any uncommitted change, and the pipeline's own files (the unit store, the graph and usage pages, ticked
  `tasks.md`, archive moves) are always uncommitted. Its `git pull --ff-only` fails on a detached HEAD.
- Planning commits and the chat's change count take every dirty file (`git add -A`), which would sweep in code edits in progress.
- Unit worktrees of the repo carry writable copies of `openspec/`, `abk.yaml` and `runs/`; the policy hook fences the planning root by path only.
- `locate()` finds a unit worktree's `abk.yaml` and treats it as the installation.
- `abk init` writes over nothing but also adds nothing to an existing `.gitignore` or `AGENTS.md`, commits with `git add -A` and hard-codes
  `openspec/changes` in two places.
- The repo's commit hooks reject the 1.4 MB unit store and the model-written run logs, and its CI runs the whole suite for a tick's spec-and-state commit.

## What Changes

- **The timers run in a pipeline worktree.** For an in-repo installation `abk install-timers` creates a worktree of the same repository (no second
  clone) outside the repo, as the units' working directory. Before every `abk tick` and `abk track` a single routine fetches and moves it to the
  default branch tip by fast-forwarding a detached HEAD, keeping the pipeline's tracked-state changes. If it cannot (diverged commits of its own, a
  conflict with a file the pipeline changed, a stray branch), the run stops with one logged reason and discards nothing. `restore_default_branch`
  and `pull_planning` are replaced by it. `planning.self_pull` still means sync before running. The person's working copy is never touched;
  specs written there reach the pipeline when they are on the default branch. A planning root that is its own repository behaves as today.
- **Names and machine-local files come from the repository.** The unit names, the default worktree root and the `.env` are worked out from the
  repository's name and its main working copy, not from the pipeline worktree's directory, and a relative repo path in `abk.yaml` is relative to the
  planning root.
- **A working copy says which installation is live.** `abk status` and `abk doctor` run from it name the pipeline worktree and print the `--config`
  to use; `abk tick`, `abk track`, `abk verify` and `abk archive` refuse there unless a config is named explicitly.
- **Verify and commits know the planning paths.** For a repo that is the planning repo, verify works in the pipeline worktree, accepts the detached
  HEAD at the default tip, exempts the planning paths from its dirty check and syncs instead of pulling. Planning commits and the chat's change
  count are limited to the planning paths.
- **Unit worktrees cannot write the planning paths** and `locate()` does not adopt a unit worktree's `abk.yaml`.
- **`planning.publish`** (`direct`, the default, or `branch`) says where abk's own planning commits go; `abk doctor` reports a protected default branch
  with `direct` as a conflict.
- **`abk init` for this layout**, `specs_dir` honoured where `openspec/changes` was hard-coded, hook and CI scoping for the planning paths, and the
  documents, skills and changelog.
- **An acceptance group** drives a scratch in-repo installation end to end.

## Impact

- agent-build-kit: `pipeline/planning_repo.py` and a new `pipeline/planning_sync.py`, `cli/pipeline.py` (`cmd_tick`, `cmd_status`, the commands that
  refuse), `tracks/runner.py` (`pull_planning`, `record_planning`, `settle_planning`, `commit_bookkeeping`), `timers.py` and `templates/systemd/`,
  `installation.py`, `config.py` (`planning.publish`, `locate`), `pipeline/verify.py`, `pipeline/attach.py`, `pipeline/wiring.py` (`build_commit`, the
  tool policy), `hooks/policy.py`, `serve/chat.py`, `init/scaffold.py`, `cli/init.py`, `cli/doctor.py`, `pipeline/stack_runner.py`,
  `.pre-commit-<redacted>`, `.github/workflows/ci.yml`, the documents, the three `abk-*` skills, `AGENTS.md`, the changelog.
- It modifies three requirements of `track-bookkeeping` and adds five capabilities.
- Other installations are unchanged: nothing here runs unless a repo listed in `abk.yaml` is the planning root's own repository.
- No `Needs:` lines: each group builds on the current default branch. Changes in flight that edit the same files (`cli/pipeline.py`, `wiring.py`) are
  ordinary merge neighbours, not code dependencies.
- Priority 2: the move of the kit's own planning into the kit waits on this change.
