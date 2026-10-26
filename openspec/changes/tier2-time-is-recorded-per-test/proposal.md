# Proposal

## Why

An e2e-test run takes 12 to 61 minutes (16 tests in 61 minutes, 12 in 40) and the only figure recorded is the pytest total, parsed from its summary line.
The tests drive the real pipeline in a scratch installation with a real agent: each `abk tick` runs agent steps (tests, implement, checks, review,
rework), and a fixture such as an `in_review` unit builds a whole unit before its test. Nobody can tell whether the time is the model, the scratch
repo's own checks, environment setup (`uv run --isolated`) or retries, so nothing can be tuned, and a slow test cannot be told from a hung one until
the thirty-minute limit passes.

## What Changes

- **Per-test durations in the result.** The e2e-test command asks pytest for every duration (`--durations=0`, added by the toolchain profile, so the
  framework stays language-independent). The runner parses the `slowest durations` lines (setup, call and teardown each their own entry), keeps them
  on `E2eResult`, and the posted "E2e-test results" section lists them slowest first, top N configurable, above the full output so the output's
  truncation cannot drop them.
- **Three slowest at the head.** The section opens with the three slowest entries, so a reviewer sees the cost without reading the table.
- **Time split by cause, per test.** A test-suite plugin attributes the usage-ledger rows the scratch installation wrote during each phase: agent time
  by role, command spans (checks, including environment setup, which cannot be told apart), and everything else. It prints one `ABK-TIME` line per
  test phase; the runner parses these as it does the durations and shows the split beside each entry.
- **Durations recorded and exported.** One `test_time` ledger row per entry (unit, change, test id, phase, seconds, split) and the histogram
  `abk.e2e.test.duration` with `marker`, `file` and `phase` attributes; the split as `abk.e2e.test.time` with `cause` and, for agent time, `role`.
  No unit id, change name or test name is an attribute.

## Impact

- agent-build-kit: `pipeline/e2e.py` (parse, `E2eResult`, snapshot), the toolchain profile hook for the durations flag and its parser
  (`profiles/base.py`, `python_uv.py`), a `test_time` ledger row and its export, a `tests/` plugin for the split, `docs/architecture.md`,
  `docs/configuration.md`, the changelog.
- Specs: `test-tiers` (what the result records), `telemetry` (the histograms). The ledger-row convention is `unit-timeline-is-recorded`'s: readers skip
  kinds they do not know.

## Not included

`abk report` and the usage page do not list tests (a later change can read the `test_time` rows); the dev-stack path of e2e-test, which runs the
repo's own script, adds no flags; a time limit per cause; attributing time inside the agent (turns, tool calls).
