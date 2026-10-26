## From `fix-flaky-tests-runtimes-test-policy-agent-harness-py-test-a-41a62277/1`

- tests/runtimes/test_policy_fake_agents_started.py:31 — The second test repeats the 'both empty' case of the parametrized test before checking the written state, so its first `assert not started(...)` adds no coverage.
- tests/runtimes/policy_fake_agents.py:93 — The race comes from `write_text` creating the file before it writes the pid. The fake could also write each pid to a temporary name and rename it into place, so no reader ever sees an empty pid file.
