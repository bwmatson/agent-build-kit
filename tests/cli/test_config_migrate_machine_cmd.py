"""`abk config --migrate` on a tracked abk.yaml moves its machine settings to abk.local.yaml, shows
one diff per changed file in order, asks once and never commits."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_build_kit.runtimes.policy_apply import BACKUP_SUFFIX
from tests.cli.config_migrate_fakes import beside, run_migrate
from tests.cli.config_migrate_machine_fakes import MACHINE, head, staged, tracked
from tests.config_migrate_machine_support import TILDE, merged

OLD_STEP = "version: 1\nmodels:\n  build: small\n"


def test_a_confirmed_run_moves_the_settings_and_keeps_the_merged_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tracked(tmp_path)
    before = head(tmp_path)

    code, _ = run_migrate(capsys, monkeypatch, path, "--yes")

    assert code == 0
    base = yaml.safe_load(path.read_text())
    local = yaml.safe_load((tmp_path / "abk.local.yaml").read_text())
    assert local == {
        "repos": {"app": {"path": "../app", "deploy": {"ssh_key": f"{TILDE}.ssh/deploy"}}},
        "planning": {"worktree_root": f"{TILDE}work/trees"},
        "project_limits": {"max_concurrent_stacks": 2},
        "verify": {"env": {"TOKEN": {"file": f"{TILDE}.config/app/.env"}}},
    }
    assert base["repos"]["app"] == {"slug": "example/app", "profile": "python-uv", "deploy": {}}
    assert base["planning"] == {}
    assert "project_limits" not in base
    assert base["verify"]["env"]["TOKEN"] == {"from": "env-file", "key": "TOKEN"}
    assert merged(path.read_text(), (tmp_path / "abk.local.yaml").read_text()) == merged(
        MACHINE, None
    )
    ignored = (tmp_path / ".gitignore").read_text().splitlines()
    assert "abk.local.yaml" in ignored and "scrub.local" in ignored
    assert head(tmp_path) == before
    assert staged(tmp_path) == ""


def test_the_diffs_come_in_order_and_the_one_question_names_both_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tracked(tmp_path)
    local = tmp_path / "abk.local.yaml"
    ignore = tmp_path / ".gitignore"

    code, terminal = run_migrate(capsys, monkeypatch, path, answers=("y",))

    assert code == 0
    assert terminal.asked == 1
    shown = terminal.shown[0]
    marks = [shown.index(f"+++ {name}") for name in (ignore, path, local)]
    assert marks == sorted(marks)
    assert terminal.out.count(f"+++ {ignore}") == 1
    new_file = shown[shown.rindex("--- ", 0, marks[2]) : marks[2]]
    assert "new file" in new_file
    assert shown.endswith(f"migrate {path} and {local}? [y/N] ")
    assert local.exists()
    assert path.with_name(path.name + BACKUP_SUFFIX).read_text() == MACHINE


def test_a_no_writes_nothing_and_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tracked(tmp_path)

    code, terminal = run_migrate(capsys, monkeypatch, path, answers=("n",))

    assert code == 1
    assert terminal.asked == 1
    assert path.read_text() == MACHINE
    assert beside(path) == [".git"]


def test_no_terminal_and_no_yes_writes_nothing_and_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tracked(tmp_path)

    code, terminal = run_migrate(capsys, monkeypatch, path, answers=None, piped="y\n")

    assert code == 1
    assert "abk.local.yaml" in terminal.out
    assert path.read_text() == MACHINE
    assert beside(path) == [".git"]


def test_only_the_old_steps_changing_asks_about_abk_yaml_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tracked(tmp_path, OLD_STEP)

    code, terminal = run_migrate(capsys, monkeypatch, path, "--include-defaults", answers=("y",))

    assert code == 0
    assert terminal.shown[0].endswith(f"migrate {path}? [y/N] ")
    assert "\nmodels:" not in path.read_text()
    assert not (tmp_path / "abk.local.yaml").exists()
