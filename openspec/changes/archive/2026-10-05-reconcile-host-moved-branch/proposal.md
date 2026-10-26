# Proposal

## Why

A unit remembers the commit it last pushed (`pushed`) and leases its next push
against it. When the host's copy of the branch is somewhere else, `adopt_host_head`
replays the commits made here since the last push onto the host's head, and
raises `StaleRemote` if they do not apply.

That failed for a unit whose branch a person rewrote to drop a commit-message
trailer and force-pushed. The content was unchanged, but:

- the unit's local branch had meanwhile been restacked onto a newer trunk, so
  `last_pushed` was no longer an ancestor of it, and
  `git rebase --onto <host> <last_pushed>` replayed the wrong range;
- the recorded `pushed` still named the old tip, so the push lease could not
  match the host.

Review had approved the local head and the host's copy held the same change.
The unit failed anyway, and the way out was to edit the store by hand. The store
should not have to be told what the remote already says.

## What Changes

- **Reconcile by content before replaying.** When the host's head differs from
  the recorded `pushed`, compare what each carries against the unit's base. If
  the host's branch has the same change as the local head (the same changed
  lines, as the approval carry-over already compares them), the host moved the
  branch without changing the work: record the host's head as the last push and
  continue, pushing the approved head with a lease on it.
- **Replay only what is ours.** When the contents differ, the commits to replay
  are the ones the local branch has that the host's does not (found by patch,
  not by ancestry of `last_pushed`), so a restacked local branch is not
  mistaken for new work.
- **Only an unexplained difference fails.** A host head that carries changes the
  local branch lacks, and local work that does not apply onto it, still raise
  `StaleRemote` and are left for a person, as now.
- **The log says which it was**: same work adopted, local work replayed, or
  refused.
