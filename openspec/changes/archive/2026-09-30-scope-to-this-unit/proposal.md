# Proposal

## Why

A change is split into task groups, and the planner packs consecutive groups into units
so each is one reviewable pull request. Nothing tells the builder to stay inside its own
groups, and it can see the whole of `tasks.md` — so a capable agent that notices the next
group is adjacent work simply does it.

That is what happened. One unit implemented its own group *and* the next one, landing 54
files and 5032 changed lines against an estimate of 520. The unit behind it then ran,
found its work already present, committed nothing, and was failed — as was a second unit
in another change, for the same reason. Three consequences, all bad:

- **Pull requests get big.** The one that worked ahead needed four review rounds, a third
  of a day's agent time, and was well past any reviewable size — which is exactly what
  the size ceiling is meant to prevent, and a ceiling on planning cannot catch, because
  the plan was reasonable and the build exceeded it.
- **The plan stops describing reality.** Groups are ticked as units pass review, so work
  done early is attributed to whichever unit happened to do it, and the change's own
  record of what remains becomes wrong.
- **The unit behind it fails.** "Produced no commits" is the same message a broken run
  gets, so a satisfied unit lands in the list a person is asked to look at.

The reviewer contributes to this too. It is told to find everything in one pass and to
sweep the domain, with no notion that some of what it finds belongs to a later unit — so
asking for it pushes the builder into working ahead, with a review round's authority
behind it.

## What Changes

- **Both prompts are told the boundary.** The builder is given its own groups *and* the
  groups the later units of the change will cover, with the instruction to implement only
  its own — not to reach forward even when the next group is one edit away.
- **The reviewer is told the same.** A change it wants that belongs to a later group is
  noted as belonging there, not required of this unit. It keeps every power it has over
  this unit's own work.
- **A unit with nothing left to do is satisfied, not failed.** When a step writes nothing
  because its groups are already implemented, the unit ends in a state saying so, its
  groups are ticked, and nothing lands in the failed list. Judged on the branch and the
  checks, never on the agent's say-so.
- **An open pull request for a satisfied unit is closed, with the reason on it.** A unit can
  reach this state after its pull request exists, and an open pull request with no diff and no
  future misleads whoever reads the queue. The reason is composed by the pipeline and posted
  before the close, so the explanation is never missing — and no model is asked to write it,
  because nothing on this path needs judgement.

## Impact

- **agent-build-kit**: the build and review prompts, and how an empty step is classified.
- Pull requests closer to the size the plan intended, and a `tasks.md` that says what was
  actually done by whom.
- Where working ahead still happens, it costs a recorded satisfied unit instead of a
  failure and a rebuild.
