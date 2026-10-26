# Design

## What counts

A check conclusion has three kinds: pass, fail (a verdict on the commit:
`FAILURE`, `TIMED_OUT`), and neither (`CANCELLED`, and for Azure DevOps
`canceled`, plus skipped and stale as already treated). `PullRequest.failing_checks`
holds the second kind only; a new field, `cancelled_checks`, holds the cancelled
ones. Both forges fill it.

## The poller

`failing_checks` unchanged in meaning, minus cancelled. A snapshot gains
`cancelled_checks`. When it newly has entries, the poller dispatches a
`rerun_checks` event, not a rework. The handler asks the forge to re-run:
GitHub `gh run rerun <id> --failed` on the cancelled run, Azure DevOps by
re-queuing the build. This is a write to the host made by the runner, in line
with the host-interaction rule that the runner changes the host and agents do
not.

## The bound

Re-runs are counted per unit per head commit, in the unit's record, reset when
the head moves. Two re-runs by default (`limits.max_check_reruns`). Past it,
the unit is not reworked and not held: it stays in review, and the log and the
pull request's status line say "checks keep being cancelled by the host".
A person can re-run by hand, or add `agent-rework` to take it from there.

## What does not change

The text handed to a rework for a real failure, the log fetch for failing
checks, and the rule that a check already red is not news. A cancelled check
that is re-run and then fails is a failing check the normal way.

## Out of scope

Detecting a host incident, delaying polls during one, or reading the host's
status page.
