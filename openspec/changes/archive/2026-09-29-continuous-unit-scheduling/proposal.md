# Proposal

## Why

A tick works out what is ready once, builds that batch in parallel, and waits
for all of it. So the batch can only shrink, never grow, and a slot that frees
up mid-pass stays empty until the whole pass returns.

That costs real time in two ordinary situations:

- **A chain cannot advance past its first link.** A same-repo dependency may be
  open — a unit stacks on its parent's branch rather than waiting for a merge —
  so the moment a parent reaches review its child is ready. But the pass it
  would join has already fixed its batch, so the child waits for every other
  unit in that batch, however unrelated. A four-unit chain beside one slow unit
  in another repo spends hours with three of four slots idle.
- **A unit re-queued after a fix waits for the next pass.** A unit set back to
  `planned` — the documented recovery once the cause of a failure is fixed —
  cannot be picked up by the pass in flight, even with slots free.

There is a latent bug in the same place. `_build` is documented to return False
when the tick should stop entirely, and the concurrent path discards every
return value. Nothing depends on it today because nothing is submitted after
the batch starts; the moment scheduling continues, a pause mid-pass has to stop
the next submission rather than being thrown away.

## What Changes

- **A pass keeps scheduling while it runs.** As each unit finishes, the tick
  re-reads the store, works out what is ready now, and fills the free slots,
  until nothing is in flight and nothing is ready. The concurrency cap, the
  stack depth cap and the dependency rules are unchanged and are re-applied on
  every round — this changes *when* readiness is evaluated, not what it means.
- **A pass notices merges while it runs.** Each scheduling round refreshes what
  the code host says first, so a dependency that merged mid-pass can release a
  cross-repo unit, and review feedback is not left unseen for the length of the
  longest build. Planning stays once per pass: it costs an agent call, and
  nothing in a pass creates new units.
- **Stopping is honoured.** A build that reports the tick should stop ends
  scheduling instead of having its answer discarded, and `--only` narrows every
  round rather than only the first.

## Impact

- **agent-build-kit** only, in the tick's build path.
- A pass can now run much longer, because it may build a whole chain rather
  than one link. That is the point, but it makes the pass — not the unit — the
  thing to watch, and `abk status` is what reports across passes.
