# Design

## What was checked, and where

Read-only against the agent-build-kit checkout; paths are under `src/agent_build_kit/`.

- `pipeline/wiring.py` `E2eGate.run` (the class holding `self._marker`) resolves `toolchain.e2e_commands(where, marker=...)` per project, runs each
  command under `stack_lock`, and for each calls `toolchain.parse_test_summary(out)` for `(passed, failed, skipped, seconds)`. The seconds are
  pytest's "in N s" figure, summed; nothing per test is read. When the repo has `scripts/dev-stack.sh`, `_run_on_dev_stack` runs the repo's own
  `up`/`test`/`down` instead and no profile command is involved.
- `profiles/python_uv.py` `e2e_commands` builds `uv run [--directory <member> --package <name> --isolated] pytest -m <marker> -v` per member with
  tests; `profiles/node_npm.py` raises its todo for it. `profiles/base.py` declares the hook and `parse_test_summary`. Framework code outside
  `profiles/` therefore must not mention pytest flags: the flag and the parser of its output belong to the profile.
- `pipeline/e2e.py` `E2eResult` holds `passed, failed, skipped, duration_seconds, command, output (last 4000 chars), stack_versions`;
  `build_snapshot` renders "## E2e-test results" with the output inside `<details>`. `pipeline/pr_body.py` `_verification_section` shrinks that output
  from the head to fit a size budget (`_output_parts`, `_OUTPUT_CUT`), so anything placed inside the output can be lost: durations must sit in the
  fixed part above it.
- `pipeline/spans.py` records `span` rows (`unit, change, node, round, started, ended, duration_ms, waited, command`); a unit-test command is a span with
  `command` set, nested inside its node's span. `pipeline/usage_ledger.py` `UsageRecord` is the `agent` row: `role`, `round`, `duration_ms`,
  `unit`, `change`. Both are lines of `<state_dir>/usage-ledger.jsonl`, with `state_dir` from `Installation(config, root).state_dir`.
- `telemetry.duration(name, seconds, **attributes)` records a histogram with the seconds buckets up to 7200 s; metrics carry bounded attributes and
  never unit ids (the `telemetry` spec). `unit-timeline-is-recorded` fixes the convention for new ledger kinds: readers skip kinds they do not know,
  so no reader changes.
- Tests: `tests/time_limit.py` is a plugin loaded through `pytest_plugins` in `tests/conftest.py` that already hooks setup, call and teardown of
  tests carrying `local_stack`; `tests/factories.py` has `scratch_app`; e2e-test tests are those marked `local_stack` under `tests/` (`pyproject.toml`
  registers it and excludes it by default).

UNVERIFIED: the location of the live scratch-installation fixtures the 12 to 61 minute runs use (there is no `tests/scratch_stack.py` in the checkout;
the plugin below takes the ledger path from a fixture the builder wires, beside whatever builds the scratch installation); whether a resumed agent call's
`duration_ms` is wall time of that call or of the session (the `usage-accounting` spec says a resumed call is counted once, not what its duration holds);
whether `scripts/dev-stack.sh test` of an installation passes extra flags to pytest.

## Recommendation: pytest's own durations, parsed

The smallest design is `--durations=0` and parsing its section, not a custom hook around every test in every repo. pytest already measures setup,
call and teardown separately and prints them slowest first as `12.34s call     tests/x.py::test_y`. The python-uv profile appends
`--durations=0 --durations-min=1.0` (sub-second entries are noise, and `-v` alone would print only the slowest ten). A second profile hook,
`parse_test_durations(output) -> list[TestTime]`, returns `TestTime(test, phase, seconds)`; the node profile returns an empty list, and an output with no
durations section gives an empty list, never an error. A custom plugin in every consumer repo was rejected: it needs installing, and the flag needs
nothing.

Several commands (one per member) are concatenated, each entry labelled with the project directory when there is one, then sorted slowest first. How
many are shown is `e2e.durations_shown` (default 15; 0 shows all), read through the settings model like the other pipeline settings (UNVERIFIED:
the section of `abk.yaml` that holds it; the builder puts it beside the e2e-test lock timeout). All entries are kept on the result and recorded; only
the table is cut.

## The result

`E2eResult` gains `durations: list[TestTime] = []` (default empty, so a stored or older result reads as before). `build_snapshot` writes, between
the result line and "Ran against":

