# Design

## What was checked, and where

Read-only against `origin/main` of `~/agent-build-kit` at `872fa344` (after `git fetch`). Paths are under the repo root.

- `tests/live_tag_drift.py`: `ROOT`/`INTEGRATION` (`:16,20`); `AGENT_HELPERS = ("tests.runtime_scratch", "tests.agent_home")` (`:22`);
  `live_modules()` globs `INTEGRATION.glob("test_*.py")` and keeps files whose text matches `\blocal_stack\b` (`:28-35`);
  `imports_an_agent_helper` (`:44-57`); `starts_an_agent` = `AGENT_COMMAND in source or imports_an_agent_helper(source)` (`:60-62`), per module;
  `drift` (`:65-92`) reports more than one tag, an untagged agent-starting `local_stack` item, an ACP scenario without a `claude_code` sibling and
  not in `ACP_ONLY_REASONS` (`:80-85`), and an empty reason (`:86-91`). `AGENT_COMMAND` comes from `tests/runtime_scratch.py:18`.
- `tests/test_live_tests_are_tagged.py`: the kit-wide test is `:68-76`; `:58-65` pins that the init-conventions module (which starts only a `claude`
  stub, `tests/integration/test_init_conventions_workspace.py:52-54,79`) passes untagged; `:146-155` pin that a Claude test with no ACP sibling is not named.
- `tests/runtime_tags.py`: `runtime_tags` (`:12-14`) and the collection check of at most one tag (`:17-27`).
- `tests/runtime_scratch.py`: `RUNTIMES`, `AGENT_COMMAND` (`:17-18`), `RUNTIME_PARAMS` / `CLAUDE_CODE_PARAMS` (`:22-27`), `runtime_scratch` (`:40-66`).
- `tests/scratch_tick.py:75-81`: `run_tick` runs `abk tick` as a process, which starts the scratch installation's agent. It is imported by
  `test_build_unit.py:38`, `test_graph_unit.py:42` and `test_telemetry_stack.py:55`, which also import `runtime_scratch`; a module that used only
  `run_tick` would pass today.
- The live modules on main and their tags: `test_build_unit.py:89` (`CLAUDE_CODE_PARAMS`), `test_graph_unit.py:165` (`CLAUDE_CODE_PARAMS`),
  `test_telemetry_stack.py:248,315` (`runtime_claude_code`). All Claude-only: these are the current gap list of item 5.
- `src/agent_build_kit/runtimes/acp.py`: `_opened` (`:1607-1611`: starts the agent, `initialize`, `session/new` in a temp directory, no prompt),
  `_advertised_models` (`:1613-1637`, 20-second `LISTING_TIMEOUT` at `:146`), `detect` (`:1639`, `known_agents.probe`, no model call), `list_models`
  (`:1654`). `known_agents.py:90-94` records for <redacted>: "run where it was installed: session/new returned a session id and modes only".
- `src/agent_build_kit/cli/e2e_cmd.py`: `unit_own_tests` (`:57-68`), `_split_declaration_warnings` (`:76-103`) compare a unit's declared split with
  the split listing of each test its branch added; printed as a warning at `:153`; `docs/cli.md:407-408` and `docs/architecture.md:1471` document that
  it warns and does not change the exit status; `tests/cli/test_e2e_check_split_declaration.py:58` pins `code == 0`.
- Documents: the tag rule `docs/agent-runtimes.md:925-931`; the repo's splits and the drift paragraph `:949-974` (it says "The test does not check
  that a `claude_code` scenario has an `acp` variant", `:974`); `AGENTS.md:145-151`; `CHANGELOG.md:3` (`## Unreleased`) with the earlier drift entry at
  `:60-62`; markers registered at `pyproject.toml:93-95`.
- Not on main (cited as audit evidence, never as something to edit): `tests/integration/replay_unit_build.py` on `spec/tier2-replays-unchanged-calls/3`
  and `tests/integration/runtimes/test_policy_check_agrees_with_agent_live_stack.py` on `spec/policy-check-asks-the-agents-own-matcher/6`. The
  abk-web-ui built-as-`runtime_acp`-but-starting-claude test is a branch observation of the audit; main holds only the plan (`tasks.md:167-183`).
- Other repos, checked 2026-10-19: no file named `test_live_tests_are_tagged.py`, no `runtime_acp`/`runtime_claude_code`/`ACP_ONLY_REASONS` in
  `~/<redacted>` or `~/<redacted>`.

## Decisions

### Discovery (item 1)

`live_modules()` walks every `*.py` under `tests/` recursively, parses it, and keeps a module that uses the attribute `pytest.mark.local_stack` (in
`pytestmark`, a decorator, a `pytest.param(..., marks=...)` or a class decorator). Syntax, not text: `tests/cli/test_e2e_check_cmd.py:58` and
`tests/e2e_check_support.py:19-21` hold the word `local_stack` in strings and are not live modules. Files that the project's pytest would not collect by
name (`replay_unit_build.py`) are collected by their path in the drift test's own `inline_genitems`, as the kit-wide test already does with explicit
paths (`tests/test_live_tests_are_tagged.py:73`). A module that fails to parse is named in the failure, not skipped.

### What starts an agent (item 2)

The question moves from the module to the test. A table `AGENT_SIGNALS` in `tests/live_tag_drift.py` (one place, each row with a reason) holds:

- imports of a named list of shared helpers that start an agent: `tests.runtime_scratch`, `tests.agent_home` (kept), `tests.scratch_tick`
  (`run_tick`), `tests.runtimes.policy_agent_harness` (`drive`); a helper that is added later is added to the list, and a test of the table asserts
  every module under `tests/` that calls `agent_connection` or `asyncio.create_subprocess_exec` on an agent command is either listed or excused;
