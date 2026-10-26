## From `fix-flaky-tests-runtimes-test-acp-outcome-py-test-an-agent-th-a5668955/1`

- The `orphan_life_fifo` docstring (tests/runtimes/acp_agent.py:882) names only `--linger`. The `--fail orphan` test now uses the same pipe through `_leave_child`, so the docstring should name both, as the `orphan_pid_file` docstring does.
- tests/runtimes/acp_agent.py:882 — The `orphan_life_fifo` docstring says the pipe is for 'the child `--linger` leaves behind'. The orphan test now uses the same pipe for the child that `--fail orphan` starts, through the same `_leave_child`.
