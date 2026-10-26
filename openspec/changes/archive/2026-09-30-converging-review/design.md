# Design

## What the loop can say today

`review_once` runs up to `max_review_rounds` rounds. Each round commits the
work, asks the reviewer, and parses a verdict of `{approved, feedback,
needs_human}`. Approval records the reviewed commit as the only one that may be
pushed. `needs_human` holds the unit for a person — wired, but written for one
narrow case: something the builder's own environment refuses to change.
Otherwise the feedback is stored, a rework runs, and the next round begins. On
the last round the loop breaks: the unit fails, its commits unpushed.

The reviewer is not short of instruction. It is told to find everything in one
pass, to sweep every instance of a kind it finds, to state what done looks like,
to separate required from optional, and — from round two on — to check the
earlier points, not to re-open settled ones, and to raise new problems only in
what the reworks changed or what was genuinely missed, with a reason why it was
not visible earlier.

Both units that hit the cap satisfied that instruction. The gap is not in what
the reviewer is asked to look for; it is that it has nowhere to put an answer
other than "not yet".

## Three outcomes the verdict needs

**Deferral.** A finding worth recording but not worth another round — a name
that could be better, an optional refactor, a doc line — currently blocks or is
dropped. A verdict that can approve *and* record the item keeps it without
spending a round. Where the item goes matters: onto the change, where the next
unit's builder and the person reviewing the PR both see it, not into a log.

Never deferrable, and the prompt must say so: behaviour that is wrong, a test
whose fakes let it pass regardless, a missing test the task asked for, anything
the command policy or the push gate forbids. Deferral is for work that can wait,
not for work that is inconvenient.

**Class escalation.** Some findings are instances of an unbounded set. A list of
forbidden command spellings is the clearest case: each round finds another
legitimate instance, and the list cannot be finished because the effect has more
spellings than a list has entries. The signal is available to the reviewer — it
raised the earlier instance itself and can see it in the rounds it is given —
and the right response is not another instance but "this cannot be enumerated;
the approach needs changing". That is a human's decision, so it escalates.

**Disagreement escalation.** The builder may decline a point with a reason, and
the reviewer is already told to check whether the reason holds. When it does not
hold in the reviewer's judgement and the builder has already refused once, a
third exchange of prose is the least likely thing to settle it. Escalate after
the second.

## Telling the reviewer what it is spending

The round note says "This is round N of the loop" and stops there. It should say
how many rounds remain and what happens at the end: the work is not merged and
not kept, and the next attempt starts from nothing.

This is not an invitation to approve loose work. It is the information needed to
weigh one residual observation against discarding a correct implementation — the
judgement the prompt already asks for ("hold it to the bar of work you would
approve, not perfection") but without the cost in view.

## The last round should not be a discard

Today the cap ends the unit: `failed`, commits unpushed, branch local. A person
who wants to see what happened reads a service log and finds a worktree.

`held` already means "a person is driving this one", and it is the honest state
for a unit whose work exists and whose open points are written down. So when the
budget is spent with blocking work outstanding: push the branch, open or update
its pull request with the outstanding points in the body, and hold the unit. The
approved-commit rule is not weakened — nothing is merged, and the pipeline still
pushes only what review approved; what changes is that a person inherits a
branch and a list instead of an abandoned directory.

## Why not simply raise the cap

Because the failures were not short of rounds; they were short of ways to
finish. One needed a different approach, the other needed one more turn — and a
cap high enough to guarantee the second would pay for many pointless rounds of
the first. The installation raised the cap to 5 as a stopgap while this is built,
and should put it back to 3 afterwards.
