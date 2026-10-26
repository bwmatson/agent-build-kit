# Proposal

## Why

The guard reads usage whenever its cache is cold, at the top of every round and before every agent step of every unit, and every
time the status command is run. Most of those readings cannot change anything: with a fifth of a window used and three hours to
its reset, no answer the endpoint could give would refuse a start, and with a window used up, no answer before its reset would
allow one. Each needless call spends a share of a rate-limited endpoint that nobody can see the size of, and a refusal makes the
guard fall back to an old reading and pause units on it.

## What Changes

- **A reading is asked for only if it could change the decision in hand:** the decision to start work or to resume paused work. If the reading already held settles it, no call is made.
- **What settles a decision:** usage only rises within a window and falls only when the window resets. So a refusal made before the
  reset stands until the reset, apart from the threshold's own rise toward its ceiling, which is computed and needs no call. An
  allowance stands while the usage could not have climbed to the threshold since the reading, using the fastest climb seen.
- **Asked at most as often as a minimum interval allows,** and the interval is the cache time of `usage-pause-deadline`. When a
  decision needs a fresh reading and the interval has not passed, the start waits the short time left and does not call.
- **The status command shows the held reading and its age,** and calls the endpoint only when asked to refresh.

## Impact

- agent-build-kit: the usage guard's decisions and its callers, the status command and the record of
  readings. Builds on `usage-pause-deadline` and `usage-api-observability`.
