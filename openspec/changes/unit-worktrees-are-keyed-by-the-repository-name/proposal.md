# Proposal

## Why

`worktree_path` (`pipeline/workspaces.py:132-133`) puts a unit's worktree at `<worktree_root>/<checkout.name>/<branch>`, and `prepare_detached` (`workspaces.py:247`) does the same for the detached `main` checkouts of a dev stack. `checkout.name` is the last segment of the repo's checkout path. For a repo declared `path: .` the checkout is the installation root, and in the pipeline-worktree role that root's folder name is the worktree's own. On a real machine that name changed three times as the layout evolved (the working copy's name, then `planning`, then `worktree` once `pipeline-state-lives-outside-the-repo` put the pipeline worktree at `<planning home>/worktree`). The effects:

- Every unit worktree made under an earlier key is orphaned. Resuming the unit computes the new path, finds nothing there, and `git worktree add` fails because git has the branch checked out at the old path: `CalledProcessError: git worktree add -q <root>/worktree/spec_x_1 spec/x/1`.
- `worktree` is not a name of anything. Two in-repo repos sharing one `worktree_root` put their units in one folder.

A repo at a fixed external folder (`~/app`) is keyed by that folder and is fine; nothing about it needs to change.

## What Changes

- **The key is the repo's name in `abk.yaml`.** One function, `worktree_key(name)`, gives the folder; `worktree_path`, `prepare_worktree`, `remove_worktree`, `prepare_detached` and the restack's temporary tree take the name. A repo whose key equals its checkout's folder name (the usual case) keeps every directory it has.
- **Git is asked first.** Whenever the pipeline needs a unit's worktree it reads `git worktree list --porcelain` of the unit's repo. A worktree for the branch under the worktree root, whatever its key, is the unit's and is used where it is. One outside the root, or the main checkout, is refused naming branch and path. A registered path whose directory is gone is pruned, then the worktree is created under the new key. Nothing is moved, removed with force or adopted from a person's own checkout.
- **Read-only probes** (`attach`, `retire`, manual steps, the review page, the restack's "has its own worktree" test, `_worktrees_of`) go through the same lookup and treat "none, or not ours" as no worktree.
- **`unit_test_of`** (`cli/pipeline.py:5655`) found a unit's repo by `worktree_root / path.name`, the same folder-name assumption; it asks git which repository a directory belongs to instead.
- **`abk doctor`** notes unit worktrees under a key other than the current one (adopted, movable with `git worktree move` while the unit is idle) and warns on a registered one whose directory is gone.
- **Docs:** the `planning.worktree_root` text, the architecture description, a changelog entry and a runbook for moving the root.

## Impact

- Capabilities: `unit-worktrees` (new), `planning-worktree` (modified: the worktree root's layout).
- agent-build-kit: `pipeline/workspaces.py`, `pipeline/restack.py`, `pipeline/events.py`, `pipeline/attach.py`, `pipeline/manual_steps.py`, `pipeline/wiring.py`, `cli/pipeline.py`, `cli/retire_cmd.py`, `serve/review.py`, `cli/doctor.py`, tests, `docs/configuration.md`, `docs/architecture.md`, `docs/runbooks/move-the-unit-worktree-root.md`, `README.md`, `CHANGELOG.md`.
- Not in this change: moving existing worktrees automatically, changing the default `worktree_root`, or the pipeline worktree's own location (`Installation.worktree_path`, `installation.py:122`, is that and is unrelated despite the name).
