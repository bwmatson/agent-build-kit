# Tasks

Acceptance: none — the tick's lines, the helpers and the hook are decided by a fake pass, a hand-made scratch directory and `pytester` runs; no consumer sees a new surface, and the next failing e2e-test run is the live confirmation.

Priority: 1

## 1. [agent-build-kit] [unit-test] A tick that builds nothing says why for each candidate unit

Done when a tick that starts nothing and is not stopped by a usage pause prints `nothing ready to build` followed by one line per candidate unit with its wait reason and what it waits on, at most 10 and then `(+M more)`, and the deadlock, full-queue and pause outputs are unchanged. Estimate: about 200 changed lines.

- [x] 1.1 Test: `tests/cli/test_tick_nothing_ready_reasons.py` with a stored plan of one unit blocked on another, one in backoff and one held for a person asserts the first output line is exactly `nothing ready to build`, followed by `  <unit> (<repo>): blocked, waits on <parent>`, `  <unit> (<repo>): backoff` and `  <unit> (<repo>): needs_person`, and that a unit in review or merged has no line.
- [x] 1.2 Test: the same file asserts 14 candidates print 10 lines and `  (+4 more)`, with the units whose reason is `ready`, `slot`, `lease` or `backoff` first, and that one candidate prints one line and no tail.
- [x] 1.3 Test: the same file asserts that with a cycle among the units the output is the deadlock report alone, that a full queue prints the full-queue report alone, and that a usage pause prints its pause line and no per-unit lines, each as before.
- [x] 1.4 Test: the same file asserts that when the reasons cannot be computed (the function raises) the output is the bare line plus one line naming the error and the tick still exits 0, that the same units start as without the lines, and that no stored unit changes.
- [x] 1.5 Add the unit lines to the last return of `_nothing_started_reason`, built from `wait_reasons` with nothing started and nothing building, bounded by a constant beside `_blocked_lines`.
- [x] 1.6 Update `docs/cli.md` with the new output of a tick that builds nothing.

## 2. [agent-build-kit] [unit-test] Live tests share one tick helper and a guarded check of the unit's branch

Done when one module gives live tests a tick result with return code, timed lines and the environment's summary, a function that runs the tick and remembers it, and a check of the unit's branch that fails with the tick output, the per-unit reasons, the run log tail and the pause marker when the branch is missing. Estimate: about 300 changed lines.

- [x] 2.1 Test: `tests/test_scratch_tick.py` runs the helper against a stand-in `abk` script that prints three lines (one on stderr) and exits 3, and asserts the result holds return code 3, the three lines in arrival order with non-decreasing times, `output` equal to them joined, and that the result is the one last remembered for that scratch (three runs keep three, a fourth drops the oldest).
- [x] 2.2 Test: the same file asserts `scratch_env_summary` lists `ABK_RUNTIME` with its value, lists a name containing `TOKEN`, `KEY`, `SECRET`, `PASSWORD`, `CREDENTIAL` or `AUTH` by name alone, and passes a value holding a registered secret through the redactor.
- [x] 2.3 Test: `tests/test_scratch_tick_branch.py` builds a bare remote with a branch of two commits and asserts the check returns their ids, then a remote without the branch and asserts the failure starts with a `cause hints:` line, then holds the tick's return code and output, the unit's wait reasons from a hand-made `decisions.jsonl`, the last lines of a run log, the contents of a `paused.json` (or `absent`) and the push history, and that it is a test failure and not a `CalledProcessError`.
- [x] 2.4 Test: the same file asserts the failure of a missing branch with no remembered tick says no tick was run, and that a failing read of any of the sources is named in one line and does not hide the others.
- [x] 2.5 Add `tests/scratch_tick.py` with the result type, the runner, the registry, the environment summary and the guarded branch check; it is named so that it does not collide with `live_build.py` or `runtime_scratch.py`.

## 3. [agent-build-kit] [unit-test] A failed live test prints the scratch installation's state, bounded and redacted

Done when a failed or errored `local_stack` test with a scratch installation gets a `SCRATCH STATE` section opening with a cause hint line and holding the sources of the design within their caps, redacted, in at most 20 KB per test and 60 KB per session, and a failure of the hook changes nothing. Estimate: about 340 changed lines.

