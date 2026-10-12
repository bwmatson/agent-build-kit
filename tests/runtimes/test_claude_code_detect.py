"""Claude Code's own probe: the executable on the path, nothing else."""

from __future__ import annotations

from agent_build_kit.runtimes import claude_code
from tests.runtimes.probe_fakes import Host


def test_the_executable_on_the_path_is_a_usable_candidate() -> None:
    host = Host(claude_code.AGENT_COMMAND[:1])

    [candidate] = claude_code.RUNTIME.detect(host.which, host.run)

    assert candidate.runtime == "claude_code"
    assert candidate.usable is True
    assert candidate.command == claude_code.AGENT_COMMAND
    assert host.runs == []


def test_its_absence_is_an_unusable_candidate_saying_so() -> None:
    host = Host()

    [candidate] = claude_code.RUNTIME.detect(host.which, host.run)

    assert candidate.usable is False
    assert any(
        claude_code.AGENT_COMMAND[0] in reason and "path" in reason for reason in candidate.reasons
    )
