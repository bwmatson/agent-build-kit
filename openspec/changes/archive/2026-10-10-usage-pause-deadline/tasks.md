# Tasks

Acceptance: none — readings, clocks and the host's usage answers are faked at the boundary; tier-1 tests prove it.

## 1. [agent-build-kit] [tier1] A pause never points into the past

Done when no pause ends before it is written and a stale reading pauses briefly with a clear reason.

- [x] 1.1 Test: with a reset time in the past the deadline is after now by the unknown-retry interval; with one in
      the future it is that time plus the grace once; the spend-limit and credits branches never end
      before now.
- [x] 1.2 Test: a stale cached reading refuses a start for the stale-retry interval (five minutes by default, set by
      the setting), the reason says it is stale and
      names its source, and its window is not used; a reading served from the cache file has a source of its own
      and is not exempt from the staleness test.
- [x] 1.3 Test: the pause line shows local time and a time after the moment it is printed.
- [x] 1.4 Move the unknown-retry interval and the grace into `pause.py` (removing the copies in `usage_guard.py`),
      add the stale-retry interval and its setting, clamp the deadline in one place, apply the grace once, treat a
      past reset as unknown, give a cache-served reading its own source, and change the stale branch and the line.
- [x] 1.5 Document the rule in `docs/architecture.md` and the pipeline skill, and add a changelog entry.

## 2. [agent-build-kit] [tier1] A failed live read is absorbed

Done when one failed request does not pause anything and the cause of a failure is logged.

- [x] 2.1 Test: a good reading is answered from the cache for the configured time, fifteen minutes by default, to the
      guard and to the status command in any process; a setting changes the time; a reading is not used past its window's
      reset.
- [x] 2.2 Test: a rate-limit answer starts a cool-down of the time the answer names, or the default, during which no call is
      made; the cool-down is kept with the cached reading so a second process honours it; a timeout is retried once and a
      rate-limit answer is not retried at once.
- [x] 2.3 Test: a live call that fails once and then succeeds is used; a live call that keeps failing falls
      to a good live reading younger than the fallback age, then to the editor's reading, and the reason
      names the source.
- [x] 2.4 Test: a failed live call logs its cause (status code or exception name) once per tick and is not
      cached as a reading; the fallback age is configurable.
- [x] 2.5 Add the cache time and its setting on `ClaudeLimitsConfig`, the retry, the kept last good reading with its
      age, the order of sources, the logging and the setting.
- [x] 2.6 Send every reader through the cache: `ClaudeCodeRuntime.get_usage_status` (which calls the live read
      directly), the pass's check, the tracks runner, and `Node.gate`, which reads once for `may_start` and again for
      `resume_at`; the gate takes one reading for both.
- [x] 2.7 Document the order and the setting in `docs/configuration.md` and `docs/architecture.md` (the
      "cached three minutes" sentence in the usage guard paragraph and the `usage-cache.json` row of the state
      table, "three-minute TTL"), and add a changelog entry.

## 3. [agent-build-kit] [tier1] A refused start stops only that unit

Done when a usage pause on one unit leaves the pass refreshing, admitting and resuming.

- [x] 3.1 Test: a unit refused for usage does not stop the pass; the next round records a merge and a new
      comment, asks the guard again, and admits builds when it allows.
- [x] 3.2 Test: units paused for usage resume within the pass when the guard allows, and keep their places
      in progress meanwhile.
- [x] 3.3 Test: when the reading says the window is used up every start is refused each round; a `rate_limit` pause
      written by a build still stops new builds for the pass until its deadline.
- [x] 3.4 Remove the pass-wide stop on a usage pause, re-ask the guard each round, and resume paused units in
      the pass.
- [x] 3.5 Update `docs/cli.md` and the pipeline skill, and add a changelog entry.

## 4. [agent-build-kit] [tier1] The usage module is the only authority

Needs: fix-flaky-tests-cli-test-tick-committed-marker-py-test-a-tick-1a4c429b group 1 merged — flaky test tests/cli/test_tick_committed_marker.py::test_a_tick_delivers_a_commit_made_and_not_delivered_once_and_removes_the_lease

Priority: 1

Done when every tick asks the usage module, the module alone decides whether to call the endpoint, and no stale
marker refuses a start.

- [x] 4.1 Test: twenty asks across fifteen minutes, from several threads and processes, make one call to the endpoint;
      a process that finds the refresh lock held serves the last good reading and does not call.
- [x] 4.2 Test: outside a `rate_limit` pause, a marker alone refuses nothing: with a usage marker whose `until` is in the
      future and a guard that allows, the tick start, the pass's check and the gate start work and the marker is cleared;
      the pass's stop flag and the tick's "paused" outcome read only a `rate_limit` marker.
- [x] 4.3 Test: a cached reading, the last good one kept past the cache time and the editor's reading alike, is not used
      past the reset of the window it describes.
- [x] 4.4 Test: a step that began under the threshold is not stopped when the next reading is over it; the gate refuses
      the next start.
- [x] 4.5 Test: a `rate_limit` pause ends at its deadline within the pass: once the deadline has passed, ready units are
      submitted in the same pass, and the stop is re-evaluated each round rather than kept as a flag.
- [x] 4.6 Test: the cache emits a count for each hit, miss, expiry and wait on the refresh lock, through the existing
      telemetry, and the per-call record is unchanged.
- [x] 4.7 Take a file lock around "read the cache file, call, write it" in `read_live_usage`, with the cool-down read
      under it, and let a process that finds it held return the last good reading; write the cache file whole so a
      reader never sees half of it.
- [x] 4.8 Make the marker an authority only for a `rate_limit` pause in every reader (`cli/pipeline.py`'s pass loop and
      tick outcome); keep each pause's stop time-bounded and re-evaluated each round; stop using a reading past its
      window's reset on the editor's source too; add the cache counters.
- [x] 4.9 Update `docs/architecture.md` (the usage guard paragraph: every run asks, the module decides, the run-time
      rule, the counters), `docs/configuration.md` and the pipeline skill, and add a changelog entry.
