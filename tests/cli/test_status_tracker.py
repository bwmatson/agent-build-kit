"""`abk status` shows a line for a repo with a tracker section and none for a repo without one
(spec: tracker-seam, "doctor and status report a configured tracker and nothing else")."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.cli.e2e_hold_fakes import abk
from tests.cli.tracker_fakes import INCOMPLETE, ORGANIZATION, SECTION, planned, served


def status_lines(config: Path, capsys: pytest.CaptureFixture[str]) -> list[str]:
    code, out, err = abk(config, capsys, "status")
    assert code == 0, err
    return [line for line in out + err if "tracker" in line.lower()]


def test_a_valid_section_adds_a_line_with_the_target(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with served():
        (line,) = status_lines(planned(tmp_path, SECTION), capsys)

    assert "app" in line
    assert ORGANIZATION in line


def test_an_invalid_section_adds_a_line_with_its_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with served():
        (line,) = status_lines(planned(tmp_path, INCOMPLETE), capsys)

    assert "project" in line
    assert "app" in line


def test_a_repo_with_no_section_adds_no_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with served():
        assert status_lines(planned(tmp_path), capsys) == []
