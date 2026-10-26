# Design

## Where it goes

`ready_units` is already the one place that answers "what may start right now",
and it already applies two caps there: it counts running units to work out free
slots, and it drops any unit whose chain is deeper than the depth cap. The open
pull request ceiling is a third condition of the same kind, in the same function,
read from the same configuration.

Putting it anywhere else would split the answer in two — one caller deciding a unit
is ready and another refusing to build it — which is how a unit ends up in a state
nobody expected.

## Counting what a person sees

The count is the pull requests the pipeline has open and unmerged, whatever their
unit's state. Not "awaiting review" specifically: a pull request being reworked is
still in the list, still costs a rebase when something merges beneath it, and still
has to be read eventually. The number in the configuration should mean the number
in the list, or an operator setting it to five will find eight.

## A gate on starting, never on finishing

This bounds how much new work begins. It must not bound work already begun:

- A unit that has built and been approved **opens its pull request**, even at the
  ceiling. Refusing would leave finished, reviewed work unpushed in a worktree —
  the failure mode that already cost this workspace a rebuild, and a far worse
  outcome than a queue of six against a ceiling of five.
- A rework, a restack, a review round and a push **all continue** at the ceiling.
  None adds a pull request, and all of them are how the queue gets shorter.
  Freezing them would deadlock the thing: the queue stays full precisely because
  nothing is allowed to finish draining it.

So the count can sit one or two over the ceiling while in-flight units land, and
that is correct rather than a bug to paper over. What the ceiling guarantees is
that nothing *new* is started while the queue is long.

## Across the workspace, though the cost is repo-local

The cost this bounds is repo-local: a merge only invalidates branches sharing its
trunk, so five open pull requests in one repository conflict with each other in a way
that five spread across three repositories do not. Counted strictly, the precise
ceiling would therefore be per repository.

It is counted across the workspace anyway, for two reasons. The concurrency cap and
the usage windows are already workspace-wide, so a per-repo ceiling here would be the
only limit of its kind and the one an operator has to reason about differently. And
the pipeline's other cost — the usage window every rework spends from — *is* shared
across repositories, so a total is the number that bounds the bill.

This is a deliberate approximation, and the sharper alternative is worth knowing
about: if a workspace finds one repository starving the others, counting per
repository is the change to make, and nothing here assumes otherwise.

## Which unit gets a free slot

`ready_units` returns the first units in the store that pass its conditions, up to
the number of free slots. Store order is the order changes were planned in, so
which unit runs next has nothing to do with what it is.

The units that pass are instead put in three classes, and the slots filled from
them in order:

1. **It has an open pull request.** It is `planned` because a review, a failing
   check or a conflict sent it back. A person is waiting on it, other units may be
   stacked on it, and it is the work that shortens the queue.
2. **It is resuming.** No pull request yet, but it has been started and carries the
   step to resume at — paused for the usage window, or held because its base moved.
   Agent time is already spent on it, and its branch ages like any other.
3. **It has never run.**

Within a class the order is the store's, as it is now, so nothing changes for a
workspace whose ready units are all of one kind.

Both facts are already on the stored unit — its pull request number and the step it
resumes from — so the ordering reads the store and asks the forge nothing.

The classes order units the other conditions have passed. They are not a way round
them: a resuming unit with no pull request still waits at the ceiling, because
finishing it adds one, and a unit waiting on a dependency or past the depth cap is
not ready in any class.

Considered and left out: ordering inside the first class by how long a pull request
has waited, or by whether others are stacked on it. Either may be worth having; with
three slots and a ceiling of five, store order within the class is rarely wrong for
long, and a rule that needs the forge's timestamps is a different size of change.

## Saying so

`nothing ready to build` is what a tick logs today when the caps hold everything
back, and it reads as an idle pipeline. At this ceiling it should say the queue is
full and give the count, because the operator's next action differs: with a spent
usage window you wait, and with a full queue the way to make the pipeline productive
again is to merge or close something.

That framing matters for the reason the ceiling exists. A full queue is not the
pipeline resting; it is the pipeline declining to buy more rework.

The same line belongs in `abk status`, which is where a person looks to decide what
to do next.

## What this is not

It is not a limit on units per change, nor a hint to the planner. The planner keeps
planning whole changes; units keep waiting in `planned` as they already do when the
concurrency cap is reached. Nothing about how work is divided changes — only when it
starts.
