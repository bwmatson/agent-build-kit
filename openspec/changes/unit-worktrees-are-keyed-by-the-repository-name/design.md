# Design

## What was checked, and where

Read from `origin/main`, paths under `src/agent_build_kit/`.

- **The key.** `workspaces.py:132-133` `worktree_path(repo: Path, branch, root)` returns `root / repo.name / re.sub(r"[^A-Za-z0-9]", "_", branch)`; `prepare_detached` (239-253) builds `root / repo.name / name`; `remove_worktree` (279-290) and `prepare_worktree` (190-236) call `worktree_path`, and `prepare_worktree` reuses whatever `path.exists()`.
- **Where `repo.name` is a folder name that moves.** `Installation.checkouts` (`installation.py:208`) maps each `repos.<key>` to `checkout_of(repo.path)`; a `path: .` repo is the installation root, whose folder is `worktree` in the pipeline-worktree role (`installation.py:119` already works around the same thing for the planning home with `repository_name`).
- **Callers of `worktree_path`:** `cli/pipeline.py:1247` (`_worktrees_of`) and `:5544` (the restack's "own worktree" test), `cli/retire_cmd.py:108`, `pipeline/attach.py:46`, `pipeline/events.py:1931`, `pipeline/manual_steps.py:105`, `pipeline/restack.py:617` (`temporary_tree`), and, not in the brief, `serve/review.py:121` (`unit_worktree`). `Installation.worktree_path` (`installation.py:122`) is the pipeline worktree (`planning_home/worktree`), unrelated.
- **Folder-name assumptions that are not `worktree_path`:** `cli/pipeline.py:5655` `cwd.parent == installation.worktree_root / path.name` in `unit_test_of`, and `restack.checked_out_at` (622-640) which calls `prepare_detached(repo, path.name, ...)`.
- **Parsing worktrees.** `restack._checked_out_in` (`restack.py:346-354`) already splits `git worktree list --porcelain` into blocks and matches `branch refs/heads/<b>`; it is the model, and becomes a caller of the shared parser.
- **Locks.** Worktree adds run in the repo's turn (`wiring.py:4077-4082`, `repo-<repo>.lock`), so the lookup-then-create below is not racy within one installation.
- **Sanitiser collision today.** `spec/a-b/1` and `spec/a_b/1` both map to `spec_a_b_1`; `prepare_worktree` finds the directory and reuses it for the second branch with no check. Found, not in the brief.

## Decisions

### The key is `repos.<key>`, not `repository_name`

`repository_name(root)` (`planning_repo.py:61`) gives the directory name of the repository's main working tree. It is right for naming a planning home (one per repository) and wrong here: it follows a rename or a new clone location of the repository, and two repos of one installation can share it (`~/a/app`, `~/b/app`). The key in `abk.yaml` is a mapping key, so it is unique within an installation by construction, does not change when a checkout moves, and is what every other per-repo path of the pipeline already uses (`runs/locks/repo-<repo>.lock`, `unit.repo`).

`worktree_key(name) = re.sub(r"[^A-Za-z0-9._-]", "_", name)`. The branch sanitiser (`[^A-Za-z0-9]`) is not reused: it would turn a key `my-app` into `my_app` and rename the directory of a repo checked out at `~/my-app`, which is fine today. Keys with only letters, digits, `.`, `_` and `-` map to themselves.

**Repos at an external folder.** Key `app`, checkout `~/app`: `worktree_key("app") == "app" == checkout.name`, so every directory keeps its place and nothing is adopted, only found. A repo whose key differs from its folder (key `app`, checkout `~/app-src`) had its worktrees under `app-src`; they are adopted where they are by the lookup below, and new units go under `app`. `abk doctor` notes the difference. Two keys that sanitise to one folder (`a b`, `a_b`) are not rejected here; the occupied-directory refusal below stops the second from using the first's folder.

### The signature

Callers that create a path need the key; callers that only look do not, because git says where a worktree is.

```
worktree_key(name: str) -> str
worktree_path(repo: Path, branch: str, root: Path, *, name: str) -> Path   # where a NEW one goes
worktree_entries(repo: Path) -> tuple[WorktreeEntry, ...]                  # path, branch | None, prunable
unit_tree(repo: Path, branch: str, root: Path) -> Path | None              # the unit's existing one; never raises
prepare_worktree(repo, branch, *, name, base, root, ...)   # name is new
remove_worktree(repo, branch, *, root)                     # looks up, no name
prepare_detached(repo, leaf, *, name, ref, root)           # name is new
restack.temporary_tree / checked_out_at / move_in_temporary_worktree(..., name=...)
```

`WorktreeEntry` is a frozen pydantic model. `unit_tree` returns the directory of the entry whose branch is `branch`, when it is under `root` (resolved) and exists; `None` otherwise (none, deleted, or not ours). Every probe replaces `worktree_path(...).exists()` or `.is_dir()` by `unit_tree(...)`. `worktree_in_turn`'s caller already has `unit.repo`; the others read `unit.repo` or the `repos` key they index `checkouts` by (`build_remove_worktree(repos, ...)` has `repo` as its argument; `checked_out_at` is reached through `checkout(path, ...)` in `build_stack_moves`, which has `names[path]`).

### Order, whenever a unit's worktree is needed to create or resume it

`prepare_worktree`, in the repo's turn:

1. Read `worktree_entries(repo)` and find the entry whose branch is `branch`.
2. **Under the root, directory present:** that directory is the worktree. The dirty check, scratch and reuse that follow are unchanged. It is not moved.
3. **Under the root, directory gone** (git marks it `prunable`): `git worktree prune`, then go to 5.
4. **Checked out anywhere else** (outside the root, or the repository's own checkout): raise `WorktreeElsewhere(branch, path)`: "<branch> is checked out at <path>, which is not under <root>; leave that checkout or switch it away, the pipeline does not use or remove it". It never adopts, switches or removes it.
5. **No entry:** the target is `worktree_path(repo, branch, root, name=name)`. If it exists and is not an empty directory, raise `WorktreeOccupied(branch, path)` naming the path (a different branch's worktree through a sanitiser collision, or a leftover that git does not know). Otherwise create it (`worktree add`, with `-b ... base` when the branch is new), as now.

`remove_worktree` uses 1-2 and 4: it removes the adopted directory without force, does nothing when there is none, and raises `WorktreeElsewhere` for 4 (retire's existing handler reports a failed removal and goes on to `branch -D`, which git refuses for a checked-out branch). `prepare_detached` has no branch: it looks for `root/<key>/<leaf>`, then for a registered detached entry under the root whose last segment is `leaf` (any key), and creates under the new key otherwise.

The restack's temporary tree stays beside where a unit's own would be (`own.parent / f"restack-{own.name}"`) under the new key; it is detached so the branch lookup never sees it, and one left under an old key is cleared by the existing `worktree remove --force` / `prune` at the start of `checked_out_at`, which is the temporary tree's own.

### Scenarios decided

| Situation | Result |
|---|---|
| Branch registered under `<root>/<old key>/...` | used there; doctor notes it |
| No worktree | created under `<root>/<key>/<branch>` |
| Registered, directory deleted | pruned, then created under the new key |
| Checked out in the working copy or any path outside the root | `WorktreeElsewhere`; probes report no worktree |
| Two branches with one sanitised name | the second is refused with `WorktreeOccupied` (it used to reuse the first's directory) |

### The doctor

A check `unit worktrees` next to `worktree root` (`doctor.py:1979`) lists, for each checkout, its entries under `inst.worktree_root`: one whose parent is not `<root>/<key>` gets an `_info` ("adopted; `git worktree move <path> <new>` when its unit is idle"), one whose directory is missing gets a `_warn` with `git worktree prune`. It reads git only and writes nothing. `abk status` is unchanged.

### Docs

`configuration.md:108-111` says the folder is `<root>/<repo dir name>/<branch>` and the default is `~/.local/share/<planning dir name>/worktrees`: it becomes `<root>/<repo key>/<branch>` and `<data home>/<repository name>/worktrees`, with the adoption paragraph. The runbook says to stop the timers and wait for no running unit and track before editing `abk.local.yaml`: the config guard (`configuration.md:877-882`) fails an unconfined step, and a track run, with `ConfigChanged` when either file differs, while a confined step only warns, so waiting is the safe rule and costs nothing.
