# Tasks

Acceptance: none — test support and result text decided by fake agents, `pytester` runs, recorded pytest output and files; the acceptance is the tier 2 runs of the two failed units `abk-web-ui/11` and `ui-chat-editing/5`, which wait on every group here, and the full-run pass of the four tests of `tests/integration/test_acp_build_unit.py` named in design.md.

Priority: 1

## 1. [agent-build-kit] [tier1] The server starts its agents in the environment it is given

Done when `start_server` takes an environment for the agents it starts, a chat turn, a new or continued session and the resume check run in it, nothing changes without one, and `abk serve` passes none.

- [x] 1.1 Test: `tests/runtimes/test_agent_environment.py` runs `AcpRuntime` with a fake agent command that writes one variable and `PYTEST_CURRENT_TEST` to a file: with `AgentRequest.environment` set the agent sees the given variable and not `PYTEST_CURRENT_TEST` or a variable only the test process has; with it `None` the agent sees the process's; with both it and `env` set it sees both.
- [x] 1.2 Test: the same file asserts `can_resume_session(session, cwd, environment=...)` starts the agent in the given environment (a fake agent lists the session only when a variable of it is set), that a yes in one environment is not reused for another, and that a call with no environment is unchanged.
- [x] 1.3 Test: the same file asserts the Claude runtime's `spawn`, bound before the guard patches it and run with a harmless argv, runs in the given environment, that `_run` passes it to an injected `execute` only when set, and that an `execute` written without the argument still works.
- [x] 1.4 Test: `tests/serve/test_chat_agent_environment.py` starts the server with `start_server(installation, agent_environment=...)` and a fake agent that records its environment, runs a chat turn on a build session, a new session and a continued session over HTTP, and asserts each agent saw the given variable and not one only the test process has; a server started with none gives the process's.
- [x] 1.5 Test: the same file asserts a source scan finds no `AgentRequest(` built under `serve/` outside `Chat.request`, that the request it builds carries the environment, that the resume check passes it, and that `cmd_serve` calls `start_server` without one.
- [x] 1.6 Add `AgentRequest.environment`, honour it in `AcpRuntime._drive`, `can_resume_session`/`_declares_loading` (and the cache key) and the Claude runtime's `_run` and `spawn`, add `agent_environment` to `start_server`, `create_app`, `register_chat` and `Chat`, and set it in `Chat.request` and `resumable`. Confirm the places design.md marks UNVERIFIED and correct the design where the code says otherwise.
- [x] 1.7 Document the argument and the whole-environment meaning in `docs/agent-runtimes.md` and `docs/architecture.md` (the serve section), and add a changelog entry.

## 2. [agent-build-kit] [tier1] A tier 2 test may start a real agent

Done when a test marked `local_stack` is not refused by the runtime-spawn and direct-`claude` guards, every other test still is, and the other guards apply to all.

- [x] 2.1 Test: `tests/test_spawn_guards.py` runs `pytester` with a conftest importing the real guards and the `local_stack` marker registered, and asserts an unmarked test that starts the runtime's real spawn fails with the guard's message.
- [x] 2.2 Test: the same file asserts a test marked `local_stack` starts a harmless program (`sys.executable`) through the original `spawn`, bound before the patch, and is not refused; and that a module-level mark gives the same result.
- [x] 2.3 Test: the same file asserts a program named `claude` is refused for an unmarked test and not by the guard for a marked one (a fake `claude` script on `PATH` that exits 0).
- [x] 2.4 Test: the same file asserts a marked test that refreshes the login, reads the usage window, runs `gh` or calls the code host fails with that guard's message.
- [x] 2.5 Make `no_real_agent` and `no_direct_claude` in `tests/conftest.py` return without patching when `request.node.get_closest_marker("local_stack")` is set, keep every other guard as it is, and say why in each docstring.
- [x] 2.6 Document the rule in `AGENTS.md`'s test section of the agent-build-kit repository and in the docstring of `tests/conftest.py`, and add a changelog entry.

