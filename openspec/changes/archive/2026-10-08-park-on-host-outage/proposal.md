# Proposal

## Why

A unit approved and pushed ended `failed` when its pull request could not be opened during a host
incident. The failure cost nothing in the work, but needed a person to requeue, and the requeue
repeated work: a tier 2 unit ran tier 2 again, and a unit with saved feedback went back to rework,
though its work was already pushed. The failed unit also carried no cause: only the tick log had
the error.

## What Changes

- **Parking.** When the retry layer reports the host unavailable for a step, the unit goes back to
  `planned` with the cause `host_unavailable`, the failing step and the error text, not `failed`.
- **Backoff.** The running pass readmits a parked unit with growing waits per unit (1, 2, 5, 10,
  30 minutes), measured from when it was parked, and logs why it is waiting.
- **Resume at the step.** A parked or requeued unit whose approved commit is its pushed head goes
  straight to opening the pull request: no second tier 2 run, no re-review, no rework from saved
  feedback.
- **Every failure keeps its error.** A unit that ends `failed` for any reason records the error
  text and the step on the unit, visible in `abk status`, not only for a rejected commit.
