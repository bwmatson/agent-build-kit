"""A `claude` run that ends because the network is down raises, not fails.

The words are the ones the CLI logged for an outage. The exception carries them and the
API host the run called, and the call's spend is told through `on_result` first, as it is
for a refused usage window. Any other failure of the same exit stays a failed result.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.runtimes import AgentRequest, AgentResult, NetworkUnavailable, ToolPolicy
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from tests.runtimes.claude_cli import FakeClaude, refused

OUTAGE = "API Error: Can't reach the API server — check your internet or DNS (EAI_AGAIN)"
REFUSAL = "I can't help with that request."


@pytest.fixture(autouse=True)
def no_inherited_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default host is the default whatever gateway this machine is pointed at."""
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)


def _request(cwd: Path, told: list[AgentResult]) -> AgentRequest:
    return AgentRequest(
        prompt="Implement group 1 of add-marker.",
        role="implement",
        cwd=cwd,
        add_dirs=(cwd / "specs",),
        model="opus",
        allowed_tools="Read Edit Write",
        policy=ToolPolicy(specs_dir=cwd / "specs"),
        on_event=lambda line: None,
        on_result=told.append,
    )


def test_a_run_that_ends_on_an_outage_raises_and_any_other_failure_stays_a_result(
    tmp_path: Path,
) -> None:
    told: list[AgentResult] = []
    down = FakeClaude(stdout=refused(tmp_path, OUTAGE), returncode=1)

    with pytest.raises(NetworkUnavailable) as caught:
        ClaudeCodeRuntime(execute=down).run(_request(tmp_path, told))

    assert "EAI_AGAIN" in str(caught.value)
    assert "Can't reach the API server" in str(caught.value)
    assert caught.value.host == "api.anthropic.com"
    assert caught.value.strength == "strong"
    assert len(told) == 1, "the spend of the call is reported before the raise"

    said_no = FakeClaude(stdout=refused(tmp_path, REFUSAL), returncode=1)
    other: list[AgentResult] = []

    result = ClaudeCodeRuntime(execute=said_no).run(_request(tmp_path, other))

    assert result.ok is False
    assert REFUSAL in result.error


@pytest.mark.parametrize(
    ("url", "host", "port"),
    [
        ("https://gateway.example.test:8443/v1", "gateway.example.test", 8443),
        ("http://localhost", "localhost", 80),
        ("https://gateway.example.test", "gateway.example.test", 443),
    ],
)
def test_a_run_pointed_at_another_base_url_names_that_host_and_port(
    tmp_path: Path, url: str, host: str, port: int
) -> None:
    request = _request(tmp_path, []).model_copy(update=dict(env=dict(ANTHROPIC_BASE_URL=url)))
    down = FakeClaude(stdout=refused(tmp_path, OUTAGE), returncode=1)

    with pytest.raises(NetworkUnavailable) as caught:
        ClaudeCodeRuntime(execute=down).run(request)

    assert (caught.value.host, caught.value.port) == (host, port)


def test_the_default_host_is_named_with_port_443_and_the_inherited_override_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    down = FakeClaude(stdout=refused(tmp_path, OUTAGE), returncode=1)
    with pytest.raises(NetworkUnavailable) as caught:
        ClaudeCodeRuntime(execute=down).run(_request(tmp_path, []))
    assert (caught.value.host, caught.value.port) == ("api.anthropic.com", 443)

    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://inherited.example.test:9000")
    with pytest.raises(NetworkUnavailable) as inherited:
        ClaudeCodeRuntime(execute=down).run(_request(tmp_path, []))
    assert (inherited.value.host, inherited.value.port) == ("inherited.example.test", 9000)
