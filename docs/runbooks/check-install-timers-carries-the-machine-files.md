# Runbook: an installation whose machine files were linked by hand

Follow it only after `install-timers-carries-the-machine-files-into-the-pipeline-worktree` is **built and merged** (both groups). Nothing in it is read by the pipeline. Tick the boxes as you go.

For the person running an in-repo planning repo (a repository that is its own planning repo) who set it up before that change existed. The pipeline worktree is a checkout of the default branch, so the git-ignored machine files (`.env`, `abk.local.yaml`, `scrub.local`) never reach it, and the units, which run from the worktree, saw defaults. The workaround was to link the three files from the working copy into the worktree by hand. The change makes `abk install-timers` do that, and `abk doctor` check it.

**What to expect:** a hand-made link to the working copy's file is exactly what `install-timers` now writes, so there is nothing to remove. This runbook proves the new behaviour by removing the hand-made files once and letting `install-timers` put them back. A file that was **copied** by hand (a regular file, not a link) is different: it drifts from the working copy, and `install-timers` refuses to overwrite it, so it has to go first.

## 1. Before you start
- [ ] The working copy has the merged change: `git pull`, and `abk status` shows the change's units `merged`.
- [ ] Find the pipeline worktree: `abk status` prints it (or `abk install-timers --dry-run` names it).
- [ ] Look at what the worktree holds: `ls -l <worktree>/.env <worktree>/abk.local.yaml <worktree>/scrub.local`. Each is a link to the working copy's file (fine), a regular file (a hand copy), or absent.
- [ ] Note which of the three exist in the working copy. A file the working copy lacks is skipped; that is not an error.

## 2. Stop the timers while you change the worktree
- [ ] `systemctl --user disable --now abk-<name>-tick.timer` and the three `abk-<name>-track-*.timer` units (`systemctl --user list-timers` shows the names). A tick that is running when a file disappears fails on it.
- [ ] Wait for `systemctl --user is-active abk-<name>-tick.service` to say `inactive`. Never kill a running tick.

## 3. Remove the hand-made files from the worktree
- [ ] A link: `rm <worktree>/<file>`. This removes only the link.
- [ ] A regular file: compare it with the working copy's first (`diff`; do not print `.env`, which holds secrets), keep any difference you want by moving it to the working copy's file, then `rm` it.

## 4. Let `install-timers` carry them
- [ ] From the working copy: `abk install-timers --no-enable`. It reports a link made for each machine file the working copy has. A refusal names the file and why (a differing regular file, or a path git would not ignore in the worktree); fix that and run it again.
- [ ] Run it a second time: every file is reported unchanged.
- [ ] `ls -l <worktree>/...` shows each link pointing at the working copy.

## 5. Check
- [ ] `abk doctor` in the worktree: the `machine files` check is ok, and nothing else regressed.
- [ ] `abk --config <worktree>/abk.yaml config --show`: the values that come from `abk.local.yaml` are in force (the worktree root, the usage limits, the models, `verify.env`).
- [ ] An edit to a machine file in the working copy shows in the worktree at once (it is the same file); the ConfigChanged fence treats an edit made during a run as a person's edit, as before.

## 6. Resume
- [ ] `abk install-timers` (this time enabling), or re-enable the four timers by hand.
- [ ] Watch one tick: no `ConfigChanged`, no defaults where your settings should be.

## Notes
- `abk config --migrate` run **inside** the worktree replaces a link with a regular file. Run it from the working copy. `abk doctor` reports the replacement and `abk install-timers` repairs it.
- If the working copy moves, the links dangle. `abk doctor` reports them and a re-run of `abk install-timers` from the new location repoints them.
- On a fresh machine or a second clone there are no machine files to carry. `abk doctor` warns; create them in the working copy and run `abk install-timers` again.
- The files are never committed: the repository is public, `.env` holds secrets and `scrub.local` lists the words that must stay out of it.

## Rollback
Remove the links and make them by hand again, `ln -s <working copy>/<file> <worktree>/<file>` for each, then re-enable the timers.
