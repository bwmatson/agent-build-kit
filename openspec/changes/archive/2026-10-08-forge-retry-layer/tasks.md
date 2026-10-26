# Tasks

Acceptance: none — one layer over a fake forge; tier-1 tests with a fake clock and a fake forge
prove it. The incident's own path is exercised in `park-on-host-outage`.

## 1. [agent-build-kit] [tier1] One retry layer, declared per operation

Done when every forge operation has a declared kind, one wrapper applies the retry rules for both
hosts, the per-library loops are gone, and every earlier retry test passes against the wrapper.

- [x] 1.1 Test: every method of the forge protocol has a table entry; a missing one fails.
- [x] 1.2 Test: with a fake forge and clock, a read and an idempotent write repeat on a server
      error or a network failure, up to the bound, with backoff and jitter, and fail with the
      unavailable error after it; a rate limit waits the larger of the backoff and its hint, and a
      hint over the ceiling fails at once.
- [x] 1.3 Test: a create that fails transiently calls its declared read: a hit returns that
      result without a second create; a miss repeats the create; a failing read counts as an
      attempt; with no declared read a create is never repeated.
- [x] 1.4 Test: an advisory call that cannot complete is logged, counted and returns its neutral
      value; authentication, not-found and other client errors are never retried.
- [x] 1.5 Test: each retry logs its operation, attempt and cause and increments the counter by
      operation and outcome; the total deadline stops a run of long waits.
- [x] 1.6 Port the transport's and the GitHub client's retry tests to the wrapper, then remove
      both retry loops; assert that no layer other than the wrapper repeats a call.
- [x] 1.7 Add the operation table, `ResilientForge`, `HostUnavailable`, the deadline setting and
      the counter, return wrapped forges from the registry, and update the documents.
- [x] 1.8 Describe the layer in `docs/code-forges.md` and `docs/architecture.md`, document the
      settings, and add a changelog entry.
