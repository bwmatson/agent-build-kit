"""`abk policy apply` closes by naming `abk policy check` as the way to confirm, and starts no
agent."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.cli.policy_apply_fakes import CURRENT_TOOLSET, OWN, Home, installation, run_apply
from tests.runtimes.policy_static_support import recording_program


def test_the_closing_text_names_the_check_that_reads_the_configuration_and_no_agent_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = Home(tmp_path, monkeypatch)
    home.holds(OWN, CURRENT_TOOLSET)
    program = recording_program(tmp_path / "bin")
    config, _ = installation(tmp_path, monkeypatch, command=[str(program), "acp"])

    code, terminal = run_apply(capsys, monkeypatch, config, home, answers=("y",))

    assert code == 0
    assert "abk policy check" in terminal.out
    assert "reads the configuration" in terminal.out
    assert "spends no" in terminal.out
    assert "spends model tokens" not in terminal.out
    assert not (tmp_path / "started.log").exists()
