# Proposal

## Why

Two units are failed and blocked on tier 2, and a third thing blinds the diagnosis of a fourth failure.

- **The in-process server's agent runs in the wrong environment.** The serve acceptance tests start the server in the
  pytest process (`start_server(scratch.installation)`, no environment) while the build tick runs `abk` as a process with
  the scratch environment, which carries the scratch agent home (`acceptance-agent-gets-its-own-state-store`) and
  `ABK_RUNTIME=acp`. The agent the server starts for a chat turn inherits the test process's own environment, so it
  cannot list the build session and the turn ends at once with `session <id> not resumed: the agent does not list it`.
  The same class is `abk-web-ui/11`'s review finding that the API server runs inside the test process without the
  scratch installation's configuration. Two tests of `ui-chat-editing/5` fail this way.
- **A tier 2 test cannot start a real agent.** The autouse guard `no_real_agent` replaces the Claude runtime's spawn
  with a refusal for every test, and `no_direct_claude` refuses any process whose program is `claude`. A test marked
  `local_stack` exists to use real agents; `abk-web-ui/11` fails at its new `claude_code` session with
  `a test tried to spawn a real agent process`.
- **A full tier 2 run loses its first errors.** The result keeps the last 4000 characters of a failing command's output.
  In a full run, four tests of `tests/integration/test_acp_build_unit.py` failed, and the same file run alone by hand with
  the same variables passed all six tests in 8m52s. The first error of each failing test is gone from the stored output,
  so the cause cannot be told from candidates (the pipeline's own environment leaking `ABK_*` variables into the scratch
  `abk` processes, the `--isolated` environment, load from units running at the same time). This change does not claim a
  cause; it makes the next full run say what failed first.

## What Changes

- **The server takes an environment for its agents.** `start_server` (and `create_app`) accept an optional environment;
  every agent process the server starts or asks, for a chat turn, a new or continued session, and the check whether a
  session would be resumed, runs in it. Without one, the process environment is used as it is now. `abk serve` passes none.
- **The tier 2 spawn guards step aside for `local_stack`.** `no_real_agent` and `no_direct_claude` are not applied to a test
  marked `local_stack`; they apply to every other test as before. The guards on the login refresh, the usage reading,
  `gh` and the code host stay for every test, decided one by one in the design.
- **A failed tier 2 run keeps its first errors.** The tier 2 command asks for a short failure summary, through the
  toolchain profile; the full output of each run is written to a file under the state directory, redacted and pruned like
  run logs, and named in the result; the result lists the first failure line of every failed or errored test above the
  output that may be cut.
- **Acceptance condition for the units.** The four tests above must pass in a full tier 2 run. This change does not decide
  why they failed; it says what must hold and gives the run what it needs to say.

## Impact

- agent-build-kit: `serve/server.py` (`start_server`, `create_app`), `serve/chat.py` (the request a turn builds and the
  resume check), `runtimes/base.py` (`AgentRequest`), `runtimes/acp.py` and `runtimes/claude_code.py` (the spawn paths),
  `tests/conftest.py`, `pipeline/tier2.py`, `pipeline/wiring.py` (the tier 2 gate), `pipeline/run_log.py` (naming and
  pruning shared with the new file), the toolchain profile hook (`profiles/base.py`, `profiles/python_uv.py`),
  `docs/agent-runtimes.md`, `docs/architecture.md`, `docs/configuration.md`, the changelog.
- Specs: `agent-runtime` (the environment of an agent's process), `test-determinism` (what a tier 2 test may start),
  `test-tiers` (what a tier 2 result keeps).
- Units: `abk-web-ui/11` and `ui-chat-editing/5` each gain a `Needs:` line per group of this change; their tests adopt the
  new API when they are reworked, and nothing of theirs is changed here.

## Not included

- The two tests files and `tests/scratch_stack.py` of the units: they are on unmerged branches, so this change only changes
  what is on `main`.
- The tier 2 lock wait (`tier2-lock-wait-is-configurable`) and the recorded time per test
  (`tier2-time-is-recorded-per-test`), which are separate changes.
- A cause for the four failures of the full run, and any change to what the pipeline passes to the tier 2 command's
  environment: until the first errors are visible a fix would be a guess.
