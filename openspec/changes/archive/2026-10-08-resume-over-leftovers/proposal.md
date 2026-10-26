# Proposal

## Why

A tick stopped while a unit's rework agent was editing. The next tick started the rework at once
and the unit ended `failed` with `DirtyWorktree`, 51 uncommitted lines sitting in its worktree.

The unit-graph design says a killed node "carries on from the tree as it is", and a resumed agent
is told to re-read its worktree. The code does the opposite. The node asks for its worktree first,
and the worktree setup refuses any existing worktree that has uncommitted changes, so the saved
session is never reached. The old engine committed such leftovers as a work-in-progress commit
before resuming; the graph switch removed that and put nothing in its place. Any kill that leaves
a dirty tree now fails the unit: a stopped service, a killed agent, a rate limit or timeout in
the middle of a run, a power loss. A kill at a clean boundary resumes fine, which is why only one
of two units killed together failed.

## What Changes

- **A node records that its run has started.** Every agent node (tests, implement, fix checks,
  rework, adapt) writes a marker naming itself into the thread state before its agent starts, and
  the node's completion clears it. A kill leaves the marker behind. It does not depend on the
  runtime reporting a session, and it is written before any file can be.
- **A node re-running after a kill is allowed over a dirty tree.** When the marker names the node
  being re-run and no live process holds the unit's branch, the uncommitted changes are taken to be
  that node's own and the worktree guard lets them through. The guard stays for everything else.
- **A resumed session is told nothing extra.** When the node continues its recorded session, the
  session already holds the edits; it is given the existing interruption prompt and nothing more.
- **A new session is handed the leftovers.** When the node starts a fresh session over a dirty
  tree (none was recorded, or the recorded one could not be resumed), its prompt names the
  changed paths and says they are uncommitted work from an interrupted run of this same step, to
  review with the diff, keep what is right and finish the step; they are not discarded.
- **Anything else parks the unit.** A dirty tree with no marker to explain it (a node that was
  reached but never started, a node that does not run an agent, a tree edited between nodes, a unit
  that was never killed) holds the unit with a cause, the file list and the words
  "commit or remove them by hand", instead of failing it. Nothing is ever cleaned automatically.
- **The leftovers are committed by the node's own commit,** not a separate work-in-progress
  commit, so the tests-first order, the red check and the approved-commit gate are unchanged;
  review reads the whole.
- **It is visible:** a log line and a counter when a node resumes over leftovers, saying whether
  the session was resumed or new.
