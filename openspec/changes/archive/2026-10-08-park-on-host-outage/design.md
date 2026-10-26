# Design

## Parking

`build_unit` and the graph's step wrapper catch `HostUnavailable` before the generic handler: the
node records `set_state(planned, cause=host_unavailable, step=<node>, note=<operation and cause>)`
with the time and a `parked_attempts` count, and the thread stays at the node so a resume re-runs
only it. Any other exception still fails the unit, now with `note` set to the error's type and text
and the step name for every exception.

## Readmission

`_sent_back` (the pass's rule) readmits a unit whose last cause is `host_unavailable` when its backoff
for `parked_attempts` has elapsed (schedule above, capped at 30 minutes); until then it is skipped
with a log line saying how long remains. A success resets the count. A tick start treats it the same.

## Resume point

`after_prepare` checks, before tier 2 and before `had_feedback`, whether `approved == pushed == head`
and the unit has a pull request step still to do (no pull request, or one with unposted replies); if
so it routes to `open_pr`. The saved feedback is left in place until `open_pr` clears it, as now.

## Dependencies

The cause field comes from `status-not-wording`; the unavailable error from `forge-retry-layer`.

## Out of scope

Retrying the other steps' non-host failures, and the replies change.
