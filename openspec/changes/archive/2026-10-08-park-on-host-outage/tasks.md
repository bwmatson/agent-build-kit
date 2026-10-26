# Tasks

Acceptance: none — scheduling and routing inside the pipeline; tier-1 tests with a fake forge and
clock prove it.

## 1. [agent-build-kit] [tier1] Park on a host outage and resume at the pull request step

Needs: forge-retry-layer group 1 merged — the unavailable error this catches
Needs: status-not-wording group 1 merged — the cause field the pass readmits by

Done when a step that cannot reach the host parks its unit with a cause and error text, the pass
readmits it with growing backoff, and a pushed, approved unit resumes straight at the pull request
step.

- [x] 1.1 Test: a pull request create answered 500 on every attempt parks an approved, pushed unit
      as planned with cause `host_unavailable`, the step and the error text, and does not fail it.
- [x] 1.2 Test: the pass readmits it after its backoff (1, 2, 5, 10, 30 minutes by consecutive
      parking, from a fake clock), skips it before then with the remaining time logged, and a
      success resets the count.
- [x] 1.3 Test: a step that raises another error fails the unit and records its text and step, for
      any exception type.
- [x] 1.4 Test: with `approved == pushed == head`, a resume after an `open_pr` failure goes to
      `open_pr` for a tier 2 unit without running tier 2, and for a unit with saved feedback
      without rework; a unit whose head moved still takes the checks path.
- [x] 1.5 Catch the unavailable error in the step wrapper and `build_unit`, add `parked_attempts`
      and the backoff to the pass's readmission, record the step and error on every failure, and
      route `after_prepare` as specified.
- [x] 1.6 Update `docs/unit-graph.md`, `docs/architecture.md` and the `abk-pipeline` skill, and add
      a changelog entry.
