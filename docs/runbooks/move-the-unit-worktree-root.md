Follow it only after group 1 and group 2 of unit-worktrees-are-keyed-by-the-repository-name are built and merged.

# Runbook: move the unit worktree root

Nothing in it is read by the pipeline. Tick the boxes as you go.

For the person who changes `planning.worktree_root`. Unit worktrees live at `<root>/<repo name in abk.yaml>/<sanitised branch>`. Changing the root leaves the old worktrees registered with git, and a unit whose worktree is outside the root is refused, so move them first.

## 1. Stop the timers
- [ ] `abk install-timers --remove`, or `systemctl --user disable --now` of the tick and track timers.
- [ ] Wait for the tick and track services to be inactive and `abk status` to show no running unit. Never kill a running one: a running unit's worktree must not be moved. An edit of `abk.local.yaml` during a step is only a warning with its diff.

## 2. Note what is there
- [ ] `git worktree list` in each repo; note the unit worktrees under the old root.

## 3. Change the root
- [ ] Edit `abk.local.yaml` (`planning.worktree_root`) to the new folder, or remove the key so the default `<data home>/<repository name>/worktrees` applies. Keep the new folder outside the repository.

## 4. Move the worktrees
- [ ] For each unit worktree whose unit is not running: `git worktree move <old> <new-root>/<repo name>/<sanitised branch>`, or `git worktree remove <old>` for a clean one. The branch keeps the work; never use `--force`.

## 5. Tidy and check
- [ ] `git worktree prune`.
- [ ] `abk doctor` shows `unit worktrees` ok.

## 6. Restart
- [ ] Restart the timers.

## Rollback
Stop the timers, restore the old `worktree_root`, and `git worktree move` the worktrees back. Any left under the new root are outside the restored root, and their units are refused until they are moved back.
