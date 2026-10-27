# Runbook: move an in-repo installation's state out of the repository

Follow it only after `pipeline-state-lives-outside-the-repo` is **built and merged** (all groups). Nothing in it is read by the pipeline. Tick the boxes as you go.

For the person running an installation whose planning repo is also one of its code repos and whose state (`runs/`) is committed. After the change the state lives in the planning home, `<data home>/<repository name>/planning/state`, the pipeline worktree at `<planning home>/worktree`, and the tracks' run logs and `tracked-issues.md` in `planning.reports_dir` (default `docs/reports`). `abk doctor` warns about files git still tracks under `runs/` until this is done. Until you follow it the units, the state and the logs are not lost: the state of this installation has not been moved, and a tick reads the new, empty state.

## 1. Before you start
- [ ] Back up the pipeline worktree's `runs/` (`cp -a <worktree>/runs <backup>`): it is the live state.
- [ ] The working copy has the merged change: `git pull`. `abk status` prints the worktree.
- [ ] Note the planning home (`abk status` or `abk install-timers --dry-run`).

## 2. Stop the timers
- [ ] `systemctl --user disable --now abk-<name>-tick.timer` and the three `abk-<name>-track-*.timer` units.
- [ ] Wait for `systemctl --user is-active abk-<name>-tick.service` to say `inactive`. Never kill a running tick.

## 3. Move the worktree
- [ ] From the working copy: `abk install-timers --no-enable`. It moves the pipeline worktree to `<home>/worktree` and says `moved planning worktree <old> to <new>`; an active unit makes it refuse.

## 4. Copy the state
- [ ] `cp -a <home>/worktree/runs/. <home>/state/` (create `<home>/state` first).

## 5. Take the state out of git, on the default branch
- [ ] Move the tracks' two run logs and `tracked-issues.md` from `runs/` to `docs/reports/`.
- [ ] `git rm -r runs/`, remove the `runs/` lines of `.gitignore`, commit and push.

## 6. Clean the worktree
- [ ] Reset the worktree's modified tracked files and remove its untracked `runs/`.

## 7. Check
- [ ] `abk doctor`: no warning about `runs/`.
- [ ] `abk status`: the same units as before, nothing replans.

## 8. Resume
- [ ] `abk install-timers` to enable the timers.
- [ ] Watch two ticks.

## Rollback
- [ ] Stop the timers and wait for the tick to be inactive.
- [ ] Set `ABK_STATE_DIR` (or `planning.state_dir: runs` in `abk.local.yaml`).
- [ ] Restore `runs/` from the backup of step 1.
- [ ] `git revert` the commit that removed `runs/`, then `abk install-timers`.
