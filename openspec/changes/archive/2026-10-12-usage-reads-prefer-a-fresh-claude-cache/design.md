# Design

## What was checked, and where

Read-only against the agent-build-kit checkout (origin/main); paths are under `src/agent_build_kit/`.

- `pipeline/usage_guard.py`: `read_cached_usage` (714-740) reads `~/.claude.json` (`DEFAULT_ANCHOR_PATH`, 91): `cachedUsageUtilization`
  with `utilization.five_hour` / `seven_day` (each `utilization` and `resets_at`) and `fetchedAtMs`, giving a reading with source
  `claude.json`, `observed_at` from `fetchedAtMs`, and `credits_enabled=False`, `credits_used_dollars=0.0`, `spend_limit_reached=False`
  (the comment there says the credits rule "simply doesn't fire on a fallback reading"). Every failure to read is `None`
  (`OSError, ValueError, KeyError, TypeError`), so an unreadable or malformed file is already silently absent.
- Today's order: `current_usage` (788-790) is `read_live_usage() or _unspent(read_cached_usage())`: the guard's own kept reading while younger
  than the cache time (`serve`, 676-691, which records a `cache` call), then the endpoint under the refresh lock, then the editor's block
  only when the call yields nothing. `held_usage` (793-797) is the kept reading, else the editor's, with no call, for the status command.
  `_unspent` (781-785) drops a reading when a window it describes has reset (`_past_reset`, 519-524). `MAX_ANCHOR_AGE` (108) is one hour:
  `may_start_unit` (915) refuses a non-live reading older than that unless `trust_age`.
- `decide_start` (979-1029): the guard's own held reading answers when it refuses or `_headroom_holds`; if it is younger than the kept time a
  fresh read is taken; otherwise `next_call_at` may refuse with `_too_soon` before any call; else `fresh()`. A step that answers without a
  call therefore has to sit before `_too_soon`, not only inside `read_live_usage`, or a fresh block would be ignored exactly when the
  minimum interval holds the endpoint back.
- `pipeline/usage_calls.py`: `UsageCall.outcome` is `ok`, `rate_limited`, `timeout`, `error` or `cache` (`CACHE`, 24). Three readers
  treat "not `cache`" as "a call to the endpoint": `next_call_at` (usage_guard 800-807), `_window` (124-150, `endpoint`, the refusal's
  quiet time and calls before it) and `_safe_interval` (153-171). A new outcome must be excluded from all three or a free reading would
  move the next permitted call and corrupt the safe interval. `rate_line` (277-283) prints `P% from the cache` from
  `CallWindow.cache_share`, which counts only `CACHE`.
- Config: `ClaudeLimitsConfig` (`config.py` 219-231) holds `usage_cache_minutes: Annotated[int, Field(gt=0)] = 15`. Docs:
  `docs/configuration.md` 112-124, the `abk-config` skill (`limits:` block, line 77), `docs/architecture.md` usage guard paragraph (876-913)
  and the call-record paragraph after it.

Verified on the machine this was written on, outside the code: the block is refreshed only by interactive use; the guard's own call
does not update it; on 2026-10-11 its block was about 57 hours old (fetched 10-09) while the file was modified that day, so the file's
modification time says nothing about the block and only `fetchedAtMs` counts.

## The read order

For a decision (a start, or a resume), the guard takes the first that applies:

1. **The fresher of the two cached readings, when either is fresh.** The guard's own kept reading is fresh while younger than the kept
   time, as today. The editor's block is fresh when `now - fetchedAtMs` is under `usage_claude_cache_minutes`, no window it describes has
   reset (`_unspent`), and both windows parsed. When both are fresh the one with the later observation time wins; a tie goes to the
   guard's own. When only one is fresh it is the one used.
2. The endpoint, as `usage-read-on-decision` and the interval rule say (and, once `a-refused-usage-read-with-headroom-does-not-pause`
   is built, its estimate when the read is refused).
3. The editor's block as the stale fallback for a failed call, exactly as today, with its own age rules (`MAX_ANCHOR_AGE`).
4. Nothing, which pauses.

