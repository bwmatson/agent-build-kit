# Proposal

## Why

Twice in one afternoon units were paused "until 17:53 UTC" at 19:38 UTC. The guard had failed to read usage
live, fell back to a reading about six hours old, found it too old to trust, and then computed the time to wait
from that old reading's own window reset, which had passed hours earlier. The grace period was added twice on
top. Nothing checked that a resume time was in the future.

The deadline was only the visible symptom. A start refused by the guard stops the rest of the pass from
admitting builds, and the pass does not look at pull requests or merges again until its running builds end, so
two units stayed paused for more than twenty minutes and a merge went unrecorded for ten. The live reading had
failed for one request and the cause was thrown away, so nothing said why.

## What Changes

- **A resume time is never before now,** with the grace period applied once, and a reset time that has
  already passed is treated as unknown.
- **A stale reading retries soon:** the pause it causes lasts a new, shorter stale-retry interval (five minutes by default) and says the
  reading is stale. It does not borrow the stale reading's window.
- **A single failed live read is absorbed:** it is retried once; if it still fails, the last good live reading
  is used for a longer age before the editor's cached reading; the reason names the source used and why live
  failed, which is logged.
- **A refused start stops only that unit:** the pass keeps refreshing and re-asking the guard, builds are
  admitted again as soon as it allows, and paused units resume within the pass.
- **The usage module is the only authority:** every run asks it; it alone decides whether to call the endpoint, with
  one process refreshing at expiry; a pause marker refuses nothing unless it is a `rate_limit` pause, which ends at its
  deadline within the pass; a reading is never used past its window's reset; the cache counts its hits and misses.

## Impact

- agent-build-kit: the usage guard, the pause marker, the pass loop, and docs. No change to thresholds, to
  what is measured, or to how a running step is treated.
