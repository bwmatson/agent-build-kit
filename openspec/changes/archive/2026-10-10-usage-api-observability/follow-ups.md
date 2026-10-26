## From `usage-api-observability/1`

- usage_calls._safe_interval: stop the lookahead for a refusal at the first call beyond SAFE_MARGIN, since the list is time-ordered, instead of scanning the whole rest of the window for every successful call.
- src/agent_build_kit/pipeline/usage_calls.py:160 — `_safe_interval` now scans every remaining call after each successful one with `any(... for later in endpoint[index + 1 :])`, which makes it quadratic in the number of calls in the window. `endpoint` is sorted by time, so the scan can stop at the first later call more than `SAFE_MARGIN` after `c`, for example with `itertools.takewhile(lambda later: later.at - c.at <= SAFE_MARGIN, endpoint[index + 1:])`.

## From `usage-api-observability/2`

- Once the adaptive interval has decayed back to `usage_cache_minutes`, the status line still says "lowered after a quiet spell". Saying "the configured time" there would be clearer. That needs the quiet-decay status test to expect the new wording.
- Each `read_live_usage` reads `usage-calls.jsonl` twice: once in `current_cache_interval` and once more when `record_call` prunes. If the record grows, read it once per call or cache the result.
