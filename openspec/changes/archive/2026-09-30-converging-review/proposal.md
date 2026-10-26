# Proposal

## Why

Two finished units were thrown away this week by the round cap, and neither was
churn: each round raised something real.

- One was enumerating the ways a pattern list can be bypassed. Round 1 found
  global options, round 2 found quoted refspecs and a code host's merge API,
  round 3 found configuration through the environment and a direct reference
  write. Every finding was correct, and the list had not converged, because the
  set of spellings for an effect is unbounded. The right answer was to re-scope
  the work — which is what happened, by hand, after the cap discarded it.
- The other was handed a genuine race in round 3: a child unit holds its branch
  lock before it writes `RUNNING`, so the merge handler does not count it as in
  flight and deletes the branch it is building on. The reviewer traced both
  consequences and named the fix. The builder never got a turn.

The review prompt is not the problem. It already says to find everything in one
pass, to sweep the domain for every instance of a kind, to say what done looks
like, and to separate required from optional. The reviewer sees the earlier
rounds and the builder's answers, and is told not to re-open settled points.

What is missing is **outcomes**. The loop can say "approved" or "changes
needed", and it can say "a human is needed" only for something the builder's
environment refuses. So a reviewer holding one non-blocking observation must
block on it; a reviewer discovering that a problem is a class rather than an
instance has no way to say so; and a reviewer in the last round does not know it
is the last, or that the entire unit will be discarded when it ends.

That last point is the expensive one. Exhausting the cap does not fail the
round — it abandons every commit the unit made, unpushed, and the next attempt
starts over.

## What Changes

- **The reviewer is told the budget and the stake**: which round this is, how
  many remain, and that when they run out the work is not merged and not kept.
  A reviewer that knows the cost can weigh a residual nit against losing a
  correct implementation.
- **A finding can be deferred instead of blocking.** A verdict may approve while
  recording what should still be done, which is written where the next unit of
  that change will see it. Correctness, a test that does not test what it
  claims, and anything the pipeline's own policy forbids are never deferrable.
- **A class that cannot be enumerated escalates.** When a round finds another
  instance of a kind an earlier round already raised, and the kind is open-ended
  rather than a list that can be finished, the reviewer says so and the unit goes
  to a person with that framing — a re-scope, not another round.
- **A repeated disagreement escalates too.** When the builder declines a point
  with a reason and the reviewer still wants it, the second exchange on that
  point goes to a person instead of a third.
- **The last round ends in a person's hands, not in a discard.** When the budget
  is spent with blocking work outstanding, the unit is held for review with its
  branch preserved and pushed, so a human sees the work and the open points
  rather than an abandoned worktree and a log line.

## Impact

- **agent-build-kit** only: the review loop, its prompts and the verdict it
  parses.
- Fewer rounds per unit, and a unit that cannot converge stops costing rebuilds.
- The cap has already gone back to 3, on the strength of the changes that keep units small —
  the measured mean is 0.9 rounds, and the only unit ever to need four was ten times its
  estimated size. So this change is no longer what permits the revert; it is what makes the
  revert safe, by ending a spent budget in a person's hands instead of a discard.
