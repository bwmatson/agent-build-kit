## From `fix-flaky-tests-runtimes-test-policy-agent-harness-py-test-a-d595a2f4/1`

- tests/runtimes/policy_agent_harness.py:16 — The harness module docstring says that on the deadline or a signal the agent's "whole process group is killed and waited for". `AgentLink.kill` only SIGKILLs the group, and `_ended` reaps only the agent, so a grandchild left in the group is never waited for. That gap is exactly why the cleanup assertion now has to poll.
