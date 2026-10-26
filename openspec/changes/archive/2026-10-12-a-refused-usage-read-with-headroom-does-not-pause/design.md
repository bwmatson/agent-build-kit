# Design

## What was checked, and where

Read-only against the agent-build-kit checkout; paths are under `src/agent_build_kit/` unless they name `docs/` or `tests/`.

- `pipeline/usage_guard.py` `decide_start` (979-1029) is the one decision every start asks. From the reading kept in the cache file
  (`_kept_reading`, 502-508) that has not passed a window's reset (`_past_reset`, 519-524) it judges the reading with `trust_age=True`; it
  answers from it when it refuses, or when `_headroom_holds` (946-964) says no window could have climbed to its threshold. If the reading is
  younger than the cache time it takes a fresh one; otherwise `next_call_at` (800-807, usage_calls cache interval) may refuse with `_too_soon` (967-976,
  the exact message of the observed pause) before any call is made.
- `_headroom_holds` adds `most_added` (`pipeline/usage_calls.py` 236-264: the fastest climb seen, no slower than `usage_climb_floor` 0.2
  points a minute, plus `usage_climb_margin_pct` 2) times the minutes since the reading. For an 89-minute-old reading that is 0.2 x 89 + 2
  = 19.8 points at the least, so 65 + 19.8 is over the weekly 80: the existing allowance, which is wall-clock and counts every consumer
  at the fastest climb ever seen, cannot hold for the weekly window after about an hour and a half, and fails sooner when the record holds a
  fast climb. (Arithmetic from the code; not run.)
- A fresh call is `read_live_usage` (527-711): a refusal writes `cooldown_until` into the cache file keeping the payload and `fetched_at`
  (618-627); under a cool-down it returns `last_good()` (560-563), which is `None` once the kept reading is as old as
  `usage_fallback_minutes` or past a reset; `current_usage` (788-790) then falls to the editor's cache (`read_cached_usage`, 714-740).
  `may_start_unit` (862-943) refuses a `None` reading as "usage is unknown" for `UNKNOWN_RETRY` (882-889) and a non-live reading older than
  `MAX_ANCHOR_AGE` as stale (915-923). So there are two ways a refused read pauses: `_too_soon`, and a failed fresh read ending in
  unknown or stale. Both are in `decide_start`.
- The doubling: `cache_interval` (`pipeline/usage_calls.py` 194-223) doubles `kept` for each refusal up to `usage_cache_max_minutes`
  (config.py 224-225, default 60), halves it after the same time without a refusal down to `usage_cache_minutes` (15), and raises it to a
  named `Retry-After` while that lasts (`_retry_after`, 226-233, which reads 0 as no time). So it does narrow; the observed "kept 30 minutes"
  was one doubling. `next_call_at` is the last asked call (a refused one included) plus `kept`: 18:56 + 30 minutes = 19:26, the time in the message.
- The "safe interval 2811s" of the status line is not a setting and not what held the call back: `_safe_interval` (153-171) is the shortest
  gap between successful calls not followed by a refusal, a reading of the record, printed by `rate_line` (277-283) and exported as a
  gauge. Nothing waits on it. `interval_line` (267-274) is the one that says "kept 30 minutes, set after a refusal".
- Retry-After: the cool-down is `_cooldown_seconds` (511-516): a header that is absent, unreadable, or not greater than zero gives
  `DEFAULT_COOLDOWN`, five minutes (100). So a retry time of zero is already read as the short default, not as a long block; what it
  still does is double `kept` like any refusal, since `cache_interval` counts every refusal.
- `pipeline/pause.py`: a usage pause is a record (`PauseKind` 40-46); `docstring` 1-20 says each tick asks the guard again and a pause
  answers to what changed; `clear_pause` (155-165) clears a usage marker the guard has found room under. Nothing in pause.py changes: the
  estimate is a decision of the guard, and the marker follows it as it does for any allowance.
