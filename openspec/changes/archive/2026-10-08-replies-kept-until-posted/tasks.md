# Tasks

Acceptance: none — bookkeeping inside the pipeline; tier-1 tests with a fake forge prove it.

## 1. [agent-build-kit] [tier1] Replies and the close are kept until done

Needs: forge-landed-checks group 1 merged — the existing-comment read these rely on

Done when a failed reply or close is retried by a later pass without being lost or duplicated, and
`abk status` shows what is waiting.

- [x] 1.1 Test: with a forge refusing every attempt, the unposted replies stay in the unit's
      pending list and the posted ones leave it; the next pass with a working forge posts the
      rest once.
- [x] 1.2 Test: a reply the forge reports as already present (the existing-comment read) is
      treated as posted, its id recorded as the pipeline's own, and not posted again.
- [x] 1.3 Test: a satisfied unit's close with a failing close is retried by the pass; the reason is
      posted once; on success the pending record is removed.
- [x] 1.4 Test: `abk status` lists a unit with unposted replies or a pending close and why.
- [x] 1.5 Return the unposted replies from the reply step and store them back, add the pending close
      record and its retry in the pass's round, and add the status lines.
- [x] 1.6 Update `docs/architecture.md` and the changelog.
