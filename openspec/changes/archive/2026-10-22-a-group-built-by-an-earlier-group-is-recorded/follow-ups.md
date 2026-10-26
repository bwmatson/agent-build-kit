## From `a-group-built-by-an-earlier-group-is-recorded/2`

- `tests_account` is set by the first tests-agent call of a stubbed group and is not refreshed when the stub loop reworks the stubs. So a test-only group that was reworked and then committed nothing records the first account, not the last. If the account should be the agent's final word, refresh it on each stub-loop round.
- In the `unit_test` node, the 'unit-test failed' line is now logged before the environment block instead of after it. This is a deliberate side effect of sharing `failed_unit_test`. Someone reading a blocked unit's run log will now see 'unit-test failed' before the block, so it may be worth a line in the run-log docs if anyone relies on the old order.
