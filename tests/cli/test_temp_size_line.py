"""`abk doctor` and `abk status` show the size of the pytest temp root and the number of leftover
run folders, warn above `global_limits.temp_warn_mb`, and print nothing when the folder does not
exist (spec: test-temp-folders-clean-up)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_build_kit.installation import Installation, load_installation
from tests.cli.in_repo_doctor import checks_of, in_repo, named
from tests.cli.test_admission_asks_own_account import isolated  # noqa: F401 — fixture
from tests.conftest import make_installation, run_status

LABEL = "pytest temp"
MEGABYTE = 1024 * 1024


def fill(root: Path, *, runs: int, megabytes: int) -> None:
    """`runs` run folders under `root`, holding `megabytes` between them."""
    for number in range(runs):
        folder = root / f"{number:08x}"
        folder.mkdir(parents=True)
        (folder / "data").write_bytes(b"x" * (megabytes * MEGABYTE // runs))


def warn_above(config: Path, megabytes: int) -> Path:
    document = yaml.safe_load(config.read_text())
    document["global_limits"] = {"temp_warn_mb": megabytes}
    config.write_text(yaml.safe_dump(document))
    return config


def doctor_lines(config: Path) -> list:
    return named(checks_of(config), LABEL)


def status_lines(
    inst: Installation, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> list[str]:
    return [line for line in run_status(inst, monkeypatch, capsys) if LABEL in line]


def status_installation(tmp_path: Path, warn_mb: int) -> Installation:
    return make_installation(
        tmp_path / "planning",
        planning={
            "state_dir": ".",
            "worktree_root": str(tmp_path / "trees"),
            "home": str(tmp_path / "home"),
        },
        global_limits={"temp_warn_mb": warn_mb},
    )


def test_doctor_shows_the_size_and_the_run_count_once_the_folder_exists(
    tmp_path: Path, data: Path
) -> None:
    config = warn_above(in_repo(tmp_path / "plan"), 100)
    root = load_installation(config).pytest_temp_root
    assert doctor_lines(config) == []

    fill(root, runs=2, megabytes=2)

    [line] = doctor_lines(config)
    assert line.status == "ok"
    assert "2 run folder(s)" in line.detail
    assert "2.0 MB" in line.detail


def test_doctor_warns_above_the_limit(tmp_path: Path, data: Path) -> None:
    config = warn_above(in_repo(tmp_path / "plan"), 1)
    fill(load_installation(config).pytest_temp_root, runs=2, megabytes=2)

    [line] = doctor_lines(config)

    assert line.status == "warn"
    assert "temp_warn_mb" in f"{line.detail} {line.fix}"


def test_status_shows_the_size_and_the_run_count_once_the_folder_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = status_installation(tmp_path, 100)
    assert status_lines(inst, monkeypatch, capsys) == []

    fill(inst.pytest_temp_root, runs=2, megabytes=2)

    [line] = status_lines(inst, monkeypatch, capsys)
    assert "2 run folder(s)" in line
    assert "2.0 MB" in line
    assert "temp_warn_mb" not in line


def test_status_warns_above_the_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = status_installation(tmp_path, 1)
    fill(inst.pytest_temp_root, runs=2, megabytes=2)

    [line] = status_lines(inst, monkeypatch, capsys)

    assert "warn" in line.lower()
    assert "temp_warn_mb" in line


def test_the_roots_the_sweep_clears_are_counted_together_and_other_folders_are_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = status_installation(tmp_path, 100)
    fill(inst.pytest_temp_root, runs=1, megabytes=1)
    fill(inst.legacy_pytest_temp_root, runs=1, megabytes=1)
    (inst.pytest_temp_root / "not-a-run").mkdir()
    (inst.pytest_temp_root / "not-a-run" / "data").write_bytes(b"x" * MEGABYTE)

    [line] = status_lines(inst, monkeypatch, capsys)

    assert "2 run folder(s)" in line
    assert "2.0 MB" in line