## 3. [agent-build-kit] [tier1] A failed tier 2 run lists the first error of every failed test

Needs: secrets-never-reach-stored-or-posted-output group 1 merged — the redaction function the result text and the output file pass through does not exist before it

Done when the tier 2 command asks for a short failure summary and the result lists the first failure line of every failed or errored test above any cut.

- [x] 3.1 Test: `tests/profiles/test_python_uv_tier2.py` asserts the python profile's tier 2 commands, with and without members, carry `-rfE` and `--tb=short`, and a source scan asserts no file outside `profiles/` names either flag.
- [x] 3.2 Test: `tests/pipeline/test_tier2_failures.py` feeds recorded pytest output (four tests erroring with one fixture line, a mix of `FAILED` and `ERROR`, a line over the fixed length, an output with no failure summary, a node-profile output) to the profile's `parse_test_failures` and asserts the entries in printed order, the visible shortening of the long line, and an empty list for the last two.
- [x] 3.3 Test: the same file runs the gate over two projects with a fake runner and asserts the failures are merged in order and labelled with the project, and that the result is otherwise as before.
- [x] 3.4 Test: `build_snapshot` lists every failed test with its line above the `<details>` block, shows no listing for a pass, and a stored result without the new fields still loads.
- [x] 3.5 Test: `tests/pipeline/test_pr_body_tier2_failures.py` builds a description whose output is cut to a small size, with thirty failed tests, and asserts the listing is whole; and that the saved feedback of the unit holds the listing when the cut output does not hold the first error.
- [x] 3.6 Test: `tests/pipeline/test_tier2_failures_redacted.py` asserts a failure line holding a known secret value is `[redacted:<NAME>]` in the listing, the result and the saved feedback, and that the value is redacted before the line is shortened.
- [x] 3.7 Add the profile hook `parse_test_failures` and the flags, `TestFailure`, `Tier2Result.failures`, and the listing in the snapshot's fixed part. Confirm the places design.md marks UNVERIFIED and correct the design where the code says otherwise.
- [x] 3.8 Update `docs/architecture.md` (the tier 2 result) and `docs/toolchain-profiles.md` (the second hook), and add a changelog entry.

## 4. [agent-build-kit] [tier1] The full output of each tier 2 run is kept in a file named in the result

Needs: secrets-never-reach-stored-or-posted-output group 1 merged — the redaction function the result text and the output file pass through does not exist before it

Done when the full output of each run is in a redacted, pruned file under the state directory, and the result and the run log name it.

- [x] 4.1 Test: `tests/pipeline/test_tier2_output_file.py` runs the gate with a fake runner whose commands print far more than 4000 characters and asserts the file under `<state>/tier2-output/` holds every command's output whole, passing ones included, named by change, unit number and time, and that the result names its path.
- [x] 4.2 Test: the same file asserts a second command that raises leaves the first command's output in the file, and that the dev stack path writes the script's output the same way.
- [x] 4.3 Test: the same file asserts the name does not match a change whose name begins with the same letters, that only the most recent files of a unit remain after more runs than the bound, and that archiving a change removes its files.
- [x] 4.4 Test: `tests/cli/test_tier2_output_listed.py` asserts the unit's run log has a line with the path and `abk status` shows it for a unit whose last result was a tier 2 failure and not for another.
- [x] 4.5 Test: `tests/pipeline/test_tier2_output_redacted.py` asserts an output holding a known secret value is `[redacted:<NAME>]` in the file, and that a raising redaction leaves the withheld notice in the file and says so in the result without changing the run's outcome.
- [x] 4.6 Add `Tier2Result.output_file`, the per-command append in both tier 2 paths with the directory and name parameterised in `pipeline/run_log.py` helpers, the run log line and the `abk status` line.
- [x] 4.7 Update `docs/architecture.md` (the new directory) and `docs/configuration.md`, and add a changelog entry.
