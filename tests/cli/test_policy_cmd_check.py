"""`abk policy check`: every class and spelling with its pattern or "not refused", the classes
not covered by design marked, the label, nothing changed, no agent started, and the exit codes."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import main
from agent_build_kit.runtimes.acp import PROBE_CLASSES
from agent_build_kit.runtimes.known_agents import KNOWN_AGENTS
from agent_build_kit.runtimes.recommended_policy import matches, patterns
from tests.cli.policy_static_cli import UNKNOWN_PROGRAM, abk_yaml, agent_command, snapshot
from tests.runtimes.policy_static_support import (
    LABEL,
    UNCOVERED_LABELS,
    agent_home,
    recording_program,
    write_config,
)

CANNOT = "cannot check: abk has no policy for this agent"


def run_check(
    config: Path, capsys: pytest.CaptureFixture[str], *argv: str
) -> tuple[int, list[str]]:
    """`abk policy check <argv>`: the exit code and what it printed, line by line."""
    capsys.readouterr()
    code = main(["--config", str(config), "policy", "check", *argv])
    shown = capsys.readouterr()
    return code, (shown.out + shown.err).splitlines()


def test_every_class_and_spelling_is_printed_with_its_pattern_or_not_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    deny = [p for p in patterns() if "amend" not in p]
    write_config(agent_home(tmp_path, monkeypatch), deny)

    code, lines = run_check(abk_yaml(tmp_path, agent_command()), capsys)

    assert code == 1
    assert LABEL in "\n".join(lines)
    for command, label in PROBE_CLASSES:
        first = next((p for p in deny if matches(p, command)), "")
        wanted = "not covered by design" if label in UNCOVERED_LABELS and not first else first
        wanted = wanted or "not refused"
        assert any(command in line and wanted in line for line in lines), (command, wanted)
    for label in UNCOVERED_LABELS:
        assert any(label in line and "not covered by design" in line for line in lines), label


def test_a_complete_configuration_exits_zero_and_changes_nothing_and_starts_no_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = agent_home(tmp_path, monkeypatch)
    write_config(home, patterns())
    program = recording_program(tmp_path / "bin")
    config = abk_yaml(tmp_path, agent_command(str(program)))
    before = snapshot(home, config.parent)

    code, lines = run_check(config, capsys)

    assert code == 0
    assert LABEL in "\n".join(lines)
    assert snapshot(home, config.parent) == before
    assert not (tmp_path / "started.log").exists()


def test_an_unrecognised_command_exits_one_saying_abk_has_no_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    write_config(agent_home(tmp_path, monkeypatch), patterns())

    code, lines = run_check(abk_yaml(tmp_path, agent_command(UNKNOWN_PROGRAM)), capsys)

    assert code == 1
    assert CANNOT in "\n".join(lines)


def test_an_absent_configuration_exits_one_naming_the_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = agent_home(tmp_path, monkeypatch)

    code, lines = run_check(abk_yaml(tmp_path, agent_command()), capsys)

    assert code == 1
    assert str(home) in "\n".join(lines)


def test_agent_names_a_known_agent_behind_a_wrapper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    write_config(agent_home(tmp_path, monkeypatch), patterns())

    code, lines = run_check(
        abk_yaml(tmp_path, agent_command(UNKNOWN_PROGRAM)), capsys, "--agent", KNOWN_AGENTS[0].name
    )

    assert code == 0
    assert CANNOT not in "\n".join(lines)


def test_an_unknown_agent_exits_two_naming_the_known_agents(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, lines = run_check(abk_yaml(tmp_path, agent_command()), capsys, "--agent", "no-such-agent")

    assert code == 2
    text = "\n".join(lines)
    assert all(agent.name in text for agent in KNOWN_AGENTS)
