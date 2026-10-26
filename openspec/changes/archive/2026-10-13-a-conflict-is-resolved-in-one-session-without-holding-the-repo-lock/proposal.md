# Proposal

## Why

Two things make a conflicted restack slower and dearer than it has to be, and both were measured on this installation's ledger and run
logs before this change was written (537 agent rows over six days, 164 unit logs; 45 `base_changed` events over 196 units, 11 of the
pre-push base checks needed resolution).

**Two agent runs for one conflict.** The conflict resolver edits only the conflicted files, in its own scoped session, with no memory
of the unit's work. When its result fails the pipeline's checks the rebase is aborted and the `adapt` step starts again: the branch is
reset to the new base, the old work is kept under a ref, and the rework model ports it, in a new session that has seen none of what the
resolver read. The cheap resolution is attempted, thrown away, and the dear one starts from nothing.

**The repo's turn is held for the whole resolver.** Every worktree add and push in a repository takes `repo-<repo>.lock`, because
git's own locks in the shared `.git` fail instead of waiting. The stack-move handler wraps the entire move in that turn, so a conflicted
restack keeps every other unit of the repository waiting at its worktree add or push for as long as the agent runs, minutes. Several
units hitting one hot file at once make a convoy. The agent does not need the lock: between `git rebase` stopping and
`git rebase --continue` it edits files in one unit's own worktree and runs no git command that writes shared state. A unit's own
restack inside a run takes no turn at all today, which leaves its rebase finish (a branch ref and the rerere cache write) unserialized
against another unit's worktree add or push.

## What Changes

- **One session, smallest change first.** The restack's agent step starts in the run that finds the conflict and states a ladder in
  its prompt. Rung a changes only the conflicting hunks and the files that conflict. When the checks fail (a marker left, the unit's own
  distinctive tokens missing, one of the unit's own tests gone) rung b widens to the unit's other files that depend on the conflict.
  Rung c, only when that cannot work, ports the old work onto the new base: the existing `adapt` behaviour, reset, ref, keep, adapt or
  retire for each uncertain test, the accounting check and its bounded asks. Each rung is checked by the existing guards. The calls
  are resumed calls of the unit's build session, so rung c starts with what rungs a and b learned.
- **Replayed resolutions keep their rules.** A replayed resolution is still staged deliberately; the agent is told which paths carry
  one; planting a conflict marker in a replayed file still rejects it and forgets the cached entry, and the rung then counts as failed.
- **A hold only when the last rung fails.** The once-per-run loop back to the restack stays for a base that keeps moving.
- **Recorded as the `restack` node**, one ledger row per agent call of the step (the node the `every-agent-call-is-recorded` change
  adds).
- **The turn per phase.** The repo's turn is taken for the fetch, the base check and the rebase up to its stop; not at all while the
  agent edits; again for `git rebase --continue` or the abort, the branch ref update, the rerere cache write, and the push with its lease.
  The stack-move handler and a unit's own restack in a run follow the same rule.
- **A branch that moved during the agent run** is detected under the turn before the rebase continues, retried once from the start of
  the restack, then held.
- **A unit with no worktree** is moved in a temporary detached worktree, the branch ref moved by compare-and-swap under the turn, the
  temporary tree removed under the turn. The operator's checkout is never switched, and a branch checked out in another worktree no
  longer makes git refuse the rebase.

Not included: a restack taking no build slot or starting as soon as it is seen (a separate change), running fewer tests after a move,
and the changelog's union merge.

## Impact

- agent-build-kit: `pipeline/restack.py` (`move_branch_onto` split into phases, the ladder, the temporary worktree, the prompts),
  `pipeline/wiring.py` (`build_restack_onto`, the turn it is given), `graph/nodes.py` (`prepare`, the `adapt` node continuing the
  session, `SESSION_ROLES`), `pipeline/events.py` (`restack`), `cli/pipeline.py` (`build_stack_moves`), `docs/architecture.md`,
  `docs/unit-graph.md`, `docs/agent-runtimes.md`, `docs/configuration.md`, the `abk-config` skill text, the changelog.
- Specs: `restack-conflicts` (adds requirements, modifies one), `restack-adapt` (adds one), `session-reuse` (modifies one),
  `unit-scheduling` (adds requirements).
- Depends on `every-agent-call-is-recorded` group 1 for the shared recording helper and the `restack` node.
