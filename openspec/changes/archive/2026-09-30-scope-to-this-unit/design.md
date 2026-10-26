# Design

## The builder can see everything and is told nothing

A build run is given the change directory and its own group numbers, and it reads
`tasks.md` in full — which it should, since a group's tasks reference the change's design
and its neighbours. What it is never told is that the groups after its own belong to
other units. An agent that has just written the code a later group depends on, and can
see that group's tasks, has every reason to finish the job.

So the fix is not to hide the plan. Hiding it would cost the builder the context that
makes a group coherent, and would not stop it inferring the next step from the code. The
fix is to name the boundary: these groups are yours, those belong to the units after you,
and leaving them alone is part of the task rather than an oversight.

That instruction has to carry a reason, or it reads as arbitrary and a capable agent will
work around it. The reason is concrete: each unit is one pull request a person reads, and
work pulled forward makes that pull request bigger and the plan's record of what is left
wrong.

## The reviewer is half the problem

The review prompt tells the reviewer to find everything in one pass and to sweep the
domain for every instance of a kind it finds. Both are right, and neither has any notion
of a unit boundary — so a reviewer looking at a unit that touches a module a later group
will finish can legitimately require that finishing, and the builder then does it with a
review round behind it.

The reviewer keeps every power over this unit's own work. What changes is that a finding
whose fix belongs to a later group is reported as belonging there: named, so it is not
lost, and not blocking, so it does not pull the work forward. That is the same shape as
the optional/required split the prompt already makes, with the boundary as the criterion
rather than the size of the fix.

## Satisfied is judged on the branch, not on the report

An agent saying "this is already done" cannot be the test. It is the same sentence a lazy
run would produce, and the runner's whole reason for counting commits on the branch rather
than trusting the commit step is that a report is not evidence.

The objective test is available: the unit added no commits of its own, and the repository's
tier-1 checks pass at the tip. Nothing to add, and what is there is sound — that is
"satisfied", and it is exactly the state where there is no diff for a reviewer to read. If
the checks fail, the unit is not satisfied; it is a unit with nothing committed and a red
tip, which is a failure and should stay one.

## What becomes of a satisfied unit

It has no diff, so it has nothing to review and nothing to merge. It ends in a state that
says the work arrived by another route, its groups are ticked so the change's record is
complete, and its dependents stop waiting for it. It never gets a pull request, and it
never appears in the failed list.

A unit that had commits from earlier steps and then found the *rest* of its work already
present is not this case: it has a diff, so it goes to review as usual.

## Closing the pull request, deterministically

A unit can become satisfied after its pull request is already open — a rework that finds the work
has landed elsewhere in the meantime. Leaving it open is the worst option: no diff to review, no
future, and it sits in the queue a person works from.

So it is closed, and the reason is posted first, so the explanation is never missing. Both halves
are mechanical:

- **The judgement** already is — no commits of its own, tier-1 checks green — so there is nothing
  for a model to decide.
- **The text** is composed the way the pull request body already is, in `pr_body`: which groups
  the unit covered, that they were implemented elsewhere, where the work landed when the graph can
  name it, and that the change's tasks are ticked. None of it varies with the code, so asking an
  agent to write it would buy variation where none is wanted.

Worth stating in the spec rather than leaving to an implementer: the surrounding code is full of
agent calls, and the habit is catching.

The forge gains the capability, because it has none — it can open a pull request, post a status
and answer a review comment, but not close one. That keeps the host-specific part behind the
interface, as with everything else it does.

A close that fails is recorded and does not unmake the unit's state: the unit is satisfied on the
evidence, and a stale pull request is a nuisance rather than a reason to revisit the judgement.

## Why not simply plan smaller

A smaller plan would not have prevented this. The plan *was* small — 520 lines for the
unit that landed 5032 — and it was the build that exceeded it, which the planning ceiling
cannot see. Scope has to be enforced where the work happens, which is the prompt, and
noticed where the evidence is, which is the branch.