- The ledger, `pipeline/usage_ledger.py`: `UsageRecord` (97-150) has `at`, `unit`, `node`, `cost` (`incremental_usd`, `cumulative_usd`),
  tokens, `context`, `session_id`; `read_ledger` (334) and `grouped_records` (344) read it; `session_spend` (381) sums a session's
  incremental dollars. `UsageLedger.spend_since` in `usage_guard.py` (202-243) is the old, undecided-by class, "not part of the decision any
  more". Nothing converts dollars or tokens to a share of a window: the windows' sizes are not published and the endpoint reports only
  percent (`UsageReading`, 134-150). UNVERIFIED that no conversion exists elsewhere; I found none.
- Thresholds: `threshold_at` (378-398) is the pause percent, rising toward the ceiling over the last quarter of the window; the observed
  installation has the session at 92 (ceiling 97) and the weekly at 80 (ceiling 90).
- Status: `cli/pipeline.py` `_usage_line` (297-318) and `cmd_status` (421-446) print the held reading (`held_usage`, 793-797, no call),
  `rate_line` and `interval_line`.
- Settings are on `ClaudeLimitsConfig` (config.py 219-231) and, per window, `UsageWindowConfig`. Docs: `docs/configuration.md` 116-124, the
  `abk-config` skill 77-78, `docs/architecture.md` 876-913.
- Tests that state the rules being extended: `tests/pipeline/test_usage_read_decision.py`, `test_usage_climb.py`,
  `test_usage_read_absorbs_failures.py`, `test_usage_calls.py`, `test_usage_guard.py`. UNVERIFIED which of them pin a refusal of a
  retry time of zero, or the default of sixty minutes for `usage_cache_max_minutes`; the builder greps for both.

## The rule

The estimate is made in `decide_start` at the two places a refused read pauses today: where `_too_soon` would refuse, and where a fresh read
failed and the reading is unknown or stale. It is made from the reading the guard's own cache keeps (`_kept_reading`), of any age. The
editor's cache is never the base: its reading is the guard's fallback for a failed call, it has no `fetched_at` of the guard's own and an
estimate resting on it would be a guess about a source the guard does not control. A reading younger than the fallback age is used as read
(`last_good`, unchanged): the estimate is for what the age cutoff refused.

For each window of the reading, judged separately (`reading.windows`):

    estimate = figure read (or 0 if reset) + allowance x units since + the reset term
    allow the start when, for both windows:  estimate + margin < threshold_at(window, now)

`threshold_at` is the same function the other decisions use, so the ramp near a reset is honoured; the comparison is strict, like the existing
one (`used_pct >= threshold` refuses). An actual reading over a threshold is not touched: `may_start_unit` still refuses it and no estimate
is made. The credit and spend-limit backstops (897-912) run first on the kept reading and keep refusing.

### What "spent since" is

Two sources, counted by unit id, so a unit is counted once:

1. units with at least one ledger record at or after the reading's `fetched_at` (the later of that and a window's reset, for that
   window). The ledger is written when an agent call ends, so it sees finished calls and not one in flight.
2. units the guard admitted on an estimate since the reading, kept in the cache file (`estimate_units`, a list of unit ids). That covers
   the in-flight call. The file is rewritten whole by a good read (`{**payload, "fetched_at": ...}`, 670), so the list is dropped
   exactly when a new reading makes it meaningless, with no clearing code; a refusal rewrites it keeping `**cached` (625), so the list
   survives. The update is made under the refresh lock the guard already takes (700). UNVERIFIED: that a start admitted by a caller who
   cannot take the lock can still be recorded; the builder uses the blocking form for this write only.

The guard learns of a unit that asks, but not that it started; `decide_start` has no unit id today. The per-unit identity needs a caller
argument (optional, default none: an unnamed ask counts as one more unit for the cap and the allowance). UNVERIFIED how the runner threads
the unit id to the guard (`wiring.py` 1564-1610 `build_may_start`); the builder decides, and the fallback of counting asks admitted
is conservative.

