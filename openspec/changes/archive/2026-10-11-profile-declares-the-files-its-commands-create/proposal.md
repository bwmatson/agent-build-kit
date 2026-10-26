# Proposal

## Why

`environment-sync-leaves-no-leftovers` made the lock paths named in a repository's `environment.inputs.lock`
the pipeline's own. A repository with no `environment` section has no such paths, so nothing is owned there.
The tier 1 commands the pipeline itself runs in a unit's worktree (lint, tests, the clean check, all started by
the toolchain profile) can still create a file in it. For the Python profile, `uv run ...` creates an untracked
lock file in a repository that has none. The next step's worktree check counts untracked files, finds one that
is not the step's own, and holds the unit with the cause `dirty_worktree` for a human. The acceptance scratch
application is such a repository, and so is any consumer repository that does not commit a lock.

A repository that tracks its lock is not affected, because the command leaves a tracked, unchanged file alone.
Only the repository that does not track one is held, and it is held by the pipeline's own output.

The knowledge of which file a command creates is toolchain knowledge. `environment-is-language-independent`
makes it a rule that framework code names no package manager or lock file and that this knowledge lives in the
toolchain profile. So the answer cannot be a built-in list in the check; the profile has to be asked.

## What Changes

- **A profile hook.** The toolchain profile gains an optional `created_files(repo)` returning the paths or
  patterns, relative to the repository, that its own commands create or rewrite. The Python profile returns
  its lock file. A profile with nothing returns an empty list, and a profile without the hook counts as
  returning one. The node profile, which cannot build yet, returns none.
- **Those paths are pipeline-owned.** The worktree check, the commit step and the move of a branch treat them as
  they treat an environment's lock paths and artifacts: not a leftover, never discarded, and an untracked one is
  never committed. A tracked one follows the existing lock rule.
- **Nothing is hard-coded.** The check takes the set from the profile of the repository, merged with the
  environment's lists; a repository whose profile has nothing and which has no environment behaves as before.

## Impact

- Capability: `pipeline-environment` (added requirements).
- Code: the profile protocol and the two profiles, the function in the environment module that resolves the
  owned set, the worktree preparation wiring and the commit step that already receive the lock paths.
- Builds on `environment-sync-leaves-no-leftovers` (merged) and fits with `environment-is-language-independent`
  (not yet merged): it adds one more source to the set that change's patterns and artifacts also feed, and works
  with either order of merging.
