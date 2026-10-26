# Design

## What was checked, and where

Read-only: `git fetch`, then `git show origin/main:<path>` (origin/main at `d5282e6c`). Paths are under `src/agent_build_kit/` unless they start with `tests/`, `docs/` or `openspec/`.

- **Who ticks.** Only the pipeline: `mark_groups` (`pipeline/task_progress.py:28-42`, a regex over the boxes of the listed groups under `file_lock(tasks.md.lock)`), reached from `StackRunner.mark_tasks` (`pipeline/stack_runner.py:1851-1855`, which resolves `<change dir>/tasks.md` per member) at `graph/nodes.py:2535` (satisfied), `graph/nodes.py:2727` (reaches `in_review`) and `pipeline/stack_runner.py:1915` (`fail`, unticks). Agents cannot write the specs directory (`hooks/policy.py:128-135`); the write grant for planning paths is `_may_write_planning` (`hooks/policy.py:198-211`), whose first branch gives a track run every `*.md` under the state directory.
- **Follow-ups.** Written by `record_follow_ups` (`stack_runner.py:1883-1901`, one `## From \`<unit>\`` block per unit under `follow-ups.md.lock`), read three ways: `follow_ups_note` (`stack_runner.py:1860-1871`, the whole file of each member's change, put into a fresh build's prompt at `graph/nodes.py:1437, 1720`; agents are never given the file, only that text), `follow_ups_for` (`stack_runner.py:1873-1881`, through `unit_follow_ups`, `:103-114`, for the pull request body, `graph/nodes.py:2650`) and `serve/server.py:395` (the review page, through `unit_follow_ups`). `spec_snapshot.py` never reads `follow-ups.md` (its module doc, line 4). So the tracking copy needs no new path to agents: the three readers change where they read.
- **What is tick-agnostic.** `specification_text` strips boxes (`pipeline/work_graph.py:189-215`, `_CHECKBOX` at `:161`), `spec_snapshot._compared` uses `without_boxes` (`pipeline/spec_snapshot.py:36-41`), the planner and `validate_tasks` read the repository file. None of them needs the ticked file.
- **Locks.** `file_lock` opens `<path>` for append and `flock`s it (`pipeline/file_lock.py:25-33`); the file is never removed and no `.gitignore` line covers `*.md.lock`. Locks that sit beside a change's files: `task_progress.py:39`, `stack_runner.py:1888`, `flakes.py:193` (`add_needs` rewrites a change's `tasks.md`) and `cli/pipeline.py:6514` (`abk tags --fix`, the `_fix_change_tags` rewrite). The other `file_lock` users (`flakes.py:127`, `e2e_schedule.py:112`, `environment.py:349`, `wiring.py:4043`, the records beside `units.json`) already sit in the state directory or a `locks/` folder. `split/remove.py` and the e2e schedule write a change's `tasks.md` (`pipeline/e2e_schedule.py:200`) but take no change lock. `templates/gitignore:9-10` ignores `runs/*.lock` and `runs/locks/`, so a state-directory lock is already ignored in a separate planning repo.
- **Archive.** `archive_ready_changes` (`pipeline/archive.py:110-165`) picks changes whose units have all merged (`is_ready_to_archive`, unit states, not ticks) and that `may_archive` lets through, then calls `openspec.archive` (`:152`, `openspec.py:62-65`, `archive <change> --yes`), then rolls up the usage ledger. It is called by the tick (`cli/pipeline.py:2090`) and by `abk verify` (`cli/pipeline.py:1262`). Nothing commits what it did: the tracks' `commit_bookkeeping` (`tracks/runner.py:560-619`) commits `<state dir>/**/*.md` and named changes, pushes (`HEAD:refs/heads/<branch>` from a detached worktree), retries once after `fetch` and `rebase --autostash`, keeps the commit and logs on a second rejection, and for `planning.publish: branch` calls `_publish_branch` (`:622-654`: push `planning/<run id>-<project>-<phase>`, `reset -q <earlier>` so the files stay in the worktree for the next fast-forward, `forge.create_pr`).
- **The sync with files left behind.** `_sync_worktree` (`pipeline/planning_sync.py:186-221`) leaves a worktree that is ahead of the tip alone (`:216-218`) and fast-forwards otherwise after `_clear_landed_files` (`:165-183`) discards an untracked or tracked-and-identical leftover that an incoming commit also brings; that is what lets a branch-published bookkeeping commit land later without stopping the sync.
- **Verify's dirty check** exempts the specs directory, state directory, graph page and usage page whole (`planning-state-paths` spec); `tests/pipeline/test_verify_planning_repo.py:90-95, 119` shows a ticked `tasks.md` and an archive move as exempt examples.
- **Doctor has no `--fix`.** `cmd_doctor` (`cli/doctor.py:1931`) only reports; the only fixing commands are `abk tags --fix` (`cli/pipeline.py:7575`) and `abk config --migrate`. `abk doctor --fix` is therefore a new flag, kept to this one repair.
- **The planning home.** `pipeline-state-lives-outside-the-repo` (group 1) defines `planning.home` (`<data home>/<repository name>/planning`) with `state/`, `worktree/` and `local/` below it; `state-can-live-on-a-network-drive` adds `planning.local_dir` (default `<planning home>/local`). This change uses `Installation.state_dir` for the tracking copy and a local directory for locks, and does not depend on the second change.

