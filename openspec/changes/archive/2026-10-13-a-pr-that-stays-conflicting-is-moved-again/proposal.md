# Proposal

## Why

A unit in review whose base is the trunk goes stale whenever the trunk moves, and nothing moves it again after its first conflict.

- **The poller reacts to a change of answer, not to a state.** A conflict rework starts when the host's answer becomes `false` and the
  recorded one was not (`pipeline/pr_poller.py`, the `after["mergeable"] is False and before.get("mergeable") is not False` test), or at
  first sight of a pull request (`_dispatch_terminal`).
- **The recorded answer outlives the host's.** The host answers "undetermined" after every push and every base move, and `poll` keeps the
  last definite answer through it, so that the conflict a rework resolves does not read as new. The price is that a pull request that
  conflicted once stays recorded `mergeable: false` through the push that fixed it and through the next base move, and the second
  conflict is never a transition.
- **The restack flow does not cover it.** A restack moves the dependents of a parent that leaves review. A unit based on the trunk has no
  parent, so a trunk merge moves nothing for it.
- **Nothing else reads the answer.** `unmergeable()` feeds only the `cannot be merged` mark on the status line.

The case this was drawn from: one unit was reworked at its first conflict (the agent found the base already merged and changed
nothing), reworked again, moved cleanly onto the trunk and pushed; the trunk then merged three more pull requests and the pull request
became conflicting again. Its stored answer was `false` from the first conflict, so nothing picked it up.

## What changes

- **A fresh definite "conflicting" is a conflict, not a transition.** The snapshot records when the last definite answer was read. A
  unit in review whose pull request the host reports as conflicting is acted on when that answer was read after the unit's own latest
  push; an undetermined answer after a push, and a definite one read before it, are not.
- **Memory that is not the stored answer.** The unit records the head it last pushed and the base tip at each conflict attempt, how many
  attempts were made at that base tip, and when. The same head and base tip is never dispatched twice; a new head or a new base tip is a
  new event.
- **Restack first, rework second.** For a unit whose base is the trunk, the first attempt at a persistent conflict is the existing stack
  move (`move_branch_onto` with the scoped resolver and rerere); a conflict it cannot settle, a second attempt at the same base tip, and a
  unit that is not trunk-based go to the existing conflict rework. The transition and first-sight paths still send a conflict rework.
- **A stated stop.** At most `limits.max_review_rounds` attempts per base tip; an attempt that changed nothing and left the conflict
  standing ends at once. Either holds the unit with a reason a person can read.
- **A rework that changes nothing resolves nothing.** Only the host's definite "mergeable" or a changed head followed by one ends a
  conflict.
- **Said in the status.** `conflicts with main since 14:50 UTC; moved 2 times` and what the unit is waiting for.

## Impact

- Capabilities: `pr-polling` (the answer's time, a conflict state rather than a transition, the status line) and `restack-conflicts`
  (the stack move as the first answer to a trunk conflict, the bound).
- Code: `pipeline/pr_poller.py` (the snapshot, one new dispatch), `pipeline/events.py` (a conflict handler beside `on_rework`),
  `pipeline/unit_store.py` (four fields), `cli/pipeline.py` (`cmd_status`, the handler's wiring), `config.py` (none: reuses
  `max_review_rounds`).
- Behaviour that stays: the transition and first-sight dispatches, the `agent-rework` label, `unmergeable()`'s meaning, the rework run.
- Sibling pending changes: related, none required (see design.md).