Step 1 answers without a call and before `_too_soon`: a fresh block settles the decision even inside the minimum interval. It is judged
by `may_start_unit` like any reading (thresholds, ramp, relief), so a fresh block over a threshold refuses and pauses exactly as an
actual reading does. Because it answers, a fresh block that is fresher than a still-fresh guard reading also changes what the guard's
own held reading would have decided: that is the point (the person's spend is in it).

The new window is `usage_claude_cache_minutes`, not the adaptive kept time: the kept time widens after refusals to protect the endpoint,
and this step touches no endpoint, so widening it would only make the guard trust an older figure. Its effective value is also capped at
`MAX_ANCHOR_AGE`, so a block the stale rule would refuse is never "fresh" here.

The `decide_start` change is small because the guard already holds `_kept_reading` and `read_cached_usage`: compute the editor's
reading once (`_unspent(read_cached_usage())`), compare its age with the window and with the held reading's, and, when it wins, judge it
with `trust_age=True`, record a `claude-json` call and return. When the setting is 0, or the block does not qualify, nothing about
today's path changes. `held_usage` (status, no call) prefers the same winner, so the status line shows what the guard would use.

## The interaction with the estimate

`a-refused-usage-read-with-headroom-does-not-pause` makes an estimate from the guard's own kept reading, of any age, when a read is refused
or unreadable, and says the editor's reading is never the base of an estimate: a stale block must not seed one. This change keeps that
exactly. The block is used here only as a *fresh reading*, which needs no estimate, and its figure is never added to an allowance, never
stored as the kept reading, and never resets or increments the count of starts made on an estimate (that count belongs to the guard's own
reading). When the block is not fresh this step does nothing and the estimate rule is unchanged. The one useful combination follows by
itself: a fresh block fresher than the guard's own reading is simply a better reading, taken before the endpoint is asked, so a
refusal that would have led to an estimate may never happen.

## The credits rule

The block has no credits state, so `credits_enabled` is false, `credits_used_dollars` zero and `spend_limit_reached` false, and the
credits and spend-limit backstops in `may_start_unit` (897-912) cannot fire on a reading from it, as already true of the fallback. The
threshold check is what protects the account on this path. This is a real, accepted weakening: while the block is fresh and
a window is full of credits the guard sees only percent used. A person who wants the backstop sets `usage_claude_cache_minutes` to 0,
or relies on the guard's own reading (which carries credits) being fresher or equal: a tie goes to it. The status line says the source so
the person can tell.

## Labels and the record

- The reason and status say `usage: session 12%/92%, weekly 31%/80% (claude.json, 6m old)`: the existing source label (`claude.json`)
  plus the age, in minutes, of the block.
- `usage_calls.py` gains `CLAUDE_JSON = "claude-json"`; the call is recorded with that outcome and the block's age, as `cache` is. It is
  not a call to the endpoint: `next_call_at`, the refusal bookkeeping in `_window` and `_safe_interval` exclude it as they exclude `cache`.
- `CallWindow` gains the share answered from the file, and `rate_line` reads `... N% from the cache, M% from claude.json, safe interval`.
  The cache's own share is unchanged (`CACHE` only). The caller and counts by outcome already come from the record.
- The cache telemetry events (`abk.usage.cache`) are not changed; `hit` still means the guard's own cache.

## The setting

`usage_claude_cache_minutes: Annotated[int, Field(ge=0)] | None = None` on `ClaudeLimitsConfig`: unset means `usage_cache_minutes`; 0 turns
the step off; a negative value is refused. The effective window is `min(setting, MAX_ANCHOR_AGE)`. A person who works interactively all day
can raise it (the block is then trusted for longer, at the cost of a staler figure); one who never uses Claude Code interactively loses
nothing, because the block is then old and the step never applies.

## UNVERIFIED, for the builder

- **Which interactive actions refresh the block.** Expected: the CLI's `/usage` panel, the statusline, and a normal turn. Not
  established, and whether the editor extension refreshes it at all is not established (its session on the day this was written
  did not). The step is correct either way: a block that is never fresh is never used. The builder may say in the docs which actions are
  known to refresh it, but only those it has seen refresh it.
- **Atomicity of `~/.claude.json` writes.** Not known whether Claude Code writes the file atomically (rename) or in place. A
  concurrent in-place write can leave a torn file, whose JSON would not parse, or one that parses with a stale block. The reader already
  treats every parse error as absent; the rule here is that a torn or partial read is absent and never zero usage. The builder
  should keep the existing `except` that returns `None`, should not default a missing figure to 0, and tests it with a truncated file.
  A file that parses but has a block older than the window is not used, so a torn-but-parsing file cannot make the block look fresher.
- That `fetchedAtMs` is the time the numbers were taken and not the time the file was written; it is what the code reads today and was
  seen to differ from the file's modification time by two days.

## What this does not change

Thresholds and their ramp, the endpoint call and its cool-down, the interval and its adaptation, the guard's own cache file and the
estimate, `MAX_ANCHOR_AGE` for the stale fallback, the pause marker, `pause.py`. The block is never written by the pipeline.

## Risks

- A fresh block can lag the account: it is refreshed when the person's session refreshes it, so a figure six minutes old can be six
  minutes behind a consumer the person did not run interactively. It is no staler than the guard's own reading would be at the same age,
  which is why the window is the cache time.
- The credits backstop does not apply on this path (above).
- Two readings that disagree (the block fresher but lower than the guard's own): the fresher wins; usage only rises within a window, so
  a lower, later figure is a later truth, not an error.

## Where the delta lands, and the dependency

The main `usage-pause` spec has no requirement that states the read order as a whole. The read-order wording sits in `A failed live read is
absorbed before anything pauses` (live reading, then last good, then the editor's) and in `A reading is not used past its window`, both
of which `a-refused-usage-read-with-headroom-does-not-pause` rewrites. This change leaves both untouched: its step runs before the endpoint
is asked, and the editor's block as the stale fallback keeps the sibling's wording. So the delta MODIFIES only `The usage endpoint is asked
only when a fresh reading could change a decision`, a requirement that exists in the main spec and that the sibling does not change (all
its original scenarios are copied), and ADDS the rest; no requirement in the delta depends on text that exists only in the sibling's
delta. Group 1 still carries a `Needs: ... group 1 merged` line, because the dependency is in the code: both changes edit `decide_start`
(the sibling inserts the estimate at its two refusal points; this adds a step before `_too_soon`), and building on the trunk after the
sibling merges avoids a textual conflict in that function.