```
- **Slowest:** `tests/e2e/test_x.py::test_a` call 14m02s; `...::test_b` setup 9m31s; `...::test_c` call 6m10s

**Time by test** (slowest first, N of M shown)

| Test | Phase | Time | Agent | Checks | Other |
```

`Agent`, `Checks` and `Other` are shown only when `ABK-TIME` lines gave a split for that test and phase, else the cells are `-`. The three slowest are
counted over entries (a phase of a test), not over tests, because the fixture build is exactly the slow part to see. The table is plain text above
the `<details>` block, so the size-budget shrinking of the output never touches it.

## The split, per test

Time inside a test is the sum of three things, taken from the scratch installation's ledger:

- **agent**, by `role`: the `duration_ms` of the `agent` rows written during the phase, summed per role; the count of calls is shown so a retry (a
  second call for the same role and round) is visible.
- **checks**: the `duration_ms` of `span` rows with `command` set. These include the scratch repo's own lint and test commands and the
  `uv run --isolated` environment setup inside them; the two cannot be separated from the ledger (UNVERIFIED that the commands print enough to split
  them, and the design does not try: the command string is kept in the row, so a person can see which command was slow).
- **other**: the phase's wall time minus agent and checks, clamped at zero. It is what the framework spent outside both (git, forge fakes, graph
  nodes, waiting for a slot) plus the test's own setup. Where agent and check time overlap or parallel units sum above wall time, other is zero and
  the line says `overlap`.

The window of a phase is the byte offset range of the ledger file: the plugin notes the file's size at the start of the phase and reads the rows
appended by its end. Offsets are used rather than timestamps because the scratch ledger belongs to one test run and the clock is faked in some
tests. A module-scoped fixture's time falls in the setup phase of the first test that uses it, which is what the table should say.

The plugin is a pytest plugin in `tests/` beside `time_limit.py` (loaded the same way), acting only on tests with `local_stack` that request a
`scratch_ledger` fixture (a path, or none). At the end of the session it prints, to the terminal summary, one line per entry:

```
ABK-TIME {"test": "tests/e2e/test_x.py::test_a", "phase": "setup", "agent": {"implement": 412000}, "calls": {"implement": 2}, "checks_ms": 90000, "other_ms": 1200}
```

JSON after a fixed prefix is language-independent: the framework parses only the prefix and the fields, and any other toolchain's tests can print the
same. The framework, not the plugin, knows nothing about pytest here: the profile's parser reads the durations section, and a generic reader merges
`ABK-TIME` lines by `(test, phase)`.

## Telemetry and the ledger

After parsing, `E2eGate` records one ledger row per entry through `record_line`:

`{kind: "test_time", at, unit, change, marker, test, phase, duration_ms, agent_ms, checks_ms, other_ms}` (the three split figures absent when unknown).

`test` is the full id; the ledger is not a metric, so a unit id and a test name are fine there. Readers skip the unknown kind
(`usage_report._entries_in`, as for `sample` rows in `unit-timeline-is-recorded`), so no reader changes.

Metrics, exported with the row as `export_span` does for spans, and a failed export never affects a run:

| name | kind | attributes |
|---|---|---|
| `abk.e2e.test.duration` | `telemetry.duration` histogram, seconds | `marker`, `file`, `phase` |
| `abk.e2e.test.time` | `telemetry.duration` histogram, seconds | `marker`, `file`, `cause` (`agent`, `checks`, `other`), `role` (for `agent`, else empty) |

`file` is the test id up to `::`: bounded by the number of test files, never a test name, unit id or change name. `role` is the closed set of agent
roles the ledger already uses as an attribute. Recording is skipped when there are no entries, so an e2e-test run of another toolchain changes nothing.

## Tests, and no e2e-test

Parsing, rendering, the ledger rows, the metric attributes and the plugin are all decided by text and files: tests feed recorded pytest output to
the parser and use `pytester` for the plugin with a fake ledger, as `tests/test_e2e_time_limit.py` does for the limit. Nothing needs the live
stack, so no group is `e2e-test` and `tasks.md` opts out of acceptance with a reason. The proof that the split is right on a real run is the next real
e2e-test run's posted result, which is not something this change can assert.

## Not included

Listing slow tests in `abk report` (a later change reads the `test_time` rows); the dev-stack path of e2e-test; a time limit per cause; attributing time
inside an agent call.