## Decisions

### Where the copy lives and what it is

`<state dir>/changes/<change>/tasks.md` and `follow-ups.md`; `progress_dir(inst, change)` returns the folder. Whatever the state directory is (`<planning home>/state` after change 1, `runs/` in a separate planning repo), the copy is beside the other pipeline state. In a separate planning repo `runs/changes/` is added to the template's ignore lines (`templates/gitignore`, which `scaffold._state_ignores` rewrites for the configured state directory), so the copy is never staged by the operator's commit of `runs/`.

`tasks.md` of the copy is the repository file's text with the boxes the pipeline set. It is made from the repository file the first time any tick, untick or read needs it, boxes included: a repository file that already carries ticks from before this change (a dirty worktree) seeds the copy with them. `follow-ups.md` is made from the repository file when it exists, else created by the first `record_follow_ups`.

### Reconciling with an edited repository `tasks.md`

Group and task numbers are the identity: a started unit carries group numbers, and a plan is refused when one of them disappears (`cli/pipeline.py:4476-4483`), so a number is never reused for another group while a unit holds it. `reconcile(inst, change)` rebuilds the copy from the repository text, under `change_lock(inst, change, "progress")` and, for the read of the repository file, `change_lock(inst, change, "tasks.md")`, always in that order:

| The repository file now | The copy gets |
|---|---|
| a task `N.M` the copy has ticked | ticked |
| a task `N.M` the copy had unticked | unticked |
| a task `N.M` the copy lacks, in a group whose every other task is ticked | ticked (the group was finished; a person added a line to it) |
| a task `N.M` the copy lacks, otherwise | unticked, in place |
| a group the copy lacks | appended with its text, unticked |
| a group the copy has and the file lacks | dropped, boxes and text |
| any other text (headings, `Needs:` lines, wording) | the repository's, byte for byte |

So the copy is always "the repository text, with ticks looked up by number"; renumbering a group that no unit holds moves its ticks with the number, which is the same as today where a tick is a box at a number. `reconcile` runs at the start of `mark_groups` and of the archive copy-back, not on a timer, so an edit is picked up by the next thing that needs the copy. A repository file that cannot be read (deleted: a withdrawn change) leaves the copy alone.

`mark_groups` ticks and unticks boxes in the copy only. Nothing in the pipeline reads a tick to decide anything (`is_ready_to_archive` reads unit states), so a copy that is a tick behind is a display matter; `abk tags --fix`, `abk replan`, a split and `add_needs` write the repository file and do not touch the copy.

### The three follow-ups readers

`follow_ups_note`, `unit_follow_ups` (so `follow_ups_for` and the review page) and `record_follow_ups` use `progress_dir(...)/follow-ups.md`, with a fallback to the repository file for a read when the copy does not exist (a file a person wrote, or one left by an older release). The runner gets the tracking folder the way it gets `change_dir` (`stack_runner.py:1828`): through the same wiring, a sibling callable, not by importing `Installation`. Builders still see follow-ups only as prompt text, so nothing about what an agent can read or write changes; the write fence gains one line, that `<state dir>/changes/` is not part of the `*.md` grant of `_may_write_planning`, since a track run is granted the whole state directory's Markdown and the copy is the pipeline's.

