# Proposal

## Why

When a unit is restacked onto a predecessor that changed, its tests may no longer be valid,
so the adapt step requires the agent to account for **every test the unit added** — `keep`,
`adapt` or `retire`, with a reason for a retirement. `check_test_decisions` then verifies
that accounting, and it is strict for a good reason, stated in its own docstring: *"A test
that silently vanished is the thing this exists to catch: a port can make a conflict
disappear by dropping what it could not carry over."*

The guard is right. What it does when the accounting is merely incomplete is not.

`github-native-stacks/1` ran its adapt step for 97 turns, produced a structured decision for
every test it had added except one, and was failed with `no decision for
\`test_a_failed_restack_keeps_the_review_feedback_already_waiting\``. The adapt commit had
already landed — the code was ported and sound — so the unit was discarded over a missing
line of bookkeeping that the checker had already identified by name.

Two things made that failure likely rather than unlucky:

- **The ask is bigger than it needs to be.** The agent is handed every test the unit added
  and must return a decision for each. Most of those tests are present and untouched by the
  replay, and the runner can see that for itself: it knows the old test names and the tests
  in the tree. Asking an agent to restate what the runner can derive is asking for a
  clerical error over a long list.
- **The check has no way to ask again.** It produces exact, actionable problems — this name
  has no decision, that one is marked keep but is not in the tree — and then fails the unit
  rather than putting them to the agent that was one line from done.

## What Changes

- **Only the uncertain tests need a decision.** A test present in the tree and unchanged by
  the replay counts as kept without being mentioned. What must be accounted for is what is
  missing, or what the replay changed — which is precisely the set where a silent drop could
  hide.
- **An incomplete accounting is asked again, not failed.** The checker's own problems go back
  to the agent, naming what is unaccounted for, bounded by a small number of attempts. Only
  then does the unit fail, with those problems on its record.
- **The guard keeps its teeth.** A test that vanished still has to be explained with a reason
  naming the predecessor's change; a `keep` that is not in the tree is still wrong; and an
  agent that cannot account for a missing test still fails the unit rather than passing.

## Impact

- **agent-build-kit**: what the adapt prompt asks for, and what happens when its answer is
  incomplete.
- Fewer units lost to bookkeeping, and shorter adapt runs, because the list to account for is
  the interesting part rather than everything.
- No change to the anti-silent-drop guarantee, which is the reason the step exists.
