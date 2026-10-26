# Tasks

Acceptance: none — the change is to the kit's own drift test and the documents; fixture modules collected with `pytester` and the kit's real live modules decide each rule, no consumer sees a new surface, and the next e2e-test run collects the real modules.

Priority: 2

## 1. [agent-build-kit] [unit-test] The drift test finds every live-stack module under tests/, not only test_*.py files in tests/integration

Done when the set of live modules is every Python file anywhere under `tests/` whose syntax marks a test `local_stack`, including helper modules run by path, and a module that cannot be parsed is named. Estimate: about 120 changed lines.

- [x] 1.1 Test: `tests/test_live_modules_are_found.py` builds a fixture tree with a `tests/integration/runtimes/test_x.py` and a non-`test_` `tests/integration/replay_unit_x.py`, each marking a test `local_stack` (by `pytestmark`, a decorator, a `pytest.param` mark and a class decorator), and asserts all are found.
- [x] 1.2 Test: the same file asserts a module that only holds the word `local_stack` in a string or a comment is not found, and a module with a syntax error is named in a failure and not skipped.
- [x] 1.3 Test: the same file asserts every file the old `INTEGRATION.glob("test_*.py")` plus text match found on the kit's tree is still found, so nothing is lost.
- [x] 1.4 Replace `live_modules()` in `tests/live_tag_drift.py` (and `test_the_init_conventions_module_which_starts_no_agent_passes_untagged`'s membership check) with the recursive, syntax-based discovery.

## 2. [agent-build-kit] [unit-test] The installed-agent listing test is tagged for the ACP runtime, with its reason

Done when `test_listing_against_the_installed_agent_sends_no_prompt` carries `runtime_acp` and the module states why it has no Claude variant, with the probe result of the design in a comment. Estimate: about 40 changed lines.

- [x] 2.1 Test: `tests/test_init_runtime_live_stack_is_tagged.py` collects `tests/integration/test_init_runtime_live_stack.py` and asserts that test's tags are exactly `["runtime_acp"]`, that the stand-in tests of the module carry none, and that the module's `ACP_ONLY_REASONS` has a non-empty entry for the listing test's name.
- [x] 2.2 Tag the listing test and add `ACP_ONLY_REASONS` to the module (the protocol's `session/new` listing; no model call; the agent installed and configured is the only requirement), with a comment of what was probed on 2026-10-19: the listing finishes with the network proxy pointing at a closed port and does not finish with an empty agent home.
- [x] 2.3 Update the module docstring's last sentence (`:12-14`) so it says the last test starts the host's agent and is in the `acp` split.

## 3. [agent-build-kit] [unit-test] Starting an agent is decided per test from a table of signals

Done when a live test is counted as starting an agent when it, a fixture it requests or a same-module function it calls shows one of the table's signals, a stand-in is not counted, and the kit's real modules still pass. Estimate: about 260 changed lines.

- [x] 3.1 Test: `tests/test_agent_start_signals.py` asserts, one fixture module per case, that an untagged test is named when it imports `tests.scratch_tick` and calls `run_tick`, calls `AcpRuntime().detect`, calls `AcpRuntime().list_models`, calls `shutil.which("claude")`, calls `runtime_scratch`, imports the policy agent harness and calls `drive`, or reads the agent command setting.
- [x] 3.2 Test: the same file asserts the signal is found through a fixture the test requests (including one in the module's `conftest.py`) and through a same-module helper function called by the test (as `installed_agents` is called at `test_init_runtime_live_stack.py:304-305`), and that a helper the test does not call does not count.
- [x] 3.3 Test: the same file asserts a test of a module that has both a stand-in test (`install_stand_in`) and an agent-starting test is named only for the second, and that a fixture that cannot be resolved is not counted and is mentioned in a note line.
- [x] 3.4 Test: the same file asserts the real kit modules (every one of group 1's set) have exactly one tag on every test that the table says starts an agent, and that the table's list of helper modules is complete: every module under `tests/` that calls `agent_connection` or starts a subprocess from an agent command is in the list or on the excused list with a reason.
- [x] 3.5 Replace `starts_an_agent` and `AGENT_HELPERS` in `tests/live_tag_drift.py` with the per-test decision over `AGENT_SIGNALS`.

## 4. [agent-build-kit] [unit-test] A runtime tag agrees with the runtime the test starts

Done when a test tagged `runtime_acp` that starts `claude`, and one tagged `runtime_claude_code` that starts a protocol agent, are named, and the kit's own tests pass. Estimate: about 150 changed lines.

- [x] 4.1 Test: `tests/test_runtime_tag_agrees_with_start.py` asserts, with fixture modules, a test tagged `runtime_acp` that calls `runtime_scratch("claude_code", ...)`, one that calls `shutil.which("claude")`, one whose callspec holds the parameter `claude_code` and one that uses `claude_account` are each named with both runtimes.
- [x] 4.2 Test: the same file asserts a test tagged `runtime_claude_code` that calls `runtime_scratch("acp", ...)`, or reads the agent command, is named; and a test tagged `runtime_acp` that starts the `claude-agent-acp` adapter is not.
- [x] 4.3 Test: the same file asserts an untagged test that puts a `claude` stub on the path (as `test_init_conventions_workspace.py:79` does) is not compared, and a correctly tagged parametrisation over `RUNTIME_PARAMS` is not named.
- [x] 4.4 Add the comparison to `drift` in `tests/live_tag_drift.py`; the table says which runtime each signal starts.

## 5. [agent-build-kit] [unit-test] The split names, the runtime markers and the documented example cannot drift apart

Done when a registered runtime marker with no split of its name, or a split of the documented example with no marker, fails the kit's tests, and every tagged live test lands in exactly one split. Estimate: about 100 changed lines.

- [x] 5.1 Test: `tests/test_live_split_names.py` asserts the splits derived from the markers registered in `pyproject.toml` (`runtime_<name>` is split `<name>`, untagged is `rest`) equal the splits in the yaml example of `docs/agent-runtimes.md`'s "This repo's own splits" section.
- [x] 5.2 Test: the same file asserts, with a fixture `pyproject.toml` and a fixture document, that an extra marker and an extra split are each named, and that every tagged live test of the kit's tree is in exactly one derived split.
- [x] 5.3 Add the mapping to `tests/live_tag_drift.py` and keep `abk e2e-test check` as it is: it still warns, and exits as before, about a group whose own test is in another split.

## 6. [agent-build-kit] [unit-test] Claude scenarios with no ACP sibling are listed, never refused

Done when the drift module returns the sorted list of Claude-only scenarios, the documents carry that list, and a difference between them is a warning and not a failure. Estimate: about 120 changed lines.

- [x] 6.1 Test: `tests/test_claude_without_acp_gap_list.py` asserts `claude_without_acp` returns `file::scenario` for a Claude-tagged scenario with no ACP sibling, nothing for a scenario with both (including one parametrised over `RUNTIME_PARAMS`), nothing for a scenario with an entry in the module's optional `CLAUDE_ONLY_REASONS`, and sorted output.
- [x] 6.2 Test: the same file asserts a gap missing from the document list, and a document entry that is no longer a gap, each raise a warning that names it, that no failure results, and that the kit's current list (the build test, the graph test and the telemetry tests) equals the document's.
- [x] 6.3 Add `claude_without_acp` to `tests/live_tag_drift.py` and the warning test; `ACP_ONLY_REASONS` behaviour is unchanged.

## 7. [agent-build-kit] [unit-test] The documents and the changelog say what the drift test now checks

Done when the runtimes document, `AGENTS.md` and the changelog describe the recursive discovery, the signals, the tag comparison, the split-name check, the gap list and the follow-up for the other repos. Estimate: about 90 changed lines.

- [x] 7.1 Test: `tests/docs/test_live_tag_rules_documented.py` asserts `docs/agent-runtimes.md` no longer says the test does not look at Claude scenarios without an ACP sibling in the sentence it says today, names `AGENT_SIGNALS`, has the heading "Claude scenarios without an ACP sibling" with the current list, says a tag is compared with what the test starts, and that it records that `<redacted>` and `<redacted>` have no such test; and that `AGENTS.md` and the `## Unreleased` section of `CHANGELOG.md` mention the change.
- [x] 7.2 Update `docs/agent-runtimes.md` (the tag rule at `:925-931`, the drift paragraph at `:968-974`, the gap-list section, the note that a tagged test may need only the installed agent and not the backend, and the follow-up for the other repos).
- [x] 7.3 Update `AGENTS.md` (how a new live test is tagged: one tag per test, by what it starts, and where the reasons tables go) beside the live-test paragraph at `:145-151`.
- [x] 7.4 Add the changelog entry under `## Unreleased`.
