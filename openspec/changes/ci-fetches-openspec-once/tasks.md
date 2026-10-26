# Tasks

Acceptance: none — a CI step, its script and the messages of integration tests are checked by unit tests (a fake `npx` on the path, a fake runner, the parsed workflow); the first main run after the change is the live confirmation, described in design.md.

Priority: 4

## 1. [agent-build-kit] [unit-test] A test that needs the OpenSpec CLI fails with one message when it cannot be run

Done when a session fixture asks the CLI for its version once and the four integration files that run it fail with "the OpenSpec CLI is not installed" and the status and the last lines of the error when it cannot start, and an exit status 127 from a later command is reported the same way and not as the thing under test failing. Estimate: about 300 changed lines.

- [x] 1.1 Test: `tests/test_openspec_cli_probe.py` drives `probe` with a fake runner and asserts a status of 0 returns, that an `OSError` and a status of 127 and a status of 1 each fail with a message that begins `the OpenSpec CLI is not installed` and carries the status and the last 5 lines of stderr, and that the runner is called with the `--version` argument and a temporary directory.
- [x] 1.2 Test: the same file asserts `require` returns a result with status 0 or 1 unchanged, fails a result with status 127 with the same message, and that a session that asks for the fixture twice calls the runner once.
- [x] 1.3 Test: the same file asserts, by `pytester` over generated files that request the fixture with a runner that exits 127, that two tests fail with the identical first line of message and that a third test which does not request the fixture passes.
- [x] 1.4 Test: `tests/test_openspec_cli_users.py` asserts every integration test file that calls `openspec.run`, `openspec.validate` or runs `abk check` or `abk init` requests the `openspec_cli` fixture and no other integration file does, so a new file that runs the CLI without it fails the test and names the file.
- [x] 1.5 Add `tests/openspec_cli.py` (`probe`, `require` and the message), the session fixture in `tests/integration/conftest.py`, the `usefixtures` marker on the four files, and pass their CLI results through `require`. Confirm the places design.md marks UNVERIFIED for these and correct the design where the code says otherwise.

## 2. [agent-build-kit] [unit-test] The integration job fetches the pinned OpenSpec once, with a bounded retry, from the pin the kit defines

Done when the integration job has a step before its tests that fetches and starts the pinned OpenSpec CLI through `npx` with at most 3 attempts and a timeout of its own, fails with "the OpenSpec CLI is not installed" when every attempt fails, and takes the package and its version from the kit's settings so the workflow spells neither. Estimate: about 260 changed lines.

- [x] 2.1 Test: `tests/test_ci_openspec_step.py` parses `.github/workflows/ci.yml` and asserts the `integration` job has a step that runs `.github/scripts/warm-openspec.sh` with the spec printed by Python from `PACKAGE` and `settings.openspec_version`, that it sits after the step that sets up uv and before the one that runs the tests, that it has `timeout-minutes`, and that neither the package name nor the version string in `settings.py` appears in the workflow file or the script.
- [x] 2.2 Test: the same file runs the script with a fake `npx` first on the `PATH` and `OPENSPEC_RETRY_DELAY=0` and asserts a fake that fails twice and then succeeds ends the script with status 0 after 3 calls with the npx cache directory removed between calls, that one that always fails ends with status 1 after exactly 3 calls and prints the line `the OpenSpec CLI is not installed`, that one that succeeds at once is called once, and that each call is made with `--yes`, the spec given and `--version`.
- [x] 2.3 Test: the same file asserts the other two jobs have no such step, and that the job's test step still runs `pytest -m integration` with no time-limit option added.
- [x] 2.4 Add `.github/scripts/warm-openspec.sh` and the step in `.github/workflows/ci.yml`, and add a sentence to the Running section of `AGENTS.md` saying the integration job fetches the pinned CLI once before its tests. Confirm the places design.md marks UNVERIFIED for these (that a later `npx` reuses the fetched entry, and that settings read no `.env` in CI) and correct the design where the run says otherwise.
