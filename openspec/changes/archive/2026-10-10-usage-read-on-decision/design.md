# Design

## Why this exists

Asking less is two things. It spares a rate-limited endpoint calls that could not change anything, and it makes the pipeline
resilient to that endpoint being down: a reading that settles the decision keeps working through an outage, however long it
lasts, where a rule that always wants a fresh reading stops all work on the first failure. A reading far under the threshold,
in a window that has not reset, still allows a start when it is older than the fallback age, and that is by design here
rather than a side effect.

## Every run asks, the module decides

The tick, each round of a pass and each gate always ask the usage module for a decision; none of them skips the question or
keeps an answer of its own. The module decides whether to call the endpoint: from the held reading it settles the decision, or
the minimum interval stops a call, or one process refreshes under the cache lock. So the number of asks says nothing about the
number of calls, and twenty ticks within the cache time make one call at most.

## What a decision depends on

The decisions that read usage are whether a unit may start and whether paused work may resume. (Judging a step that ends
having written nothing used to be a third; main no longer does that, so it is not one here.) Each compares the percentage used in the session window and in the week window with a
threshold. A threshold is the configured pause percentage, rising toward its ceiling over the last part of the window; both are
functions of the time and the window, not of the endpoint.

## When the held reading settles it

Usage within a window never falls, and drops only when the window resets. From a reading taken at time t with percentage p, in a
window that resets at r:

- **If p is at or over the threshold now** and now is before r: a start is refused, and no fresh reading can change that. The
  only thing that can change it is the threshold rising with time, which is worked out from the held reading, so the guard knows
  when to look again: when the threshold would reach p, or at r.
- **If p plus the most usage could have added since t is under the threshold now** and under the threshold at the time the decision
  will matter: a start is allowed, and a fresh reading cannot change that.
- **If now is at or past r:** the reading is of a window that has ended, and a fresh one is needed.
- **Otherwise,** a fresh reading could change the decision, and one is asked for, subject to the minimum interval.

The most usage could have added is the fastest climb seen, in percentage points a minute, times the minutes since t. It is taken from
the record of readings (from `usage-api-observability`), with a configured floor for a pipeline that has no history, and a margin.
The rate is derived per window, since the session window and the week window climb at different speeds.

## The minimum interval

Whatever the above says, the endpoint is not asked more often than the cache time allows, a fifteen-minute default that adapts. When a
decision needs a fresh reading inside that time, the guard does not call: it refuses the start for the time left to the next permitted
call, a short stale pause rather than a pause on an old window, and says so. This trades a short delay near a threshold for a bound
on the call rate.

## Units that cannot start anyway

A round reads usage to decide whether to admit builds. Units left out of the round by `--only`, by a lease another process
holds or by a backoff cannot start in it, so a decision about them is not a decision, and the round asks for no reading on
their account. Today those exclusions are applied inside the round's evaluation and turn the units `held` before the
candidates are known, so the guard cannot tell them from units that wait on something else. The round passes the guard the
exclusion set explicitly, as `start-order-by-stack-age` does for its age calculation, and the guard counts only the candidates
that are not in it.

## The status command

The status command prints the held reading with its age and the source, and calls the endpoint only with an explicit refresh.

## What this does not change

Thresholds, what is measured, the treatment of a running step, the cool-down after a refusal, and the order of fallbacks are those
of `usage-pause-deadline`; this only decides whether to ask.
