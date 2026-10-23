"""`abk policy check` reports ACP's sandbox coverage as unverified against a real agent until the
shipped probe's recorded result says it ran and what held; the probe asks the agent for a denied
write, a denied read and a denied host (spec: sandbox-acp, group 2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.installation import load_installation
from agent_build_kit.runtimes import policy_check
from agent_build_kit.runtimes.policy_check import SandboxProbeResult
from tests.cli.policy_static_cli import abk_yaml, agent_command
from tests.cli.test_policy_cmd_check import run_check

UNVERIFIED_LINE = "sandbox_coverage: process (unverified against a real agent)"
ALL = ("write", "read", "host")


def coverage_line(lines: list[str]) -> str:
    return next(line for line in lines if "sandbox_coverage:" in line)


def test_with_no_probe_recorded_the_check_reports_process_unverified(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, lines = run_check(abk_yaml(tmp_path, agent_command()), capsys)

    assert UNVERIFIED_LINE in coverage_line(lines)


def test_a_probe_that_did_not_run_leaves_the_coverage_unverified(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = abk_yaml(tmp_path, agent_command())
    policy_check.record_sandbox_probe(load_installation(config), SandboxProbeResult(ran=False))

    _, lines = run_check(config, capsys)

    assert UNVERIFIED_LINE in coverage_line(lines)


def test_a_recorded_probe_that_ran_drops_the_note_and_names_what_held(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = abk_yaml(tmp_path, agent_command())
    policy_check.record_sandbox_probe(
        load_installation(config), SandboxProbeResult(ran=True, held=ALL)
    )

    _, lines = run_check(config, capsys)

    line = coverage_line(lines)
    assert "sandbox_coverage: process" in line
    assert "unverified" not in line
    assert "held: write, read, host" in line
    assert "not held" not in line


def test_a_recorded_probe_names_what_did_not_hold(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = abk_yaml(tmp_path, agent_command())
    policy_check.record_sandbox_probe(
        load_installation(config), SandboxProbeResult(ran=True, held=("write",))
    )

    _, lines = run_check(config, capsys)

    line = coverage_line(lines)
    assert "held: write" in line
    assert "not held: read, host" in line


def test_a_recorded_result_is_read_back_and_a_later_one_replaces_it(tmp_path: Path) -> None:
    installation = load_installation(abk_yaml(tmp_path, agent_command()))
    assert policy_check.recorded_sandbox_probe(installation) is None

    policy_check.record_sandbox_probe(installation, SandboxProbeResult(ran=True, held=ALL))
    assert policy_check.recorded_sandbox_probe(installation) == SandboxProbeResult(
        ran=True, held=ALL
    )

    policy_check.record_sandbox_probe(installation, SandboxProbeResult(ran=True, held=("host",)))
    assert policy_check.recorded_sandbox_probe(installation) == SandboxProbeResult(
        ran=True, held=("host",)
    )


def test_the_probe_asks_for_a_denied_write_a_denied_read_and_a_denied_host(
    tmp_path: Path,
) -> None:
    protected = tmp_path / "protected" / "file.txt"
    hidden = tmp_path / "secret" / "token.txt"

    prompt = policy_check.sandbox_probe_prompt(protected, hidden, "blocked.example.com")

    lowered = prompt.lower()
    assert str(protected) in prompt and "write" in lowered
    assert str(hidden) in prompt and "read" in lowered
    assert "blocked.example.com" in prompt and "connect" in lowered
