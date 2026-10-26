# Proposal

## Why

A unit built in a repository that declares an `environment` has the repository's `sync` run in its worktree
whenever the inputs' hash differs from the one recorded for that worktree. In a repository with no lock file
yet, a package manager's `sync` creates one. That file is untracked, so the next step's worktree check finds
uncommitted changes that are not the running step's own and holds the unit for a human: "uncommitted changes in
the worktree: uv.lock — commit or remove them by hand".

This stopped a live acceptance run. A scratch unit was held at its second step, a rework, so the test that
asserts a second review round never saw one and failed. The unit's own reviewer had already written that the
untracked lock was an environment artifact and not part of the diff. A second acceptance test that drives a unit
through a rework failed in the same run; its error text was not saved, so that it is the same hold is likely but
unverified.

Real repositories are exposed too. A unit that changes a dependency makes `sync` rewrite a tracked lock file, and
any such modification would hold the unit the same way, or be swept into an unrelated commit.

## What Changes

- **The dirty-worktree check ignores the environment's lock files:** a path named in the repository's
  `environment.inputs.lock` that is untracked or modified does not hold a unit, and is never discarded.
- **The commit step treats them by whether the unit changed dependencies:** a tracked lock is committed with the
  unit's change when the unit changed a dependency input, and is otherwise restored to the branch's version; a
  lock the branch does not track is never committed.
- **Nothing changes for a repository without an environment section,** and no lock file name is built in: the
  paths come from the configured inputs.

## Impact

- Capability: `pipeline-environment` (added requirements).
- Code: the worktree preparation and its dirty check, the commit step, the leftovers note given to an agent.
- Follows `pipeline-environment` group 3, which introduced the sync in the unit's worktree.
