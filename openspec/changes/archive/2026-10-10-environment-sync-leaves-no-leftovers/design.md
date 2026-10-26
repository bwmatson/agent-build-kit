# Design

## What is verified

- The repository's `sync` runs in the unit's worktree from the environment preparation that the graph's
  tests, checks and tier 1 steps call (`worktree_fault`). It runs when the inputs' hash differs from the one in
  the worktree's git directory, or none is recorded.
- The worktree check is in the workspace preparation (`prepare_worktree`, `DirtyWorktree`). It lists every
  uncommitted path, untracked files included (`_porcelain`), and runs when a step asks for the tree of an
  existing worktree. The graph turns the error into a hold with the cause `dirty_worktree`, unless the running
  step is an editing step that had recorded its start, which carries on over the leftovers.
- The check is therefore reached by a step *after* the one whose sync wrote the file. In the failing run the
  tests step ran the sync (creating the lock) and the rework step's tree request then held the unit. A step that
  commits after the sync would instead sweep the untracked lock into its commit, because the commit step stages
  everything (`git add -A`). Both are wrong.
- The lock paths are already known to the framework from configuration: `environment.inputs.lock`, which is also
  how `generated_file_patterns` leaves lock files out of a unit's size. Those patterns match by file name; the
  paths here are relative to the worktree root, as the inputs' hash reads them.
- Correction to the brief: the sync itself does not hold anything. The preparation of the worktree record also
  stores the hash taken *before* the sync, so a sync that creates a lock makes the next step's hash differ and
  sync run once more. This is harmless and is left alone.

## The options

**(a) Ignore the lock paths in the dirty check only.** Removes the hold. Alone it is not enough: a tracked lock
the sync rewrote because the unit changed a dependency would be ignored by the check and then either swept into
a commit by luck or lost when a step resets the branch (`reset_to` does a hard reset).

**(b) Make the commit step carry the lock.** Needed for a lock a unit legitimately changed, so that the change
and its lock land together. Alone it is not enough: the hold happens before any commit.

**(c) Run the sync locked or frozen.** Rejected. The framework knows no package manager, so it cannot add a flag
to an argv it does not understand, and a frozen sync fails exactly for the unit that changed a dependency, which
the pipeline would then report as the unit's own failure.

**Chosen: (a) plus the part of (b) that decides what is committed.**

## The rules

1. **Ownership.** A path in the repository's `environment.inputs.lock` is pipeline-owned in that repository's
   worktrees. The dirty check does not report it whether untracked or modified, and nothing discards it. The
   leftovers note given to an agent resuming over leftovers does not list it either. Any other path is checked
   exactly as before, and the hold still lists only those.
2. **Tracked lock, dependencies changed.** When the unit changed a dependency input against the point its branch
   left the base (the comparison the environment preparation already makes, by git object ids), the commit step
   stages the modified lock with the change, so the lock the unit's dependencies need is in the unit's diff.
3. **Tracked lock, dependencies unchanged.** A rewrite the sync made without the unit changing a dependency (a
   tool upgrade that reformats the lock) is noise in an unrelated change. The commit step restores that file to
   the branch's version instead of staging it. This is the only place a pipeline-owned file is overwritten, and it
   is the pipeline's own output.
4. **Untracked lock.** A lock the branch does not track is never staged. This follows the repository's own
   choice: a repository that tracks its lock has it in the branch; one that does not, such as the scratch fixture,
   gets none from a unit. Unit size already leaves lock files out through `limits.generated_files`, so the commit
   gate is not asked to judge it. The file stays in the worktree, which the environment needs, and is ignored by
   rule 1. A repository that wants its first lock tracked adds it by hand.
5. **No environment section,** no paths: nothing is ignored and the commit step stages as before.

## Where it lives

The check and commit step take the lock paths as an argument resolved from the repository's configuration where
they are wired, and the path list is the only coupling. Matching is by the configured paths, normalised relative
to the worktree root, never by a name in the code.

## Risks

- A step that moves the branch with a tree that has an unstaged tracked lock (a rebase rather than a hard reset)
  would refuse. The implementation restores tracked locks that the unit did not change before such a move, as
  rule 3 does at the commit step, and a test covers the restack.
- A lock listed in `inputs.lock` that a person also edits by hand in the worktree is treated as the pipeline's.
  That is the meaning of listing it there.
