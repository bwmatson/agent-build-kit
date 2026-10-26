# Tasks

Acceptance: none — the endpoint's answers and the clock are faked; tier-1 tests prove each behaviour.

## 1. [agent-build-kit] [tier1] Record every use and show the rate

Needs: usage-pause-deadline group 2 merged — the cache and the cool-down this records and tunes

Done when every use of the endpoint is in a local record, the rate is derived from it and printed, and it is exported.

- [x] 1.1 Test: a call, a refusal with rate-limit and retry headers, a timeout and an error each append a line with time, caller,
      outcome, status, latency and the headers; a reading answered from the cache appends a line with its age; no line holds a
      token; lines older than a week are dropped; archiving a change leaves the record; a call made by the runtime's
      usage status or by the tracks runner is recorded under its own caller.
- [x] 1.2 Test: from a recorded run, the reading gives the calls by outcome and caller over the last hour and the last day, the
      cache share, the refusals with the quiet time and the calls in the fifteen minutes before each, and the shortest interval
      between successful calls not followed by a refusal; a day with no refusals gives none.
- [x] 1.3 Test: the status command prints the calls in the hour, the refusals, the cache share and the interval in one line, and
      the figures are exported as a counter by outcome and caller and a gauge of the interval in whole seconds, and shown from the record when the metrics store is
      not available.
- [x] 1.4 Add the record (`usage-calls.jsonl` in the state directory, with its gitignore line in the template), recorded
      in the one read every caller goes through, the reading, the status line and the metric.
- [x] 1.5 Document the record and the reading in `docs/architecture.md` and add a changelog entry.

## 2. [agent-build-kit] [tier1] The interval adapts

Done when the time a reading is kept doubles after a refusal, halves after a quiet, and the status command says why.

- [x] 2.1 Test: a refusal doubles the time up to the configured maximum; a refusal that names a longer retry time is respected;
      the same time without a refusal halves it, never below the configured value; the status command names the interval and
      what set it.
- [x] 2.2 Add the adaptation and its maximum setting, and use it for the cache time.
- [x] 2.3 Document the setting in `docs/configuration.md` and add a changelog entry.
