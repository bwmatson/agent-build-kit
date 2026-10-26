# Proposal

## Why

Builders never tick `tasks.md` and unit pull requests never contain ticks: agents are denied `openspec/` (`hooks/policy.py:128-135`) and the pipeline ticks the boxes itself. `mark_groups` (`pipeline/task_progress.py:28-42`) is called through `mark_tasks` (`pipeline/stack_runner.py:1851-1855`) when a unit is satisfied (`graph/nodes.py:2535`), when it reaches `in_review` (`graph/nodes.py:2727`), and to untick on failure (`pipeline/stack_runner.py:1915`). `record_follow_ups` (`stack_runner.py:1883-1901`) writes `follow-ups.md` in the same directory. All of it happens in the planning checkout, which for an in-repo installation is the pipeline worktree: a checkout of the default branch that `planning_sync.py:186-221` only ever moves with `git merge --ff-only`. Three costs follow:

- **Tracked files are dirty after every tick.** When a person edits the same `tasks.md` on the default branch (a split, a retag, `abk tags --fix`), the fast-forward cannot proceed and the sync stops.
- **Locks land in the repository.** `file_lock` (`pipeline/file_lock.py:25-33`) opens `<file>.lock` beside the file, so `tasks.md.lock` and `follow-ups.md.lock` appear in `openspec/changes/<change>/` and nothing ignores or removes them.
- **The archive is never committed.** `archive_ready_changes` (`pipeline/archive.py:110-165`) runs `openspec archive` (`openspec.py:62-65`) and leaves the moved change directory and the synced main specs as uncommitted edits, so the default branch never shows a merged change as archived, and the worktree stays dirty.

Nothing that reads the specification is affected by ticks: `specification_text` and `without_boxes` strip boxes (`pipeline/work_graph.py:189-215`, `pipeline/task_progress.py:23-25`), and the spec snapshot compares tasks without boxes (`pipeline/spec_snapshot.py:36-41`), so a tick never makes a plan stale.

## What Changes

- **A tracking copy** of `tasks.md` and `follow-ups.md` per change, under `<state dir>/changes/<change>/`, is where the pipeline ticks, unticks, reads and writes. It is made from the repository file the first time, and reconciled with the repository `tasks.md` whenever a person has edited it (new groups unticked, removed groups dropped, a task added to a finished group counts as done). Everything that reads the specification keeps reading the repository file. The agent write fence is unchanged and does not grant the tracking directory.
- **Change locks leave the repository.** A helper `change_lock(inst, change, name)` returns `<local dir>/locks/changes/<change>/<name>.lock`; every lock that sits beside a file of a change uses it. `abk doctor` reports stray `*.md.lock` files under the changes directory and `abk doctor --fix` removes the untracked ones; `*.md.lock` joins the planning ignore block as a safety net.
- **The archive writes and commits.** Before `openspec archive` the tracking copy's ticked `tasks.md` and `follow-ups.md` replace the repository files; afterwards the archive move, the synced main specs and those files are committed, path-limited, through the planning publish path (`planning.publish: direct` pushes to the default branch, `branch` opens a pull request), sharing the push, retry and pull-request code of the tracks' bookkeeping commit.
- **Documents and tests** that say the repository `tasks.md` is ticked as units pass review are amended.

## Impact

- Capabilities: `task-progress-tracking`, `change-locks`, `archive-commit` (new); `unit-joining`, `unit-scope`, `planning-state-paths` (modified).
- agent-build-kit: `pipeline/task_progress.py`, `pipeline/stack_runner.py`, `graph/nodes.py` (call sites), `serve/server.py` (follow-ups read), `hooks/policy.py`, `pipeline/file_lock.py`, `pipeline/flakes.py`, `cli/pipeline.py` (`tags --fix`, the tick and `verify` archive wiring), `pipeline/archive.py`, `tracks/runner.py` (shared publish tail), `cli/doctor.py`, `templates/gitignore`, `docs/`, the `abk-pipeline` skill, `pipeline/pr_body.py` wording, `CHANGELOG.md`, `tests/`.
- Not in this change: moving the state directory itself (`pipeline-state-lives-outside-the-repo`), the local directory setting (`state-can-live-on-a-network-drive`), the locks that already sit in the state directory (`flakes.lock`, `planned.lock`, `scheduled-e2e.lock` and the like), and retiring the tracks' bookkeeping commit.
