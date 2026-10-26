# Proposal

## Why

The guard has two cached sources and reads them in the wrong order for a person who works at the same account. Its own reading
(`usage-cache.json`) is kept for the cache time, then the endpoint is asked, and Claude Code's own cache (`~/.claude.json`,
`cachedUsageUtilization`) is used only when that call fails. Yet that block is refreshed by interactive Claude Code use, which is exactly
the consumption the pipeline cannot see, and when it is fresh it is as good a reading as the endpoint would give. Asking the endpoint
instead costs a call that is refused about one time in nine even at about one call an hour (a 429 with a retry time of zero), and a
refusal widens the interval and, until `a-refused-usage-read-with-headroom-does-not-pause` is built, can pause the whole pipeline.

Nothing refreshes that block while only headless runs work (verified: its block was about 57 hours old when this was written, though
the file itself is rewritten daily). So the step helps only when someone is using Claude Code, and then it is a free, fresh reading that
includes their spend. When the block is old the guard does exactly what it does today.

## What Changes

- **A fresh reading in `~/.claude.json` is used before the endpoint is asked:** when its block's `fetchedAtMs` is younger than
  `usage_claude_cache_minutes`, no window it describes has reset, and it is fresher than the guard's own kept reading (a tie goes to the
  guard's own), the guard decides from it and makes no call, even inside the minimum interval.
- **Same validation as any reading:** both windows present and parsed, no reset passed; an unreadable, torn, missing or malformed file reads
  as absent, silently, as today. File modification time is never used: only `fetchedAtMs` says how old the block is.
- **It is only a reading:** never written to the guard's own cache, never the base of an estimate, never starts a cool-down or moves the
  interval. Its credits fields are absent, so the credits rule does not fire on it (as for the fallback today).
- **Labelled and counted:** the reason and `abk status` say `usage: ... (claude.json, 6m old)`; the call record logs outcome `claude-json`
  with the age; the call-rate line counts it apart from the cache. A `claude-json` line is not a call to the endpoint.
- **A setting:** `usage_claude_cache_minutes` defaults to `usage_cache_minutes`; 0 turns the step off and restores today's order.

## Impact

- agent-build-kit: the usage guard's read order and `decide_start`, `held_usage` for the status command, the call record and its rate line,
  one setting, the configuration and architecture documents, the config skill, the changelog.
- Spec: `usage-pause` (modifies one requirement, adds four).
