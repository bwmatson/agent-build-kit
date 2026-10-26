# Proposal

## Why

The guard asks an undocumented, rate-limited endpoint where the usage windows stand, and the number of requests it allows
is not published and not announced in its answers. It answered 429 on one call and 200 on the next, a few minutes later. The
pipeline cannot say how often it calls, who calls, how many answers were refusals, or how long it was quiet before the first
one, so the only way to choose a safe interval is to guess. A refusal also makes the guard fall back to an old reading and
pause units on it, so a wrong guess has a cost.

## What Changes

- **Every call and every answer from the cache is recorded:** when, who asked (the guard, the status command, or another
  reader), the outcome (ok, rate limited, timeout, error, answered from the cache), how long it took, the status, and any
  rate-limit or retry headers the answer carried, including on a refusal, which is when they matter.
- **A reading of the call rate:** calls in the last hour and the last day, refusals, the cache's hit rate, the quiet time before
  each refusal, and the shortest interval between successful calls that has not been followed by one. The status command
  prints it, and it is exported as a metric.
- **The pipeline sets its own interval:** after a refusal the time a reading is kept grows, and after a long run without one it
  shrinks back, within bounds, and the status command says what the interval is and why.

## Impact

- agent-build-kit: the usage guard, a local record and a metric, the status command, and the settings and docs. Builds on the
  cache and cool-down of `usage-pause-deadline`.