### The allowance is points per unit, not converted dollars

The ledger holds dollars and tokens and the endpoint gives percent of a window whose size is not published, so a conversion would be a
guess presented as a calculation. Calibrating one from the record (the points a pair of good readings gained against the dollars between
them) is possible, but the gain includes the person's own use, is noisy near whole-point steps, and needs a history a fresh install lacks.
A flat allowance per unit is conservative, explainable ("each unit may cost ten points of the session"), and a person sets it from what
their units cost. It is set per window, since a unit costs a larger share of the five-hour session than of the week:

- `usage_unit_allowance_pct`, on each window's settings beside `usage_pause_pct`: ten points for the session window and two for the weekly
  by default. UNVERIFIED as a measurement: they are chosen so that, with the defaults, three units (the cap) add thirty points to the session
  and six to the weekly. A person calibrates from `abk`'s cost reports (the cost of the units that ran, against what the window
  gained over the same period) and should set the allowance to something above the dearest unit they run. How the two windows take
  different defaults from one `UsageWindowConfig` class is for the builder (the documented example sets both at the same figure).

### The margin and the cap bound what the estimate cannot see

The estimate counts only the pipeline. The person's interactive use of the same account, and any other consumer, is invisible to it, and
that is the residual risk: a person who opens a long session while the endpoint refuses could take the window past the threshold, and the guard
would not know until a read succeeds. Two bounds on that, both settings:

- `usage_headroom_margin_pct`, five points by default, on `ClaudeLimitsConfig`: the room required between the estimate and the threshold.
  At the floor climb of 0.2 points a minute, five points is the room for twenty-five minutes of the unseen consumer, which is about the
  longest the endpoint is out of reach with the interval ceiling below (thirty minutes) and the five-minute cool-down. A single margin for
  both windows: the weekly climbs the slower, so it is the larger bound there.
- `usage_estimate_max_starts`, three by default: units admitted on an estimate for one reading. When the cap is reached further starts are
  refused until the next permitted call (`_too_soon`'s time), when a read either replaces the reading and the count or is refused again and
  the rule starts over for that call. So the number of units that can start blind in the longest outage the interval allows is three, plus
  those already running; with the defaults at most 30 session points and 6 weekly points of the pipeline's own spend, beyond the margin.

What this does not do: it does not stop the person's use, and it does not stop units already running. It does stop the pipeline starting
many units on a figure it cannot refresh. A person who wants it stricter sets the cap to 0 (the old behaviour, beyond the fallback age) or the
margin higher; a person who wants it looser raises the cap or lowers the margin. A cap of zero is valid; a negative one is not.

### A reading is only valid inside its window

Usage within a window only rises and falls at its reset (`usage-read-on-decision`), so a reading says nothing about a window that has since
reset. Today that makes the whole reading unusable (`_past_reset` is true if either window reset). The estimate judges each window apart:

- A window that has not reset: the reading's figure plus the allowance.
- A window that has reset since the reading, `reading.observed_at < resets_at <= now`: the reading's figure is dropped; the estimate is zero
  at the reset plus `most_added` for the minutes since the reset (the same bound `_headroom_holds` uses: the fastest climb seen, no
  slower than the floor, plus the margin) plus the allowance for the units since the reset. This is not "treat as fresh/zero": a new
  window may not be empty, because the person may have used it between the reset and now, and the pipeline cannot see that; it is not
  "unknown" either, since a window that reset an hour ago can have grown only so much. Zero-plus-the-time-bound is safe because it
  falls back to refusing as the time since the reset grows: ten hours at the default floor is 122 points, which refuses (the scenario
  fixes this), so a long outage does not stay open on a window nobody measured.
- A window whose reading says no window is open (`resets_at` is `None`): its figure, which is zero, and the allowance. The threshold then
  has no ramp (`threshold_at` 387).

That changes `A reading is not used past its window`: the reading is not used as the figure of a reset window, but the other window's
figure is. Its scenario is kept and a scenario added. `A failed live read is absorbed` is amended in two sentences: the fallback age
covers a failed call as a reading, and older than that a reading stands only through the estimate, and the one scenario whose premise
("nothing recent") would now allow a start with a kept reading is narrowed to "no kept reading an estimate can rest on". The stale rule
stands for the editor's reading (its scenario says the reading is not one the guard's cache kept) and does not apply to a kept
one, which goes through the estimate.

