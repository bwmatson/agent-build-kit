# Tasks

Acceptance: none — parsing, rendering, ledger rows and the plugin are decided by recorded pytest output, files and `pytester` runs; no consumer sees a new surface, and the live run that proves the split is the next real e2e-test run.

Priority: 2

## 1. [agent-build-kit] [unit-test] Record each test's time in the e2e-test result, the ledger and the metrics

Done when the e2e-test command asks for durations, the parsed entries are listed slowest first with the three slowest at the head of the result, one ledger row and two histograms are written per entry with bounded attributes, and an output with no durations changes nothing.

- [x] 1.1 Test: `tests/profiles/test_python_uv_e2e.py` asserts the python profile's e2e-test commands, with and without members, carry `--durations=0` and `--durations-min=1.0`, and a source scan asserts no file outside `profiles/` names `--durations`.
- [x] 1.2 Test: `tests/pipeline/test_e2e_durations.py` feeds recorded pytest output (a setup of 9 minutes and a call of 14 minutes for one test, sixteen tests, output with no durations section, a node-profile output) to the profile's parser and asserts the entries, one per phase, and an empty list for the last two.
- [x] 1.3 Test: the same file runs the gate over two projects with a fake runner and asserts the entries are merged, labelled with the project and sorted slowest first, and that the result is otherwise as before.
- [x] 1.4 Test: `build_snapshot` leads with the three slowest entries, lists the configured number with "N of M shown" and every entry at zero, and a dash for entries with no split; a stored result without `durations` still loads.
- [x] 1.5 Test: `tests/pipeline/test_pr_body_e2e_durations.py` builds a description whose output is cut to a small size and asserts the durations listing is whole.
- [x] 1.6 Test: `tests/pipeline/test_e2e_test_time_ledger.py` asserts one `test_time` row per entry with the unit, change, marker, test, phase and milliseconds, that the ledger reader skips it, and that nothing is written for a run with no entries.
- [x] 1.7 Test: `tests/test_e2e_test_time_metrics.py` asserts the histograms `abk.e2e.test.duration` and `abk.e2e.test.time` with the attributes of the spec, that no attribute holds a unit id, change name or test name, that a raising export does not fail the run, and that telemetry off exports nothing.
- [x] 1.8 Add the profile hook `parse_test_durations` and the flags, `TestTime` and `E2eResult.durations`, the `ABK-TIME` merge, the snapshot, the `test_time` row and its export, and the setting `e2e.durations_shown`.
- [x] 1.9 Update `docs/architecture.md` (e2e-test result, ledger kinds, metrics table) and `docs/configuration.md`, and add a changelog entry.

## 2. [agent-build-kit] [unit-test] Split an e2e-test test's time by agent role, checks and the rest

Done when an e2e-test test using the scratch installation prints, per phase, its agent time by role, checks time and remainder from the ledger rows written during that phase.

- [x] 2.1 Test: `tests/test_e2e_time_split.py` runs a `pytester` test marked `local_stack` that appends an `agent` row of 120 s for `implement` and a command span of 30 s to a fake scratch ledger and asserts its call line gives agent 120 s with one call, checks 30 s and other as the remainder.
- [x] 2.2 Test: the same file asserts two `agent` rows for one role give two calls and their sum, and parts above the wall time give other zero and say they overlap.
- [x] 2.3 Test: the same file asserts a module fixture's rows land in the setup of the first test using it and in no other entry, and a `local_stack` test without the scratch ledger gets no line.
- [x] 2.4 Test: the line's prefix and JSON round-trip through the framework's reader, and a malformed line is ignored.
- [x] 2.5 Add the plugin `tests/time_split.py` (loaded beside `tests.time_limit`), the `scratch_ledger` fixture for the live scratch-installation tests, and the framework's reader of its lines.
- [x] 2.6 Document the plugin and the line format in `docs/architecture.md` and add a changelog entry.
