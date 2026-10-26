# Tasks

Acceptance: none — readings, thresholds and the clock are faked; tier-1 tests prove each decision.

## 1. [agent-build-kit] [tier1] Decide whether a fresh reading is needed

Needs: usage-pause-deadline group 2 merged — the cache time and the cool-down this uses as its minimum interval

Done when the guard asks the endpoint only when a fresh reading could change a decision, and never more often than the interval.

- [x] 1.1 Test: far from the threshold with a long time to the reset, a start is allowed from a reading older than the cache time with
      no call; a reading at or over the threshold before the reset refuses without a call until the time the threshold reaches it or
      the window resets; a reading with less headroom than could have been added, a reading of a window that has reset, and no reading
      each make a call.
- [x] 1.2 Test: within the minimum interval a decision that needs a fresh reading refuses the start for the time left, with a reason that
      says so, and makes no call.
- [x] 1.3 Test: the status command prints the held reading, its age and source and calls nothing; with a refresh it calls, subject to the
      interval.
- [x] 1.4 Test: a round whose every candidate is excluded by `--only`, a lease or a backoff asks for no reading; one with a
      candidate that is not excluded does.
- [x] 1.5 Add the decision rule, the minimum interval and the status refresh option, pass the exclusion set into the round's
      decision, and route the start check and the resume time through it.
- [x] 1.6 Document the rule in `docs/architecture.md` and `docs/cli.md`, and add a changelog entry.
- [x] 1.7 Correct the docs that still claim a step that ends having written nothing is judged against the usage window
      (the check no longer exists): the usage guard paragraph and the implement step in `docs/architecture.md`, the
      `implement` row of the node table in `docs/unit-graph.md`, and the `running` row of the unit states table in the
      pipeline skill.

## 2. [agent-build-kit] [tier1] How fast usage can climb

Needs: usage-api-observability group 1 merged — the record of readings the rate is taken from

Done when the amount of usage that could have been added since a reading comes from the fastest climb seen.

- [x] 2.1 Test: from a recorded run the fastest climb per window in points a minute is derived, times the minutes since the reading, with the
      margin; with no record the configured floor is used, and the floor is a lower bound when the record shows less.
- [x] 2.2 Test: the session and week windows use their own rates.
- [x] 2.3 Derive the climb from the record, add the floor and margin settings, and use them in the rule.
- [x] 2.4 Document the settings in `docs/configuration.md` and add a changelog entry.
