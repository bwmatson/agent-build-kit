"""A file that goes away while `abk status` measures the pytest temp root is skipped, an unreadable
root is no root, and the command goes on (spec: test-temp-folders-clean-up)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.temp_sweep import temp_size
from tests.cli.test_admission_asks_own_account import isolated  # noqa: F401 — fixture
from tests.cli.test_temp_size_line import MEGABYTE, fill, status_installation
from tests.conftest import run_status

GONE = "gone"


@pytest.fixture
def vanishing(monkeypatch: pytest.MonkeyPatch) -> None:
    """The file named `gone` is removed for every `lstat` and `stat` of it, as if it went away
    between the directory listing and the look."""
    real_lstat = Path.lstat
    real_stat = Path.stat

    def lstat(self: Path, *args, **kwargs):
        if self.name == GONE:
            raise FileNotFoundError(str(self))
        return real_lstat(self, *args, **kwargs)

    def stat(self: Path, *args, **kwargs):
        if self.name == GONE:
            raise FileNotFoundError(str(self))
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", lstat)
    monkeypatch.setattr(Path, "stat", stat)


def test_a_file_removed_during_the_walk_is_skipped(tmp_path: Path, vanishing: None) -> None:
    inst = status_installation(tmp_path, 100)
    fill(inst.pytest_temp_root, runs=2, megabytes=2)
    (inst.pytest_temp_root / "00000000" / GONE).write_bytes(b"x" * MEGABYTE)

    found = temp_size(inst)

    assert found is not None
    assert found.runs == 2
    assert found.size == 2 * MEGABYTE


def test_status_goes_on_when_a_file_is_removed_during_the_walk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    vanishing: None,
) -> None:
    inst = status_installation(tmp_path, 100)
    fill(inst.pytest_temp_root, runs=2, megabytes=2)
    (inst.pytest_temp_root / "00000000" / GONE).write_bytes(b"x" * MEGABYTE)

    lines = run_status(inst, monkeypatch, capsys)

    assert any("pytest temp" in line for line in lines)


def test_an_unreadable_root_has_no_size(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    inst = status_installation(tmp_path, 100)
    fill(inst.pytest_temp_root, runs=2, megabytes=2)
    real_iterdir = Path.iterdir

    def iterdir(self: Path):
        if self == inst.pytest_temp_root:
            raise PermissionError(str(self))
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", iterdir)

    assert temp_size(inst) is None