### Locks outside the repository

`change_lock(inst, change, name)` in `pipeline/file_lock.py` is `file_lock(local_dir / "locks" / "changes" / change / f"{name}.lock")`. `local_dir` is `planning.local_dir` when `state-can-live-on-a-network-drive` has landed; until then it is `<planning home>/local`, derived from the same planning home as change 1; in a separate planning repo (no planning home) it is `<state dir>/locks`, already ignored. The names: `tasks.md` (every write of the repository file: `add_needs`, `tags --fix`), `progress` (the tracking copy's ticks), `follow-ups.md` (the follow-ups writer). The old name `tasks.md.lock` was one lock for ticks and rewrites because they were the same file; they are now two files and two locks, taken in the order progress then tasks.md and never the other way round.

Cleaning up old files: `abk doctor` warns when an `*.md.lock` exists under the changes directory; `abk doctor --fix` deletes the untracked ones it can take (`try_file_lock`, so one a live process holds is left) and names a tracked one for `git rm`. The archive also removes the change's own lock files before the move. The `.gitignore` line `*.md.lock` stays in the planning block (`templates/gitignore`, written by `init/scaffold.py` with the other lines) only as a safety net for a tool that is not this pipeline.

### The archive writes, then commits

Order, per change, inside `archive_ready_changes`: (1) `reconcile`; (2) copy the copy's `tasks.md` and `follow-ups.md` over the repository files (a copy that does not exist is skipped, so a change with no follow-ups keeps none); (3) `openspec.archive`; (4) if it succeeded, the new `publish` hook runs, then the copy is deleted. The function stays free of git: it takes a `publish: Callable[[str], None]` and a `progress` folder resolver beside its other path parameters, and `cmd_tick` and `cmd_verify` pass the commit. A failed `openspec archive` puts the repository files back as they were (the copy-back is undone) so the next tick starts from the same state.

The commit reuses the tracks' machinery by extracting its tail. `commit_bookkeeping` (`tracks/runner.py:584-619`) from `commit` through the retried push, and `_publish_branch`, become one function `publish_commit(inst, branch, label, message, earlier, body)` in `tracks/runner.py`'s module (or a module it imports), used by `commit_bookkeeping` unchanged in behaviour and by the archive. For the archive: the pathspec is `<specs dir>/changes/<change>`, `<specs dir>/changes/archive` and `<specs dir>/specs` and nothing else (never `abk.yaml`, never the state directory, never code); `message` is `archive: <change>`; for a direct publish from the detached worktree the refspec is `HEAD:refs/heads/<default branch>`, for a working copy or a separate planning repo it pushes the current branch, exactly as `commit_bookkeeping` chooses; for `planning.publish: branch` the head is `planning/archive-<change>-<run id>` and the pull request body says which change and that abk archived it. The retry is `fetch`, `rebase` onto `origin/<branch>` with the abort-on-conflict of `:606-609`, then one more push; a second rejection keeps the commit and logs it with the root path. The commit stays: the worktree is then ahead of the tip and the sync leaves it (`planning_sync.py:216-218`), and the next archive's push carries it too.

### The trade-off

A person loses the in-repo progress ticks between planning and archive: `openspec/changes/<change>/tasks.md` on the default branch stays as it was written (all boxes empty) until the change is archived, when the archived copy shows the ticks. The progress is read through the `.planning` link (`<planning home>/state/changes/<change>/tasks.md`, from `init-makes-the-state-home-and-the-planning-view`) or `<state dir>/changes/...` where that link does not exist, and `abk status` shows unit states. The gain: the pipeline worktree has no tracked change from a tick, a person's edit of `tasks.md` on the default branch never stops the sync, no lock file reaches the repository, and an archived change finally reaches the default branch with its main specs.

## Risks

- A repository `tasks.md` that someone ticked by hand: the copy ignores it after the first seeding; the archive overwrites it with the copy's ticks (the repository text is otherwise reproduced byte for byte, so the diff is only boxes).
- A push race with a person on the default branch is the tracks' case and has the tracks' answer (one retry, then the commit is kept and reported).
- A group removed and re-added with a new number loses its ticks: its units are separate units by then.
- The kit is public: tests and documents use neutral names (`app`, `example`) and temporary directories only.
