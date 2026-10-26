# Design

## What counts as the node's own

Two things already in the thread state are not enough. The pending node (`snapshot.next`) is the same
for a node killed mid-run and for one reached but never started, for example waiting out a usage
window; and the session id is written only on the agent's init event, a few seconds in, and not at
all by a runtime that reports no session. So a new marker is added.

`UnitRun.running_node` (a node name or empty). Each agent node writes its own name into the thread
state with the same state update the session id uses, before its agent starts and before it can
write a file, and clears it with the session id when it completes. A kill leaves it behind.

A dirty tree is the node's own when `running_node` names the node being re-run and no live process
holds the unit's branch lock (the check `resumable_units` already makes). Every other dirty tree is
foreign: no marker (the node was reached but never started, a node that runs no agent, a tree edited
between nodes), a marker naming another node, or a lock held by a live run.

The session id keeps its one job, deciding resume versus new session; it is not used to decide
whether the tree is the node's own.

A person who edits the tree during the same window in which a run was killed cannot be told from the
agent's own leftovers. The edit is then handed to the agent as leftovers and review reads the result;
the design accepts that.

## The guard

`prepare_worktree(..., allow_dirty=False)`. The agent nodes pass `allow_dirty` when re-running
after a kill; the new-worktree path, the restack, `remove_worktree` and every other caller keep
the refusal. With the flag the function returns the path and the node learns the dirty paths from
`git status --porcelain` (including untracked files), capped at a sensible count.

## Resumed or new session

The node already decides this (by the session id): it continues the recorded session with the interruption prompt, and
falls back to a new session when the runtime cannot resume it. The leftover note is added only on
the new-session path, from the same packaged prompt part for every agent node: the paths, one
sentence that they are uncommitted work from an interrupted run of this step, and the instruction
to review them with the diff, keep what is right and finish. The note is part of the prompt only
for that run.

## Parking

A dirty tree that is not the node's own raises a distinct error from the worktree setup instead of
the failure path: the step wrapper records the unit as held with the cause `dirty_worktree`, the
changed paths and the sentence that a person should commit or remove them, and the thread stays at
the node. `abk requeue` after the tree is cleaned resumes it. The tick's status lists such units
with their reason.

## Commit

Unchanged: the node's commit stages everything. Leftovers become part of the node's commit; for a
tests node they are test files, for an implement node code, so the commit order the push gate
checks is the one the node was already producing.

## Visibility

`node <name>: resuming over uncommitted work in <n> file(s), session resumed|new` in the unit log;
a counter `abk.leftovers.resumed{node,session}`; the hold text for a parked unit.

## Documents and tests

Correct the unit-graph document's claim about carrying on from the tree, and remove the stale
mention of the old reclaim in a test comment. The tests use a real git repository and the real
worktree setup, driven by the existing killed-run helpers.

## Out of scope

Which units a tick starts (`one-round-per-refresh`), and the approved-commit gate.
