# Tasks

Acceptance: none — every figure is proved by tier 1 tests over recorded streams and fixture ledgers; running the backfill
on an installation is a person's step after the build.

## 1. [agent-build-kit] [tier1] Both costs on every row, and the sums become right

Priority: 1

Done when each agent row carries a `cost` object with the call's own spend and the session's running total, a session of
N calls sums to its final cumulative, and every sum, the report, the summaries and the cost counter read the incremental
figure.

- [x] 1.1 Test: per runtime, the record's semantics. The Claude Code runtime's first call of a session records the total as
      incremental and cumulative with basis `first`; a resumed call records the difference with basis `derived`; a total
      below the baseline starts a new baseline and is noted; ACP calls record their amount as `cumulative_usd` with basis
      `derived` or `first`; a gateway-attributed call records the gateway's figure as incremental, the running sum as
      cumulative and the runtime's own incremental figure as `reported_usd`; a figure the runtime does not report is absent.
- [x] 1.2 Test: the baseline sources. The recorded `AgentSession` carries the call's cumulative figure to the next call and
      drops it with the session (`_sessions_after`, `ported_session`); a resume with no recorded baseline reads the last
      ledger record with the same session id; with neither, the row has basis `unknown` and no incremental figure, never
      the total.
- [x] 1.3 Test: the reader. A session of N calls, some resumed under one node and round, sums its `incremental_usd` to the
      final cumulative; the one-record-per-unit-node-round rule is unchanged; a line with the object ignores flat fields.
- [x] 1.4 Test: the report and the summaries. A unit's, a change's, a repository's and a day's cost equal the session
      increments (use a fixture of the shape in the design's worked session: 2.63, 2.86, 7.69, 2.22, 4.38, 0.84, 0.78,
      2.52, 1.47 summing to 25.39); the per-session `cumulative` column is shown; a session whose increments do not add up
      is flagged; the summary written at archive sums increments and its breakdown still sums to its totals; the web UI's
      usage view and the `abk.agent.cost` counter read the incremental figure and add nothing for an absent one.
- [x] 1.5 Test: legacy rows. A line with a flat `cost_usd` and no object is read with basis `legacy` and the old figure
      kept apart; it is never summed as incremental; the report counts and lists it and shows its total on a line of its
      own; a summary with no breakdown and a ledger line with unknown fields still load.
- [x] 1.6 Add `CostBasis` as a `StrEnum` and the `cost` object to `UsageRecord`; make `_spent` in `runtimes/claude_code.py`
      report the total as cumulative; have `runtimes/acp.py` report its cumulative figure and take the ledger fallback; carry
      the baseline on `AgentSession` in `graph/state.py` and through `_recorder` in `graph/nodes.py`; make `records_in` and
      `_combine` in `pipeline/usage_ledger.py` add incremental figures and read legacy lines; move `export_call`,
      `pipeline/usage_report.py` (including `roll_up_change`, the per-session column and the flag) and `serve/metrics.py`
      to the incremental figure.
- [x] 1.7 Document the `cost` object, its basis values, the legacy reading and the date from which the cost counter is
      right in `docs/architecture.md` (the usage ledger section), `docs/cli.md` (`abk report`) and the changelog.

## 2. [agent-build-kit] [tier1] A temporary one-time backfill of the ledger

Priority: 1

Done when `abk usage backfill-costs` turns every legacy row into an incremental one, safely and idempotently, and says
what it could not correct.

- [x] 2.1 Test: a dry run prints the before and after totals per unit and overall and the counts of rows changed and left
      unknown, and writes nothing, not even a copy.
- [x] 2.2 Test: `--apply` writes a timestamped copy first, rewrites atomically, a second run reports no legacy rows and
      leaves the ledger unchanged, and a record appended while it runs is not lost (the ledger lock).
- [x] 2.3 Test: the per-runtime rules. A `claude_code` session stored as 2.63, 5.49, 13.18 becomes 2.63, 2.86, 7.69 with
      cumulative 13.18 and basis `backfilled`; ACP and gateway rows keep their figure as incremental and gain a running
      cumulative; a session in which a figure falls is left `unknown` with no incremental figure and listed; a fixture with
      the design's per-unit shape shows the recorded total falling to the session-increment total.
- [x] 2.4 Test: summaries. A summary whose unit's detail rows survive is recomputed through `roll_up_change`; one whose
      detail is gone is marked `cumulative_summed` and listed, and is not presented as corrected.
- [x] 2.5 Add the `usage` subcommand beside `report` with `backfill-costs [--apply]`, its output and its help text, which
      says "temporary: removed once every installation has run it".
- [x] 2.6 Document the command and say it is temporary in `docs/cli.md` and the changelog. Last, after the build and not
      performed by it: a person runs `abk usage backfill-costs`, reads the output against the design's worked numbers, and
      runs it with `--apply`; the command's removal is the TODO in `follow-ups.md`.

## 3. [agent-build-kit] [tier1] Context window used against max, per step and cumulatively

Needs: fix-flaky-tests-cli-test-tick-scheduling-py-test-a-rate-limit-f8a057a3 group 1 merged — flaky test tests/cli/test_tick_scheduling.py::test_a_rate_limit_pause_still_stops_new_builds_for_the_pass

Priority: 2

Done when each agent row carries a `context` object in tokens, `abk report --context` shows it, and a step near the limit
is visible in the report, in telemetry and in one log line.

- [x] 3.1 Test: Claude Code per-request usage. From a recorded stream, `used_start`, `used_end`, `peak` and `added` follow
      the requests' input plus cache read plus cache creation; a repeated message counts once; sub-agent requests are not
      counted. First confirm against a recorded stream the three things the design lists as unverified (the compaction
      boundary event, `modelUsage[model].contextWindow`, per-request usage on `assistant` events) and fix the design where
      they differ.
- [x] 3.2 Test: the window. `max` is the result's `modelUsage[model].contextWindow` when present (added to `ResultEvent`,
      salvaged), else the configured per-model table, else absent with basis `unknown`.
- [x] 3.3 Test: ACP reads `UsageUpdate.used` and `.size`; a resumed session starts from the previous step's end, a new one
      from the first update; an update with neither figure leaves the context absent and the run unaffected.
- [x] 3.4 Test: compaction. A drop in the fill larger than `context.compaction_drop_share` counts one compaction, with `added`
      never negative and the peak kept; the runtime's own marker is counted instead when the stream has one.
- [x] 3.5 Test: reporting. `abk report --context` shows per step kind the mean and p90 added, the compactions and the end
      fill as `used / max`, the peak only where it differs, per session the growth, and the biggest adders; rows with no
      context are counted unknown; the two gauges and the compaction counter are exported; a step ending above
      `context.warn_share` logs one warning and nothing is scheduled from it.
- [x] 3.6 Add `ContextBasis` as a `StrEnum` and the `context` object to `UsageRecord`; parse `modelUsage` in
      `pipeline/claude_stream.py` and track per-request usage from `assistant` events; read the `UsageUpdate` fields in
      `runtimes/acp.py`; add `context.compaction_drop_share`, `context.warn_share` and `runtimes.context_windows` to the
      configuration; add `--context` to the report and the gauges and counter to the metrics export.
- [x] 3.7 Document the `context` object, the report option, the gauges and the settings in `docs/architecture.md`,
      `docs/configuration.md`, `docs/cli.md` and the changelog, and say that rows written before this change have no
      context and that it cannot be rebuilt from retained transcripts, which hold only each call's aggregate usage.
