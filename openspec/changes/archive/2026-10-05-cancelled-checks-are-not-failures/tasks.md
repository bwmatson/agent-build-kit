# Tasks

Acceptance: none — poller and forge behaviour inside the pipeline; tier-1 tests
over the polls, the handlers and both forges' conclusions prove it.

## 1. [agent-build-kit] [tier1] Re-run cancelled checks instead of reworking

Done when a cancelled check raises no rework, is re-run by the runner up to a
bound per head commit, and a failing or timed-out check is reworked as before on
both hosts.

- [x] 1.1 Test: GitHub and Azure DevOps pull requests with `CANCELLED` /
      `canceled` checks report them in `cancelled_checks` and not in
      `failing_checks`; `FAILURE` and `TIMED_OUT` stay in `failing_checks`.
- [x] 1.2 Test: a poll that newly finds cancelled checks dispatches a re-run
      event and no rework; a mixed outcome dispatches both.
- [x] 1.3 Test: the re-run handler asks the forge to re-run the cancelled
      runs, counts it against the unit's head commit, resets the count when the
      head moves, and past `limits.max_check_reruns` asks for nothing and logs
      that the host keeps cancelling the checks.
- [x] 1.4 Test: a re-run check that then fails is reworked through the normal
      failing-checks path with its log.
- [x] 1.5 Add `cancelled_checks` to the pull request model and both forges,
      the re-run event and handler, the forge `rerun_checks` operation, the
      per-head count on the stored unit (loading older units unchanged), and
      `limits.max_check_reruns` (default 2) with its documentation.
- [x] 1.6 Describe it in `docs/architecture.md` where the poller's events are
      listed, in `docs/code-forges.md` for the new forge operation, and add a
      changelog entry.
