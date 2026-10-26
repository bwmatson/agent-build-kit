# Proposal

## Why

`forges/github.py` lists `FAILURE`, `TIMED_OUT` and `CANCELLED` as the
conclusions that make a check failing, and the poller reports each newly failing
check as a rework with the check's log. During a host incident, jobs waited
about 15 minutes for a runner and were cancelled with no step run. The unit was
sent back for rework twice for checks that had never started, then a third time.
An agent cannot fix a runner outage: the rework either changes nothing or makes
speculative edits, and costs a session's usage either way.

A check also gets cancelled when a newer run supersedes it, or a person cancels
it. Neither is a verdict on the commit.

## What Changes

- **A cancelled check is not a failing check.** It does not raise a rework. A
  timed-out check stays a failure, since a hung test is real.
- **The runner re-runs it.** When the checks on a unit's head are cancelled and
  nothing else has failed, the runner asks the host to run them again, itself,
  without an agent. Bounded per head commit: after the bound it says so on the
  unit's log and in its status, and leaves it for a person.
- **It is visible.** The unit's log records "checks cancelled on <sha>; re-run
  n of m", so a pull request that sits unfinished has a reason someone can read.
- **Both hosts.** The same rule for Azure DevOps' canceled results.
- **Mixed outcomes still rework.** A pull request with a cancelled check and a
  genuine failure is reworked for the genuine one, and the cancelled one is
  re-run as well.
