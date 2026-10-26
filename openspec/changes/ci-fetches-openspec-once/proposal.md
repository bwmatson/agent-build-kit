# Proposal

## Why

A CI run of the kit on 2026-10-15 UTC failed its `integration` job on main: five of eleven tests failed together, all because the OpenSpec CLI could
not be run. The log shows `sh: 1: openspec: not found` (exit status 127) from `npx --yes @fission-ai/openspec@<pin> validate ...`, the end-to-end `abk init`
reporting that `openspec init` failed with the same text, `abk check` returning 1 in both tests of the scheduled-tier-2 change test, and a fifth test
running past its 60-second limit. The run before it and the run after it on main passed, so the failure was transient, and the same run shows GitHub's
cache service failing at that moment (design: "What was checked"), so an incident on GitHub's side is the likely cause. No `npm ERR` line is in the
log, so the cause of the missing binary is not known (UNVERIFIED).

What the repository can fix is the weakness the incident exposed. The integration job fetches OpenSpec at test time, through `npx --yes`, inside whichever
test needs it first, with the suite's 60-second limit on that test and no retry. One slow or failed fetch therefore fails every test that needs the CLI,
each with a different message (an assertion on stdout, an `abk init` error, `abk check` returning 1), and a person reading the run has to work out that
they are one cause. It also breaks main's status for a reason that has nothing to do with the code.

## What Changes

- **The CLI is fetched once, before the tests.** A step of the integration job runs the same `npx --yes <package>@<pin> --version` the tests run, so
  `npx` fetches and caches the package in a step with its own timeout, and retries a bounded number of times, clearing `npx`'s own cache between tries
  because a half-written entry is one way a binary goes missing. It fails with one message if every try fails.
- **The pin has one source.** The step asks the kit's settings for the package name and the version, so the version is written only in `settings.py`;
  a test fails if the workflow spells it.
- **A test that needs the CLI says so once.** A session fixture asks the CLI for its version, once, and the four integration files that run it fail
  with the same message, "the OpenSpec CLI is not installed", with the exit status and the last lines of the error as detail. A later command that
  exits 127 is reported the same way and not as the thing under test failing.
- **The 60-second limit stays.** What changes is that the fetch no longer spends it.

## Impact

- agent-build-kit: `.github/workflows/ci.yml` (one step), a new `.github/scripts/warm-openspec.sh`, `tests/openspec_cli.py`,
  `tests/integration/conftest.py`, the four integration test files that run the CLI, two new test files, and a sentence in `AGENTS.md`. No framework
  source, no change to `openspec.py` or to `openspec.command`, and no changelog entry (design: "No changelog").
- Spec: `openspec-cli-in-tests`.
