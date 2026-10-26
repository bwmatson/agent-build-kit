# Design

## What was verified against the code

- The tier 1 commands run in the unit's worktree: the profile's `lint_command`, `test_commands`, `clean_command`
  and `extra_checks` run with the worktree as the working directory. The Python profile starts every one of
  them with `uv run`, which creates a lock file where the repository has none. A step that runs the sync
  (`prepare_worktree` in the environment module) is not needed for this; it needs no `environment` section.
- The dirty check is `prepare_worktree` in the workspaces module. It lists `_porcelain` (every untracked file
  named), removes the entries whose path is in its `locks` argument, and raises `DirtyWorktree` for the rest
  unless `allow_dirty`. The match is on the literal path today (`name not in locks`).
- `lock_paths` in the environment module returns the normalised `environment.inputs.lock` entries, and returns
  an empty tuple when the repository has no `environment` section. `build_worktree` in the wiring module
  passes it as the `locks` option and nothing else. **This is why the archived change cannot help a repository
  with no environment section.**
- The commit step is the `commit` closure in the wiring module. Its `attempt` runs
  `restore_unchanged_locks`, then `git add -A`, then `unstage_untracked_locks`, then commits. The restack
  calls `restore_unchanged_locks` before it moves a branch. Both functions are in the environment module and
  start from `lock_paths`. They are the mechanism to reuse.
- `restore_unchanged_locks` does nothing without an `environment` section, and `_changed_from_base` over an
  environment with no dependency inputs answers "unchanged".
- `ToolchainProfile` (profiles/base.py) is a `Protocol`, typing only. Hooks that not every profile has
  (`failed_tests`, `serial_rerun_command` on the Python profile) are not in it and are read with `getattr`.
  `profiles.get(name)` raises `KeyError` for an unknown profile, and nothing in configuration loading checks
  the name; the wiring fails at its own `profiles.get(repo.profile)`.
- `ProjectConfig` lets a repository list projects, each with a path and its own `profile`; a repository's
  `profile` is the toolchain of the root.
- `workspaces.commit_changes` also runs `git add -A`, but nothing in the unit's commit path calls it; it is not
  changed.

### Corrections to the brief

- `environment-sync-leaves-no-leftovers` is merged and archived; `environment-is-language-independent` is the
  only sibling still open. The mechanism to reuse is `lock_paths`, `restore_unchanged_locks` and
  `unstage_untracked_locks` in the environment module, not code in the wiring module; the wiring module holds
  only the `git add -A` call between them.
- That change's tracked-lock rule decides by `_changed_from_base` over the environment's dependency inputs.
  Without an environment there are none, so applied as written it would restore every tracked file the profile
  names, including a lock an agent legitimately changed. Decision 4 below handles it; the brief said only
  "follows the sibling rule".
- The Python profile has no field naming its lock file. `detect_markers` mentions it, but that is a detection
  hint and also lists the manifest, which a command does not create. The hook is new, not a rename.
- The human-driven discard in `attach.py` (`discard_changes`) takes no lock paths today and is left that way:
  a person asked for it.

## Decisions

1. **The hook.** `created_files(repo: Path) -> list[str]` on the profile protocol, where `repo` is the
   repository's checkout root. It returns paths or patterns relative to the repository, `/` separated, in the
   syntax of `environment-is-language-independent` when that has landed and as literal paths before. It names
   what the profile's own commands create or rewrite when they run in a worktree, not what a build produces
   (that is `environment.artifacts`). A profile without it counts as returning none, read as `failed_tests` is,
   so a third-party profile keeps working. The Python profile returns its lock file; the node profile returns
   none until it is written.
2. **Where the set is computed.** One function in the environment module resolves the owned set for a
   `RepoConfig`: it asks the profile of the repository, and the profile of each of its `projects` with the
   project's path prefixed to what it returns, and merges them with `environment.inputs.lock` and
   `environment.artifacts`. It is evaluated once per entry point, that is once per worktree request, once per
   commit attempt and once per move of a branch, and the value is passed down to the dirty check, the restore
   and the unstage as the lock paths are today. It is not cached across calls, since it is cheap and the
   configuration is reloaded between runs. The dirty check and the commit step stay free of any file name.
3. **Merging.** Each owned path carries an `Ownership` (a `StrEnum`: `lock`, `artifact`, `created`), the source
   it came from. A path named by several sources is one entry. The strictest wins, in the order `artifact`,
   `lock`, `created`: an artifact is never staged, a lock follows the lock rule, a created file follows the
   lock rule where it can be evaluated (decision 4). A path in both `inputs.lock` and `created_files` is a
   lock once, so it is restored or staged once and not twice. A profile path matching a path the repository
   tracks is handled by decision 4, never by the pattern.
4. **Untracked and tracked.**
   - An untracked owned path is not a leftover, is never discarded and is never committed: the commit step takes
     it out of the index after `git add -A` as `unstage_untracked_locks` does for a lock, with the same
     function now fed the whole set. It stays in the worktree, which the profile's commands need.
   - A tracked owned path that came from `lock` or `artifact` behaves as those changes specify.
   - A tracked path that only the profile named (`created`) follows the lock rule: committed with the change when
     the unit changed a dependency input, otherwise restored to the branch's version. That comparison needs the
     environment's dependency inputs. Where the repository declares none (no environment section, or an empty
     list), the answer would always be "unchanged" and a legitimate edit would be erased. So there a tracked
     `created` path is **not owned**: it is ordinary tracked work, held for and committed as before. The
     failure this change fixes is the untracked file; a tracked one is the repository's own and a command that
     leaves it unchanged leaves nothing to report.
5. **Unknown profile.** The set is computed with no profile contribution and without raising: the lists from the
   environment still apply and the hook adds nothing. The run already fails loudly where it asks for the
   profile (the wiring's own `profiles.get`), and a worktree check must not be the place that fails first with a
   less useful error.
6. **A hook that raises or returns nonsense.** A path that is absolute, contains `..` or names `.git` is
   dropped, as an input pattern like it is a configuration error in the sibling change; a hook that raises
   propagates, since a profile bug should not be hidden.
7. **No change for the quiet case.** A repository with no environment section whose profile returns nothing
   gets the empty set, and every function behaves as it did.

## Group 1

The tests come first. They use the existing environment and worktree fakes and a real git worktree, a profile
whose commands create a file (the fake the profile tests already use), and two fake profiles that return
different files so the check is shown to read the profile and not a name.

## Risks

- A profile that lists a file a person also edits by hand in the worktree owns it for that repository, as a lock
  listed in `inputs.lock` does. The hook describes only what the profile's commands create.
- `created_files` and the sibling's `detect_environment` are both optional hooks on one protocol; each is read
  with `getattr`, so neither requires the other.
- The merged set is also what `generated_file_patterns` could use for unit sizing. Not done here: sizing reads
  `limits.generated_files` for configuration, and an untracked file never reaches a diff.
