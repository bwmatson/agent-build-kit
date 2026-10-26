# Proposal

## Why

`tests/test_live_tests_are_tagged.py` exists so that a live e2e-test that starts an agent is in one of the kit's two splits (`acp`, `claude_code`),
because a split held for an out-of-budget backend must park exactly the tests that need it. An audit on 2026-10-19 of `origin/main`
(`872fa344`) found six ways a test can start an agent, or be tagged for the wrong one, and pass the test:

1. **Discovery is shallow.** `live_modules()` globs `INTEGRATION.glob("test_*.py")` (`tests/live_tag_drift.py:33`): not recursive and only `test_`
   names. It misses `tests/integration/replay_unit_build.py` (a driver-run file; on branch `spec/tier2-replays-unchanged-calls/3`, `local_stack` at
   line 52, `runtime_scratch("claude_code", ...)` at line 149) and `tests/integration/runtimes/test_policy_check_agrees_with_agent_live_stack.py`
   (branch `spec/policy-check-asks-the-agents-own-matcher/6`, marks at lines 36-37). It also reads "is live" from the text `local_stack` anywhere in a
   file (`:34`), so a fixture string counts and a differently spelled mark does not.
2. **Agent-start detection is two imports and one environment name.** `starts_an_agent` (`:60-62`) is true when the module's source holds
   `<redacted>` or imports `tests.runtime_scratch` or `tests.agent_home` (`:21-24`, `:44-57`). It is per module, not per test. A test
   that calls `AcpRuntime().detect`, `shutil.which("claude")`, `run_tick` (`tests/scratch_tick.py:75-81`) or the policy agent harness is not seen.
3. **A tag is never compared with what the test starts.** `drift` (`:65-92`) only counts tags. A test tagged `runtime_acp` that starts a real `claude`
   passes (the audit found abk-web-ui group 11, planned at `openspec/changes/abk-web-ui/tasks.md:167-183`, built that way).
4. **A group's `Split:` is not compared with the markers of the tests it adds** anywhere a failure results: `abk e2e-test check` only warns
   (`src/agent_build_kit/cli/e2e_cmd.py:76-103`, printed at `:153`), by design of `split-start-gate`.
5. **A Claude scenario with no ACP sibling is invisible.** The test says so itself: `test_a_claude_test_with_no_acp_sibling_is_not_named`
   (`tests/test_live_tests_are_tagged.py:146-155`) and `docs/agent-runtimes.md:974`. The missing halves are tracked only in a draft.
6. **One real-agent test is untagged.** `tests/integration/test_init_runtime_live_stack.py:308`
   (`test_listing_against_the_installed_agent_sends_no_prompt`) starts the installed protocol agent (`AcpRuntime().list_models`, `:315`) and sends no
   prompt; it has no runtime tag, and the drift test passes it because none of its signals appear in the module.

## What Changes

- Discovery is recursive over `tests/`, finds a live module by the `local_stack` mark in its syntax tree (a decorator, `pytestmark`, or a
  parametrization mark) and includes non-`test_` helper modules that are run by path.
- "Starts an agent" is decided per test, from a named table of signals (the helper imports, calls such as `AcpRuntime().detect` / `list_models`,
  `shutil.which` of an agent program, `runtime_scratch`, `run_tick`, the policy agent harness, the agent command setting), looking through the
  fixtures the test requests and the module's own functions it calls. A stand-in agent (`install_stand_in`) is not a real agent.
- A tag must agree with what the test starts: a `runtime_acp` test that starts `claude`, and a `runtime_claude_code` test that starts a protocol
  agent, are named.
- `test_listing_against_the_installed_agent_sends_no_prompt` is probed for the model backend (it needs the agent installed and configured, not the
  backend), tagged `runtime_acp`, and given an `ACP_ONLY_REASONS` entry.
- The drift module computes the splits the kit's markers map to and fails when a registered runtime marker, the documented split example and the
  rule disagree; the product warning of item 4 stays a warning (see design).
- Claude scenarios with no ACP sibling are listed as a gap list in the documents; a new gap is a warning, never an error.
- The documents (`docs/agent-runtimes.md:925-931`, `:968-974`, `AGENTS.md`) and the changelog say all of it.

## Impact

- agent-build-kit only: `tests/live_tag_drift.py`, `tests/test_live_tests_are_tagged.py` (and new sibling test files),
  `tests/integration/test_init_runtime_live_stack.py`, `docs/agent-runtimes.md`, `AGENTS.md`, `CHANGELOG.md`. No `src/` change.
- Spec: new capability `live-test-tags`.
- Priority 2: a mis-tagged live test is run, or held, in the wrong split; the abk-web-ui acceptance groups (11, 12) wait on a trustworthy tagging.

## Not included

- <redacted> and <redacted> have no drift test and no `runtime_*` markers (<redacted> `pyproject.toml:48-51` registers `local_stack` and `dev_stack`
  only; <redacted> `pyproject.toml:92-94` registers `local_stack`; neither has a file like `test_live_tests_are_tagged.py`). Whether they need runtime
  markers is a follow-up: nothing in them is split by agent runtime today.
- Turning `abk e2e-test check`'s split-declaration warning into an error (a product change against `split-start-gate`).
- Adding the missing ACP halves of the Claude scenarios (`acp-variants-of-the-runtime-tests`).
