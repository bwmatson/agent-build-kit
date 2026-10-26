# Tasks

Acceptance: none — the file in the user's home and the clock are faked in tier 1; the reading's source, its record and its status line are
all the tests can show a consumer, and no route or tool changes.

Priority: 2

## 1. [agent-build-kit] [tier1] A fresh reading in Claude Code's own cache is used before the endpoint is asked

Needs: a-refused-usage-read-with-headroom-does-not-pause group 1 merged — both edit `decide_start` and the read order in `usage_guard.py`, and this group adds its step before the estimate and `_too_soon` paths that group writes

Done when a block in `~/.claude.json` that is fresh, unreset and fresher than the guard's own reading decides a start with no call, labelled and recorded as its own source, and a setting of 0 gives back the old order.

- [x] 1.1 Test: `tests/pipeline/test_usage_claude_cache.py` — a block fetched six minutes ago (window fifteen) with an old guard reading decides the start with no call, writes nothing to the guard's own cache file, and the reason ends `(claude.json, 6m old)`; the same block decides the resume time in `refreshed_usage`/`held_usage` for the status command with no call.
- [x] 1.2 Test: a block fetched twenty minutes ago is not used; a file modified a minute ago with a block fetched two days ago is not used (only `fetchedAtMs` counts); a window of 0 never uses a block fetched a minute ago and the order is today's; a window above `MAX_ANCHOR_AGE` does not use a block seventy minutes old.
- [x] 1.3 Test: both fresh — the block fresher than the guard's reading wins, the block older than it loses, a tie goes to the guard's own; only one fresh, that one is used.
- [x] 1.4 Test: a block whose session or weekly window reset since it was fetched is not used; a missing file, invalid JSON, a truncated file, no `cachedUsageUtilization`, one window only and a non-numeric `fetchedAtMs` each read as absent with nothing logged and no zero reading.
- [x] 1.5 Test: a fresh block over a threshold refuses and pauses until the relief with no call; a fresh block inside the minimum interval (a call two minutes ago) allows without `_too_soon`; with credits enabled in the guard's own older reading the credits rule does not fire on a block reading (decided by the thresholds alone).
- [x] 1.6 Test: `tests/pipeline/test_usage_calls.py` — a `claude-json` line holds the caller and age and no status or token; `next_call_at`, the refusal bookkeeping and `_safe_interval` give the same results with or without it; `rate_line` prints the cache's share and the block's share apart (three endpoint calls, four cache and five block answers: 33% and 42%); the cache's share is unchanged by a block answer.
- [x] 1.7 Test: `tests/test_config.py` — `usage_claude_cache_minutes` defaults to `usage_cache_minutes` (including when that is changed), accepts 0, refuses a negative value.
- [x] 1.8 Test: a stale block with no kept reading and a refused read is not the base of an estimate and the stale rule applies to it as before; a decision from a block does not change the guard's own cache file or its cool-down.
- [x] 1.9 Add `usage_claude_cache_minutes` to `ClaudeLimitsConfig` in `config.py` (unset follows `usage_cache_minutes`, `ge=0`), and `CLAUDE_JSON = "claude-json"` to `pipeline/usage_calls.py`, excluded wherever `CACHE` is excluded from endpoint calls (`next_call_at`, `_window`, `_safe_interval`), with its own share on `CallWindow` and in `rate_line`.
- [x] 1.10 In `pipeline/usage_guard.py` add the step: the editor's block through `_unspent(read_cached_usage())`, its age against the effective window, the fresher of the two readings, judged with `trust_age=True`, recorded as `claude-json` with its age and returned from `decide_start` before `_too_soon` and `fresh()`; make `held_usage` prefer the same winner; leave `read_cached_usage` as the stale fallback; the label carries the age; do not write the block anywhere.
- [x] 1.11 Update `docs/configuration.md` (the usage settings block), the `abk-config` skill's `limits:` block and `docs/architecture.md`'s usage guard paragraph and call-record paragraph: the read order, the setting, that the file's block is refreshed only by interactive Claude Code use (say which actions are known to refresh it, only those seen to), that the credits rule does not apply to it, the label and the record outcome and the rate line. Add one bullet under `## Unreleased` in `CHANGELOG.md` as `AGENTS.md`'s Changelog section says, naming no installation.
