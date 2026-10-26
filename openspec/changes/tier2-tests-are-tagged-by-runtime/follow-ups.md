## From `tier2-tests-are-tagged-by-runtime/2`

- `_VERBOSITY_FLAGS` drops only `-q`, `-qq`, `-v` and `-vv` from the listing argv, so `--quiet`, `--verbose` and `-vvv` still pass through. The absolute `--verbosity=-1` that comes after them should still win, so this is untidy rather than wrong. A later unit could strip any word that starts with `-q`/`-v` or is `--quiet`/`--verbose`, to keep the listing argv clean.

## From `tier2-tests-are-tagged-by-runtime/11`

- tests/pipeline/test_scheduled_e2e_due.py:42 — The parametrize argument is still called `day`, and the test is still named `test_the_date_is_read_from_the_name_of_exactly_that_repos_change`. Both now carry and assert a `(date, variant)` tuple from `scheduled_parts`, not a date.

## From `tier2-tests-are-tagged-by-runtime/6`

- E2eSession._groups still runs its listings inside the e2e-test stack lock (wiring.py:2630). The number of listings is now one per command and runtime rather than one per failure and runtime. Moving the attribution after the `with self._locked()` block would also free the lock during those collections.
- Under own scope with something parked, _park drops runs only when every run lists empty. A run whose own-selection listing is empty is otherwise kept and still started under the lock. Dropping each empty run on its own would save those commands.

## From `tier2-tests-are-tagged-by-runtime/9`

- The `e2e_runtimes=lambda: e2e.runtimes()` line in `build_runner` (src/agent_build_kit/pipeline/wiring.py:3501) is still not exercised by any test. The new tests cover `E2eSession.runtimes()` and the node passing `runtimes=` to the gate, but nothing checks that the runner `build_runner` assembles wires the session's groups through. If that line were dropped, the runner would fall back to the default of every group. A small test that builds a runner and asserts `runner.e2e_runtimes()` matches the session's groups would close this.

## From `tier2-tests-are-tagged-by-runtime/7`

- In CHANGELOG.md, the edited line in the e2e-test parking bullet ("a tick does not start it again; `abk status` shows it as blocked. When it resumes it runs only that runtime's tests on the same commit (the whole run if") is no longer wrapped like the lines around it. Re-wrap the bullet so it matches the others.
- `E2eSession.run` (wiring.py) stamps `only` onto whatever `self.result` holds after `_execute`. `_execute` never resets `self.result` at the start, so a path that returns without setting a result would label the previous run's result as the one-group run. Setting `self.result = None` at the top of `_execute` would make the label always belong to this run.

## From `tier2-tests-are-tagged-by-runtime/12`

- src/agent_build_kit/pipeline/e2e_holds.py:129 — `declared_splits` folds the declarations into one `hold` value, so the case that mirrors 1.3 is still reported for the whole installation rather than per repo. Example: repo `app` follows a top-level `acp` with no hold, repo `platform` declares its own `acp` with `hold: false`, and `e2e-held.json` holds `acp`. The combined value is False, so `acp` is listed as overridden and `abk status` prints no held line, yet `app`'s units still leave `acp` out (wiring.py:3453 judges each repo).

## From `tier2-tests-are-tagged-by-runtime/15`

- The `RuntimeScratch` docstring calls `env` 'the process environment its `abk` runs with', but it holds only the agent-home entry, the account variables and `ABK_RUNTIME`. The test still has to merge it into `process_env(...)`. Say 'the entries to add to its process environment'.
- tests/runtime_scratch.py:56 — The `runtimes` entry is written by interpolating the Python list repr (`command: {command}`) into YAML. This copies the pattern the three scratch tests use today, but now it sits in the one shared helper.
- tests/runtime_scratch.py:46 — Any runtime name other than `acp`, a typo included, falls into the claude_code branch without complaint.
- tests/integration/test_runtime_scratch_setup.py:20 — The test adds its own `Factory` class, which duplicates `_Factory` in `tests/test_agent_home.py:50`. pytest's `tmp_path_factory` already satisfies `TempFactory`, and `tests/test_agent_home.py:63` passes it straight to `agent_home`.
- tests/integration/test_runtime_scratch_setup.py:17 — `AGENT_COMMAND` is redefined here even though `tests/runtime_scratch.py:17` now exports the same constant.
- tests/integration/test_runtime_scratch_setup.py:29 — The helper's test needs neither node nor the network, but it is marked `integration`, so `uv run poe test` never runs it.

## From `tier2-tests-are-tagged-by-runtime/13`

- src/agent_build_kit/pipeline/verify.py:168 — This rework changed `_held_live_tests` so that a listing that fails (`list_tests` returns None) now counts as the held split holding a live test, and the verification waits. No test exercises this branch.

## From `tier2-tests-are-tagged-by-runtime/14`

- tests/e2e_gate_fakes.py:121 — `Planning.open_fix` now forwards `**kwargs: Any` to the module-level `open_fix`, so pyrefly no longer checks the keyword names and types at its callers (`met_by`, `repo`, `with_unit`, `split`).

## From `tier2-tests-are-tagged-by-runtime/19`

- The unit's commit subject says "The graph test runs on Claude and on ACP, and the ACP session listing is an ACP-only step", but the commit makes the test run on Claude Code only and removes the session listing. The squash title should describe what landed: Claude Code only, with no ACP-only step.
- tests/integration/test_graph_unit.py:15 — The module docstring still says the test "Needs an agent speaking the protocol". That describes the ACP agent this change removed from the file. The opening paragraph was updated to say Claude Code, but this sentence was not.
- tests/integration/test_graph_unit.py:55 — `CLAUDE_CODE = [p for p in RUNTIME_PARAMS if p.values[0] == "claude_code"]` reads into pytest's ParameterSet layout to pick one runtime. Each module that runs on one runtime will copy this line: group 15's test_build_unit and group 17's test_telemetry_stack are both due to do the same.

## From `tier2-tests-are-tagged-by-runtime/18`

- tests/integration/test_telemetry_stack.py:75 — `DEAD_COLLECTOR_REASON` is no longer referenced anywhere. The dead-collector test's docstring now repeats its text word for word.

## From `tier2-tests-are-tagged-by-runtime/16`

- `assert_runs_on_claude_code_alone` in tests/runtime_tag_collection.py uses the looser check from the graph test (`"claude_code" in i.nodeid`). The build test used to check `nodeid.endswith("[claude_code]")`. Both are sufficient, because the tag-list assertion already rules out any other parameter. The stricter form would still read more precisely.
