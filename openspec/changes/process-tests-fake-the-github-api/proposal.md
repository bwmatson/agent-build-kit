# Proposal

## Why

`github-typed-client` moved every GitHub call off the `gh` command and onto the REST API. The
e2e-test tests that run `abk tick` as a real process (`test_acp_build_unit.py`,
`test_graph_acp_unit.py`, and the `gh` stand-in in `test_telemetry_stack.py`) still fake the host as
a `gh` script on `PATH`. Nothing calls it any more except `gh auth token`, so the forge sends its
requests to `https://api.github.com` with the stand-in's fake token and the host answers 401 when the
unit reaches `open_pr`. Both ACP tests fail on that, in `init-writes-changelog-conventions/2` and in
any unit that reaches e2e-test: the run exercised them for the first time after the switch.

A process cannot be given an `httpx` transport the way an in-process test gives one, and the API
address is a constant. The tests need a seam at the process boundary, and a fake host behind it that
answers the way GitHub does.

## What Changes

- **The GitHub API address is a setting** (`ABK_GITHUB_API_URL`, default `https://api.github.com`),
  read through `settings` like the others and used by the forge's client and by `abk doctor`. It is
  also what a GitHub Enterprise host needs.
- **A fake GitHub host for process tests:** a small HTTP server in the test support code that serves
  the REST routes the forge calls, from the recorded GitHub answers the forge tests already use
  (`tests/forges/recorded`, `github_answers.py`), with its state (a pull request created, a review
  comment, a merge) changed by the test the way a reviewer would on the host.
- **The e2e-test tests that fake `gh` use it:** the two ACP tests start the server, point
  `ABK_GITHUB_API_URL` at it and keep the `gh` stand-in only for `gh auth token`, which is the
  command the credential still comes from.

## Impact

- agent-build-kit: `settings`, the GitHub forge's client construction, `abk doctor`, the test
  support code and three integration test files. No change to the forge's behaviour against GitHub.
