# Design

## Derive what can be derived

The runner already holds both halves of the comparison: `restacked.old_tests` — the tests the
unit had added before the replay — and `self.tests_in(tree)`, the tests present now. The
difference between those two sets is exactly where a silent drop can hide, and everything
outside it is a test that survived the replay untouched.

So the accounting can be narrowed to three cases, computed rather than requested:

- **Present and unchanged by the replay.** No decision needed; it was kept, and the tree says
  so. The agent is not asked about it.
- **Missing from the tree.** A decision is required, and the existing rule stands: a
  retirement needs a reason naming what in the predecessor made the test invalid.
- **Present but changed by the replay.** A decision is required, because a test that still
  exists can have been quietly weakened — an assertion relaxed, a case deleted from a table —
  and that is the same failure mode as a drop, only harder to see.

That last case is why "present and unchanged" has to mean unchanged in content, not merely
present by name. The comparison is against the old ref, which the step already keeps.

## Ask again before failing

`check_test_decisions` returns a list of precise, human-readable problems: a name with no
decision, a retirement without a reason, a `keep` that is not in the tree. Those strings are
already the right prompt.

So an incomplete accounting becomes a bounded second ask — the problems, the names still
outstanding, and nothing else — followed by the same check. A unit fails only when the agent
cannot account for its own tests after being told exactly what is missing, and then the
problems are recorded on the unit rather than left in a tick's log.

The adapt commit has already landed by the time the check runs, so this costs one short
prompt rather than a re-port: the code is in place and only the accounting is outstanding.

## The pattern this is the third instance of

Three failures this week had the same shape: work that was done, a mechanical gap in how it
was reported, and a unit discarded rather than asked. A commit rejected by a formatter that
had already fixed the file. A review that ran out of rounds with the reviewer's fix named.
And this, an accounting missing one line the checker could point at.

The habit worth breaking is failing where the pipeline could ask again — and the discipline
that keeps that safe is the one used each time: bound the asks, keep the guarantee, and record
the reason when it does fail.

## What is deliberately unchanged

The step still runs on every restack onto a changed predecessor. It still requires an
explanation for anything that vanished. `keep` still has to correspond to reality. And the
number of attempts is small: an agent that cannot account for its tests after being told what
is missing is telling us something about the port, not about the bookkeeping.
