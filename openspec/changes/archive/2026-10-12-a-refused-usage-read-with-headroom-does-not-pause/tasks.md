# Tasks

Acceptance: none — the endpoint's refusal, the clock and the ledger are faked in tier 1; nothing a consumer drives changes beyond what those tests show.

Priority: 1

## 1. [agent-build-kit] [tier1] A refused read with headroom allows a start on an estimate

Done when a refused or unreadable read with a kept reading far under both thresholds allows a start, with a reason that says it is an
estimate, and every case that should still pause does.

- [x] 1.1 Test: `tests/pipeline/test_usage_estimate.py` — the observed case: a kept reading 89 minutes old (session 0% against 92, weekly 65%
      against 80), a cool-down in force after a 429 with a retry time of zero and `kept` thirty minutes; `decide_start` allows, makes no call
      and writes no pause; the reason carries the reading's age, each window's estimate (read plus spent) and "allowing starts".
- [x] 1.2 Test: the same refusal with the weekly at 78% pauses (78 + 5 is not below 80) with the weekly figure named; with the session at 88%
      pauses; the session at 10% and the weekly at 77% pauses for the weekly, so one window's room does not offset the other's; a live
      reading over a threshold pauses as before and makes no estimate.
- [x] 1.3 Test: no reading kept pauses for the unknown-retry interval as before; the editor's reading alone, with ample headroom, is not the
      base of an estimate and the stale rule applies to it; a kept reading showing the plan limit reached, or credits enabled with a window
      full, pauses; a kept reading younger than the fallback age is used as read with no estimate.
- [x] 1.4 Test: spend since the reading — session read 70%, allowance 10, margin 5: one unit with ledger records since the reading allows
      (80 + 5 < 92), two units refuse (90 + 5); one unit with four records counts once; a unit admitted on an estimate with no ledger record
      yet counts, and counts once when its record arrives; records before the reading's `fetched_at` do not count.
- [x] 1.5 Test: a window reset since the reading — the session reset forty minutes ago starts from the reset (zero plus the climb bound plus
      the allowance), not from its 88% reading, while the weekly keeps its figure; a session reset ten hours ago refuses (122 points at the
      default floor and margin); a reading with no open window starts from zero with no ramp.
- [x] 1.6 Test: the cap — three units admitted on an estimate, the fourth refused until the time the endpoint may next be asked with a reason
      that says three starts were made on an estimate; a good live reading resets the count; a cap of zero never allows on an estimate;
      the count survives a refusal that rewrites the cache file and is dropped by a good read.
- [x] 1.7 Test: the estimate allows when `_too_soon` would have refused (the minimum interval has not passed) and makes no call; with the
      estimate not ample the old refusal and its message are unchanged.
- [x] 1.8 Test: `abk status` prints the estimate line from the held reading with no call when the reading is older than the interval and a
      cool-down is in force, and prints the held reading, the rate line and the interval line as before; a refusal that rests on an estimate
      names the window and says it is not the margin under the threshold.
- [x] 1.9 Test: settings — `usage_headroom_margin_pct` and `usage_estimate_max_starts` reject a negative value, `usage_unit_allowance_pct`
      rejects a negative value, the defaults are 5, 3, and 10 and 2 for the session and weekly windows, and `usage_fallback_minutes` at its
      default of thirty still leaves the observed case allowed.
- [x] 1.10 Update the tests that state the old rule: in `tests/pipeline/test_usage_read_absorbs_failures.py` the "nothing recent" case gains
      "no kept reading an estimate can rest on"; the stale-reading test names a reading the guard's cache did not keep; the
      reset-window fallback test keeps its premise. A search of `tests/` for `usage_cache_max_minutes` and `usage_fallback_minutes` finds
      any other that pins the old default or the old cutoff.
- [x] 1.11 Add the three settings in `config.py` beside the others (`usage_headroom_margin_pct`, `usage_estimate_max_starts` on
      `ClaudeLimitsConfig`; `usage_unit_allowance_pct` per window) and the estimate: a pure function in `pipeline/usage_guard.py` (or a
      module it imports) from the kept reading, the ledger's units since, the time and `Limits`, returning each window's figure read, points
      spent and verdict.
- [x] 1.12 Call it in `decide_start` at the two places a refused read pauses today (where `_too_soon` would refuse, and where the fresh
      read ends in no reading or a stale one), record the unit admitted in the cache file under the refresh lock, and write the
      reason; leave `may_start_unit` and `pause.py` as they are.
- [x] 1.13 Print the estimate line in `cmd_status` (`cli/pipeline.py`) from the held reading with no call.
- [x] 1.14 Update `docs/configuration.md` (the usage settings block), the `abk-config` skill's `limits:` block, and the usage guard paragraph
      of `docs/architecture.md`: the estimate, its three settings, how `usage_fallback_minutes` and the estimate relate and that a raised fallback
      age is no longer needed, the residual risk of unseen consumers, and the status line. Add one bullet under `## Unreleased` in
      `CHANGELOG.md` as `AGENTS.md`'s Changelog section says.

## 2. [agent-build-kit] [tier1] A refusal that asks for no wait does not widen the interval

Done when a refusal naming a retry time of zero leaves the time a reading is kept where it was, and the ceiling defaults to thirty minutes.

- [x] 2.1 Test: `tests/pipeline/test_usage_calls.py` — `cache_interval` after one refusal whose headers hold `Retry-After: 0` stays at the
      base (fifteen minutes) with reason `configured`; after one with no header or a positive one it doubles to thirty; a second refusal
      without a header stays at the default ceiling of thirty; a longer named retry time still wins past the ceiling.
- [x] 2.2 Test: the cool-down after a 429 with `Retry-After: 0` is the five-minute default and not zero, and after an absent or unreadable header
      the same; the next permitted call after such a refusal is fifteen minutes after it, not thirty (the observed case).
- [x] 2.3 Test: quiet halving is unchanged — a time of thirty minutes after thirty minutes without a refusal reads as fifteen; the status line
      says a refusal that asked for no wait did not widen it (`interval_line`).
- [x] 2.4 Test: the default of `usage_cache_max_minutes` is 30, and a configured value above it is kept; update any test that pins sixty.
- [x] 2.5 In `pipeline/usage_calls.py` make `cache_interval` skip the doubling for a refusal whose `Retry-After` is zero (a retry time that
      is absent still doubles), and add the matching reason in `interval_line`; change the default of `usage_cache_max_minutes` in
      `config.py` to 30.
- [x] 2.6 Update `docs/configuration.md` (`usage_cache_max_minutes`), the `abk-config` skill, and the usage paragraph of
      `docs/architecture.md` ("an hour by default" becomes thirty minutes, and the refusal that asks for no wait); fold the change into the
      `## Unreleased` bullet group 1 added instead of adding another.
