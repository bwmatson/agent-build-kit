"""`abk config --migrate --include-defaults` also moves the settings a team may commit."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_build_kit.cli import main
from agent_build_kit.cli.doctor import MACHINE_KEYS, Check, run_doctor
from tests.cli.config_migrate_fakes import beside, run_migrate
from tests.cli.config_migrate_machine_fakes import merged
from tests.cli.public_content_repo import committed_config
from tests.cli.test_doctor import Answers
from tests.factories import which_all

DEFAULTS = {
    "runtimes": {"claude_code": {"limits": {"session": {"usage_pause_pct": 70}}}},
    "tests": {
        "e2e_schedule": False,
        "e2e_splits": {"slow": {"marker": "slow", "hold": True}},
    },
}


def machine_keys(config: Path) -> list[Check]:
    return [
        check
        for check in run_doctor(config, run=Answers(), which=which_all)
        if check.name == MACHINE_KEYS
    ]


def test_the_flag_moves_the_defaults_and_keeps_the_merged_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = committed_config(tmp_path, DEFAULTS)
    before = path.read_text()

    code, _ = run_migrate(capsys, monkeypatch, path, "--include-defaults", "--yes")

    assert code == 0
    local_text = (tmp_path / "abk.local.yaml").read_text()
    local = yaml.safe_load(local_text)
    assert (
        local["runtimes"]["claude_code"]["limits"] == DEFAULTS["runtimes"]["claude_code"]["limits"]
    )
    assert local["tests"]["e2e_schedule"] is False
    assert local["tests"]["e2e_splits"]["slow"]["hold"] is True
    base = yaml.safe_load(path.read_text())
    assert "limits" not in base["runtimes"]["claude_code"]
    assert "e2e_schedule" not in base["tests"]
    assert "hold" not in base["tests"]["e2e_splits"]["slow"]
    assert merged(path.read_text(), local_text) == merged(before, None)


def test_without_the_flag_the_defaults_stay_and_the_doctor_still_notes_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = committed_config(tmp_path, DEFAULTS)
    before = path.read_text()

    code, terminal = run_migrate(capsys, monkeypatch, path, "--yes")

    assert code == 0
    assert "nothing needed migrating" in terminal.out
    assert path.read_text() == before
    assert not (tmp_path / "abk.local.yaml").exists()
    noted = {check.detail.split(" in abk.yaml")[0] for check in machine_keys(path)}
    assert {"runtimes.claude_code.limits", "tests.e2e_schedule"} <= noted


def test_the_flag_needs_migrate(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = committed_config(tmp_path, DEFAULTS)
    before = path.read_text()

    code = main(["--config", str(path), "config", "--include-defaults"])

    assert code == 2
    assert "--migrate" in capsys.readouterr().err
    assert path.read_text() == before
    assert not (tmp_path / "abk.local.yaml").exists()
    assert ".git" in beside(path)


def test_after_a_run_with_the_flag_the_doctor_names_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = committed_config(tmp_path, DEFAULTS)
    run_migrate(capsys, monkeypatch, path, "--include-defaults", "--yes")

    assert machine_keys(path) == []