- calls: `runtime_scratch(...)`, `run_tick(...)`, `AcpRuntime().detect`/`.list_models`/`.run`, `agent_connection(...)`, `drive(...)`;
- `shutil.which` of an agent program (`claude`, or any `KNOWN_AGENTS` program);
- a read of `<redacted>` (kept);
- the fixtures: the fixtures the test requests and the module's own functions it calls, followed transitively within the module (the test at
  `test_init_runtime_live_stack.py:308` reaches `detect` through `installed_agents`, `:303-305`, and `list_models` directly at `:315`).

A stand-in is not a real agent: `install_stand_in` and `machine` (`tests/scripted_abk.py`) are on an excused list with the reason, so the other
tests of `test_init_runtime_live_stack.py` (`:125-295`, protocol stand-ins that assert no `session/prompt`) stay untagged. That is why detection must be
per test: a module-wide signal would tag them.

### Tag versus start (item 3)

For a test with exactly one tag, the drift test derives which runtime its signals start: `claude_code` from `runtime_scratch("claude_code", ...)`,
a `claude_code` parameter in its callspec, `shutil.which("claude")` or the `claude_account` variables; `acp` from `runtime_scratch("acp", ...)`, an `acp`
parameter, a read of the agent command, `AcpRuntime` use. A mismatch is named: `<id>: tagged runtime_acp but starts claude_code`. The Claude adapter
`claude-agent-acp` (`known_agents.py:167-169`) is a protocol agent, so a test of it is `acp`, which is why the signal is the `claude` program and the
`claude_code` runtime, not the word claude. A test that starts both is the existing two-runtimes case (two tests). Untagged tests are not compared
(a stub on the path is the init-conventions case).

### Item 6, probed 2026-10-19 on this host

`AcpRuntime().list_models(["<redacted>", "acp"])` through `tests/runtimes/recording_proxy.py`: the client sent `initialize` and `session/new` only, the
agent answered both and pushed two `session/update` notifications, in 8.8 s; with `HTTPS_PROXY`/`HTTP_PROXY`/`ALL_PROXY` pointing at a closed port
the same run still finished in 11.9 s with the same messages, so no model backend call is made or needed. With an empty `<redacted>` the agent did not
answer `session/new` within the 20 s timeout (`acp.py:146`), so the test needs the agent installed and configured with its own credentials, not the
backend's budget. Decision: tag it `runtime_acp` and add `ACP_ONLY_REASONS["test_listing_against_the_installed_agent_sends_no_prompt"]`. Reasons:
`docs/agent-runtimes.md:925-927` defines untagged as "needs no agent", and this test skips without an installed agent (`:310-311`), so untagged would
be false; and the tag is the kit's record of a real agent started whether or not a prompt is sent. The reason text says the test lists models through
the protocol's `session/new`, which the Claude runtime does not use, and that it makes no model call. Consequence stated in the documents: holding the
`acp` split for an exhausted backend also holds this test, which would have run; accepted, as the split is also the agent's availability. The other
choice (leave untagged with a documented reason) is rejected for the reason above. The probe result goes in the reason's comment, not in a test.

### Split line versus tests (item 4)

The product already compares a unit's declared split with the split of each test its branch added and prints a warning (`e2e_cmd.py:76-103`); it is a
warning by decision of `split-start-gate`, with parking as the backstop (`docs/architecture.md:1469-1471`). This change does not alter that. What
the kit's repo can check on its own is the vocabulary a `Split:` line can use: the drift module maps each registered `runtime_<name>` marker
(`pyproject.toml:93-95`) to the split of that name, the untagged to `rest`, and a test asserts that this mapping equals the splits in the example
`docs/agent-runtimes.md:954-962` and that every tagged live test lands in exactly one of them. A new marker without a split, or a split without a
marker, then fails in the kit's CI, so a `Split:` line written to the documented names always selects the tests it was written for. The per-group
comparison stays `abk e2e-test check`'s. Open question for review: raise the warning to a finding (exit 1) in a later product change.

### Gap list (item 5)

`claude_without_acp(items)` returns the sorted `file::scenario` of every Claude-tagged scenario with no ACP sibling and no entry in a module table
`CLAUDE_ONLY_REASONS` (a table is optional and, unlike `ACP_ONLY_REASONS`, never required). A test compares that list with the list in
`docs/agent-runtimes.md` (a bullet list under a heading "Claude scenarios without an ACP sibling") and, on a difference, raises a `UserWarning` naming the
new or stale scenarios; it never fails. Today's list is the build test, the graph test and the telemetry tests (see the files above).

## Risks

- Per-test detection needs the AST of fixtures in other modules (`conftest.py`); it follows imports of `tests.*` helpers one level and treats an
  unresolvable fixture as not starting an agent, and says so in a note line of the test output, not in silence.
- The new signals can name a test that starts an agent only to count it (the `test_runtime_scratch_*` modules call `runtime_scratch` with a stub check).
  They are not `local_stack` and are not checked.

## Relationship to other changes

- `tier2-tests-are-tagged-by-runtime` (group 18, built) created the drift test; this change extends it. No `Needs:`.
- `abk-web-ui` groups 11 and 12 wait on tagged live tests (`tasks.md:171`); this change makes that tagging checkable. No `Needs:` here.
- `acp-variants-of-the-runtime-tests` adds ACP halves; item 5 lists what it should cover.
- All groups are `[unit-test]`: fixture modules collected with `pytester`, and the real kit modules by the existing kit-wide test; no live stack.
