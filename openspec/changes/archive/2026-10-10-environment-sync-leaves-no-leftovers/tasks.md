# Tasks

Acceptance: none — the worktree is a real git worktree and the sync a real child process in the existing environment fakes, so tier 1 tests prove it.

Priority: 1

## 1. [agent-build-kit] [tier1] The environment's lock files are the pipeline's

Done when a unit whose repository's sync writes or rewrites a lock file named in its lock inputs is not held for
it, and the commit step keeps a lock the unit changed and leaves out one it did not.

- [x] 1.1 Test: a sync that creates an untracked lock named in the lock inputs, then a second step asking for
      the worktree, runs the step and does not hold the unit; the file is still there. Cover it through the graph
      with the existing environment fakes, with a rework step as the second step.
- [x] 1.2 Test: a tracked lock rewritten by the sync does not hold the next step and is not discarded; another
      uncommitted file next to it still holds the unit with the cause `dirty_worktree` and names only that file.
- [x] 1.3 Test: the lock inputs of two repositories name different files, and each ignores only its own; a
      repository with no environment section holds for an uncommitted lock as before.
- [x] 1.4 Test: a unit that changed a dependency manifest and whose sync rewrote the tracked lock commits both
      together; a rewrite with no dependency change is restored and not committed; an untracked lock is never
      committed and stays in the worktree.
- [x] 1.5 Test: a restack of a unit with a rewritten tracked lock the unit did not change succeeds.
- [x] 1.6 Pass the repository's lock paths to the worktree preparation and its dirty check, and leave them out of
      the leftovers note; make the commit step apply the rules above; restore an unchanged tracked lock before a
      move of the branch.
- [x] 1.7 Update `docs/architecture.md` where the dirty-worktree rule and the environment sync are described, and
      add a changelog entry.
