"""`abk e2e status`, the held lines of `abk status` and the held checks of `abk doctor`
(spec: e2e-runtime-blocks, "What is held is visible")."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as pipeline_cli
from agent_build_kit.cli.doctor import Check, run_doctor
from agent_build_kit.pipeline.e2e_holds import HELD_FILE
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.cli.e2e_hold_fakes import (
    SPLITS_ACP_RELEASED,
    abk,
    gate_entry,
    own_splits,
    planning,
)
from tests.cli.test_doctor import Answers
from tests.factories import init_repo, stored_unit, which_all


def e2e_status(config: Path, capsys: pytest.CaptureFixture[str]) -> list[str]:
    code, out, err = abk(config, capsys, "e2e-test", "status")
    assert code == 0, err
    return out


def line_of(lines: list[str], split: str) -> str:
    (found,) = [line for line in lines if line.split() and line.split()[0] == split]
    return found


def in_two_days() -> datetime:
    return datetime.now(UTC) + timedelta(days=2)


def test_status_lists_each_split_and_rest_as_usable_or_held_with_what_holds_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = planning(tmp_path)
    assert abk(config, capsys, "e2e-test", "hold", "acp", "--reason", "out of budget")[0] == 0
    until = in_two_days()
    gate_entry(config, "claude_code", until)

    lines = e2e_status(config, capsys)

    acp = line_of(lines, "acp")
    assert "held" in acp and "out of budget" in acp and "command" in acp
    assert "configuration" in acp and "file" in acp
    claude = line_of(lines, "claude_code")
    assert "held" in claude and "gate" in claude and f"{until:%Y-%m-%d}" in claude
    assert "usable" in line_of(lines, "rest")


def test_status_shows_a_split_the_configuration_releases_although_the_file_holds_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = planning(tmp_path, SPLITS_ACP_RELEASED)
    gate_entry(config, "acp", in_two_days())

    acp = line_of(e2e_status(config, capsys), "acp")

    assert "usable" in acp
    assert "configuration" in acp and "releases" in acp


def test_status_shows_the_splits_the_schedule_will_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = planning(tmp_path)

    scheduled = [line for line in e2e_status(config, capsys) if "schedule" in line]

    assert len(scheduled) == 1
    assert all(name in scheduled[0] for name in ("acp", "claude_code", "rest"))


def test_abk_status_prints_one_line_per_held_split_and_none_when_nothing_is_held(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pipeline_cli, "current_usage", lambda: None)
    config = planning(tmp_path)
    UnitStore(config.parent / "units.json").upsert([stored_unit("one/1", change="one")])
    assert abk(config, capsys, "e2e-test", "hold", "acp", "--reason", "out of budget")[0] == 0
    until = in_two_days()
    gate_entry(config, "claude_code", until)

    held = [line for line in abk(config, capsys, "status")[1] if "e2e-test split" in line]
    assert len(held) == 2
    assert "acp" in held[0] and "out of budget" in held[0]
    assert "claude_code" in held[1] and f"{until:%Y-%m-%d}" in held[1]

    assert abk(config, capsys, "e2e-test", "release", "acp")[0] == 0
    (config.parent / HELD_FILE).unlink()
    assert not [line for line in abk(config, capsys, "status")[1] if "e2e-test split" in line]


def test_a_hold_in_one_repos_own_declaration_shows_in_both_status_commands(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pipeline_cli, "current_usage", lambda: None)
    config = planning(tmp_path, platform_tests=own_splits("          hold: true\n"))
    UnitStore(config.parent / "units.json").upsert([stored_unit("one/1", change="one")])

    assert "held" in line_of(e2e_status(config, capsys), "acp")
    held = [line for line in abk(config, capsys, "status")[1] if "e2e-test split" in line]
    assert len(held) == 1 and "acp" in held[0]


def doctor(config: Path) -> list[Check]:
    init_repo(config.parent)
    return run_doctor(config, run=Answers(), which=which_all)


def about(checks: list[Check], word: str) -> list[Check]:
    return [check for check in checks if word in check.detail and check.name != "config"]


def test_doctor_reports_a_held_split_as_information(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = planning(tmp_path)
    assert abk(config, capsys, "e2e-test", "hold", "acp", "--reason", "out of budget")[0] == 0

    (held,) = about(doctor(config), "out of budget")

    assert held.status == "info"
    assert "acp" in held.detail


def test_doctor_warns_that_the_configuration_releases_what_the_file_holds(
    tmp_path: Path,
) -> None:
    config = planning(tmp_path, SPLITS_ACP_RELEASED)
    gate_entry(config, "acp", in_two_days())

    (conflict,) = about(doctor(config), "releases")

    assert conflict.status == "warn"
    assert "acp" in conflict.detail
    assert "configuration wins" in conflict.detail + conflict.fix
    assert "abk e2e-test release" in conflict.fix


def test_doctor_fails_an_unreadable_file(tmp_path: Path) -> None:
    config = planning(tmp_path)
    (config.parent / HELD_FILE).write_text("{not json")

    (unreadable,) = about(doctor(config), HELD_FILE)

    assert unreadable.status == "FAIL"
    assert "abk e2e-test hold" in unreadable.fix


def test_doctor_warns_of_an_entry_naming_an_undeclared_split(tmp_path: Path) -> None:
    config = planning(tmp_path)
    gate_entry(config, "gone", in_two_days())

    (unknown,) = about(doctor(config), "gone")

    assert unknown.status == "warn"
    assert "abk e2e-test release" in unknown.fix


tier2_status = e2e_status  # abk-shim