### Relation of `usage_fallback_minutes` and the estimate

`usage_fallback_minutes` keeps its meaning: the age of the last good reading that covers a failed call as a reading, without an estimate.
The estimate path takes the cases beyond it. It replaces the age cutoff only when headroom is ample, under the same thresholds, so a person
who raised the fallback age to 180 to get work moving can put it back to thirty: the same units start, and units whose estimate is not
ample no longer start on an old figure, which a long fallback age allows.

## The interval

Two changes, both in `pipeline/usage_calls.py`, the second a default in config.py:

1. A refusal whose answer names a retry time of zero (a `Retry-After` header equal to 0) does not double `kept`. Nothing in an answer that asks for
   no wait says the calls were too frequent; widening the interval on it turned one such refusal into thirty minutes of no call. The
   cool-down stays the short default (`_cooldown_seconds`): a zero is not honoured as "call again now", which would re-ask a limited
   endpoint every tick, nor read as a long block; both "retry soon" and "do not hammer" are served by five minutes. A refusal with no
   header, or a positive one, still doubles, and the longer of the doubled time and a named one still wins. UNVERIFIED that a
   header of zero is the only form the endpoint uses to mean "soon"; a header with a time shorter than the base interval is left
   alone because the observed answer is zero and the other forms are not known.
2. `usage_cache_max_minutes` defaults to thirty minutes (it was sixty). A ceiling of fifteen, the figure that would remove the 47 minute
   figure altogether, equals the base time and so removes the adaptation `usage-api-observability` exists for: doubling would be a
   no-op. Thirty is one doubling, which is what the observed refusal reached; a second refusal does not take the interval past it. With
   the estimate in place a wide interval no longer pauses the pipeline, but it still delays the next real reading, and the longer it is, the
   longer the pipeline lives on an estimate, so the ceiling bounds that too. A configured value stays whatever the person set.

Halving after quiet is unchanged: it does narrow, which the observation that "it grew" did not show.

## The status line

A decision on an estimate says: `usage: reading 89m old, session ~15% estimated (0% read + 15% spent), weekly ~71% estimated (65% read +
6% spent), allowing starts` and the thresholds each is judged against. A refusal that rests on an estimate says the same and which window
failed (`weekly ~83% estimated (65% read + 18% spent) is not 5 points under 80%`). `abk status` computes the same line from the held reading
without a call, whenever the reading it holds is older than the interval and the endpoint cannot be asked (a cool-down is in force or the
minimum interval has not passed); it still prints the held reading and `rate_line`/`interval_line`.

## What this does not change

Thresholds and their ramp, what is measured, a running step (it finishes), the cool-down after a refusal, `MAX_ANCHOR_AGE` for the editor's
reading, the unknown-retry interval for no reading, the pause marker (a usage marker refuses nothing), and the rule that an actual
reading over a threshold pauses until its relief. Nothing here changes `pause.py`.

## Risks

- The allowance is a number nobody measured here (UNVERIFIED). Too small and a few units run past what the window had; the margin and the cap
  bound it, and every good read corrects it. Too large and the guard pauses where it need not, which is today's behaviour, not a new
  harm.
- The estimate does not see the person's own use, as stated. If the interval ceiling is raised by hand the outage the estimate covers
  grows with it; the cap does not shrink on its own.
- The count of starts is kept in a file shared by processes; two ticks admitting at once is bounded by taking the update under the lock.
