# Tasks

Acceptance: none — the worktree is a real git worktree and the profile's commands are fakes that create a file, so tier 1 tests prove it.

Priority: 2

## 1. [agent-build-kit] [tier1] The profile names what its commands create

Done when a repository with no environment section whose tier 1 commands create a file the profile names is not
held at the next step and does not commit that file, and nothing outside the profile names it.

- [x] 1.1 Test: a repository with no environment section and a profile whose command creates an untracked file
      it names: the next step asking for the worktree runs and does not hold the unit; the file is still there.
      Cover it through the graph with a rework step as the second step.
- [x] 1.2 Test: the commit step leaves that untracked file out of the commit and it stays in the worktree; the
      unit's diff holds only the unit's own files.
- [x] 1.3 Test: another uncommitted file next to it still holds the unit with the cause `dirty_worktree` and
      names only that file.
- [x] 1.4 Test: a repository that tracks the file and whose environment declares dependency inputs follows the
      lock rule: committed with a change to a dependency input, restored when none changed. With no environment
      section a tracked file the profile names is ordinary work, as before.
- [x] 1.5 Test: a profile that returns nothing, and a profile without the hook, change nothing.
- [x] 1.6 Test: the paths come from the profile. Two fake profiles that return different files each own only
      their own; a fake profile in a second ecosystem's shape returns a nested file and is owned identically;
      a repository whose profile is unknown gets the environment's lists only and no error from the check.
- [x] 1.7 Test: a path named by the profile and by `inputs.lock` is one lock entry, restored or staged once; a
      path named by the profile and by `artifacts` is an artifact; a profile path that is absolute, has `..`
      or names `.git` is dropped; a repository with projects owns each project's paths under its path prefix.
- [x] 1.8 Add `created_files(repo)` to the profile protocol, return the lock file from the Python profile and
      none from the node profile, read the hook so a profile without it counts as none, add `Ownership` as a
      `StrEnum`, resolve the merged set in one function in the environment module, and feed it to the worktree
      preparation, the commit step and the restack where the lock paths go today.
- [x] 1.9 Update `docs/toolchain-profiles.md` for the hook, `docs/architecture.md` where the dirty-worktree rule
      and ownership are described, and add a changelog entry.
