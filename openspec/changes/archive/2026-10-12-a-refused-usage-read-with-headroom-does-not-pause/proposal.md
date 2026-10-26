# Proposal

## Why

The whole pipeline was paused ("usage must be read again but the endpoint was asked too recently: the minimum interval allows the next call
at 19:26") although the last good reading showed the session at 0% against a pause threshold of 92% and the weekly window at 65% against 80%.
The chain was: the endpoint answered 429 with a retry time of zero; the guard set its short cool-down and, as `usage-api-observability`
specifies, doubled the time a reading is kept, from fifteen to thirty minutes, so the next permitted call was thirty minutes after the refused
one; the good reading was eighty-seven minutes old, older than `usage_fallback_minutes` (thirty), so it could not cover the failed call as a
reading, and the time a fresh one was allowed had not come. With no usable reading and no permission to ask, the guard fails closed. The
person raised `usage_fallback_minutes` to 180 by hand to get work moving.

Failing closed is right when nothing is known. Here a great deal was known: usage only rises inside a window, and the pipeline's own spend
since the reading is in its ledger. The only thing it did not know was what the account's other consumers used, and a margin and a cap on
how many units may start meanwhile bound that. A refused read should delay the next reading, not stop work that no plausible reading
could have refused.

## What Changes

- **A start is allowed on an estimate:** when a read is refused or unreadable and the guard's own cache holds a last good reading of any
  age, each window is estimated as the reading plus a flat allowance (points, per window, settable) for each unit that has spent since the
  reading or been admitted on an estimate since; a start is allowed while, in both windows, the estimate plus a margin
  (`usage_headroom_margin_pct`) is below that window's threshold. Otherwise it pauses as today, and with no reading kept it fails closed as today.
- **A reset window is estimated from its reset,** not from the reading: a reading is only valid inside its own window.
- **A cap on starts per reading** (`usage_estimate_max_starts`) bounds what an unseen consumer could cost while the endpoint is out of reach.
- **The status line and the reason say so:** `usage: reading 89m old, session ~15% estimated (0% read + 15% spent), ..., allowing starts`.
- **`usage_fallback_minutes` keeps its meaning,** the age at which a reading covers a failed call without an estimate; the estimate path
  takes over only beyond it, and only when headroom is ample, so a raised fallback age is no longer needed.
- **A refusal that asks for no wait does not widen the interval,** and the default ceiling of the interval is thirty minutes (it was sixty).

## Impact

- agent-build-kit: the usage guard's start decision, the cache file's record of starts on an estimate, the settings, the status command, the
  call record's interval, the configuration and architecture documents, the config skill, the changelog.
- Spec: `usage-pause` (modifies five requirements, adds five).
