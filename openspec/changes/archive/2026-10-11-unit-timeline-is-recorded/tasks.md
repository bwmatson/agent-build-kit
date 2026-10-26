# Tasks

Acceptance: none — every behaviour here is a record or a report over records, and tier-1 tests with a recorded fixture prove each one.

Priority: 2

## 1. [agent-build-kit] [tier1] Wait reasons, the decision log, timestamps, spans and samples

Done when each not-running unit has one reason, a change of reason is logged once and survives a restart, a unit remembers when it became ready
and when a person first answered, waits and review rounds are spans with a reason or cause, and the running pass writes a sample each refresh.

- [x] 1.1 Test: `WaitReason` is a `StrEnum` whose `slot` and `usage_pause` members equal the strings already in the ledger; a unit blocked on a
      prerequisite, at the limit, at the concurrency cap, paused, leased, in backoff, in review, held or failed, and one startable gets exactly one
      reason each, and `_evaluate` returns the same units as before.
- [x] 1.2 Test: the recorder writes only when the reason or what it waits on changes, writes nothing over many unchanged ticks, writes a closing
      record when the wait ends, resumes from the file's tail after a restart without repeating the last reason, and a failing write does not fail a pass.
- [x] 1.3 Test: `ready_at` is set once, not reset by a rework or a later wait, and is absent for a unit older than this release; start and review
      entry read from `history`; `first_human_activity_at` is set by the first poll that sees a comment or review not in the pipeline's own posts and
      never by the pipeline's own post.
- [x] 1.4 Test: the unit store round-trips both fields, omits them while unset, drops them when an older release reads them unset, and an older
      release's read of a set value is refused naming the unit, field and value.
- [x] 1.5 Test: a wait with each new reason is one span with `waited` set and no node and is counted once by the report and the wait metric; a
      review round is a span with cause review, check or conflict; a usage-paused unit's effective state is `paused` with no stored state change.
- [x] 1.6 Test: each refresh of `_schedule` writes one `sample` row with the named counts, a ledger reader skips it, and the gauges `abk.slots.free` and
      `abk.slots.idle_with_ready` are set without a unit or change attribute.
- [x] 1.7 Implement `WaitReason`, the reason function used by `_evaluate`/`run_round`, `WaitRecorder`, the two `StoredUnit` fields, the span causes, the
      samples and the gauges.
- [x] 1.8 Update `docs/architecture.md` (state-directory table, ledger kinds, metrics table), `docs/configuration.md` and the `abk-pipeline` skill, and
      add a changelog entry that says a store with these fields set needs this release.

## 2. [agent-build-kit] [tier1] Filled summaries and `abk report --waits`

Done when a summary carries all three wait figures for every unit and `abk report --waits` reproduces the analysis table from a recorded fixture.

- [x] 2.1 Test: over the worked-example fixture (72 merged units, a ledger, a decision log and a units file) the report gives planned 1,343 h,
      in review 172 h, running 93 h, agent 11.6 h, 47 of 87 hours idle, 17 of them with a full queue and 30 with room.
- [x] 2.2 Test: the causes (planned-blocked, planned-ready, running-agent, running-checks, running-other, in-review-person, in-review-round, paused,
      failed) sum to each unit's wall time, `--by unit` and `--by day` regroup the same total, `--json` carries the same rows, and a unit with no
      records reads as absent, not zero.
- [x] 2.3 Test: the roll-up at archive writes `slot_wait_ms`, `pause_wait_ms` and `review_wait_ms` (split person, round, checks) for every unit, an older
      summary with null fields still loads, and the report prints the estimate ratio per kind when estimates exist.
- [x] 2.4 Implement the wait rows on `Report`/`ReportRow`, the idle-hours computation from samples, the roll-up fill and `abk report --waits`.
- [x] 2.5 Document the flag in `docs/cli.md` and the `abk-pipeline` skill, and add a changelog entry.

## 3. [agent-build-kit] [tier1] Ledger completeness and retention

Done when every agent call on every path leaves exactly one ledger row and the files this change adds are bounded.

- [x] 3.1 Test: for a new, a resumed and a continued call, under the Claude and the ACP runtime, exactly one ledger row is written per call.
- [x] 3.2 Test: the decision log is trimmed to `retention.decision_log_mb` keeping the newest lines; a unit's log older than `retention.unit_log_days`
      is removed after its summary line is written, a unit without a summary keeps its log, and archiving still removes a change's logs.
- [x] 3.3 Fix each path 3.1 finds that writes none or more than one row, and implement the retention and its settings.
- [x] 3.4 Update `docs/configuration.md`, `docs/architecture.md` (run logs) and the `abk-config` skill, and add a changelog entry.
