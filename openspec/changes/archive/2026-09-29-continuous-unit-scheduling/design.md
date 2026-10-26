# Design

## Where readiness is decided, and where it should be

`ready_units` already answers "what may start right now" from a graph plus two
caps, and it answers correctly. Nothing about it changes. The problem is that
the tick asks it once, hands the answer to a pool, and waits for all of it:

```
ready = ready_units(...)        # asked once
with ThreadPoolExecutor(max_workers=len(ready)) as pool:
    list(pool.map(build, ready))   # and every answer discarded
```

The pool is sized to the batch, so it cannot grow; the batch is a list, so it
cannot be extended; and the results are thrown away.

The shape it wants is a scheduling loop: submit, wait for the *first*
completion, recompute, submit again. `as_completed` gives that directly. The
pool is sized to the concurrency cap instead of the first batch, and the set of
units already submitted in this pass is tracked so recomputing cannot hand the
same unit out twice — `ready_units` filters on the stored state, which a
just-submitted unit only reaches once its build sets it.

## Why re-asking is safe

Every guard a unit passes today it still passes, because the same functions are
called: the dependency rules, the depth cap, and the concurrency cap, which is
derived from how many units the store says are running. `_build` re-reads the
unit's state under its branch lock and skips anything another tick has taken —
that guard exists because ticks already overlap deliberately, and it is what
makes a second look inside one tick no more dangerous than the second tick the
timer would have started anyway.

Termination is not in question either: nothing in a pass creates units, so each
round either consumes a completion or finds nothing to add, and both are finite.

## What a round does besides recompute

Refreshing from the code host first, on each round, rather than only at the top
of the pass. Two reasons, one of them the whole point of the change:

- A cross-repo dependency must have **merged** before its dependent may start.
  If that merge happens during a long pass, only a refresh reveals it, and
  without one the dependent waits for the next pass — the same idling this
  change exists to remove.
- A pass that now lasts hours would otherwise leave review feedback unseen for
  hours. Polling is cheap next to a build, and already tolerates failure by
  skipping rather than stopping.

Planning stays once per pass. It costs an agent call, and no unit appears
mid-pass for it to find.

## Stopping, and `--only`

`_build` reporting that the tick should stop — a usage window spent, say — must
end scheduling rather than be discarded. In-flight builds are left to finish,
because each checks the guard itself before its own agent runs and killing one
mid-build would leave work uncommitted; what stops is submission of anything
new. `--only` is applied to every round, not just the first, so narrowing a
pass to one unit cannot be widened by a completion.

## Landing beside other work

This rewrites the tick's build path, and other changes in flight edit the same
module. That is ordinary: the unit that merges second is restacked and its
conflict resolved, which is the mechanism working, not a reason to serialize
the plan. Nothing here depends on another change's behaviour.
