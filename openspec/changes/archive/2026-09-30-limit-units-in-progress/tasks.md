# Tasks

Acceptance: none — this is a readiness rule inside the pipeline, with no surface a
consumer drives; what proves it is tier-1 tests over the readiness rules, the
configuration and the reporting.

## 1. [agent-build-kit] [tier1] A limit on units in progress, replacing the pull request ceiling

Done when a unit that has been started and not finished counts against one
limit whether or not it has a pull request, the limit only ever stops a unit
that has never started, `max_open_prs` and its code are gone, and a full queue
is reported with the units holding it.

- [x] 1.1 Test: running, in review, held, failed, and planned with a pull
      request or a step to resume from all count as in progress; merged,
      closed, satisfied, unplanned without a pull request, and planned with
      neither — blocked on a dependency or not — do not.
- [x] 1.2 Test: at the limit a ready unit that has never started is not started
      and stays planned; when one in progress merges it may start.
- [x] 1.3 Test: at and over the limit a rework, a resume from a paused build and
      a unit finishing its review loop all proceed, and the finishing unit opens
      its pull request.
- [x] 1.4 Test: a paused unit with no pull request and a failed unit each hold a
      place, so with four started units, one of them failed, and a limit of
      five, exactly one new unit may start.
- [x] 1.5 Test: `limits.max_units_in_progress` defaults to 5 and must be at
      least 1, and `limits.max_open_prs` is no longer accepted.
- [x] 1.6 Test: a pass that starts nothing new because of the limit logs the
      count, the limit and the units in progress by state, and `abk status`
      says the same.
- [x] 1.7 Replace the open pull request count and the builds-heading count with
      the in-progress predicate, and gate only never-started units on it.
- [x] 1.8 Remove `max_open_prs` and the pull request counting behind it, add
      `max_units_in_progress`, and update the reporting.
- [x] 1.9 Update `docs/configuration.md`, `docs/architecture.md`, `docs/cli.md`,
      the `abk-config` and `abk-pipeline` skills, and the changelog.
