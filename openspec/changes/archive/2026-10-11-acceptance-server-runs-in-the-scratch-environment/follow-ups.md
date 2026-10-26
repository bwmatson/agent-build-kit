## From `acceptance-server-runs-in-the-scratch-environment/1`

- src/agent_build_kit/runtimes/acp.py:1033 — Commands the ACP agent asks abk to run through `terminal/create` still start in the abk process's environment. They ignore `request.environment` (and `request.env`). So a test's `PYTEST_CURRENT_TEST` and other variables only the test process has still reach anything the agent runs through its terminal.
- docs/architecture.md:1262 — The new paragraph about `start_server(..., agent_environment=...)` now opens 'The web server' section, before the sentence that introduces `abk serve` and `serve/server.py`.
- src/agent_build_kit/serve/chat.py:915 — `resumable` reads the environment from the `register` closure's `agent_environment`, but `Chat.request` reads it from `chat.agent_environment`. That is two sources for one value.

## From `acceptance-server-runs-in-the-scratch-environment/3`

- The builder could not edit the planning repo. A person should add the confirmed fact to design.md's UNVERIFIED paragraph and to section 3 ('The command') of the change, or to this PR's description: below `-vv`, and when not on CI, pytest 9.1.1 cuts each FAILED/ERROR summary message to the terminal width. It drops the message entirely when the test id fills the line (_pytest/terminal.py:1565-1571). That is why the python profile sends `-vv -rfE --tb=short`.
- pytest's `--force-short-summary` option (config.option.force_short_summary) brings the cut back even at `-vv`. If an installation sets it in its addopts, the listing is cut again. A later unit could add `-o`/addopts handling, or mention this in the profile docs.
- docs/toolchain-profiles.md:41 — The `parse_test_failures` row says the python profile asks pytest for the summary with `-rfE --tb=short`. The profile now also sends `-vv`, and the parser depends on it to get whole messages.

## From `acceptance-server-runs-in-the-scratch-environment/4`

- tests/cli/test_tier2_output_listed.py: the first status test (`test_status_shows_the_file_of_a_unit_whose_last_result_was_a_tier_2_failure`) builds the installation, store and usage stub by hand, which is what the `_status_of` helper added this round already does. It could use the helper, or the helper could take a list of units, so the setup lives in one place.
- The base run that the predecessor added (`Tier2Session._judge`) repeats untouched failed tests on the base, and its output is not written to the tier 2 output file. The spec covers only the unit's own run, but someone checking why a test was called pre-existing has nothing to read. A later change could append the base run's output under its own header.
