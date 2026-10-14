"""The commands the policy check judges (`PROBE_CLASSES`) stay in step with the command rules."""

from __future__ import annotations

from agent_build_kit.pipeline.command_policy import check_command
from agent_build_kit.runtimes.acp import PROBE_CLASSES, probe_branch


def test_every_probed_command_is_one_the_rules_refuse() -> None:
    """The list cannot drift from `command_policy`: a class the rules would
    allow could never be reported as enforced."""
    for command, label in PROBE_CLASSES:
        verdict = check_command(command, branch=probe_branch())
        assert not verdict.allowed, f"{label}: {command!r} is allowed by the rules"
