"""`abk config --migrate` renames `limits` under the runtimes and accounts of abk.yaml, and tells
the person which lines of abk.local.yaml to change, without editing it; `abk doctor` tells them
the same."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from agent_build_kit.cli import main
from agent_build_kit.cli.doctor import run_doctor
from agent_build_kit.runtimes.policy_apply import BACKUP_SUFFIX
from tests.cli.config_migrate_fakes import beside, run_migrate, write
from tests.cli.config_migrate_machine_fakes import tracked
from tests.cli.config_migrate_running_fakes import ONE, run_watched, running_unit
from tests.cli.test_doctor import Answers, which_all
from tests.factories import init_repo

OLD = (
    "version: 1\n"
    "runtimes:\n"
    "  claude_code:\n"
    "    # the usage windows\n"
    "    limits:\n"
    "      session:\n"
    "        usage_pause_pct: 62\n"
    "    accounts:\n"
    "      kit:\n"
    "        limits:\n"
    "          session:\n"
    "            usage_pause_pct: 55\n"
)
NEW = OLD.replace("    limits:", "    usage_limits:").replace(
    "        limits:", "        usage_limits:"
)
OVERLAY = (
    "runtimes:\n"
    "  claude_code:\n"
    "    limits:\n"
    "      weekly:\n"
    "        usage_pause_pct: 70\n"
    "    accounts:\n"
    "      kit:\n"
    "        limits:\n"
    "          session:\n"
    "            usage_pause_pct: 50\n"
)


def test_the_rename_shows_one_diff_asks_once_and_writes_once_with_a_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, OLD)

    code, terminal = run_migrate(capsys, monkeypatch, path, answers=("y",))

    assert code == 0
    assert terminal.asked == 1
    assert len(terminal.shown) == 1
    assert "+    usage_limits:" in terminal.shown[0]
    assert path.read_text() == NEW
    assert beside(path) == [path.name + BACKUP_SUFFIX]
    assert path.with_name(path.name + BACKUP_SUFFIX).read_text() == OLD


def test_a_second_run_has_nothing_to_migrate_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, OLD)
    assert run_migrate(capsys, monkeypatch, path, "--yes")[0] == 0

    code, terminal = run_migrate(capsys, monkeypatch, path, "--yes")

    assert code == 0
    assert "nothing needed migrating" in terminal.out
    assert path.read_text() == NEW


def test_a_dry_run_shows_the_rename_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, OLD)

    code, terminal = run_migrate(capsys, monkeypatch, path, "--dry-run")

    assert code == 0
    assert "+    usage_limits:" in terminal.out
    assert path.read_text() == OLD
    assert beside(path) == []


def test_an_unsupported_form_writes_nothing_and_prints_the_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    anchored = OLD.replace("    limits:\n", "    limits: &w\n", 1)
    path = write(tmp_path, anchored)

    code, terminal = run_migrate(capsys, monkeypatch, path, "--yes")

    assert code == 2
    assert "limits" in terminal.err
    assert re.search(r"anchor|alias", terminal.err)
    assert path.read_text() == anchored
    assert beside(path) == []


def test_the_migrated_file_loads_with_no_deprecation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, OLD)
    assert run_migrate(capsys, monkeypatch, path, "--yes")[0] == 0
    capsys.readouterr()

    code = main(["--config", str(path), "config"])

    captured = capsys.readouterr()
    assert code == 0
    assert "renamed usage_limits" not in captured.err
    shown = yaml.safe_load(captured.out)
    assert shown["runtimes"]["claude_code"]["usage_limits"]["session"]["usage_pause_pct"] == 62


def test_running_units_are_named_before_the_question_for_a_tracked_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tracked(tmp_path, OLD)
    running_unit(tmp_path)

    code, terminal = run_watched(capsys, monkeypatch, path, answers=("y",))

    assert code == 0
    assert terminal.asked == 1
    assert ONE in terminal.err_when_asked[0]
    assert "usage_limits:" in path.read_text()


def test_the_overlay_is_left_as_it_is_and_each_line_to_change_is_printed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, OLD)
    overlay = write(tmp_path, OVERLAY, "abk.local.yaml")

    code, terminal = run_migrate(capsys, monkeypatch, path, "--yes")

    assert code == 0
    assert overlay.read_text() == OVERLAY
    notice = terminal.out + terminal.err
    assert "abk.local.yaml" in notice
    assert re.search(r"abk\.local\.yaml\D*:3\b", notice), notice
    assert re.search(r"abk\.local\.yaml\D*:8\b", notice), notice
    assert "usage_limits" in notice
    assert beside(path) == [overlay.name, path.name + BACKUP_SUFFIX]


def test_config_prints_each_overlay_line_to_change_and_leaves_the_overlay(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, NEW)
    overlay = write(tmp_path, OVERLAY, "abk.local.yaml")

    code = main(["--config", str(path), "config"])

    err = capsys.readouterr().err
    assert code == 0
    assert overlay.read_text() == OVERLAY
    assert re.search(r"abk\.local\.yaml\D*:3\b", err), err
    assert re.search(r"abk\.local\.yaml\D*:8\b", err), err


def test_doctor_warns_with_each_overlay_line_and_does_not_fail(tmp_path: Path) -> None:
    planning = init_repo(tmp_path / "planning")
    (planning / "abk.yaml").write_text(NEW)
    overlay = planning / "abk.local.yaml"
    overlay.write_text(OVERLAY)

    checks = run_doctor(planning / "abk.yaml", run=Answers(), which=which_all)

    warned = [
        check for check in checks if check.status == "warn" and "usage_limits" in check.detail
    ]
    assert warned
    text = " ".join(check.detail + check.fix for check in warned)
    assert re.search(r"abk\.local\.yaml\D*:3\b", text), text
    assert re.search(r"abk\.local\.yaml\D*:8\b", text), text
    assert [check for check in checks if check.name == "config"][0].status == "ok"
    assert overlay.read_text() == OVERLAY