- [x] 3.1 Test: `tests/test_scratch_dump.py` runs a `pytester` test marked `local_stack` that registers a hand-made scratch (state directory with `units.json`, `paused.json`, `decisions.jsonl`, a ledger, a lease, a bare remote with two heads, a fake host with three recorded requests) and fails, and asserts the report holds a `SCRATCH STATE` section whose first line starts `cause hints:` and which holds the last tick's output, the reason of each unit, the unit summary lines (id, state, branch, held_by, failure reason), the pause marker, the lease holder, the heads, the log tails, the three requests and the environment names.
- [x] 3.2 Test: the same file asserts a passing test, a skipped one, an unmarked failing one and a failing `local_stack` test with no scratch get no section; a failure in setup and one in teardown get one; and the section is the last part of that test's failure block.
- [x] 3.3 Test: `tests/test_scratch_dump_bounds.py` asserts a tick output of 100 000 characters is cut to its last 6000, 40 units give 20 lines, a `paused.json` of 5000 characters is cut to 1000, 100 branches give 30 lines, each log tail gives 15 lines of at most 300 characters, one dump is at most 20 480 characters, and a third failing test in a session whose first two used 60 KB gets one line saying its dump was left out.
- [x] 3.4 Test: `tests/test_scratch_dump_redaction.py` asserts a secret-named environment variable's value, planted in the tick output, the ledger tail and a unit's failure reason, appears nowhere in the section and its name does; that a failing redactor (it raises) leaves one line saying the dump was withheld and no text of it; and that no secret value appears in a `ps`-visible argument of the `git` commands it ran.
- [x] 3.5 Test: the same file and `tests/test_scratch_dump.py` assert a dump that raises in any one source (an unreadable `units.json`, a missing remote, a `git` that times out at its 10 seconds on a fake clock) puts `scratch state unavailable: <ExceptionType>` for that item only, that the test's outcome and traceback are exactly those of the same run without the plugin, and that no file in the scratch directory is created or changed by the hook.
- [x] 3.6 Add `tests/scratch_dump.py` with the report hook and one function per source, list it in `tests/conftest.py` beside `tests.time_split`, and put the cause hints line in the guarded branch check of group 2 through the same function.

## 4. [agent-build-kit] [unit-test] The graph, build and telemetry live tests use the shared helpers, and the documents say how a live test is written

Done when no live test file defines a tick result type or runs `abk tick` itself, no assertion about a unit's branch runs bare git, every assertion about a tick or a unit's state in the three files prints the tick's output or the scratch state through the helpers, and the architecture, CLI and authoring documents and the changelog say so. Estimate: about 330 changed lines.

- [x] 4.1 Test: `tests/test_live_tests_use_shared_tick.py` parses the three files (and any file under `tests/integration/` marked `local_stack`) and asserts none defines a class named `Ticked`, none calls `subprocess.run` or `Popen` with `tick` among its arguments, none names `commits_on_branch`, and every `git log main..` in them is in `tests/scratch_tick.py`.
- [x] 4.2 Test: the same file asserts each of the three files registers its scratch (`register_scratch` or a fixture argument the plugin finds), and that a `pytester` copy of the graph test with its tick replaced by a stand-in printing `nothing ready to build` fails with a message whose first line is `cause hints:` and which holds that output.
- [x] 4.3 Move the graph test (`Ticked`, `tick`, `commits_on_branch`), the build test (its own tick, `output_of`, the pushed-commits check) and the telemetry helper (`Ticked`, the `pushed` flag and its try block) onto `tests/scratch_tick.py`; the telemetry helper keeps its `FakeGitHub` and registers the scratch it builds.
- [x] 4.4 Give the assertions that attach nothing today the tick's output through the helper: the graph test's later branch checks and thread checks, the build test's forbidden-command, tip, reflog and report/ledger assertions, and the telemetry test's trace, metric and quiet-collector assertions; each message ends with the output the helper holds.
- [x] 4.5 Test: `tests/docs/test_failed_live_test_documented.py` asserts `docs/architecture.md` names `tests/scratch_tick.py`, the `SCRATCH STATE` section, its caps and its place in the e2e log, `docs/cli.md` shows the per-unit lines, `AGENTS.md` tells a new live test to use the shared tick and the guarded branch check, and the changelog has an entry.
- [x] 4.6 Update `docs/architecture.md` (e2e-test and test sections), `AGENTS.md` (how to write a live test), and add the changelog entry.
