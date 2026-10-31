"""A confined Claude Code step may reach the host that renews its login, and no other runtime
gains it (spec: claude-steps-can-renew-their-login).

The CLI renews an expired access token by posting the refresh token to its OAuth endpoint. A step
inside the sandbox could reach only the model and connector hosts, so it could not."""

from __future__ import annotations

from agent_build_kit.runtimes.acp import AcpRuntime
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime


def test_a_claude_code_step_may_reach_the_host_that_renews_its_login() -> None:
    hosts = ClaudeCodeRuntime().sandbox_paths()["hosts"]

    assert "platform.claude.com" in hosts


def test_the_host_comes_beside_the_model_and_connector_hosts() -> None:
    hosts = ClaudeCodeRuntime().sandbox_paths()["hosts"]

    assert "api.anthropic.com" in hosts
    assert "mcp-proxy.anthropic.com" in hosts
    assert len(set(hosts)) == len(hosts)


def test_the_acp_runtime_does_not_gain_the_host() -> None:
    assert "platform.claude.com" not in AcpRuntime().sandbox_paths().get("hosts", [])
